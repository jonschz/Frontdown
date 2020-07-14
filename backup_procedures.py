"""The high level methods for scanning and comparing directories.

Contains all higher-level methods and classes for scanning and comparing backup directories
as well as generating the actions for these. The actual execution of the actions is implemented
in applyActions.py.
"""

import sys
from collections import OrderedDict

from progressBar import ProgressBar
from file_methods import * #@UnusedWildImport
# from statistics_module import stats # implicit in file_methods


class BackupData:
	"""Collects any data needed to perform the backup from one source folder.
	
	Attributes:
		name: str
			A name for the particular source (like "c-users")
		sourceDir: str
			The path of the source directory for this particular root folder (like "C:\\Users").
		targetDir: str
			The path of the target directory for this particular root folder
			(like "F:\\Backups\\2019_10_10\\c-users"); it is always located at <backup root>/<source name>.
		compareDir: str
			The path where the comparison backup for this particular root folder is located
			(like "F:\\Backups\\2019_10_09\\c-users")
		fileDirSet: list
			a list of FileDirectory objects, which include (in particular) the relative paths
			of all file objects; see the documentation for FileDirectory for details
	
	"""
	# Note that the folder stucture backupDir\name is set in this init procedure!
	def __init__(self, name, sourceDir, backupDir, compareBackup, fileDirSet):
		self.name = name
		self.sourceDir = sourceDir
		self.targetDir = os.path.join(backupDir, name)
		self.compareDir = os.path.join(compareBackup, name)
		self.fileDirSet = fileDirSet
		self.actions = []
	# Returns object as a dictionary; this is for action file saving where we don't want the fileDirSet
	def to_action_json(self):
		return {
			'name': self.name,
			'sourceDir': self.sourceDir,
			'targetDir': self.targetDir,
			'compareDir': self.compareDir,
			'actions': self.actions
		}
	# Needed to get the object back from the json file
	@classmethod
	def from_action_json(cls, json_dict):
		obj = cls.__new__(cls)  # Does not call __init__
		obj.name = json_dict["name"]
		obj.sourceDir = json_dict["sourceDir"]
		obj.targetDir = json_dict["targetDir"]
		obj.compareDir = json_dict["compareDir"]
		obj.actions = json_dict["actions"]
		obj.fileDirSet = []
		return obj


class FileDirectory:
	"""An object representing a directory or file which was scanned for the purpose of being backed up.
	
	These objects are supposed to be listed in instances of BackupData.FileDirSet; see the documentation
	for further details.
	
	Attributes:
		path: str
			The path of the object relative to some backup root folder.
		isDirectory: Boolean
			True if the object is a directory, False if it is a file
		inSourceDir: Boolean
			Whether the file or folder is present in the source directory
			(at <BackupData.sourceDir>\<path>)
		inCompareDir: Boolean
			Whether the file or folder is present in the compare directory
			(at <BackupData.compareDir>\<path>)
		fileSize: Integer
			The size of the file in bytes, or 0 if it is a directory
	
	"""
	def __init__(self, path, *, isDirectory, inSourceDir, inCompareDir, fileSize=0):
		self.path = path
		self.inSourceDir = inSourceDir
		self.inCompareDir = inCompareDir
		self.isDirectory = isDirectory
		self.fileSize = 0 if isDirectory else fileSize		# zero for directories
		
	def __str__(self):
		inStr = []
		if self.inSourceDir:
			inStr.append("source dir")
		if self.inCompareDir:
			inStr.append("compare dir")
		return self.path + ("(directory)" if self.isDirectory else "") + " (" + ",".join(inStr) + ")"

# Possible actions:
# - copy (always from source to target),
# - delete (always in target)
# - hardlink (always from compare directory to target directory)
# - rename (always in target) (2-variate) (only needed for move detection)
# not implemented right now:
# - hardlink2 (alway from compare directory to target directory) (2-variate) (only needed for move detection)
def Action(actionType, isDirectory, **params):
	return OrderedDict(type=actionType, isDir=isDirectory, params=params)


def filesEq(a, b, compare_methods):
	try:
		aStat = os.stat(a)
		bStat = os.stat(b)

		for method in compare_methods:
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
				sys.exit(1)
		else:
			return True

		return False # This will be executed if break was called from the loop
	except Exception as e: # Why is there no proper list of exceptions that may be thrown by filecmp.cmp and os.stat?
		logging.error("For files '" + a + "'' and '" + b + "'' either 'stat'-ing or comparing the files failed: " + str(e))
		return False # If we don't know, it has to be assumed they are different, even if this might result in more file operations being scheduled
		

