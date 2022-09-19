from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from ftplib import FTP
import logging
import os
from pathlib import Path, PurePath, PurePosixPath
import re
import shutil
# import sys
from typing import Any, ClassVar, Iterator, Optional

from pydantic import BaseModel

from .basics import COMPARE_METHOD, MAXTIMEDELTA, BackupError, datetimeToLocalTimestamp, timestampToDatetime
from .statistics_module import stats
from .file_methods import (FileMetadata,
                           checkConsistency,
                           checkPathAvailable,
                           dirEmpty,
                           fileBytewiseCmp,
                           relativeWalk,
                           MountedDirectoryEntry,
                           FTPDirectoryEntry)
from .config_files import ConfigFileSource


class DataSource(ABC, BaseModel):
    """
    An abstract base class for a root directory to be backed up (e.g. a local or a remote directory)
    """
    config: ConfigFileSource

    # Code for managing subclasses that implement DataSource
    _subclassRegistry: ClassVar[list[type['DataSource']]] = []
    # use a list so _default is shared between subclasses. This list may have at most one element
    _default: ClassVar[list[type['DataSource']]] = []

    def __init_subclass__(cls, default: bool = False, **kwargs: dict[str, Any]) -> None:
        super().__init_subclass__(**kwargs)
        if default:
            if len(cls._default) == 0:
                cls._default.append(cls)
            else:
                raise RuntimeError(f"Default class is already set to '{cls._default}'")
        else:
            cls._subclassRegistry.append(cls)

    @classmethod
    def parseConfigFileSource(cls, configSource: ConfigFileSource) -> 'DataSource':
        for entry in cls._subclassRegistry:
            try:
                res = entry._parseConfig(configSource)
                if res is not None:
                    return res
            except TypeError:   # abstract subclasses still show up in cls._registry
                pass
        if len(cls._default) > 0:
            try:
                res = cls._default[0]._parseConfig(configSource)
                if res is not None:
                    return res
            except TypeError:
                pass
        raise ValueError(f"Source does not match any implemented source types: '{configSource}'")

    @classmethod
    @abstractmethod
    def _parseConfig(cls, configSource: ConfigFileSource) -> Optional['DataSource']:
        """
        This should check if `configSource` matches this subclass and return an instance or None, respectively.
        If it matches but the data is invalid, it should raise a `ValueError`.
        If this is the default class, it should always return an instance.
        """

    class DataSourceConnection(ABC):
        parent: 'DataSource'
        @abstractmethod
        def scan(self, excludePaths: list[str]) -> Iterator[FileMetadata]: ...
        @abstractmethod
        def copyFile(self, relPath: PurePath, modTime: datetime, toPath: Path) -> None: ...

    @contextmanager
    def connection(self) -> Iterator[DataSourceConnection]:
        """To be used as
        ```
        with DataSource.connection() as c:
            ...
        ```"""
        # Split into two parts so subclasses do not need to explicitly
        # set the decorator @contextmanager
        yield from self._generateConnection()

    @abstractmethod
    def _generateConnection(self) -> Iterator[DataSourceConnection]:
        """This should yield exactly one `DataSourceConnection` instance. For example,
        ```
        try:
            connection = ...
            yield connection
        finally:
            connection.close()
        ```
        or
        ```
        with ...  as connection:
            yield connection
        ```"""

    @abstractmethod
    def dirEmpty(self, path: PurePath) -> bool: ...
    @abstractmethod
    def bytewiseCmp(self, sourceFile: FileMetadata, comparePath: Path) -> bool: ...
    @abstractmethod
    def available(self) -> bool: ...

    def filesEq(self, sourceFile: FileMetadata, comparePath: Path, compare_methods: list[COMPARE_METHOD]) -> bool:
        try:
            compareStat = comparePath.stat()
            compareModTime = timestampToDatetime(compareStat.st_mtime)
            for method in compare_methods:
                if method == COMPARE_METHOD.MODDATE:
                    # to avoid rounding issues which may show up, we ignore sub-microsecond differences
                    if abs(sourceFile.modTime - compareModTime) >= MAXTIMEDELTA:
                        return False
                elif method == COMPARE_METHOD.SIZE:
                    if sourceFile.fileSize != compareStat.st_size:
                        return False
                elif method == COMPARE_METHOD.BYTES:
                    if not self.bytewiseCmp(sourceFile, comparePath):
                        return False
            return True
        except Exception as e:
            stats.scanningError(f"Comparing files '{sourceFile.relPath}' and '{comparePath}' failed: ", exc_info=e)
            # If we don't know, it has to be assumed they are different, even if this might result in more file operations being scheduled
            return False


