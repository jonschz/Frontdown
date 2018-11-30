import os,sys
import json
import logging
import time

import strip_comments_json as configjson
from applyActions import executeActionList
from constants import *
from backup_procedures import *
from htmlGeneration import generateActionHTML

# Work in progress:
# - Statistics module:
#    - show progress proportional to size, not number of files (sensible for folders + hardlinks that they generate zero progress?)
#    - In the action html: a new top section with statistics

# Running TODO:
# - should a success flag be set if applyActions==false? 
# - Detailed tests for the new error handling
#	 - check: no permissions to delete, permissions to scan but not to copy
# - detailed tests of compare_pathnames; re-run full backup to check for anomalies
# - Evaluate full backup for completeness
# - Progress bars: display the current file to see which files take long; make performance tests for 100.000's of "print" commands
# - Think about which modes make sense with "versioned" and which don't, and remove "versioned" (and potentially "compare_with_last_backup" from the config file
# - Implement statistics for deletions? Might be hard: We could compute the size of everything to be deleted a priori, but how do we check what is actually being deleted, especially if we delete entire folders at once?

# Ideas
# - object-oriented rewrite of the main procedures?
# - statistics at the end for plausibility checks, possibly in file size (e.g. X GBit checked, Y GBit copied, Z GBit errors)
# - exclude directories: make sure if a directory is excluded, the contents is excluded, too (maybe not as important; wildcards seem to work)
# - more accurate condition for failure / success other than the program not having crashed (pfirsich)
# - archive bit as means of comparison (probably doesn't integrate well into the concept)
# - pfirsich's notes_todo.txt

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

if __name__ == '__main__':
	testMode = True

	# Setup logger
	logger = logging.getLogger()
	stderrHandler = logging.StreamHandler(stream=sys.stderr)
	stderrHandler.setFormatter(LOGFORMAT)
	logger.addHandler(stderrHandler)

	# Find and load the user config file
	userConfigPath = ""
	# Lazy code because PN does not support parameters to backup.py
	if testMode:
		userConfigPath = "test-setup.json"
#		userConfigPath = "test-temp.json"
	else:
		if len(sys.argv) < 2:
			logging.critical("Please specify the configuration file for your backup.")
			sys.exit(1)
		userConfigPath = sys.argv[1]

	if not os.path.isfile(userConfigPath):
		logging.critical("Configuration file '" + sys.argv[1] + "' does not exist.")
		sys.exit(1)
	with open(DEFAULT_CONFIG_FILENAME, encoding="utf-8") as configFile:
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
	

	logger.setLevel(config["log_level"])

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

	# Find the folder of the backup to compare to - one level below backupDirectory
	compareBackup = ""
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
				logging.debug("Chose old backup to compare to: " + compareBackup)
				break
			else:
				logging.error("It seems the last backup failed, so it will be skipped and the new backup will compare the source to the backup '" + backup["name"] + "'. The failed backup should probably be deleted.")
		else:
			logging.warning("No old backup found. Creating first backup.")

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
	for i,source in enumerate(config["sources"]):
		# Folder structure: backupDirectory\source["name"]\files
		if not os.path.isdir(source["dir"]):
			logging.error("The source path \"" + source["dir"] + "\" is not valid and will be skipped.")
			continue
		logging.info("Scanning source \"" + source["name"] + "\" at " + source["dir"])
		fileDirSet = buildFileSet(source["dir"], os.path.join(compareBackup, source["name"]), source["exclude-paths"])
		backupDataSets.append(BackupData(source["name"], source["dir"], backupDirectory, compareBackup, fileDirSet))
	
	# Plot intermediate statistics
	print("Scanning statistics:")
	print(statistics.scanning_protocol())
	
	# Generate actions for all data sets
	for dataSet in backupDataSets:
		if len(dataSet.fileDirSet) == 0:
			logging.warning("There are no files in the backup \"" + dataSet.name +"\". No actions will be generated.")
			continue
		logging.info("Generating actions for backup \""+dataSet.name + "\" with "+ str(len(dataSet.fileDirSet)) + " files.. ")
		dataSet.actions = generateActions(dataSet, config)
	
		
	if config["save_actionfile"]:
		# Write the action file
		actionFilePath = os.path.join(backupDirectory, ACTIONS_FILENAME)
		logging.info("Saving the action file to " + actionFilePath)
		# returns a JSON array whose entries are JSON object with a property "name" and "actions"
		actionJson = "[\n" + ",\n".join(map(lambda s:json.dumps(s.to_action_json()), backupDataSets)) + "\n]"
		with open(actionFilePath, "w") as actionFile:
			actionFile.write(actionJson)

		if config["open_actionfile"]:
			os.startfile(actionFilePath)

			
	if config["save_actionhtml"]:
		# Write HTML actions
		actionHtmlFilePath = os.path.join(backupDirectory, ACTIONSHTML_FILENAME)
		templateFilePath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.html")
		generateActionHTML(actionHtmlFilePath, templateFilePath, backupDataSets, config["exclude_actionhtml_actions"])

		if config["open_actionhtml"]:
			os.startfile(actionHtmlFilePath)

	if config["apply_actions"]:
		for dataSet in backupDataSets:
			executeActionList(dataSet)

	logging.debug("Writing \"success\" flag to the metadata file")
	# Finish Metadata: Set successful to true
	metadata["successful"] = True

	with open(os.path.join(backupDirectory, METADATA_FILENAME), "w") as outFile:
		json.dump(metadata, outFile, indent=4)
	
	logging.info("Job finished successfully.")
	
	print("Final statistics:")
	print(statistics.scanning_protocol())
	print(statistics.backup_protocol())
