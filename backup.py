import os, sys

from collections import OrderedDict, defaultdict
import fnmatch
import importlib.util
import json
import locale
import logging
import time
from itertools import chain

from applyActions import executeActionList
from constants import *
import strip_comments_json as configjson

# Running TODO:
# - test various modes; in particular, if hardlinks are actually used and if the correct comparison is being used
# - test run with full backup

# Ideas
# - statistics at the end for plausibility checks, possibly in file size (e.g. X GBit checked, Y GBit copied, Z GBit errors)
# - archive bit as means of comparison
# - Fix json errors being incomprehensible, because the location specified does not match the minified json (Joel)
# - exclude directories: make sure if a directory is excluded, the contents is excluded, too (maybe not as important; wildcards seem to work)
# - more accurate condition for failure / success other than the program not having crashed (Joel)

# Done:
# - support multiple sources or write a meta-file to launch multiple instances
# - start the backup in a sub-folder, so we can support multiple sources and log/metadata files don't look like part of the backup

class BackupData:
	def __init__(self, name, sourceDir, backupDir, compareBackup, fileDirSet):
		self.name = name
		self.sourceDir = sourceDir
		self.targetDir = os.path.join(backupDir, name)
		self.compareDir = os.path.join(compareBackup, name)
		self.fileDirSet = fileDirSet

class FileDirectory:
	def __init__(self, path, *, isDirectory, inSourceDir, inCompareDir):
		self.path = path
		self.inSourceDir = inSourceDir
		self.inCompareDir = inCompareDir
		self.isDirectory = isDirectory

	def __str__(self):
		inStr = []
		if self.inSourceDir:
			inStr.append("source dir")
		if self.inCompareDir:
			inStr.append("compare dir")
		return self.path + ("(directory)" if self.isDirectory else "") + " (" + ",".join(inStr) + ")"

# os.walk is not used since files would always be processed separate from directories
# But os.walk will just ignore errors, if no error callback is given, scandir will not.
def relativeWalk(path, startPath = None):
	if startPath == None: startPath = path
	if not os.path.isdir(startPath): return
	# strxfrm -> locale aware sorting - https://docs.python.org/3/howto/sorting.html#odd-and-ends
	for entry in sorted(os.scandir(path), key = lambda x: locale.strxfrm(x.name)):
		try:
			#print(entry.path, " ----- ",  entry.name)
			if entry.is_file():
				yield os.path.relpath(entry.path, startPath), False
			elif entry.is_dir():
				yield os.path.relpath(entry.path, startPath), True
				yield from relativeWalk(entry.path, startPath)
			else:
				logging.error("Encountered an object which is neither directory nor file: " + entry.path)
		except OSError as e:
			logging.error(e)

# Possible actions:
# copy (always from source to target),
# delete (always in target)
# hardlink (always from compare directory to target directory)
# rename (always in target) (2-variate) (only needed for move detection)
# hardlink2 (alway from compare directory to target directory) (2-variate) (only needed for move detection)
def Action(type, **params):
	return OrderedDict(type=type, params=params)

def fileBytewiseCmp(a, b):
	BUFSIZE = 8192 # http://stackoverflow.com/questions/236861/how-do-you-determine-the-ideal-buffer-size-when-using-fileinputstream
	with open(a, "rb") as file1, open(b, "rb") as file2:
		while True:
			buf1 = file1.read(BUFSIZE)
			buf2 = file2.read(BUFSIZE)
			if buf1 != buf2: return False
			if not buf1: return True

def filesEq(a, b):
	try:
		aStat = os.stat(a)
		bStat = os.stat(b)

		equal = True
		for method in config["compare_method"]:
			if method == "moddate":
				if aStat.st_mtime != bStat.st_mtime:
					break
			elif method == "size":
				if aStat.st_size != bStat.st_size:
					break
			elif method == "bytes":
				if not fileBytewiseCmp(a, b):
					break
			else:
				logging.critical("Compare method '" + method + "' does not exist")
				quit()
		else:
			return True

		return False # This will be executed if break was called from the loop
	except Exception as e: # Why is there no proper list of exceptions that may be thrown by filecmp.cmp and os.stat?
		logging.error("For files '" + a + "'' and '" + b + "'' either 'stat'-ing or comparing the files failed: " + str(e))
		return False # If we don't know, it has to be assumed they are different, even if this might result in more file operatiosn being scheduled

def dirEmpty(path):
	try:
		for entry in os.scandir(path):
			return False
		else:
			return True
	except Exception as e:
		logging.error("Scanning directory '" + path + "' failed: " + str(e))
		return True

