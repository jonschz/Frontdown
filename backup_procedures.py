import os

from collections import OrderedDict
import fnmatch
import locale
import logging
import re
from progressBar import ProgressBar

# Put the majority of the backup code here so the main file has better readability

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

# Possible actions:
# - copy (always from source to target),
# - delete (always in target)
# - hardlink (always from compare directory to target directory)
# - rename (always in target) (2-variate) (only needed for move detection)
# not implemented right now:
# - hardlink2 (alway from compare directory to target directory) (2-variate) (only needed for move detection)
def Action(type, **params):
	return OrderedDict(type=type, params=params)

# TODO: possibly buggy - what happens if a's size is a multiple of 8192, and b contains a but is longer?
def fileBytewiseCmp(a, b):
	BUFSIZE = 8192 # http://stackoverflow.com/questions/236861/how-do-you-determine-the-ideal-buffer-size-when-using-fileinputstream
	with open(a, "rb") as file1, open(b, "rb") as file2:
		while True:
			buf1 = file1.read(BUFSIZE)
			buf2 = file2.read(BUFSIZE)
			if buf1 != buf2: return False
			if not buf1: return True

def filesEq(a, b, compare_methods):
	try:
		aStat = os.stat(a)
		bStat = os.stat(b)

		equal = True
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

def dirEmpty(path):
	try:
		for entry in os.scandir(path):
			return False
		else:
			return True
	except Exception as e:
		logging.error("Scanning directory '" + path + "' failed: " + str(e))
		return True


def is_excluded(path, excludePaths):
	for exclude in excludePaths:
		if fnmatch.fnmatch(path, exclude): return True
	return False

def relativeWalk(path, excludePaths = [], startPath = None):
	"""
	Walks recursively through a directory.

	Parameters
	----------
	path : string
		The directory to be scanned
	excludePath : array of strings
		Patterns to exclude; matches using fnmatch.fnmatch against paths relative to startPath
	excludePath : startPath
		The results will be relative paths starting at startPath

	Returns
	-------
	iterator
		All files in the directory path relative to startPath
	"""
	if startPath == None: startPath = path
	if not os.path.isdir(startPath): return
	# os.walk is not used since files would always be processed separate from directories
	# But os.walk will just ignore errors, if no error callback is given, scandir will not.
	# strxfrm -> locale aware sorting - https://docs.python.org/3/howto/sorting.html#odd-and-ends
	for entry in sorted(os.scandir(path), key = lambda x: locale.strxfrm(x.name)):
		try:
			relpath = os.path.relpath(entry.path, startPath)
			
			if is_excluded(relpath, excludePaths): continue
			#logging.debug(entry.path + " ----- " + entry.name)
			if entry.is_file():
				yield relpath, False
			elif entry.is_dir():
				yield relpath, True
				yield from relativeWalk(entry.path, excludePaths, startPath)
			else:
				logging.error("Encountered an object which is neither directory nor file: " + entry.path)
		except OSError as e:
			logging.error("Error while scanning " + path + ": " + str(e))

			
def compare_pathnames(s1, s2):
	"""
	Compares two paths using locale.strcoll level by level.
	
	This comparison method is compatible to relativeWalk in the sense that the result of relativeWalk is always ordered with respect to this comparison.
	"""
	parts_s1 = re.split("([/\\\\])", s1) # Split by slashes or backslashes; quadruple escape needed; keep the slashes in the list
	parts_s2 = re.split("([/\\\\])", s2)
	for ind, part in enumerate(parts_s1):
		if ind >= len(parts_s2): return 1		# both are equal up to len(s2), s1 is longer
		coll = locale.strcoll(part, parts_s2[ind])
		if coll != 0: return coll
	if len(parts_s1) == len(parts_s2): return 0
	else: return -1						# both are equal up to len(s1), s2	is longer


def buildFileSet(sourceDir, compareDir, excludePaths):
	fileDirSet = []
	for name, isDir in relativeWalk(sourceDir, excludePaths):
		# Double check here, though relativeWalk should take care of this
		if is_excluded(name, excludePaths):
			logging.error("relativeWalk missed " + name)
			break
		else:
			fileDirSet.append(FileDirectory(name, isDirectory = isDir, inSourceDir = True, inCompareDir = False))

	logging.info("Comparing with compare directory")
	insertIndex = 0
	# Logic:
	# The (relative) paths in relativeWalk are sorted as they are created, where each folder is immediately followed by its subfolders.
	# This makes comparing folders including subfolders very efficient - We walk consecutively through sourceDir and compareDir and 
	# compare both directories on the way. If an entry exists in compareDir but not in sourceDir, we add it to fileDirSet in the right place.
	# This requires that the compare function used is consistent with the ordering - a folder must be followed by its subfolders immediately.
	# This is violated by locale.strcoll, because in it "test test" comes before "test\\test2", causing issues in specific cases.
	for name, isDir in relativeWalk(compareDir):
		# Debugging
		logging.debug("name: " + name + "; sourcePath: " + fileDirSet[insertIndex].path + "; Compare: " + str(compare_pathnames(name, fileDirSet[insertIndex].path)))
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
	