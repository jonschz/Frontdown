import os, sys

from backup_procedures import *
import json
import shutil
import logging

from constants import *
from progressBar import ProgressBar

# From here: https://github.com/sid0/ntfs/blob/master/ntfsutils/hardlink.py
import ctypes
from ctypes import WinError
from ctypes.wintypes import BOOL
CreateHardLink = ctypes.windll.kernel32.CreateHardLinkW
CreateHardLink.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p]
CreateHardLink.restype = BOOL

def hardlink(source, link_name):
	res = CreateHardLink(link_name, source, None)
	if res == 0:
		raise WinError()	# automatically extracts the last error that occured on Windows using getLastError()

def executeActionList(dataSet):
	logging.info("Applying actions for the target \"" + dataSet.name + "\"")
	if len(dataSet.actions) == 0:
		logging.warning("There is nothing to do for the target \"" + dataSet.name + "\"")
		return

	os.makedirs(dataSet.targetDir, exist_ok = True)
	progbar = ProgressBar(50, 1000, len(dataSet.actions))
	for i, action in enumerate(dataSet.actions):
		progbar.update(i)

		actionType = action["type"]
		params = action["params"]
		try:
			if actionType == "copy":
				fromPath = os.path.join(dataSet.sourceDir, params["name"])
				toPath = os.path.join(dataSet.targetDir, params["name"])
				logging.debug('copy from "' + fromPath + '" to "' + toPath + '"')

				if os.path.isfile(fromPath):
					os.makedirs(os.path.dirname(toPath), exist_ok = True)
					shutil.copy2(fromPath, toPath)
					statistics.bytes_copied += os.path.getsize(fromPath)	# If copy2 doesn't fail, getsize shouldn't either
					statistics.files_copied += 1
				elif os.path.isdir(fromPath):
					os.makedirs(toPath, exist_ok = True)
				else:
					# We know there is a problem, because isfile and isdir both return false. Most likely permissions or a missing file,
					# in which case the error handling is done in the permission check. If not, throw a general error
					accessible, filesize = filesize_and_permission_check(fromPath)
					if accessible: 
						logging.error("Entry \"" + fromPath + "\" exists but is neither a file nor a directory.")
						statistics.backup_errors += 1
			elif actionType == "delete":
				path = os.path.join(dataSet.targetDir, params["name"])
				logging.debug('delete file "' + path + '"')

				if os.path.isfile(path):
					os.remove(path)
				elif os.path.isdir(path):
					shutil.rmtree(path)
			elif actionType == "hardlink":
				# TODO: possibly more error handling here? It should be covered in the scanning phase, but this part should still be autonomous
				fromPath = os.path.join(dataSet.compareDir, params["name"])
				toPath = os.path.join(dataSet.targetDir, params["name"])
				logging.debug('hardlink from "' + fromPath + '" to "' + toPath + '"')
				toDirectory = os.path.dirname(toPath)
				os.makedirs(toDirectory, exist_ok = True)
				hardlink(fromPath, toPath)
				statistics.bytes_hardlinked += os.path.getsize(fromPath)	# If hardlink doesn't fail, getsize shouldn't either
				statistics.files_hardlinked += 1
			else:
				logging.error("Unknown action type: " + actionType)
		except OSError as e:
			logging.error(e)
			statistics.backup_errors += 1
		except IOError as e:
			logging.error(e)
			statistics.backup_errors += 1

	print("") # so the progress output from before ends with a new line

if __name__ == '__main__':
	if len(sys.argv) < 2:
		quit("Please specify a backup metadata directory path")

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