def buildFileSet(sourceDir, compareDir, excludePaths):
	fileDirSet = []
	for name, isDir in relativeWalk(sourceDir):
		for exclude in excludePaths:
			if fnmatch.fnmatch(name, exclude):
				break
		else:
			fileDirSet.append(FileDirectory(name, isDirectory = isDir, inSourceDir = True, inCompareDir = False))

	logging.info("Comparing with compare directory")
	insertIndex = 0
	for name, isDir in relativeWalk(compareDir):
		while insertIndex < len(fileDirSet) and locale.strcoll(name, fileDirSet[insertIndex].path) > 0:
			insertIndex += 1

		if insertIndex < len(fileDirSet) and locale.strcoll(name, fileDirSet[insertIndex].path) == 0:
			fileDirSet[insertIndex].inCompareDir = True
		else:
			fileDirSet.insert(insertIndex, FileDirectory(name, isDirectory = isDir, inSourceDir = False, inCompareDir = True))

		insertIndex += 1

	for file in fileDirSet:
		logging.debug(file)
	return fileDirSet

def generateActions(sourceDir, config, fileDirSet):
	lastProgress = 0
	percentSteps = 5
	inNewDir = None
	actions = []
	for i, element in enumerate(fileDirSet):
		progress = int(i/len(fileDirSet)*100.0/percentSteps + 0.5) * percentSteps
		if lastProgress != progress:
			print(str(progress) + "%  ", end="", flush = True)
		lastProgress = progress

		# source\compare
		if element.inSourceDir and not element.inCompareDir:
			if inNewDir != None and element.path.startswith(inNewDir):
				actions.append(Action("copy", name=element.path, htmlFlags="inNewDir"))
			else:
				actions.append(Action("copy", name=element.path))
				if element.isDirectory:
					inNewDir = element.path

		# source&compare
		elif element.inSourceDir and element.inCompareDir:
			if element.isDirectory:
				if config["versioned"] and config["compare_with_last_backup"]:
					# only explicitly create empty directories, so the action list is not cluttered with every directory in the source
					if dirEmpty(os.path.join(config["source_dir"], element.path)):
						actions.append(Action("copy", name=element.path, htmlFlags="emptyFolder"))
			else:
				# same
				if filesEq(os.path.join(sourceDir, element.path), os.path.join(compareDirectory, element.path)):
					if config["mode"] == "hardlink":
						actions.append(Action("hardlink", name=element.path))

				# different
				else:
					actions.append(Action("copy", name=element.path))

		# compare\source
		elif not element.inSourceDir and element.inCompareDir:
			if config["mode"] == "mirror":
				if not config["compare_with_last_backup"] or not config["versioned"]:
					actions.append(Action("delete", name=element.path))
	print("") # so the progress output from before ends with a new line
	return actions
	

# MAIN CODE STARTS HERE

if __name__ == '__main__':
	testMode = True

	# Setup logger, read config files, integrity checks
	logger = logging.getLogger()

	stderrHandler = logging.StreamHandler(stream=sys.stderr)
	stderrHandler.setFormatter(LOGFORMAT)
	logger.addHandler(stderrHandler)

	userConfigPath = ""
	if testMode:
		userConfigPath = "test-setup.json"
	else:
		if len(sys.argv) < 2:
			logging.critical("Please specify the configuration file for your backup.")
			quit()
		userConfigPath = sys.argv[1]

	if not os.path.isfile(userConfigPath):
		logging.critical("Configuration '" + sys.argv[1] + "' does not exist.")
		quit()

	with open(DEFAULT_CONFIG_FILENAME, encoding="utf-8") as configFile:
		config = configjson.load(configFile)	

	with open(userConfigPath, encoding="utf-8") as userConfigFile:
		try:
			userConfig = configjson.load(userConfigFile)
		except json.JSONDecodeError as e:
			# The position given in e is wrong as the comments are stripped before the file is parsed; maybe fix later
			logging.critical("Parsing of the user configuration file failed: " + str(e))
			quit()

	# Sanity check the user config file
	for k, v in userConfig.items():
		if k not in config:
			logging.critical("Unknown key '" + k + "' in the passed configuration file '" + userConfigPath + "'")
			quit()
		else:
			config[k] = v
	for mandatory in ["sources", "backup_root_dir"]:
		if mandatory not in userConfig:
			logging.critical("Please specify the mandatory key '" + mandatory + "' in the passed configuration file '" + userConfigPath + "'")
			quit()	
			
	logger.setLevel(config["log_level"])

	if config["mode"] == "hardlink":
		config["versioned"] = True
		config["compare_with_last_backup"] = True

	# create root directory if necessary
	os.makedirs(config["backup_root_dir"], exist_ok = True)
	# Make sure that in the "versioned" mode, the backup path is unique: Use a timestamp (plus a suffix if necessary)

	if config["versioned"]:
		backupDirectory = os.path.join(config["backup_root_dir"], time.strftime(config["version_name"]))

		suffixNumber = 1
		while True:
			try:
				path = backupDirectory
				if suffixNumber > 1: path = path + "_" + str(suffixNumber)
				os.makedirs(path)
				backupDirectory = path
				break
			except FileExistsError as e:
				suffixNumber += 1
				logging.error("Target Backup directory '" + path + "' already exists. Appending suffix '_" + str(suffixNumber) + "'")
	else:
		backupDirectory = config["backup_root_dir"]

	# At this point: config is read, backup directory is set, now start the actual work

	# Init log file
	fileHandler = logging.FileHandler(os.path.join(backupDirectory, LOG_FILENAME))
	fileHandler.setFormatter(LOGFORMAT)
	logger.addHandler(fileHandler)


	# What does the code do from this point on?
	# 1. Find the old backup to compare to


	# Why are we creating the folder at this point? should do this later
