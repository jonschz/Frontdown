"""A collection of various file system related methods used in several other modules.

All file system related methods that are not specific to backups go into this file.

"""

from dataclasses import dataclass
import platform
import subprocess
import itertools
import os
import logging
import fnmatch
import locale
from datetime import datetime
from pathlib import Path, PurePath, PurePosixPath
from ftplib import FTP
from typing import Iterator, Optional, Union

import pydantic.validators
import pydantic.json

from .statistics_module import stats

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


def is_excluded(path: Union[str, PurePath], excludePaths: list[str]) -> bool:
    """
    Checks if `path` matches any of the entries of `excludePaths` using `fnmatch.fnmatch()`
    """
    return any(fnmatch.fnmatch(str(path), exclude) for exclude in excludePaths)


def stat_and_permission_check(path: Path) -> Optional[os.stat_result]:
    """Checks if we have os.stat permission on a given file

    Tries to call os.path.getsize (which itself calls os.stat) on path
     and does the error handling if an exception is thrown.

    Returns:
        accessible (bool), filesize (int)
    """
    try:
        fileStatistics = path.stat()
    except PermissionError:
        logging.error(f"Access denied to '{path}'")
        stats.scanning_errors += 1
        return None
    except FileNotFoundError:
        logging.error(f"File or folder '{path}' cannot be found.")
        stats.scanning_errors += 1
        return None
    # Which other errors can be thrown? Python does not provide a comprehensive list
    except Exception as e:
        logging.error("Unexpected exception while handling problematic file or folder: " + str(e))
        stats.scanning_errors += 1
        return None
    else:
        return fileStatistics


# this is kind of dirty, but it works well enough
# TODO: think about cleaner solutions
# - do we need to export and import FileMetadata? If not, we might allow arbitrary types
# because Path shows up in _VALIDATORS and is a subclass of PurePath, we must insert PurePath at the end
pydantic.validators._VALIDATORS.append((PurePath, [lambda x: PurePath(x)]))
pydantic.json.ENCODERS_BY_TYPE[PurePath] = str


@dataclass
class FileMetadata:
    """
    An object representing a directory or file which was scanned for the purpose of being backed up.

    These objects are supposed to be listed in instances of BackupData.FileDirSet; see its documentation
    for further details.

    Attributes:
        relPath: PurePath
            The path of the object relative to some backup root folder (see the different relativeWalk functions).
        isDirectory: bool
            True if the object is a directory, False if it is a file
        moddate: float
            Timestamp when the file was modified
        fileSize: Integer
            The size of the file in bytes, or 0 if it is a directory
    """
    relPath: PurePath
    isDirectory: bool
    modTime: float
    fileSize: int = 0        # zero for directories


def relativeWalkMountedDir(path: Path, excludePaths: list[str] = [], startPath: Optional[Path] = None) -> Iterator[FileMetadata]:
    """Walks recursively through a directory.

    Parameters
    ----------
    path : Path
        The directory to be scanned
    excludePaths : list[str]
        Patterns to exclude; matches using fnmatch.fnmatch against paths relative to startPath
    startPath: Optional[str]
        The resulting paths will be relative to startPath. If not provided, all results will be relative to `path`

    Yields
    -------
    iterator of tuples (relativePath: String, isDirectory: Boolean, filesize: Integer)
        All files in the directory path relative to startPath; filesize is defined to be zero on directories
    """
    if startPath is None:
        startPath = path
    if not startPath.is_dir():
        return

    # TODO: refactor to path.iterdir(); check if path.iterdir() has proper error handling (like missing permissions)

    # os.walk is not used since files would always be processed separate from directories
    # But os.walk will just ignore errors, if no error callback is given, scandir will not.
    # strxfrm -> locale aware sorting - https://docs.python.org/3/howto/sorting.html#odd-and-ends
    for entry in sorted(os.scandir(path), key=lambda x: locale.strxfrm(x.name)):
        try:
            absPath = Path(entry.path)
            relPath = absPath.relative_to(startPath)

            if is_excluded(relPath, excludePaths):
                continue

            statResult = stat_and_permission_check(absPath)
            if statResult is None:
                # The error handling is done in permission check, we can just ignore the entry
                continue

            fileMetadata = FileMetadata(relPath=relPath, isDirectory=absPath.is_dir(), modTime=statResult.st_mtime, fileSize=statResult.st_size)
            if entry.is_file():
                yield fileMetadata
            elif entry.is_dir():
                yield fileMetadata
                yield from relativeWalkMountedDir(absPath, excludePaths, startPath)
            else:
                logging.error("Encountered an object which is neither directory nor file: " + entry.path)
        except OSError as e:
            logging.error(f"Error while scanning {path}: {e}")
            stats.scanning_errors += 1


# datetime.timestamp() raises an exception for modtimes earlier than this
earliestTime = datetime(1970, 1, 2, 1, 0, 0)


def relativeWalkFTP(ftp: FTP, path: PurePosixPath, excludePaths: list[str] = [], startPath: Optional[PurePosixPath] = None) -> Iterator[FileMetadata]:
    if startPath is None:
        startPath = path
    # TODO: do we need to check this? If so, how to implement?
    # TODO: test FTP with a non-existing source path
    # if not startPath.is_dir():
    #     return
    try:
        for entry in sorted(ftp.mlsd(path=str(path), facts=['size', 'modify', 'type']), key=lambda x: locale.strxfrm(x[0])):
            # the entry contains only the name without the path to it; for the absolute path, need to combine it with path
            absPath = path.joinpath(entry[0])
            relPath = absPath.relative_to(startPath)
            if is_excluded(relPath, excludePaths):
                continue

            # TODO check if this works as expected with 1970 files
            # This needs proper testing. In particular: does Windows act up if we set the modtime = 0. or modtime=-1.?
            modtime = datetime.strptime(entry[1]['modify'], '%Y%m%d%H%M%S.%f')
            if modtime > earliestTime:
                modstamp = modtime.timestamp()
            else:
                modstamp = 0.
            fileMetadata = FileMetadata(relPath=relPath, isDirectory=(entry[1]['type'] == 'dir'),
                                        modTime=modstamp, fileSize=int(entry[1]['size']))
            yield fileMetadata
            if fileMetadata.isDirectory:
                yield from relativeWalkFTP(ftp, absPath, excludePaths, startPath)
    # TODO: Improve exception handling - split up different cases depending on the FTP source
    except Exception as e:
        logging.error(f"Error while scanning {path}: {e}")
        stats.scanning_errors += 1


def compare_pathnames(s1: PurePath, s2: PurePath) -> int:
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


def open_file(filename: Path) -> None:
    # from https://stackoverflow.com/a/17317468
    """A platform-independent implementation of os.startfile()."""
    if platform.system() == "Windows":
        os.startfile(filename)
    else:
        opener = "open" if platform.system() == "Darwin" else "xdg-open"
        subprocess.call([opener, str(filename)])
