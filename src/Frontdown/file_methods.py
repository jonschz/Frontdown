"""A collection of various file system related methods used in several other modules.

All file system related methods that are not specific to backups go into this file.

"""

from dataclasses import dataclass
import platform
import subprocess
import itertools
import os
import fnmatch
import locale
from datetime import datetime
from pathlib import Path, PurePath
from typing import Callable, Iterator, Optional, Union

import pydantic.validators
import pydantic.json

from .basics import BackupError, timestampToDatetime
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
        stats.scanningError(f"Scanning directory '{path}' failed: {e}")
        # declare non-readable directories as empty
        return True


def is_excluded(path: Union[str, PurePath], excludePaths: list[str]) -> bool:
    """
    Checks if `path` matches any of the entries of `excludePaths` using `fnmatch.fnmatch()`
    """
    return any(fnmatch.fnmatch(str(path), exclude) for exclude in excludePaths)


def stat_and_permission_check(path: Path) -> Optional[os.stat_result]:
    """
    Checks if we have os.stat() permission on a given file.
    Returns the stat or logs the error, respectively.
    """
    try:
        fileStatistics = path.stat()
    except PermissionError:
        stats.scanningError(f"Access denied to '{path}'")
        return None
    except FileNotFoundError:
        stats.scanningError(f"File or folder '{path}' cannot be found.")
        return None
    # Which other errors can be thrown? Python does not provide a comprehensive list
    except Exception as e:
        stats.scanningError(f"Unexpected exception while scanning '{path}'.", exc_info=e)
        return None
    else:
        return fileStatistics


def checkPathAvailable(p: Path) -> bool:
    # Every platform: If the path exists, return True
    if p.exists():
        return True
    # On Windows: check if the drive letter exists
    # (if the drive is mounted but the directory does not exist, we still want to return True)
    if platform.system() == 'Windows':
        anchor = p.anchor
        if anchor != '' and Path(anchor).exists():
            return True
    # Is it possible to distinguish the following cases in Linux?
    # - A path onto a mounted device that does not exist
    # - A path to an unmounted device
    return False


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
            The path of the object relative to some backup root folder (see relativeWalk).
        isDirectory: bool
            True if the object is a directory, False if it is a file
        moddate: datetime
            Timestamp when the file was modified. Should be an aware, not a naive object, i.e. with timezone information
            (https://docs.python.org/3/library/datetime.html#aware-and-naive-objects)
        fileSize: Integer
            The size of the file in bytes, or 0 if it is a directory
    """
    relPath: PurePath
    isDirectory: bool
    modTime: datetime
    fileSize: int = 0        # zero for directories


def relativeWalk(path: PurePath,
                 scanFunction: Callable[[PurePath], Iterator[FileMetadata]],
                 excludePaths: list[str] = [],
                 startPath: Optional[PurePath] = None) -> Iterator[FileMetadata]:
    """
    Walks recursively through a local or remote directory.

    Parameters
    ----------
    path : PurePath
        The directory to be scanned.
    scanFunction : (PurePath) -> Iterator[FileMetadata]
        A function that is called to scan a given path on the target device. This function usually is
        a bound function of some connection instance. Despite the name, the yielded FileMetadata.relPath should be
        absolute and will be made relative to startPath in this function.
    excludePaths : list[str]
        Patterns to exclude; matches using fnmatch.fnmatch against paths relative to startPath.
    startPath: PurePath | None
        The resulting paths will be relative to startPath. If not provided, all results will be relative to `path`.

    Yields
    -------
    iterator of tuples (relativePath: String, isDirectory: Boolean, filesize: Integer)
        All files in the directory path relative to startPath; filesize is defined to be zero on directories
    """
    if startPath is None:
        startPath = path
    # TODO: do we need to check this? If so, how to implement?
    # TODO: test FTP with a non-existing source path
    # if not startPath.is_dir():
    #     return
    for entry in sorted(scanFunction(path), key=lambda p: locale.strxfrm(p.relPath.name)):
        # make relPath relative to startPath
        absPath = entry.relPath
        entry.relPath = absPath.relative_to(startPath)
        yield entry
        if entry.isDirectory:
            yield from relativeWalk(absPath, scanFunction, excludePaths, startPath)


# Scanning mounted directories is also needed for compare and target, which is why it should not
# be implemented in MountedDataSourceConnection
def scanDirMounted(path: PurePath) -> Iterator[FileMetadata]:
    try:
        # TODO: refactor to path.iterdir(); check if path.iterdir() has proper error handling (like missing permissions)
        for scanEntry in os.scandir(path):
            try:
                absPath = Path(scanEntry.path)
                statResult = stat_and_permission_check(absPath)
                if statResult is None:
                    # The error handling is done in permission check, we can just ignore the entry
                    continue
                # stat_result.st_mtime is a float timestamp in the local timezone
                modTime = timestampToDatetime(statResult.st_mtime)
                yield FileMetadata(relPath=absPath,
                                   isDirectory=absPath.is_dir(),
                                   modTime=modTime,
                                   fileSize=statResult.st_size)
            except OSError as e:
                # exception while handling a scan result
                stats.scanningError(f"Unexpected exception while processing '{scanEntry.path}': ", e)
    except OSError as e:
        # exception in os.scandir
        stats.scanningError(f"Error while scanning directory '{path}': {e}")


def relativeWalkMountedDir(path: PurePath,
                           excludePaths: list[str] = [],
                           startPath: Optional[PurePath] = None) -> Iterator[FileMetadata]:
    yield from relativeWalk(path, scanDirMounted, excludePaths, startPath)


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


def checkConsistency(path: Path, *, expectedDir: bool) -> None:
    """
    Checks if `path` is a directory if `expectedDir == True` or if `path` is a file if `expectedDir == False`.
    Throws a matching exception if something does not match.
    """
    # avoid two calling both is_dir() and is_file() if everything is as expected
    if (expectedDir and path.is_dir()) or (not expectedDir and path.is_file()):
        return
    if (expectedDir and path.is_file()):
        raise BackupError(f"Expected '{path}' to be a directory, got a file instead")
    if (not expectedDir and path.is_dir()):
        raise BackupError(f"Expected '{path}' to be a file, got a directory instead")
    if not path.exists():
        raise BackupError(f"The {'directory' if expectedDir else 'file'} '{path}' does not exist or cannot be accessed")
    # path exists, but is_dir() and is_file() both return False
    raise BackupError(f"Entry '{path}' exists but is neither a file nor a directory.")