#	targetDirectory = os.path.join(backupDirectory, os.path.basename(config["source_dir"]))
#	

	# Introduce new variable for the compare root; compareDirectory should be one level lower
	compareBackup = ""
	# update compare directory: Scan for old backups, select the most recent successful backup for comparison
	if config["versioned"] and config["compare_with_last_backup"]:
		oldBackups = []
		for entry in os.scandir(config["backup_root_dir"]):
			if entry.is_dir() and os.path.join(config["backup_root_dir"], entry.name) != backupDirectory: # backupDirectory is already created at this point
				metadataFile = os.path.join(config["backup_root_dir"], entry.name, METADATA_FILENAME)
				if os.path.isfile(metadataFile):
					with open(metadataFile) as inFile:
						oldBackups.append(json.load(inFile))

		logging.debug("Found " + str(len(oldBackups)) + " old backups: " + str(oldBackups))

		for backup in sorted(oldBackups, key = lambda x: x['started'], reverse = True):
			if backup["successful"]:
				compareBackup = os.path.join(config["backup_root_dir"], backup['name'])
				logging.debug("Chose old backup to compare to: " + compareBackup)
				break
			else:
				logging.error("It seems the last backup failed, so it will be skipped and the new backup will compare the source to the backup '" + backup["name"] + "'. The failed backup should probably be deleted.")
		else:
			logging.warning("No old backup found. Creating first backup.")

	# Prepare metadata.json
	metadata = {
			'name': os.path.basename(backupDirectory),
			'successful': False,
			'started': time.time(),
			'sources': config["sources"],
			'compareBackup': compareBackup,
			'backupDirectory': backupDirectory,
		}
	with open(os.path.join(backupDirectory, METADATA_FILENAME), "w") as outFile:
		json.dump(metadata, outFile, indent=4)

#	logging.info("Source directory: " + config["source_dir"])
#	logging.info("Backup directory: " + backupDirectory)
#	logging.info("Target directory: " + targetDirectory)
#	logging.info("Compare directory: " + compareDirectory)
#	logging.info("Starting backup in " + config["mode"] + " mode")

	# Build a list of all files in source directory and compare directory
	# TODO: Include/exclude empty folders
	logging.info("Building file set.")
	logging.info("Reading source directories")
