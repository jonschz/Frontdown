import os,sys #@UnusedImport
import json
import logging #@UnusedImport
import time
import shutil

import strip_comments_json as configjson
from applyActions import executeActionList
from constants import * #@UnusedWildImport
from backup_procedures import * #@UnusedWildImport
from htmlGeneration import generateActionHTML
from statistics_module import sizeof_fmt

# Work in progress:
# - Statistics module: show progress proportional to size, not number of files
#	 - benchmark: done
#    - see comments below for status quo
# - Refactoring plus implementation of large paths:
# 	- split backup_procedures into two files, one with low-level operations, one with high-level objects
#      - partially done
# 	- wrap all OS / file system calls with custom functions; these calls will perform long path modifications,
#		OS checks and so forth, like: if (os == Windows): os.scandir("\\\\?\\" + path)
#     Old comment:
#     scanning of long directories might also be affected and new bugs may be introduced, see e.g.
#     https://stackoverflow.com/questions/29557760/long-paths-in-python-on-windows
#     pseudocode in applyAction.py:
#     if (os == Windows) and (len(fromPath) >= MAX_PATH) # MAX_PATH == 260 including null terminator, so we need >=
#     fromPath = '\\\\?\\' + fromPath
#     same with toPath

# Planning of the progress bar upgrade:
# Test results yield:
#  1 ms overhead duration per copied file
# .6 ms overhead per hardlinked file (close enough to 1 ms)
# 10 ms / megabyte of copied data
# so for each file, the progress bar should count one unit plus one unit for each 100 kib
# Question: How do we manage this information efficiently?
# Major problem: If we want to run the actions independently, we will either have to
# a) scan the entire set of files to compute the total amount beforehand or
# b) scan the file sizes during the scanning phase, don't save them in the action file, and provide a legacy
#	progress bar in case we run the action file separately
# c) save the total file size, total expected hardlink size, and total expected copy size in the action file
# Further potential problem: We might run above or finish below 100 % if the true file size differs
# from the expected one; ideas? Maybe dynamically update the top cap by comparing the real file size with the expected one?


# Running TODO
# - various TODO notes in different files
# - Show "amount to hardlink" and "amount to copy" after scanning
#    - especially important if we do scanning and saving separately
#    - second step: Compute if there is enough free disk space, throw an error if not
# - bug: metadata is not updated if the backup is run from applyActions.py
# - debug the issue where empty folders are not recognized as "copy (empty)", on family PC
# - backup errors does not count / display right; test manually (e.g. delete a file between scan and backup)
# - should a success flag be set if applyActions==false? 
# - 	maybe a new flag "no_action_applied"?
# - Detailed tests for the new error handling
#	 - check: no permissions to delete, permissions to scan but not to copy
# - Progress bars: display the current file to see which files take long; make performance tests for 100.000's of "print" commands
# - Think about which modes make sense with "versioned" and which don't, and remove "versioned" (and potentially "compare_with_last_backup" from the config file
# - Implement statistics for deletions? Might be hard: We could compute the size of everything to be deleted a priori, but how do we check what is actually being deleted, especially if we delete entire folders at once?
# - test the behaviour of directory junctions and see if it could run into infinite loops

# Ideas
# - Multithreading the scanning phase so source and compare are scanned at the same time 
#	 - should improve the speed a lot!
#    - Concurrent is enough, probably don't need parallel
# - In the action html: a new top section with statistics
# - give an option to use the most recent backup as a backup reference even if it has failed; this is e.g. good if the computer has crashed
# - change user interface:
#	 - allow all settings to be set via command line, remove full dependency on config files, at least for one source
#	 - check if sufficient data is given to run without config file
#	 - allow efficient diffing of large folders (think about most sensible interface choice)
#	 - a way to merge an existing backup efficiently into another one
# - object-oriented rewrite of the entire code? Large scale refactor
# - statistics at the end for plausibility checks, possibly in file size (e.g. X GBit checked, Y GBit copied, Z GBit errors)
# - exclude directories: make sure if a directory is excluded, the contents is excluded, too (maybe not as important; wildcards seem to work)
# - more accurate condition for failure / success other than the program not having crashed (pfirsich)
# - archive bit as means of comparison (probably doesn't integrate well into the concept)
# - pfirsich's notes_todo.txt

