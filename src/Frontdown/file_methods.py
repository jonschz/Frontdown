"""A collection of various file system related methods used in several other modules.

All file system related methods that are not specific to backups go into this file.

"""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
import platform
import shutil
import subprocess
import itertools
import os
import logging
import fnmatch
import locale
from datetime import datetime
from pathlib import Path, PurePath, PurePosixPath
from ftplib import FTP
from typing import Any, Iterator, Optional, Union

import pydantic.validators
import pydantic.json
from pydantic import BaseModel

from .basics import COMPARE_METHOD, BackupError
from .statistics_module import stats

# from ctypes.wintypes import MAX_PATH # should be 260

# terminology:
#   source              (e.g. "C:\\Users")
#   backup_root_dir     (e.g. "D:\\Backups")
#       compareRoot     (e.g. "2021-12-31")
#           compareDir  (e.g. "c-users")
#       targetRoot      (e.g. "2022-01-01")
#           targetDir   (e.g. "c-users")


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


class DataSource(ABC, BaseModel):
    """
    An abstract base class for a root directory to be backed up (e.g. a local or a remote directory)
    """
    # This method can be overwritten by subclasses which do implement non-trivial connections
    @contextmanager
    def connection(self) -> Iterator[object]:
        yield object()

    @abstractmethod
    def scan(self, excludePaths: list[str]) -> Iterator[FileMetadata]: ...
    @abstractmethod
    def dirEmpty(self, path: PurePath) -> bool: ...
    @abstractmethod
    def bytewiseCmp(self, sourceFile: FileMetadata, comparePath: Path) -> bool: ...
    @abstractmethod
    def copyFile(self, relPath: PurePath, modTime: float, toPath: Path, connection: object) -> None: ...

    def filesEq(self, sourceFile: FileMetadata, comparePath: Path, compare_methods: list[COMPARE_METHOD]) -> bool:
        try:
            compareStat = comparePath.stat()
            for method in compare_methods:
                if method == COMPARE_METHOD.MODDATE:
                    if sourceFile.modTime != compareStat.st_mtime:
                        return False
                elif method == COMPARE_METHOD.SIZE:
                    if sourceFile.fileSize != compareStat.st_size:
                        return False
                elif method == COMPARE_METHOD.BYTES:
                    if not self.bytewiseCmp(sourceFile, comparePath):
                        return False
            return True
        # Why is there no proper list of exceptions that may be thrown by filecmp.cmp and os.stat?
        except Exception as e:
            logging.error(f"For files '{sourceFile.relPath}' and '{comparePath}' either 'stat'-ing or comparing the files failed: {e}")
            # If we don't know, it has to be assumed they are different, even if this might result in more file operations being scheduled
            return False


class MountedDataSource(DataSource):
    rootDir: Path

    def fullPath(self, relPath: PurePath) -> Path:
        return self.rootDir.joinpath(relPath)

    def scan(self, excludePaths: list[str]) -> Iterator[FileMetadata]:
        yield from relativeWalkMountedDir(self.rootDir, excludePaths)
    # def dirEmpty(self, path: PurePath) -> bool:
    #     return dirEmpty(self.dir.joinpath(path))

    def bytewiseCmp(self, sourceFile: FileMetadata, comparePath: Path) -> bool:
        return fileBytewiseCmp(self.fullPath(sourceFile.relPath), comparePath)

    # FIXME: for FTP, we need the modtime as a parameter, but for files, we get them "for free". What should we do?
    # Option 1: use the modtime in the parameter -> Problem: Will be inconsistent if the file has changed in the meantime
    # Option 2: ignore the parameter, use shutil
    # Option 3: compare the modtimes, throw a warning if they disagree
    def copyFile(self, relPath: PurePath, modTime: float, toPath: Path, connection: object) -> None:
        sourcePath = self.fullPath(relPath)
        logging.debug(f"copy from '{sourcePath}' to '{toPath}'")
        checkConsistency(sourcePath, expectedDir=False)
        shutil.copy2(sourcePath, toPath)

    # TODO is this needed?
    def dirEmpty(self, path: PurePath) -> bool:
        return dirEmpty(self.fullPath(path))

    # required for decent logging output
    def __str__(self) -> str:
        return str(self.rootDir)


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


class FTPDataSource(DataSource):
    host: str
    # use PurePosixPath because it uses forward slashes and is available on all platforms
    rootDir: PurePosixPath
    username: Optional[str] = None
    password: Optional[str] = None
    port: Optional[int] = None

    @contextmanager
    def connection(self) -> Iterator[FTP]:
        with FTP() as ftp:
            if self.port is None:
                ftp.connect(self.host)
            else:
                ftp.connect(self.host, port=self.port)
            # omit parameters which are not specified, so ftp.login sets them to default
            loginParams: dict[str, Any] = {}
            if self.username is not None:
                loginParams['user'] = self.username
            if self.password is not None:
                loginParams['passwd'] = self.password
            ftp.login(**loginParams)
            # The iterator is interrupted and resumes when the outer 'with' statement ends.
            # Then this inner with statement ends, and the connection is closed.
            yield ftp

    def scan(self, excludePaths: list[str]) -> Iterator[FileMetadata]:
        with self.connection() as ftp:
            yield from relativeWalkFTP(ftp, self.rootDir, excludePaths)

    def bytewiseCmp(self, sourceFile: FileMetadata, comparePath: Path) -> bool:
        logging.critical("Bytewise comparison is not implemented for FTP")
        raise BackupError()

    # TODO: scan for empty dirs in scanning phase, then delete this function
    def dirEmpty(self, path: PurePath) -> bool:
        return False

    def copyFile(self, relPath: PurePath, modTime: float, toPath: Path, connection: object) -> None:
        fullSourcePath = self.rootDir.joinpath(relPath)
        with toPath.open('wb') as toFile:
            # TODO is a solution using generics cleaner?
            assert isinstance(connection, FTP)
            connection.retrbinary(f"RETR {fullSourcePath}", lambda b: toFile.write(b))
        os.utime(toPath, (modTime, modTime))

    # required for decent logging output (and prevents passwords from being logged)
    def __str__(self) -> str:
        return f"ftp://{self.host}/{'' if str(self.rootDir) == '.' else self.rootDir}"