# source paths without a prefix like ftp:// or mtp:// are assumed to be directories, hence default=True
class MountedDataSource(DataSource, default=True):
    rootDir: Path

    @dataclass
    class MountedDataSourceConnection(DataSource.DataSourceConnection):
        parent: 'MountedDataSource'

        def scan(self, excludePaths: list[str]) -> Iterator[FileMetadata]:
            rootDir = self.parent.rootDir
            rootEntry = MountedDirectoryEntry(absPath=rootDir)
            if not rootDir.is_dir():
                logging.error(f"The source path '{rootDir}' is inaccessible or does not exist and will therefore be skipped.")
                return
            yield from relativeWalk(rootEntry, excludePaths)
        # def dirEmpty(self, path: PurePath) -> bool:
        #     return dirEmpty(self.dir.joinpath(path))

        def copyFile(self, relPath: PurePath, modTime: datetime, toPath: Path) -> None:
            sourcePath = self.parent.fullPath(relPath)
            # shutil.copy2 copies the modtime alongside the other metadata. We check if this agrees with the modTime we get
            # from the scanning phase. Other sources (like FTP) just apply the provided modtime
            currentModTime = timestampToDatetime(sourcePath.stat().st_mtime)
            if abs(currentModTime - modTime) >= MAXTIMEDELTA:
                logging.warning(f"File '{sourcePath}' was modified on {currentModTime}, "
                                f"expected {modTime}")
            logging.debug(f"copy from '{sourcePath}' to '{toPath}'")
            checkConsistency(sourcePath, expectedDir=False)
            shutil.copy2(sourcePath, toPath)

    @classmethod
    def _parseConfig(cls, configSource: ConfigFileSource) -> Optional[DataSource]:
        # Since `default=True`, no checks will be run
        return cls(config=configSource, rootDir=Path(configSource.dir))

    def _generateConnection(self) -> Iterator[DataSource.DataSourceConnection]:
        yield self.MountedDataSourceConnection(parent=self)

    def fullPath(self, relPath: PurePath) -> Path:
        return self.rootDir.joinpath(relPath)

    def bytewiseCmp(self, sourceFile: FileMetadata, comparePath: Path) -> bool:
        return fileBytewiseCmp(self.fullPath(sourceFile.relPath), comparePath)

    def available(self) -> bool:
        return checkPathAvailable(self.rootDir)

    def dirEmpty(self, path: PurePath) -> bool:
        return dirEmpty(self.fullPath(path))

    # required for decent logging output
    def __str__(self) -> str:
        return str(self.rootDir)