def buildFileSet(sourceDir, compareDir, excludePaths):
	logging.info("Reading source directory " + sourceDir)
	# Build the set for the source directory
	fileDirSet = []
	for name, isDir, filesize in relativeWalk(sourceDir, excludePaths):
		# update statistics
		if isDir: stats.folders_in_source += 1
		else: stats.files_in_source += 1
		stats.bytes_in_source += filesize
		fileDirSet.append(FileDirectory(name, isDirectory = isDir, inSourceDir = True, inCompareDir = False, fileSize = filesize))
	
	logging.info("Comparing with compare directory " + compareDir)
	insertIndex = 0
	# Logic:
	# The (relative) paths in relativeWalk are sorted as they are created, where each folder is immediately followed by its subfolders.
	# This makes comparing folders including subfolders very efficient - We walk consecutively through sourceDir and compareDir and 
	# compare both directories on the way. If an entry exists in compareDir but not in sourceDir, we add it to fileDirSet in the right place.
	# This requires that the compare function used is consistent with the ordering - a folder must be followed by its subfolders immediately.
	# This is violated by locale.strcoll, because in it "test test2" comes before "test\\test2", causing issues in specific cases.
	
	for name, isDir, filesize in relativeWalk(compareDir):
		# Debugging
		#logging.debug("name: " + name + "; sourcePath: " + fileDirSet[insertIndex].path + "; Compare: " + str(compare_pathnames(name, fileDirSet[insertIndex].path)))
		# update statistics
		if isDir: stats.folders_in_compare += 1
		else: stats.files_in_compare += 1
		stats.bytes_in_compare += filesize
		
		# Compare to source directory
		while insertIndex < len(fileDirSet) and compare_pathnames(name, fileDirSet[insertIndex].path) > 0:
			# Debugging
			logging.debug("name: " + name + "; sourcePath: " + fileDirSet[insertIndex].path + "; Compare: " + str(compare_pathnames(name, fileDirSet[insertIndex].path)))
			insertIndex += 1
		if insertIndex < len(fileDirSet) and compare_pathnames(name, fileDirSet[insertIndex].path) == 0:
			fileDirSet[insertIndex].inCompareDir = True
		else:
			fileDirSet.insert(insertIndex, FileDirectory(name, isDirectory = isDir, inSourceDir = False, inCompareDir = True))
		insertIndex += 1

	for file in fileDirSet:
		logging.debug(file)
	return fileDirSet


def generateActions(backupDataSet, config):
	inNewDir = None
	actions = []
	progbar = ProgressBar(50, 1000, len(backupDataSet.fileDirSet))
	
	for i, element in enumerate(backupDataSet.fileDirSet):
		progbar.update(i)

		# source\compare
		if element.inSourceDir and not element.inCompareDir:
			stats.files_to_copy += 1
			stats.bytes_to_copy += element.fileSize
			if inNewDir != None and element.path.startswith(inNewDir):
				actions.append(Action("copy", element.isDirectory, name=element.path, htmlFlags="inNewDir"))
			else:
				if element.isDirectory:
					inNewDir = element.path
					actions.append(Action("copy", True, name=element.path, htmlFlags="Folder"))
				else:
					actions.append(Action("copy", False, name=element.path))

		# source&compare
		elif element.inSourceDir and element.inCompareDir:
			if element.isDirectory:
				if config["versioned"] and config["compare_with_last_backup"]:
					# Formerly, only empty directories were created. This step was changed, as we want to create all directories
					# explicitly for setting their modification times later
					if dirEmpty(os.path.join(backupDataSet.sourceDir, element.path)):
						actions.append(Action("copy", True, name=element.path, htmlFlags="emptyFolder"))
					else:
						actions.append(Action("copy", True, name=element.path, htmlFlags="Folder"))
			else:
				# same
				if filesEq(os.path.join(backupDataSet.sourceDir, element.path), os.path.join(backupDataSet.compareDir, element.path), config["compare_method"]):
					if config["mode"] == "hardlink":
						actions.append(Action("hardlink", False, name=element.path))
						stats.files_to_hardlink += 1
						stats.bytes_to_hardlink += element.fileSize
				# different
				else:
					actions.append(Action("copy", False, name=element.path))
					stats.files_to_copy += 1
					stats.bytes_to_copy += element.fileSize

		# compare\source
		elif not element.inSourceDir and element.inCompareDir:
			if config["mode"] == "mirror":
				if not config["compare_with_last_backup"] or not config["versioned"]:
					actions.append(Action("delete", element.isDirectory, name=element.path))
					stats.files_to_delete += 1
					stats.bytes_to_delete += element.fileSize
	print("") # so the progress output from before ends with a new line
	return actions
	