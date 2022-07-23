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
from datetime import datetime, timezone
from pathlib import Path, PurePath, PurePosixPath
from ftplib import FTP
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
    """
    Checks if we have os.stat() permission on a given file.
    Returns the stat or logs the error, respectively.
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
        logging.error(f"Unexpected exception while scanning '{path}'.", exc_info=e)
        stats.scanning_errors += 1
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
            The path of the object relative to some backup root folder (see the different relativeWalk functions).
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


def relativeWalkMountedDir(path: Path,
                           excludePaths: list[str] = [],
                           startPath: Optional[Path] = None) -> Iterator[FileMetadata]:
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
            # stat_result.st_mtime is a float timestamp in the local timezone
            modTime = timestampToDatetime(statResult.st_mtime)
            fileMetadata = FileMetadata(relPath=relPath, isDirectory=absPath.is_dir(), modTime=modTime, fileSize=statResult.st_size)
            if entry.is_file():
                yield fileMetadata
            elif entry.is_dir():
                yield fileMetadata
                yield from relativeWalkMountedDir(absPath, excludePaths, startPath)
            else:
                logging.error(f"Encountered an object which is neither directory nor file: '{entry.path}'")
        except OSError as e:
            # This catches errors e.g. from os.scandir() when yielding from a sub-directory
            # TODO what are the consequences of switchting the try-except with the loop?
            # If scandir() raises the exception, nothing should change. Can anything else raise an exception here?
            # Maybe is_file(), is_dir()?
            logging.error(f"Error while scanning {path}: {e}")
            stats.scanning_errors += 1


def relativeWalkFTP(ftp: FTP, path: PurePosixPath, excludePaths: list[str] = [], startPath: Optional[PurePosixPath] = None) -> Iterator[FileMetadata]:
    FTPFACTS: Final[tuple[str, ...]] = ('size', 'modify', 'type')
    if startPath is None:
        startPath = path
    # TODO: do we need to check this? If so, how to implement?
    # TODO: test FTP with a non-existing source path
    # if not startPath.is_dir():
    #     return
    # Catch the errors of ftp.mlsd() outside, and the errors of processing a single entry inside
    try:
        for entry in sorted(ftp.mlsd(path=str(path), facts=FTPFACTS), key=lambda x: locale.strxfrm(x[0])):
            # the entry contains only the name without the path to it; for the absolute path, need to combine it with path
            absPath = path.joinpath(entry[0])
            logging.debug(f"FTP Scan: {absPath}")
            try:
                relPath = absPath.relative_to(startPath)
                if is_excluded(relPath, excludePaths):
                    continue
                if not all(key in entry[1] for key in FTPFACTS):
                    raise ValueError(f"Fact(s) missing for '{absPath}': {[key for key in FTPFACTS if key not in entry[1]]}")
                # The standard defines the modification time as YYYYMMDDHHMMSS(\.F+)? with the fractions of a second being optional,
                # see https://datatracker.ietf.org/doc/html/rfc3659#section-2.3 . Furthermore, we assume that the FTP server works in UTC,
                # which is true for F-Droid's primitive ftpd and the default setting for pylibftpd.
                # The code below also works if the fractions of a second are not present.
                modTime = datetime.strptime(entry[1]['modify'], '%Y%m%d%H%M%S.%f').replace(tzinfo=timezone.utc)
                # TODO try to see how well os.utime deals with 1970's: Full phone backup of '/'
                fileMetadata = FileMetadata(relPath=relPath,
                                            isDirectory=(entry[1]['type'] == 'dir'),
                                            modTime=modTime,
                                            fileSize=int(entry[1]['size']))
                yield fileMetadata
                if fileMetadata.isDirectory:
                    yield from relativeWalkFTP(ftp, absPath, excludePaths, startPath)
            except EOFError:
                # This means a loss of connection, which should be propagated
                raise
            except Exception as e:
                # Error in processing a single entry
                logging.error(f"Error while processing '{absPath}': {e}")
                stats.scanning_errors += 1
    # TODO: Improve exception handling - split up different cases depending on the FTP source
    except EOFError:
        raise
    except Exception as e:
        # Error in ftp.mlsd()
        logging.error(f"{type(e).__name__} while scanning '{path}': {e}")
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