class FTPDataSource(DataSource):
    host: str
    # use PurePosixPath because it uses forward slashes and is available on all platforms
    rootDir: PurePosixPath
    username: Optional[str] = None
    password: Optional[str] = None
    port: Optional[int] = None

    @dataclass
    class FTPDataSourceConnection(DataSource.DataSourceConnection):
        parent: 'FTPDataSource'
        ftp: FTP

        def scan(self, excludePaths: list[str]) -> Iterator[FileMetadata]:
            try:
                rootEntry = FTPDirectoryEntry(absPath=self.parent.rootDir, ftp=self.ftp)
                yield from relativeWalk(rootEntry, excludePaths)
            except EOFError:
                logging.critical("The connection to the FTP server has been lost. The backup will be aborted.")
                raise BackupError

        def copyFile(self, relPath: PurePath, modTime: datetime, toPath: Path) -> None:
            fullSourcePath = self.parent.rootDir.joinpath(relPath)
            with toPath.open('wb') as toFile:
                self.ftp.retrbinary(f"RETR {fullSourcePath}", lambda b: toFile.write(b))
            # os.utime needs a timestamp in the local timezone
            modtimestamp = datetimeToLocalTimestamp(modTime)
            os.utime(toPath, (modtimestamp, modtimestamp))

    @classmethod
    def _parseConfig(cls, configSource: ConfigFileSource) -> Optional[DataSource]:
        dir = configSource.dir
        if not dir.startswith('ftp://'):
            return None
        try:
            if dir.find('@') > -1:
                # Regex documentation:
                # - first group: match anything after ftp:// until an (optional) colon or the mandatory @
                # - second group: optional; matches :passwd until the mandatory @, does not capture the colon.
                #   If there are multiple colons, the first will separate user and passwd, all the others will be part of passwd
                # - third group: match anything from the @ to the next colon, forward slash, or end
                # - fourth group: optional; matches :12345 until the end or forward slash, does not capture the colon
                #   (because the fourth group is marked as optional while the third is not, the fourth group will not participate if no colon is present)
                # - fifth group: optional; matches a forward slash and anything after that excluding @, but does not capture the forward slash;
                #   the exclusion of @ ensures that certain erroneous expressions with two @ symbols do not match
                serverData = re.fullmatch('^ftp://([^:@/]+)(?::([^@]+))?@([^:@/]+)(?::(\\d+))?(?:/([^@]*))?$', dir)
                assert serverData is not None
                # setting the default value explicitly improves type checking
                matchgroups = serverData.groups(default=None)
                assert len(matchgroups) == 5
                username, password, host, port, path = matchgroups
                assert host is not None
                # use construct here, because otherwise the validator for PurePath initialises a PureWindowsPath
                return FTPDataSource.construct(config=configSource,
                                               host=host,
                                               rootDir=PurePosixPath('' if path is None else path),
                                               username=username,
                                               password=password,
                                               port=None if port is None else int(port))
            else:
                # Scheme 2: ftp://host:port/path, and both user and password can be provided by other named parameters
                serverData = re.fullmatch('^ftp://([^:/]+)(?::(\\d+))?(?:/([^@]*))?$', dir)
                assert serverData is not None
                matchgroups = serverData.groups(default=None)
                assert len(matchgroups) == 3
                host, port, path = matchgroups
                assert host is not None
                # TODO implement extra parameters for user and password
                return FTPDataSource.construct(
                    config=configSource,
                    host=host,
                    rootDir=PurePosixPath('' if path is None else path),
                    username=None,
                    password=None,
                    port=None if port is None else int(port))
        except AssertionError:
            raise ValueError(f"FTP URL '{dir}' does not match the pattern 'ftp://user:password@host:port/path'"
                             " or 'ftp://host:port/path'.")

    def _generateConnection(self) -> Iterator[DataSource.DataSourceConnection]:
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
            # This iterator method is interrupted after the yield and resumes when the outer 'with' statement ends.
            # Then this inner with statement ends, and the connection is closed.
            yield self.FTPDataSourceConnection(parent=self, ftp=ftp)

    def bytewiseCmp(self, sourceFile: FileMetadata, comparePath: Path) -> bool:
        logging.critical("Bytewise comparison is not implemented for FTP")
        raise BackupError()

    def available(self) -> bool:
        try:
            with self.connection():
                return True
        except Exception:
            pass    # so pylance does not complain
        return False

    # TODO: Relocate the scan for empty dirs into the scanning phase, then delete this function
    def dirEmpty(self, path: PurePath) -> bool:
        return False

    # required for decent logging output (and prevents passwords from being logged)
    def __str__(self) -> str:
        return f"ftp://{self.host}{f':{self.port}' if self.port is not None else ''}/{'' if str(self.rootDir) == '.' else self.rootDir}"


##########################
# MTP support on Windows #
##########################


# if sys.platform == 'win32':
#     from .PortableDevices import PortableDevices as PD

#     class MTPDataSource(DataSource):
#         deviceName: str
#         # use PurePosixPath because it uses forward slashes and is available on all platforms
#         rootDir: PurePosixPath
#         deviceManager: ClassVar[PD.PortableDeviceManager | None] = None

#         @dataclass
#         class MTPDataSourceConnection(DataSource.DataSourceConnection):
#             parent: 'MTPDataSource'
#             pdc: PD.PortableDeviceContent

#             def scan(self, excludePaths: list[str]) -> Iterator[FileMetadata]:
#                 try:
#                     yield from relativeWalk(self.parent.rootDir, self.scanDirWPD, excludePaths)
#                 except EOFError:
#                     logging.critical("The connection to the FTP server has been lost. The backup will be aborted.")
#                     raise BackupError