#	logging.debug(config["sources"])
#	logging.debug(config["sources"][0])
	# For testing, limit to one source
	backupDataSets = []

	for i,source in enumerate(config["sources"]):
		# Folder structure: backupDirectory\source["name"]\files
		logging.debug("Params to buildFileSet: " + source["dir"] + '\n' + os.path.join(compareBackup, source["name"]) + "\n" + str(source["exclude-paths"]))
		if not os.path.isdir(source["dir"]):
			logging.error("The source path \"" + source["dir"] + "\" is not valid and will be skipped.")
			continue
		logging.info("Scanning source \"" + source["name"] + "\" at " + source["dir"])
		fileDirSet = buildFileSet(source["dir"], os.path.join(compareBackup, source["name"]), source["exclude-paths"])
		backupDataSets.append(BackupData(source["name"], source["dir"], backupDirectory, compareBackup, fileDirSet))

	
	# ============== SAVE
	# Write all files that are in source, but are not already existing in compare (in that version)
	# source\compare: copy
	# source&compare:
	#   same: ignore
	#   different: copy
	# compare\source: ignore

	# --- move detection:
	# The same, except if files in source\compare and compare\source are equal, don't copy,
	# but rather rename compare\source (old backup) to source\compare (new backup)

	# ============== MIRROR
	# End up with a complete copy of source in compare
	# source\compare: copy
	# source&compare:
	#   same: ignore
	#   different: copy
	# compare\source: delete

	# --- move detection:
	# The same, except if files in source\compare and compare\source are equal, don't delete and copy, but rename


	# ============== HARDLINK
	# (Attention: here the source is compared against an older backup!)
	# End up with a complete copy of source in compare, but have hardlinks to already existing versions in other backups, if it exists
	# source\compare: copy
	#   same: hardlink to new backup from old backup
	#   different: copy
	# compare\source: ignore

	# --- move detection:
	# The same, except if files in source\compare and compare\source are equal, don't copy,
	# but rather hardlink from compare\source (old backup) to source\compare (new backup)

	

	for dataSet in backupDataSets:
		logging.info("Generating actions for backup \""+dataSet.name + "\" with "+ str(len(dataSet.fileDirSet)) + " files.. ")
		dataSet.actions = generateActions(dataSet.sourceDir, config, dataSet.fileDirSet)
	
	
	# Feature disabled for the moment
	
	# if config["save_actionfile"]:
		# # Write the action file
		# actionFilePath = os.path.join(backupDirectory, ACTIONS_FILENAME)
		# logging.info("Saving the action file to " + actionFilePath)
		# actionJson = "[\n" + ",\n".join(map(json.dumps, actions)) + "\n]"
		# with open(actionFilePath, "w") as actionFile:
			# actionFile.write(actionJson)

		# if config["open_actionfile"]:
			# os.startfile(actionFilePath)

	# Feature disabled for the moment
			
	# if config["save_actionhtml"]:
		# # Write HTML actions
		# actionHtmlFilePath = os.path.join(backupDirectory, ACTIONSHTML_FILENAME)
		# logging.info("Generating and writing action HTML file to " + actionHtmlFilePath)
		# templatePath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.html")
		# with open(templatePath, "r") as templateFile:
			# template = templateFile.read()

		# with open(actionHtmlFilePath, "w", encoding = "utf-8") as actionHTMLFile:
			# templateParts = template.split("<!-- ACTIONTABLE -->")

			# actionHist = defaultdict(int)
			# for action in actions:
				# actionHist[action["type"]] += 1
			# actionOverviewHTML = " | ".join(map(lambda k_v: k_v[0] + "(" + str(k_v[1]) + ")", actionHist.items()))
			# actionHTMLFile.write(templateParts[0].replace("<!-- OVERVIEW -->", actionOverviewHTML))

			# # Writing this directly is a lot faster than concatenating huge strings
			# for action in actions:
				# if action["type"] not in config["exclude_actionhtml_actions"]:
					# # Insert zero width space, so that the line breaks at the backslashes
					# itemClass = action["type"]
					# itemText = action["type"]
					# if "htmlFlags" in action["params"]:
						# flags = action["params"]["htmlFlags"]
						# itemClass += "_" + flags
						# if flags == "emptyFolder":
							# itemText += " (empty directory)"
						# elif flags == "inNewDir":
							# itemText += " (in new directory)"
						# else:
							# logging.error("Unknown html flags for action html: " + str(flags))
					# actionHTMLFile.write("\t\t<tr class=\"" + itemClass + "\"><td class=\"type\">" + itemText
										 # + "</td><td class=\"name\">" + action["params"]["name"].replace("\\", "\\&#8203;") + "</td>\n")

			# actionHTMLFile.write(templateParts[1])

		# if config["open_actionhtml"]:
			# os.startfile(actionHtmlFilePath)

	if config["apply_actions"]:
		for dataSet in backupDataSets:
			os.makedirs(dataSet.targetDir, exist_ok = True)
			executeActionList(dataSet.sourceDir, dataSet.targetDir, dataSet.compareDir, dataSet.actions)
	
	# Finish Metadata: Set successful to true
	metadata["successful"] = True

	with open(os.path.join(backupDirectory, METADATA_FILENAME), "w") as outFile:
		json.dump(metadata, outFile, indent=4)