# - Meta Script TODO notes:
#    - wait for phone to connect
#    - backup from C, D, phone to F
#	 - wait for H to connect
#    - backup from C, D, F, phone to H
# -> open problems:
#    - how to do phone most efficiently?
#		- could mirror phone to some folder, then hardlink backup from there to F\\Frontdown and H\\Frontdown
#			- Advantage: works; Disadvantage: Double memory usage and every new file copied twice
#		- could to a versioned backup of phone to F and independently H
#			- Advantage: most elegant and clear; Disadvantage: Wacky phase of comparing and copying from phone must be done twice, prob. slow, battery usage
#		- could to a versioned backup of phone to a seperate folder and backup that folder
#			- Advantage: none of the disadvantages above; Disadvantage: How to tell Frontdown to copy the lastest backup from a different backup?


# Done:
# - test run with full backup
# - support multiple sources or write a meta-file to launch multiple instances
# - start the backup in a sub-folder, so we can support multiple sources and log/metadata files don't look like part of the backup
# - Fix json errors being incomprehensible, because the location specified does not match the minified json (pfirsich)
# - Fixed a well hidden bug where some folders would not be recognized as existing in the compare directory due to an sorting / comparing error
# - Introduced proper error handling for inaccessible files
# - Put exludePaths as parameters to relativeWalk to be able to supress Access denied errors and speed up directory scanning
# - track statistics: how many GB copied, GB hardlinked, how many file errors, ...?
#    - In the action html: a new top section with statistics
# - option to deactivate copy (empty folder) in HTML

# Backup Modes: Concepts and plans
# -------------
# === SAVE ===
# Write all files that are in source, but are not already existing in compare (in that version)
# source\compare: copy
# source&compare:
#   same: ignore
#   different: copy
# compare\source: ignore

# --- move detection:
# The same, except if files in source\compare and compare\source are equal, don't copy,
# but rather rename compare\source (old backup) to source\compare (new backup)

# === MIRROR ===
# End up with a complete copy of source in compare
# source\compare: copy
# source&compare:
#   same: ignore
#   different: copy
# compare\source: delete

# --- move detection:
# The same, except if files in source\compare and compare\source are equal, don't delete and copy, but rename


# === HARDLINK ===
# (Attention: here the source is compared against an older backup!)
# End up with a complete copy of source in compare, but have hardlinks to already existing versions in other backups, if it exists
# source\compare: copy
#   same: hardlink to new backup from old backup
#   different: copy
# compare\source: ignore

# --- move detection:
# The same, except if files in source\compare and compare\source are equal, don't copy,
# but rather hardlink from compare\source (old backup) to source\compare (new backup)

def loadUserConfig(userConfigPath):
	"""Loads the provided config file, checks for mandatory keys and adds missing keys from the default file.
	
	"""
	defaultConfigPath = os.path.join(os.path.dirname(__file__), DEFAULT_CONFIG_FILENAME)
	with open(defaultConfigPath, encoding="utf-8") as configFile:
		config = configjson.load(configFile)
	with open(userConfigPath, encoding="utf-8") as userConfigFile:
		try:
			userConfig = configjson.load(userConfigFile)
		except json.JSONDecodeError as e:
			logging.critical("Parsing of the user configuration file failed: " + str(e))
			sys.exit(1)
	# Now that the user config file can be loaded, sanity check it
	for k, v in userConfig.items():
		if k not in config:
			logging.critical("Unknown key '" + k + "' in the passed configuration file '" + userConfigPath + "'")
			sys.exit(1)
		else:
			config[k] = v
	for mandatory in ["sources", "backup_root_dir"]:
		if mandatory not in userConfig:
			logging.critical("Please specify the mandatory key '" + mandatory + "' in the passed configuration file '" + userConfigPath + "'")
			sys.exit(1)
	if config["mode"] == "hardlink":
		config["versioned"] = True
		config["compare_with_last_backup"] = True
	return config