#             def scanDirWPD(self, excludePaths: list[str]) -> Iterator[FileMetadata]:
#             # name = pdc.name
#             # assert isinstance(name, str)
#             # thisSourcePath = f"{parentPath}/{name}"
#             # thisTargetPath = targetPath.joinpath(name)
#             # log(thisSourcePath+'\n', logfile)
#             # # if verbose:
#             # #     print(thisSourcePath)
#             # #     print(pdc.moddate)
#             # if pdc.isFolder:
#             #     if verbose:
#             #         print(f"Creating {thisTargetPath}")
#             #     # make folder and recurse into it
#             #     thisTargetPath.mkdir(exist_ok=True)
#             #     try:
#             #         for c in pdc.getChildren():
#             #             copyPDContent(c, parentPath=thisSourcePath, targetPath=thisTargetPath, logfile=logfile, verbose=verbose)
#             #     except PD.COMError as e:
#             #         error(f"COMError in getChildren() of {thisSourcePath}: {comErrorToStr(e)}", logfile)
#             # else:
#             #     if verbose:
#             #         print(f"Copying {thisSourcePath} to {thisTargetPath}")
#             #     with thisTargetPath.open('wb') as outfile:
#             #         pdc.downloadStream(outfile)
#             # # modification timestamp
#             # #TODO do we have the modtime down to the millisecond?
#             # if pdc.moddate:
#             #     print(pdc.moddate.strftime('%Y%m%d%H%M%S.%f'))
#             #     winTimestamp = pdc.moddate.timestamp()
#             #     os.utime(thisTargetPath, (winTimestamp, winTimestamp))

#             #         #FIXME Proceed here

#             #         def scan(self, excludePaths: list[str]) -> Iterator[FileMetadata]:
#             #             try:
#             #                 yield from relativeWalkFTP(self.ftp, self.parent.rootDir, excludePaths)
#             #             except EOFError:
#             #                 logging.critical("The connection to the FTP server has been lost. The backup will be aborted.")
#             #                 raise BackupError

#             def copyFile(self, relPath: PurePath, modTime: datetime, toPath: Path) -> None:
#                 fullSourcePath = self.parent.rootDir.joinpath(relPath)
#                 with toPath.open('wb') as toFile:
#                     self.ftp.retrbinary(f"RETR {fullSourcePath}", lambda b: toFile.write(b))
#                 # os.utime needs a timestamp in the local timezone
#                 modtimestamp = datetimeToLocalTimestamp(modTime)
#                 os.utime(toPath, (modtimestamp, modtimestamp))

#         @classmethod
#         def _parseConfig(cls, configSource: ConfigFileSource) -> Optional[DataSource]:
#             dir = configSource.dir
#             if not dir.startswith('mtp://'):
#                 return None
#             try:
#                 urlmatch = re.fullmatch('^mtp://([^/]+)/(.+))$', dir)
#                 assert urlmatch is not None
#                 matchgroups = urlmatch.groups(default=None)
#                 assert len(matchgroups) == 2
#                 deviceName = matchgroups[0]
#                 pathStr = matchgroups[1]
#                 assert deviceName is not None
#                 assert pathStr is not None
#                 return MTPDataSource.construct(
#                     deviceName=deviceName,
#                     rootDir = PurePosixPath(pathStr)
#                 )
#             except AssertionError:
#                 raise ValueError(f"MTP URL '{dir}' does not match the pattern 'mtp://device/path'. "
#                                  "The path may be empty, the forward slash after device is mandatory.")

#         def _generateConnection(self) -> Iterator[DataSource.DataSourceConnection]:
#             #TODO: work out how the ctypes classes are freed / released after use
#             with FTP() as ftp:
#                 if self.port is None:
#                     ftp.connect(self.host)
#                 else:
#                     ftp.connect(self.host, port=self.port)
#                 # omit parameters which are not specified, so ftp.login sets them to default
#                 loginParams: dict[str, Any] = {}
#                 if self.username is not None:
#                     loginParams['user'] = self.username
#                 if self.password is not None:
#                     loginParams['passwd'] = self.password
#                 ftp.login(**loginParams)
#                 # This iterator method is interrupted after the yield and resumes when the outer 'with' statement ends.
#                 # Then this inner with statement ends, and the connection is closed.
#                 yield self.FTPDataSourceConnection(parent=self, ftp=ftp)

#         def bytewiseCmp(self, sourceFile: FileMetadata, comparePath: Path) -> bool:
#             logging.critical("Bytewise comparison is not implemented for FTP")
#             raise BackupError()

#         def available(self) -> bool:
#             try:
#                 with self.connection():
#                     return True
#             except Exception:
#                 pass    # so pylance does not complain
#             return False

#         # TODO: Relocate the scan for empty dirs into the scanning phase, then delete this function
#         def dirEmpty(self, path: PurePath) -> bool:
#             return False

#         # required for decent logging output (and prevents passwords from being logged)
#         def __str__(self) -> str:
#             return f"ftp://{self.host}{f':{self.port}' if self.port is not None else ''}/{'' if str(self.rootDir) == '.' else self.rootDir}"
