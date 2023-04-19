"""A collection of various file system related methods used in several other modules.

All file system related methods that are not specific to backups go into this file.

"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from ftplib import FTP
import logging
import platform
import subprocess
import itertools
import os
import fnmatch
import locale
from datetime import datetime, timezone
from pathlib import Path, PurePath
from typing import Final, Iterator, Optional, Union

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
    fileSize: int = 0         # zero for directories
    isEmptyDir: bool = False  # False for files


@dataclass
class DirectoryEntry(ABC):
    """
    This represents a file or folder on any mounted device together with a function to scan the foll
    """
    absPath: PurePath

    @abstractmethod
    def scandir(self) -> Iterator[tuple[DirectoryEntry, bool, datetime, int]]:
        """Yields tuples (directoryEntry, isDirectory, moddate, filesize)"""


class MountedDirectoryEntry(DirectoryEntry):
    """This represents a file or folder on a mounted device."""

    def scandir(self) -> Iterator[tuple[DirectoryEntry, bool, datetime, int]]:
        try:
            # TODO: refactor to path.iterdir(); check if path.iterdir() has proper error handling (like missing permissions)
            for scanEntry in os.scandir(self.absPath):
                try:
                    childPath = Path(scanEntry.path)
                    statResult = stat_and_permission_check(childPath)
                    if statResult is None:
                        return None
                    modTime = timestampToDatetime(statResult.st_mtime)
                    yield (MountedDirectoryEntry(absPath=childPath),
                           childPath.is_dir(),
                           modTime,
                           statResult.st_size)
                except OSError as e:
                    # exception while handling a scan result
                    stats.scanningError(f"Unexpected exception while processing '{scanEntry.path}': ", e)
        except OSError as e:
            # exception in os.scandir
            stats.scanningError(f"Error while scanning directory '{self.absPath}': {e}")


@dataclass
class FTPDirectoryEntry(DirectoryEntry):
    ftp: FTP
    FTPFACTS: Final[tuple[str, ...]] = ('size', 'modify', 'type')

    def scandir(self) -> Iterator[tuple[DirectoryEntry, bool, datetime, int]]:
        try:
            for entry in self.ftp.mlsd(path=str(self.absPath), facts=self.FTPFACTS):
                # the entry contains only the name without the path to it; for the absolute path, need to combine it with path
                childPath = self.absPath.joinpath(entry[0])
                try:
                    if not all(key in entry[1] for key in self.FTPFACTS):
                        raise ValueError(f"Fact(s) missing for '{childPath}': {[key for key in self.FTPFACTS if key not in entry[1]]}")
                    # The standard defines the modification time as YYYYMMDDHHMMSS(\.F+)? with the fractions of a second being optional,
                    # see https://datatracker.ietf.org/doc/html/rfc3659#section-2.3 . Furthermore, we assume that the FTP server works in UTC,
                    # which is true for F-Droid's primitive ftpd and the default setting for pylibftpd.
                    # The code below also works if the fractions of a second are not present.
                    # TODO try to see how well os.utime deals with 1970's: Full phone backup of '/'
                    modTime = datetime.strptime(entry[1]['modify'], '%Y%m%d%H%M%S.%f').replace(tzinfo=timezone.utc)
                    yield (FTPDirectoryEntry(absPath=childPath, ftp=self.ftp),
                           entry[1]['type'] == 'dir',
                           modTime,
                           int(entry[1]['size']))
                # Error in processing a single entry
                except ValueError as e:
                    stats.scanningError(e.args[0])
                except Exception as e:
                    stats.scanningError(f"Unexpected exception while processing '{childPath}': ", exc_info=e)
        # Error in ftp.mlsd() or propagated EOFError
        except EOFError:
            # This means a loss of connection, which should be propagated
            raise
        except Exception as e:
            stats.scanningError(f"Unexpected exception while scanning '{self.absPath}': ", exc_info=e)


def relativeWalk(start: DirectoryEntry,
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
    logging.debug(f"Scanning '{start.absPath}'")
    if startPath is None:
        startPath = start.absPath
    for entry, isDir, modtime, filesize in sorted(start.scandir(), key=lambda p: locale.strxfrm(p[0].absPath.name)):
        # make relPath relative to startPath
        relPath = entry.absPath.relative_to(startPath)
        if is_excluded(relPath, excludePaths):
            continue
        yield FileMetadata(relPath=relPath,
                           isDirectory=isDir,
                           modTime=modtime,
                           fileSize=filesize)
        if isDir:
            yield from relativeWalk(entry, excludePaths, startPath)


def relativeWalkMountedDir(path: Path,
                           excludePaths: list[str] = [],
                           startPath: Optional[PurePath] = None) -> Iterator[FileMetadata]:
    yield from relativeWalk(MountedDirectoryEntry(absPath=path), excludePaths, startPath)


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
