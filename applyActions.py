import os, sys
import json
import shutil
import logging
from file_methods import hardlink, filesize_and_permission_check
from statistics_module import stats

from backup_procedures import BackupData
from constants import * #@UnusedWildImport
from progressBar import ProgressBar

	
			

def executeActionList(dataSet):
	logging.info("Applying actions for the target \"" + dataSet.name + "\"")
	if len(dataSet.actions) == 0:
		logging.warning("There is nothing to do for the target \"" + dataSet.name + "\"")
		return

	os.makedirs(dataSet.targetDir, exist_ok = True)
	progbar = ProgressBar(50, 1000, len(dataSet.actions))
	# Phase 1: apply the actions
	for i, action in enumerate(dataSet.actions):
		progbar.update(i)

		actionType = action["type"]
		params = action["params"]
		try:
			if actionType == "copy":
				fromPath = os.path.join(dataSet.sourceDir, params["name"])
				toPath = os.path.join(dataSet.targetDir, params["name"])
				logging.debug('copy from "' + fromPath + '" to "' + toPath + '"')
				#TODO: remove the manual checks for isFile etc., switch to action["isDir"]; test for regressions
				if os.path.isfile(fromPath):
					os.makedirs(os.path.dirname(toPath), exist_ok = True)
					shutil.copy2(fromPath, toPath)
					stats.bytes_copied += os.path.getsize(fromPath)	# If copy2 doesn't fail, getsize shouldn't either
					stats.files_copied += 1
				elif os.path.isdir(fromPath):
					os.makedirs(toPath, exist_ok = True)
				else:
					# We know there is a problem, because isfile and isdir both return false. Most likely permissions or a missing file,
					# in which case the error handling is done in the permission check. If not, throw a general error
					accessible, _ = filesize_and_permission_check(fromPath)
					if accessible: 
						logging.error("Entry \"" + fromPath + "\" exists but is neither a file nor a directory.")
						stats.backup_errors += 1
			elif actionType == "delete":
				path = os.path.join(dataSet.targetDir, params["name"])
				logging.debug('delete file "' + path + '"')
				stats.files_deleted += 1
				if os.path.isfile(path):
					stats.bytes_deleted += os.path.getsize(path)
					os.remove(path)
				elif os.path.isdir(path):
					shutil.rmtree(path)
			elif actionType == "hardlink":
				fromPath = os.path.join(dataSet.compareDir, params["name"])
				toPath = os.path.join(dataSet.targetDir, params["name"])
				logging.debug('hardlink from "' + fromPath + '" to "' + toPath + '"')
				toDirectory = os.path.dirname(toPath)
				os.makedirs(toDirectory, exist_ok = True)
				hardlink(fromPath, toPath)
				stats.bytes_hardlinked += os.path.getsize(fromPath)	# If hardlink doesn't fail, getsize shouldn't either
				stats.files_hardlinked += 1
			else:
				logging.error("Unknown action type: " + actionType)
		except Exception as e:
			logging.error(e)
			stats.backup_errors += 1
	print("") # so the progress output from before ends with a new line
	
	# Phase 2: Set the modification timestamps for all directories
	# This has to be done in a separate step, as copying into a directory will reset its modification timestamp
	logging.info("Applying directory modification timestamps for the target \"" + dataSet.name + "\"")
	progbar.update(0)
	for i, action in enumerate(dataSet.actions):
		progbar.update(i)
		params = action["params"]
		if not action["isDir"]:
			continue
		try:
			fromPath = os.path.join(dataSet.sourceDir, params["name"])
			toPath = os.path.join(dataSet.targetDir, params["name"])
			logging.debug('set modtime for "' + toPath + '"')
			modTime = os.path.getmtime(fromPath)
			os.utime(toPath, (modTime, modTime))
		except Exception as e:
			logging.error(e)
			stats.backup_errors += 1
	print("") # so the progress output from before ends with a new line
	
#TODO: No log is saved if we start from here. See other TODO in the main file for global restructuring
if __name__ == '__main__':
	if len(sys.argv) < 2:
		quit("Please specify a backup metadata directory path")

	stats.reset()
	metadataDirectory = sys.argv[1]

	fileHandler = logging.FileHandler(os.path.join(metadataDirectory, LOG_FILENAME))
	fileHandler.setFormatter(LOGFORMAT)
	logging.getLogger().addHandler(fileHandler)

	logging.info("Apply action file in backup directory " + metadataDirectory)

	dataSets = []
	with open(os.path.join(metadataDirectory, ACTIONS_FILENAME)) as actionFile:
		jsonData = json.load(actionFile)
		for jsonEntry in jsonData:
			dataSets.append(BackupData.from_action_json(jsonEntry))
	
	for dataSet in dataSets:
		executeActionList(dataSet)
	
	print(stats.backup_protocol())