def findTargetDirectory(config):
	backupDirectory = os.path.join(config["backup_root_dir"], time.strftime(config["version_name"]))
	suffixNumber = 1
	while True:
		try:
			path = backupDirectory
			if suffixNumber > 1: path = path + "_" + str(suffixNumber)
			os.makedirs(path)
			backupDirectory = path
			break
		except FileExistsError:
			suffixNumber += 1
			logging.error("Target Backup directory '" + path + "' already exists. Appending suffix '_" + str(suffixNumber) + "'")
	return backupDirectory

def findCompareBackup(config, backupDirectory):
	"""Locates the most recent previous complete backup.
	
	"""
	# Find the folder of the backup to compare to - one level below backupDirectory
	# Scan for old backups, select the most recent successful backup for comparison
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
				logging.info("Chose old backup to compare to: " + compareBackup)
				return compareBackup
			else:
				logging.error("It seems the most recent backup '" + backup["name"] + "' failed, so it will be skipped. " 
							+ "The failed backup should probably be deleted.")
		else:
			logging.warning("No old backup found. Creating first backup.")
		return ""



def main(userConfigPath):
	# Reset statistics (important if main is run multiple times in a meta script)
	stats.reset()
	# Setup logger
	logger = logging.getLogger()
	if not len(logger.handlers):
		# Only add a handler if this hasn't been called before; relevant for meta files calling main multiple times
		stderrHandler = logging.StreamHandler(stream=sys.stderr)
		stderrHandler.setFormatter(LOGFORMAT)
		logger.addHandler(stderrHandler)

	# Locate and load config file
	if not os.path.isfile(userConfigPath):
		logging.critical("Configuration file '" + sys.argv[1] + "' does not exist.")
		sys.exit(1)
	config = loadUserConfig(userConfigPath)

	logger.setLevel(config["log_level"])

	# create root directory if necessary
	os.makedirs(config["backup_root_dir"], exist_ok = True)

	# Make sure that in the "versioned" mode, the backup path is unique: Use a timestamp (plus a suffix if necessary)
	if config["versioned"]:
		backupDirectory = findTargetDirectory(config)
	else:
		backupDirectory = config["backup_root_dir"]

	# At this point: config is read, backup directory is set, now start the actual work

	# Init log file
	fileHandler = logging.FileHandler(os.path.join(backupDirectory, LOG_FILENAME))
	fileHandler.setFormatter(LOGFORMAT)
	logger.addHandler(fileHandler)

	compareBackup = findCompareBackup(config, backupDirectory)

	# Prepare metadata.json; the 'successful' flag will be changed at the very end
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

	# Build a list of all files in source directory and compare directory
	# TODO: Include/exclude empty folders
	logging.info("Building file set.")
	backupDataSets = []
	for source in config["sources"]:
		# Folder structure: backupDirectory\source["name"]\files
		if not os.path.isdir(source["dir"]):
			logging.error("The source path \"" + source["dir"] + "\" is not valid and will be skipped.")
			continue
		logging.info("Scanning source \"" + source["name"] + "\" at " + source["dir"])
		fileDirSet = buildFileSet(source["dir"], os.path.join(compareBackup, source["name"]), source["exclude-paths"])
		backupDataSets.append(BackupData(source["name"], source["dir"], backupDirectory, compareBackup, fileDirSet))
	
	# Plot intermediate statistics
	logging.info("Scanning statistics:\n" + stats.scanning_protocol())
	
	# Generate actions for all data sets
	for dataSet in backupDataSets:
		if len(dataSet.fileDirSet) == 0:
			logging.warning("There are no files in the backup \"" + dataSet.name +"\". No actions will be generated.")
			continue
		logging.info("Generating actions for backup \""+dataSet.name + "\" with "+ str(len(dataSet.fileDirSet)) + " files.. ")
		dataSet.actions = generateActions(dataSet, config)
	
	logging.info("Statistics pre-exectution:\n" + stats.action_generation_protocol())
		
	if config["save_actionfile"]:
		# Write the action file
		actionFilePath = os.path.join(backupDirectory, ACTIONS_FILENAME)
		logging.info("Saving the action file to " + actionFilePath)
		# returns a JSON array whose entries are JSON object with a property "name" and "actions"
		actionJson = "[\n" + ",\n".join(map(lambda s:json.dumps(s.to_action_json()), backupDataSets)) + "\n]"
		with open(actionFilePath, "w") as actionFile:
			actionFile.write(actionJson)

		if config["open_actionfile"]:
			open_file(actionFilePath)

			
	if config["save_actionhtml"]:
		# Write HTML actions
		actionHtmlFilePath = os.path.join(backupDirectory, ACTIONSHTML_FILENAME)
		templateFilePath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.html")
		generateActionHTML(actionHtmlFilePath, templateFilePath, backupDataSets, config["exclude_actionhtml_actions"])

		if config["open_actionhtml"]:
			open_file(actionHtmlFilePath)

	# Check if there is enough space on the target drive
	#TODO: test this code with a target that is actually too small; all the if clauses have been tested
	freeSpace = shutil.disk_usage(backupDirectory).free
	if (freeSpace < stats.bytes_to_copy):
		if config["target_drive_full_action"] == 'prompt':
			answer = ''
			while not answer.lower() in ["y", "n"]:
				answer = input("The target drive has %s free space. The backup is expected to need another %s. Proceed anyway? (y/n)"
							 % (sizeof_fmt(freeSpace), sizeof_fmt(stats.bytes_to_copy)))
			if answer.lower() == 'n':
				logging.critical("The backup was interrupted by the user.")
				exit(1)
		elif config["target_drive_full_action"] == 'abort':
			logging.critical("The target drive has %s free space. The backup is expected to need another %s. The backup will be aborted."
							 % (sizeof_fmt(freeSpace), sizeof_fmt(stats.bytes_to_copy)))
			exit(1)
		elif config["target_drive_full_action"] == 'proceed':
			logging.error("The target drive has %s free space. The backup is expected to need another %s. The backup will try to proceed anyway."
						 % (sizeof_fmt(freeSpace), sizeof_fmt(stats.bytes_to_copy)))
		else:
			#TODO: possibly move this detection into the parsing of the config file
			logging.error("Invalid value in config file for 'target_drive_full_action': %s\nDefaulting to 'abort'" % config["target_drive_full_action"])
			exit(1)
	
	#TODO: restructure the code; this code should also run when applyActions is being called
	# idea: split the main method into two, one for scanning, one for applying;
	# store more information in the metadata file if needed
	# refactor the applyActions file; move everything but its __main__ code elsewhere, move everything from backup into a new file
	# backup_job.py, make an object oriented model, have backup and applyActions call methods from backup_job.py
	# also remove exit() statements, in case we want to call from meta py files. Instead, use exceptions and have a nonzero return
	# value of main()
	
	backup_successful = ((config["max_scanning_errors"] == -1 or stats.scanning_errors <= config["max_scanning_errors"])
						and (config["max_backup_errors"] == -1 or stats.backup_errors <= config["max_backup_errors"]))
	
	if config["apply_actions"]:
		for dataSet in backupDataSets:
			executeActionList(dataSet)
		logging.debug("Writing \"success\" flag to the metadata file")
		# Finish Metadata: Set successful to true
		# We deliberately do not set "successful" to true if we only ran a scan and not a full backup
		#TODO: Find a better solution, in particular, set the successful flag if we run the action file separately
		metadata["successful"] = backup_successful

	with open(os.path.join(backupDirectory, METADATA_FILENAME), "w") as outFile:
		json.dump(metadata, outFile, indent=4)
	
	if backup_successful:
		logging.info("Job finished successfully.")
	else:
		logging.critical("The number of errors was higher than the threshold. It will considered to have failed. "
						+ "The threshold can be increased in the configuration file.")
	
	logging.info("Final statistics:\n" + stats.full_protocol())
	#TODO: new feature - compare statistics how much was planned vs how much was actually done

if __name__ == '__main__':
	# Find and load the user config file
	if len(sys.argv) < 2:
		logging.critical("Please specify the configuration file for your backup.")
		sys.exit(1)

	main(sys.argv[1])
