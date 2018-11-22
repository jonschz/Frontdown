import os, sys

from backup_procedures import BackupData
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
		raise WinError()

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
				elif os.path.isdir(fromPath):
					os.makedirs(toPath, exist_ok = True)
				else:
					# TODO: copy this code to the scanning phase; we still need to keep it here if e.g. things change between scanning and execution
					try:
						os.stat(fromPath)
					except PermissionError:
						logging.error("Access denied to \"" + fromPath + "\"")
					except FileNotFoundError:
						logging.error("Entry \"" + fromPath + "\" cannot be found.")
					except Exception as e:	# Which other errors can be thrown? Python does not provide a comprehensive list
						logging.error("Exception while handling problematic file: " + str(e))
					else:
						logging.error("Entry \"" + fromPath + "\" is neither a file nor a directory.")
			elif actionType == "delete":
				path = os.path.join(dataSet.targetDir, params["name"])
				logging.debug('delete file "' + path + '"')

				if os.path.isfile(path):
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
			else:
				logging.error("Unknown action type: " + actionType)
		except OSError as e:
			logging.error(e)
		except IOError as e:
			logging.error(e)

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
