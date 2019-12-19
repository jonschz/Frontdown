"""A collection of various file system related methods used in several other modules.

All file system related methods that are not specific to backups go into this file.

"""

import os
import logging
import fnmatch
import re
import locale
from statistics import statistics

# TODO: What is the best place to integrate \\?\ ? In every file related function call, and we wrap it?
# Or can we make sure that the \\?\ is added in a few crucial places and always used then? Would the latter
# have any regressions / side effects?
#from ctypes.wintypes import MAX_PATH # should be 260

# This code has untested modifications, in particular: does it work correctly if file1's size is a multiple of BUFSIZE?
def fileBytewiseCmp(a, b):
    BUFSIZE = 8192 # http://stackoverflow.com/questions/236861/how-do-you-determine-the-ideal-buffer-size-when-using-fileinputstream
    with open(a, "rb") as file1, open(b, "rb") as file2:
        while True:
            buf1 = file1.read(BUFSIZE)
            buf2 = file2.read(BUFSIZE)
            if buf1 != buf2: return False
            if not buf1: 
                return False if buf2 else True


def dirEmpty(path):
    try:
        for _ in os.scandir(path):    # Test if there is at least one entry
            return False
        return True
    except Exception as e:
        logging.error("Scanning directory '" + path + "' failed: " + str(e))
        return True

def is_excluded(path, excludePaths):
    for exclude in excludePaths:
        if fnmatch.fnmatch(path, exclude): return True
    return False

def filesize_and_permission_check(path):
    """Checks if we have os.stat permission on a given file

    Tries to call os.path.getsize (which itself calls os.stat) on path
     and does the error handling if an exception is thrown.
    
    Returns:
        accessible (Boolean), filesize (Integer)
    """
    try:
        filesize = os.path.getsize(path)
    except PermissionError:
        logging.error("Access denied to \"" + path + "\"")
        statistics.scanning_errors += 1
        return False, 0
    except FileNotFoundError:
        logging.error("File or folder \"" + path + "\" cannot be found.")
        statistics.scanning_errors += 1
        return False, 0
    # Which other errors can be thrown? Python does not provide a comprehensive list
    except Exception as e:            
        logging.error("Unexpected exception while handling problematic file or folder: " + str(e))
        statistics.scanning_errors += 1
        return False, 0
    else:
        return True, filesize

def relativeWalk(path, excludePaths = [], startPath = None):
    """Walks recursively through a directory.

    Parameters
    ----------
    path : string
        The directory to be scanned
    excludePath : array of strings
        Patterns to exclude; matches using fnmatch.fnmatch against paths relative to startPath
    excludePath : startPath
        The results will be relative paths starting at startPath

    Yields
    -------
    iterator of tuples (relativePath: String, isDirectory: Boolean, filesize: Integer)
        All files in the directory path relative to startPath; filesize is defined to be zero on directories
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
            
            accessible, filesize = filesize_and_permission_check(entry.path)
            if not accessible:
                # The error handling is done in permission check, we can just ignore the entry
                continue
            #logging.debug(entry.path + " ----- " + entry.name)
            if entry.is_file():
                yield relpath, False, filesize
            elif entry.is_dir():
                yield relpath, True, 0
                yield from relativeWalk(entry.path, excludePaths, startPath)
            else:
                logging.error("Encountered an object which is neither directory nor file: " + entry.path)
        except OSError as e:
            logging.error("Error while scanning " + path + ": " + str(e))
            statistics.scanning_errors += 1


# TODO: What should this function return on ("test\test2", "test/test2")? 0 or strcoll("\", "/")? Right now it is the latter    
def compare_pathnames(s1, s2):
    """
    Compares two paths using locale.strcoll level by level.
    
    This comparison method is compatible to relativeWalk in the sense that the result of relativeWalk is always ordered with respect to this comparison.
    """
    parts_s1 = re.split("([/\\\\])", s1) # Split by slashes or backslashes; quadruple escape needed; use () to keep the (back)slashes in the list
    parts_s2 = re.split("([/\\\\])", s2)
    for ind, part in enumerate(parts_s1):
        if ind >= len(parts_s2): return 1        # both are equal up to len(s2), s1 is longer
        coll = locale.strcoll(part, parts_s2[ind])
        if coll != 0: return coll
    if len(parts_s1) == len(parts_s2): return 0
    else: return -1                        # both are equal up to len(s1), s2 is longer


import platform
#TODO: Check if there is a difference between hardlink and os.link on Windows
# if not, remove this code and change everything to os.link; before 3.2, os.link was not implemented on Windows,
# which might be the reason for this code
if (platform.system() == "Windows"):
	# From here: https://github.com/sid0/ntfs/blob/master/ntfsutils/hardlink.py
	import ctypes
	from ctypes import WinError
	from ctypes.wintypes import BOOL
	CreateHardLink = ctypes.windll.kernel32.CreateHardLinkW #@UndefinedVariable
	CreateHardLink.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p]
	CreateHardLink.restype = BOOL
	def hardlink(source, link_name):
		res = CreateHardLink(link_name, source, None)
		if res == 0:
			raise WinError()    # automatically extracts the last error that occured on Windows using getLastError()
else:
	def hardlink(source, link_name):
		os.link(source, link_name)

# from https://stackoverflow.com/questions/17317219/is-there-an-platform-independent-equivalent-of-os-startfile
import subprocess
def open_file(filename):
	"""A platform-independent implementation of os.startfile()."""
	if platform.system() == "Windows":
		os.startfile(filename)
	else:
		opener ="open" if platform.system() == "Darwin" else "xdg-open"
		subprocess.call([opener, filename])
