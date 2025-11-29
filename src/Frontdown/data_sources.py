from __future__ import annotations

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
import sys
from typing import Any, ClassVar, Iterator, Optional

from .basics import (
    COMPARE_METHOD, BackupError, MAXTIMEDELTA, datetimeToLocalTimestamp,
    timestampToDatetime, localTimezone)
from .statistics_module import stats
from .file_methods import (
    FileMetadata, DirectoryEntry, MountedDirectoryEntry, FTPDirectoryEntry,
    checkConsistency, checkPathAvailable, fileBytewiseCmp, relativeWalk)
from .config_files import ConfigFileSource


@dataclass
class DataSource(ABC):
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
    def parseConfigFileSource(cls, configSource: ConfigFileSource) -> DataSource:
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
        """This should yield exactly one `DataSourceConnection` instance if the source is available, and raise an FileNotFoundError
        if it is not. For example,
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
    def bytewiseCmp(self, sourceFile: FileMetadata, comparePath: Path) -> bool: ...

    def available(self) -> bool:
        try:
            # self._generateConnection() must raise a FileNotFoundError if the source is unavailable
            with self.connection():
                return True
        except FileNotFoundError as e:
            logging.debug(f"Source '{self}': not found: ", exc_info=e)
            pass    # do not return False here so pylance does not complain
        # Anything other than a FileNotFoundError is not normal, so other exceptions will be propagated
        return False

    def filesEq(self, sourceFile: FileMetadata, comparePath: Path, compare_methods: list[COMPARE_METHOD]) -> bool:
        try:
            compareStat = comparePath.stat()
            compareModTime = timestampToDatetime(compareStat.st_mtime)
            for method in compare_methods:
                if method == COMPARE_METHOD.MODDATE:
                    # to avoid rounding issues which may show up, we ignore sub-microsecond differences
                    if abs(sourceFile.modTime - compareModTime) >= MAXTIMEDELTA:
                        logging.debug("File '%s' differs in age: %s vs. %s", sourceFile.relPath, sourceFile.modTime, compareModTime)
                        return False
                elif method == COMPARE_METHOD.SIZE:
                    if sourceFile.fileSize != compareStat.st_size:
                        logging.debug("File '%s' differs in size: %i vs. %i", sourceFile.relPath, sourceFile.fileSize, compareStat.st_size)
                        return False
                elif method == COMPARE_METHOD.BYTES:
                    if not self.bytewiseCmp(sourceFile, comparePath):
                        logging.debug("File '%s' differs in bytes", sourceFile.relPath)
                        return False
            return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            stats.scanningError(f"Comparing files '{sourceFile.relPath}' and '{comparePath}' failed: ", exc_info=e)
            # If we don't know, it has to be assumed they are different, even if this might result in more file operations being scheduled
            return False


# source paths without a prefix like ftp:// or mtp:// are assumed to be directories, hence default=True
@dataclass
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
        if not checkPathAvailable(self.rootDir):
            raise FileNotFoundError(f"Could not find or access source directory '{self.rootDir}'.")
        yield self.MountedDataSourceConnection(parent=self)

    def fullPath(self, relPath: PurePath) -> Path:
        return self.rootDir.joinpath(relPath)

    def bytewiseCmp(self, sourceFile: FileMetadata, comparePath: Path) -> bool:
        return fileBytewiseCmp(self.fullPath(sourceFile.relPath), comparePath)

    # required for decent logging output
    def __str__(self) -> str:
        return str(self.rootDir)


@dataclass
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
                return FTPDataSource(config=configSource,
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
                return FTPDataSource(
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
            try:
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
            except (TimeoutError, ConnectionError) as e:
                # these kinds of errors can happen if the FTP server is not available
                raise FileNotFoundError(e)

    def bytewiseCmp(self, sourceFile: FileMetadata, comparePath: Path) -> bool:
        logging.critical("Bytewise comparison is not implemented for FTP")
        raise BackupError()

    # required for decent logging output (and prevents passwords from being logged)
    def __str__(self) -> str:
        return f"ftp://{self.host}{f':{self.port}' if self.port is not None else ''}/{'' if str(self.rootDir) == '.' else self.rootDir}"


##########################
# MTP support on Windows #
##########################


if sys.platform == 'win32':
    from .PortableDevices import PortableDevices as PD
    # disable mypy until further work has been done
    from .PortableDevices.PortableDevices import comErrorToStr, PortableDeviceContent, COMError

    @dataclass
    class WPDDirectoryEntry(DirectoryEntry):
        pdc: PortableDeviceContent

        def scandir(self) -> Iterator[tuple[DirectoryEntry, bool, datetime, int]]:
            try:
                # separate reading the IDs and the data of the children so if there is an error
                # in one child, its sister elements can still be read
                for childID in self.pdc.getChildIDs():
                    try:
                        child = PortableDeviceContent(self.pdc.content,
                                                      childID,
                                                      self.pdc.properties,
                                                      errorIfModdateUnavailable=True)
                        childPath = self.absPath.joinpath(child.name)
                        childEntry = WPDDirectoryEntry(absPath=childPath, pdc=child)
                        # for mypy/pylance only; setting errorIfModdateUnavailable=True guarantees this
                        assert child.moddate is not None
                        # PortableDeviceContent.moddate is a naive datetime in the timezone of the connected device.
                        # I am not aware of a way to extract this timezone information. If the device supports
                        # WPD_DEVICE_DATETIME, one could at least guess the timezone. However, my devices do not support
                        # this feature, so I can't test it.
                        moddate = child.moddate.replace(tzinfo=localTimezone())
                        yield (childEntry, child.isFolder, moddate, child.filesize)
                    # errors in one child
                    except (ValueError, COMError) as e:
                        stats.scanningError(f"Error while reading a child of {self.absPath}: {e}")
            # TODO: abort or continue?
            # TODO: try to disconnect the phone while scanning, analyse the errors that appear
            except COMError as e:
                stats.scanningError(f"COMError in reading the children of {self.absPath}: {comErrorToStr(e)}")
            except Exception as e:
                stats.scanningError(f"Unexpected error in reading the children of {self.absPath}", e)

    @dataclass
    class MTPDataSource(DataSource):
        deviceName: str
        # use PurePosixPath because it uses forward slashes and is available on all platforms
        rootDir: PurePosixPath

        @dataclass
        class MTPDataSourceConnection(DataSource.DataSourceConnection):
            parent: 'MTPDataSource'
            pdc: PortableDeviceContent

            def scan(self, excludePaths: list[str]) -> Iterator[FileMetadata]:
                try:
                    dirEntry = WPDDirectoryEntry(self.parent.rootDir, self.pdc)
                    yield from relativeWalk(dirEntry, excludePaths)
                # except COMError as e?
                except Exception:
                    # TODO improve exception handling
                    logging.critical("The connection to the MTP device has been lost. The backup will be aborted.")
                    raise BackupError

            def copyFile(self, relPath: PurePath, modTime: datetime, toPath: Path) -> None:
                entry = self.pdc.getPath(str(relPath))
                if entry is None:
                    raise FileNotFoundError(f"'{str(self.parent)}/{relPath}' could not be found on the MTP device.")
                with toPath.open('wb') as toFile:
                    entry.downloadStream(toFile)
                # os.utime needs a timestamp in the local timezone
                modtimestamp = datetimeToLocalTimestamp(modTime)
                os.utime(toPath, (modtimestamp, modtimestamp))

        @classmethod
        def _parseConfig(cls, configSource: ConfigFileSource) -> Optional[DataSource]:
            dir = configSource.dir
            if not dir.startswith('mtp://'):
                return None
            try:
                urlmatch = re.fullmatch('^mtp://([^/]+)/(.+)$', dir)
                assert urlmatch is not None
                matchgroups = urlmatch.groups(default=None)
                assert len(matchgroups) == 2
                deviceName = matchgroups[0]
                pathStr = matchgroups[1]
                assert deviceName is not None
                assert pathStr is not None
                return MTPDataSource(
                    config=configSource,
                    deviceName=deviceName,
                    rootDir=PurePosixPath(pathStr)
                )
            except AssertionError:
                raise ValueError(f"MTP URL '{dir}' does not match the pattern 'mtp://device/path'. "
                                 "The path may be empty, the forward slash after 'device' is mandatory.")

        def _generateConnection(self) -> Iterator[DataSource.DataSourceConnection]:
            # comtypes instances are released in __del__, which is usually called when there are no more references
            # to the object (see https://www.youtube.com/watch?v=IFjuQmlwXgU). Cleaner solutions could be possible,
            # but that would likely require large scale changes to comtypes. For now, don't free anything, it is
            # likely done automatically.
            #
            # Use a new PortableDeviceManager at every call because an instance does not get updated:
            # If the user connects their device after the DeviceManager is created (e.g. after the prompt for
            # a missing source), it will never be returned by the existing DeviceManager.
            #
            # Use a local variable so the reference count hits zero at the end of this function
            #
            #
            deviceManager = PD.PortableDeviceManager()
            # TODO test alternative: use RefreshDeviceList(), keep deviceManager global ClassVar[]
            # deviceManager.deviceManager.RefreshDeviceList()
            device = deviceManager.getDeviceByName(self.deviceName)
            if device is None:
                raise FileNotFoundError(f"Could not find the MTP device '{self.deviceName}'.")
            # TODO How well does this work with relative paths, e.g. str(self.rootDir) == './abc/def'?
            pdc = device.getContent().getPath(str(self.rootDir))
            if pdc is None:
                raise FileNotFoundError(f"Could not find the root folder '{self.rootDir}' on the MTP device '{self.deviceName}'.")
            yield self.MTPDataSourceConnection(parent=self, pdc=pdc)

        def bytewiseCmp(self, sourceFile: FileMetadata, comparePath: Path) -> bool:
            logging.critical("Bytewise comparison is not implemented for MTP")
            raise BackupError()

        # required for decent logging output
        def __str__(self) -> str:
            return f"mtp://{self.deviceName}/{'' if str(self.rootDir) == '.' else self.rootDir}"
