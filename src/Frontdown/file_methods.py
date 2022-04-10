"""A collection of various file system related methods used in several other modules.

All file system related methods that are not specific to backups go into this file.

"""

import platform
import subprocess
import itertools
import os
import logging
import fnmatch
import locale
from pathlib import Path
from typing import Iterator, Optional

from Frontdown.statistics_module import stats

# TODO: What is the best place to integrate \\?\ ? In every file related function call, and we wrap it?
# Or can we make sure that the \\?\ is added in a few crucial places and always used then? Would the latter
# have any regressions / side effects?
# from ctypes.wintypes import MAX_PATH # should be 260


# TODO This code has untested modifications, in particular: does it work correctly if file1's size is a multiple of BUFSIZE?
def fileBytewiseCmp(a: Path, b: Path) -> bool:
    # https://stackoverflow.com/q/236861
    BUFSIZE = 8192
    with a.open("rb") as file1, b.open("rb") as file2:
        while True:
            buf1 = file1.read(BUFSIZE)
            buf2 = file2.read(BUFSIZE)
            if buf1 != buf2:
                return False
            if not buf1:
                return False if buf2 else True


def dirEmpty(path: Path) -> bool:
    try:
        for _ in path.iterdir():
            return False
        return True
    except Exception as e:
        logging.error(f"Scanning directory '{path}' failed: {e}")
        # declare non-readable directories as empty
        return True


def is_excluded(path: Path, excludePaths: list[str]) -> bool:
    """
    Checks if `path` matches any of the entries of `excludePaths` using `fnmatch.fnmatch()`
    """
    return any(fnmatch.fnmatch(str(path), exclude) for exclude in excludePaths)


def filesize_and_permission_check(path: Path) -> tuple[bool, int]:
    """Checks if we have os.stat permission on a given file

    Tries to call os.path.getsize (which itself calls os.stat) on path
     and does the error handling if an exception is thrown.

    Returns:
        accessible (bool), filesize (int)
    """
    try:
        filesize = path.stat().st_size
    except PermissionError:
        logging.error(f"Access denied to '{path}'")
        stats.scanning_errors += 1
        return False, 0
    except FileNotFoundError:
        logging.error(f"File or folder '{path}' cannot be found.")
        stats.scanning_errors += 1
        return False, 0
    # Which other errors can be thrown? Python does not provide a comprehensive list
    except Exception as e:
        logging.error("Unexpected exception while handling problematic file or folder: " + str(e))
        stats.scanning_errors += 1
        return False, 0
    else:
        return True, filesize


def relativeWalk(path: Path, excludePaths: list[str] = [], startPath: Optional[Path] = None) -> Iterator[tuple[Path, bool, int]]:
    """Walks recursively through a directory.

    Parameters
    ----------
    path : string
        The directory to be scanned
    excludePaths : list[str]
        Patterns to exclude; matches using fnmatch.fnmatch against paths relative to startPath
    startPath: Optional[str]
        The results will be relative paths starting at startPath

    Yields
    -------
    iterator of tuples (relativePath: String, isDirectory: Boolean, filesize: Integer)
        All files in the directory path relative to startPath; filesize is defined to be zero on directories
    """
    if startPath is None:
        startPath = path
    if not startPath.is_dir():
        return

    # TODO: refactor to path.iterdir()

    # os.walk is not used since files would always be processed separate from directories
    # But os.walk will just ignore errors, if no error callback is given, scandir will not.
    # strxfrm -> locale aware sorting - https://docs.python.org/3/howto/sorting.html#odd-and-ends
    for entry in sorted(os.scandir(path), key=lambda x: locale.strxfrm(x.name)):
        try:
            # TODO verify - run scan on full backup, compare both relpaths
            relpath = Path(entry.path).relative_to(startPath)
            # relpath = os.path.relpath(entry.path, startPath)

            if is_excluded(relpath, excludePaths):
                continue

            accessible, filesize = filesize_and_permission_check(Path(entry.path))
            if not accessible:
                # The error handling is done in permission check, we can just ignore the entry
                continue
            # logging.debug(entry.path + " ----- " + entry.name)
            if entry.is_file():
                yield relpath, False, filesize
            elif entry.is_dir():
                yield relpath, True, 0
                yield from relativeWalk(Path(entry.path), excludePaths, startPath)
            else:
                logging.error("Encountered an object which is neither directory nor file: " + entry.path)
        except OSError as e:
            logging.error(f"Error while scanning {path}: {e}")
            stats.scanning_errors += 1


def compare_pathnames(s1: Path, s2: Path) -> int:
    """
    Compares two paths using `locale.strcoll` level by level.

    This comparison method is compatible to `relativeWalk` in the sense that the result of relativeWalk is always ordered with respect to this comparison.
    """
    for part1, part2 in itertools.zip_longest(s1.parts, s2.parts, fillvalue=""):
        # if all parts are equal but one path is longer, comparing with "" yields the correct result
        coll = locale.strcoll(part1, part2)
        if coll != 0:
            return coll
    # if the loop terminates, all parts are equal
    return 0


# TODO: Check if there is a difference between hardlink and os.link on Windows
# if not, remove this code and change everything to os.link; before 3.2, os.link was not implemented on Windows,
# which might be the reason for this code
if (platform.system() == "Windows"):
    # From here: https://github.com/sid0/ntfs/blob/master/ntfsutils/hardlink.py
    import ctypes
    from ctypes import WinError
    from ctypes.wintypes import BOOL
    CreateHardLink = ctypes.windll.kernel32.CreateHardLinkW
    CreateHardLink.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p]
    CreateHardLink.restype = BOOL

    def hardlink(source, link_name):  # type: ignore
        res = CreateHardLink(link_name, source, None)
        if res == 0:
            # automatically extracts the last error that occured on Windows using getLastError()
            raise WinError()
else:
    def hardlink(source, link_name):    # type: ignore
        os.link(source, link_name)


def open_file(filename: Path) -> None:
    # from https://stackoverflow.com/a/17317468
    """A platform-independent implementation of os.startfile()."""
    if platform.system() == "Windows":
        os.startfile(filename)
    else:
        opener = "open" if platform.system() == "Darwin" else "xdg-open"
        subprocess.call([opener, str(filename)])
