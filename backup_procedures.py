import sys
from collections import OrderedDict

from progressBar import ProgressBar
from file_methods import * #@UnusedWildImport

# Put the majority of the backup code here so the main file has better readability

# A full data set for one source folder, with target directory, compare directory, and the set of all files
class BackupData:
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
def Action(actionType, **params):
	return OrderedDict(type=actionType, params=params)


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
		return False # If we don't know, it has to be assumed they are different, even if this might result in more file operatiosn being scheduled
		

def buildFileSet(sourceDir, compareDir, excludePaths):
	logging.info("Reading source directory " + sourceDir)
	# Build the set for the source directory
	fileDirSet = []
	for name, isDir, filesize in relativeWalk(sourceDir, excludePaths):
		# update statistics
		if isDir: statistics.folders_in_source += 1
		else: statistics.files_in_source += 1
		statistics.bytes_in_source += filesize
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
		if isDir: statistics.folders_in_compare += 1
		else: statistics.files_in_compare += 1
		statistics.bytes_in_compare += filesize
		
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
					if dirEmpty(os.path.join(backupDataSet.sourceDir, element.path)):
						actions.append(Action("copy", name=element.path, htmlFlags="emptyFolder"))
			else:
				# same
				if filesEq(os.path.join(backupDataSet.sourceDir, element.path), os.path.join(backupDataSet.compareDir, element.path), config["compare_method"]):
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
	