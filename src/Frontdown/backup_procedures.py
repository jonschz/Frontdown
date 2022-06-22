"""The high level methods for scanning and comparing directories.

Contains all higher-level methods and classes for scanning and comparing backup directories
as well as generating the actions for these. The actual execution of the actions is implemented
in applyActions.py.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from ftplib import FTP
import os
import shutil
import logging
from typing import Any, Iterator, NamedTuple, Optional
from pathlib import Path, PurePath, PurePosixPath
from pydantic import BaseModel, Field

from .statistics_module import stats
from .basics import ACTION, BACKUP_MODE, COMPARE_METHOD, HTMLFLAG, BackupError
from .config_files import ConfigFile
from .progressBar import ProgressBar
from .file_methods import FileMetadata, fileBytewiseCmp, relativeWalkMountedDir, relativeWalkFTP, compare_pathnames, dirEmpty


# TODO: benchmark if creating 100k of these is a significant bottleneck. If yes,
# try if a pydantic dataclass or an stdlib dataclass also does the job. Also consider using construct()
@dataclass
class FileDirectory:
    data: FileMetadata
    inSourceDir: bool
    inCompareDir: bool

    @property
    def relPath(self) -> PurePath:
        return self.data.relPath

    @property
    def isDirectory(self) -> bool:
        return self.data.isDirectory

    @property
    def modTime(self) -> float:
        return self.data.modTime
    """
    An object representing a directory or file which was scanned for the purpose of being backed up.

    These objects are supposed to be listed in instances of BackupData.FileDirSet; see its documentation
    for further details.

    Attributes:
        metadata: FileMetadataa
            All data concerning the file itself (name, size, moddate, isDirectory)
        inSourceDir: bool
            Whether the file or folder is present in the source directory
            (at <BackupData.sourceDir>\\<path>)
        inCompareDir: bool
            Whether the file or folder is present in the compare directory
            (at <BackupData.compareDir>\\<path>)
    """

    def __str__(self) -> str:
        inStr = []
        if self.inSourceDir:
            inStr.append("source dir")
        if self.inCompareDir:
            inStr.append("compare dir")
        return f"{self.relPath} {'(directory)' if self.isDirectory else ''} ({','.join(inStr)})"


class DataSource(ABC, BaseModel):
    @abstractmethod
    def scan(self, excludePaths: list[str]) -> Iterator[FileMetadata]: ...
    @abstractmethod
    def dirEmpty(self, path: PurePath) -> bool: ...
    @abstractmethod
    def bytewiseCmp(self, sourceFile: FileMetadata, comparePath: Path) -> bool: ...
    @abstractmethod
    def copyFile(self, relPath: PurePath, modTime: float, toPath: Path) -> None: ...

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
    def copyFile(self, relPath: PurePath, modTime: float, toPath: Path) -> None:
        sourcePath = self.fullPath(relPath)
        logging.debug(f"copy from '{sourcePath}' to '{toPath}'")
        checkConsistency(sourcePath, expectedDir=False)
        shutil.copy2(sourcePath, toPath)

    # TODO is this needed?
    def dirEmpty(self, path: PurePath) -> bool:
        return dirEmpty(self.fullPath(path))


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


# TODO Next step: Test config and run for an FTP source
class FTPDataSource(DataSource):
    host: str
    # use PurePosixPath because it uses forward slashes and is available on all platforms
    rootDir: PurePosixPath
    username: str
    password: str
    port: Optional[int] = None

    def createFTP(self) -> FTP:
        ftp = FTP()
        try:
            if self.port is None:
                ftp.connect(self.host)
            else:
                ftp.connect(self.host, port=self.port)
            ftp.login(user=self.username, passwd=self.password)
            return ftp
        except Exception as e:
            # close the connection and re-raise the error
            try:
                ftp.close()
            except Exception:
                pass
            raise e

    def scan(self, excludePaths: list[str], ftp: Optional[FTP] = None) -> Iterator[FileMetadata]:
        if ftp is None:
            with self.createFTP() as newftp:
                yield from relativeWalkFTP(newftp, self.rootDir, excludePaths)
        else:
            yield from relativeWalkFTP(ftp, self.rootDir, excludePaths)

    def bytewiseCmp(self, sourceFile: FileMetadata, comparePath: Path) -> bool:
        logging.critical("Bytewise comparison is not implemented for FTP")
        raise BackupError()

    # TODO: scan for empty dirs in scanning phase, then delete this function
    def dirEmpty(self, path: PurePath) -> bool:
        return False

    # TODO: Reuse the FTP object for all file copies. Think about a good interface
    def copyFile(self, relPath: PurePath, modTime: float, toPath: Path, ftp: Optional[FTP] = None) -> None:
        fullSourcePath = self.rootDir.joinpath(relPath)
        with toPath.open('wb') as toFile:
            if ftp is None:
                with self.createFTP() as newftp:
                    newftp.retrbinary(f"RETR {fullSourcePath}", lambda b: toFile.write(b))
            else:
                ftp.retrbinary(f"RETR {fullSourcePath}", lambda b: toFile.write(b))
        # FIXME: files are incorrectly recongized as modified.
        # 1) compare toPath.stat() to modTime, see if they disagree
        # 2) change to an int-based type for modTime, see if that fixes things
        os.utime(toPath, (modTime, modTime))

# terminology:
#   sourceDir           (e.g. "C:\\Users")
#   backup_root_dir     (e.g. "D:\\Backups")
#       compareRoot     (e.g. "2021-12-31")
#           compareDir  (e.g. "c-users")
#       targetRoot      (e.g. "2022-01-01")
#           targetDir   (e.g. "c-users")


class BackupTree(BaseModel):
    """
    Collects all data needed to perform the backup from one source folder.
    """
    name: str
    source: DataSource
    targetDir: Path
    compareDir: Optional[Path]
    fileDirSet: list[FileDirectory]
    actions: list[Action] = Field(default_factory=list)

    @classmethod
    def createAndScan(cls, name: str, source: DataSource, targetRoot: Path, compareRoot: Optional[Path], exclude_paths: list[str]) -> BackupTree:
        """
        Alternative constructor, which infers some parameters and runs `buildFileSet`.

        Parameters:
            name: str
                The name of this source (e.g. "c-users")
            sourceDir: Path
                The path of the source directory for this particular folder (e.g. "C:\\Users").
            targetRoot: Path
                The root path of the backup being created (e.g. "D:\\Backups\\2022_01_01").
                The directory `sourceDir` will be backed up to targetRoot\\name.
            compareRoot: Path
                The root path of the comparison backup (e.g. "D:\\Backups\\2021_12_31")
            excludePaths: list[str]
                A list of rules which paths to exclude, relative to sourceDir.
                Matches using fnmatch (https://docs.python.org/3.10/library/fnmatch.html)
        """
        inst = cls.construct(name=name, source=source, targetDir=targetRoot.joinpath(name),
                             compareDir=compareRoot.joinpath(name) if compareRoot is not None else None,
                             fileDirSet=[])
        # Scan the files here
        inst.buildFileSet(exclude_paths)
        return inst

    # Returns object as a dictionary; this is for action file saving where we don't want the fileDirSet

    def to_action_json(self) -> str:
        return self.json(exclude={'fileDirSet'})

    @classmethod
    def from_action_json(cls, json_dict: dict[str, Any]) -> BackupTree:
        # untested code; as fileDirSet is not saved, we add a dummy here
        json_dict['fileDirSet'] = []
        return cls(**json_dict)

    def buildFileSet(self, excludePaths: list[str]) -> None:
        logging.info(f"Reading source directory {self.source}")
        # Build the set for the source directory
        fileDirSet: list[FileDirectory] = []
        for fileData in self.source.scan(excludePaths):
            # update statistics
            if fileData.isDirectory:
                stats.folders_in_source += 1
            else:
                stats.files_in_source += 1
            stats.bytes_in_source += fileData.fileSize
            fileDirSet.append(FileDirectory(data=fileData, inSourceDir=True, inCompareDir=False))

        if self.compareDir is not None:
            logging.info(f"Comparing with compare directory {self.compareDir}")
            insertIndex = 0
            # Logic:
            # The (relative) paths in relativeWalk are sorted as they are created, where each folder is immediately followed by its subfolders.
            # This makes comparing folders including subfolders very efficient - We walk consecutively through sourceDir and compareDir and
            # compare both directories on the way. If an entry exists in compareDir but not in sourceDir, we add it to fileDirSet in the right place.
            # This requires that the compare function used is consistent with the ordering - a folder must be followed by its subfolders immediately.
            # This is violated by locale.strcoll, because in it "test test2" comes before "test\\test2", causing issues in specific cases.

            for file in relativeWalkMountedDir(self.compareDir):
                # Warning: Do not debug output fileDirSet[insertIndex] here, as insertIndex might be equal to len(fileDirSet)
                # update statistics
                if file.isDirectory:
                    stats.folders_in_compare += 1
                else:
                    stats.files_in_compare += 1
                stats.bytes_in_compare += file.fileSize

                # Insert the entries of the compare directory into fileDirSet in the correct place
                # Step 1: skip ahead as long as file > fileDirSet[insertIndex]
                while insertIndex < len(fileDirSet) and compare_pathnames(file.relPath, fileDirSet[insertIndex].relPath) > 0:
                    # Debugging
                    logging.debug(f"comparePath: {file.relPath}; \tsourcePath: {fileDirSet[insertIndex].relPath}; \t"
                                  f"Compare: {compare_pathnames(file.relPath, fileDirSet[insertIndex].relPath)}")
                    insertIndex += 1
                # Step 2: if file == fileDirSet[insertIndex], mark fileDirSet[insertIndex] as present in compare
                if insertIndex < len(fileDirSet) and compare_pathnames(file.relPath, fileDirSet[insertIndex].relPath) == 0:
                    logging.debug(f"Found {file.relPath} in source path at index {insertIndex}")
                    fileDirSet[insertIndex].inCompareDir = True
                # Step 3: if not, insert the file (which is only present in compare) at this location
                else:
                    logging.debug(f"Did not find {file.relPath} in source path, inserted at index {insertIndex}")
                    fileDirSet.insert(insertIndex, FileDirectory(data=file, inSourceDir=False, inCompareDir=True))
                insertIndex += 1

        self.fileDirSet = fileDirSet

    def generateActions(self, config: ConfigFile) -> None:
        actions: list[Action] = []
        progbar = ProgressBar(50, 1000, len(self.fileDirSet))
        # newDir is set to the last directory found in 'source' but not in 'compare'
        # This is used to discriminate 'copy' from 'copy_inNewDir'
        newDir: Optional[PurePath] = None

        for i, element in enumerate(self.fileDirSet):
            def newAction(type: ACTION, htmlFlags: HTMLFLAG = HTMLFLAG.NONE) -> None:
                """Helper method to insert a new action; reduces redundant code"""
                actions.append(Action(type=type, isDir=element.isDirectory, relPath=element.relPath, modTime=element.modTime, htmlFlags=htmlFlags))

            progbar.update(i)

            # source\compare
            if element.inSourceDir and not element.inCompareDir:
                stats.files_to_copy += 1
                stats.bytes_to_copy += element.data.fileSize
                if newDir is not None and element.relPath.is_relative_to(newDir):
                    newAction(ACTION.COPY, HTMLFLAG.IN_NEW_DIR)
                else:
                    if element.isDirectory:
                        newDir = element.relPath
                        newAction(ACTION.COPY, HTMLFLAG.NEW_DIR)
                    else:
                        newAction(ACTION.COPY, HTMLFLAG.NEW)

            # source&compare
            elif element.inSourceDir and element.inCompareDir:
                # directory
                if element.isDirectory:
                    if config.versioned and config.compare_with_last_backup:
                        # Formerly, only empty directories were created. This step was changed, as we want to create
                        # all directories explicitly for setting their modification times later
                        if self.source.dirEmpty(element.relPath):
                            if config.copy_empty_dirs:
                                newAction(ACTION.COPY, HTMLFLAG.EMPTY_DIR)
                        else:
                            newAction(ACTION.COPY, HTMLFLAG.EXISTING_DIR)
                # file
                else:
                    assert self.compareDir is not None      # for type checking
                    # same
                    if self.source.filesEq(element.data, self.compareDir.joinpath(element.relPath), config.compare_method):
                        if config.mode == BACKUP_MODE.HARDLINK:
                            newAction(ACTION.HARDLINK)
                            stats.files_to_hardlink += 1
                            stats.bytes_to_hardlink += element.data.fileSize
                        # TODO: Think about the expected behaviour of the following settings:
                        # versioned=true, compare_with_last_backup=true, and mode = COPY / MIRROR
                    # different
                    else:
                        newAction(ACTION.COPY, HTMLFLAG.MODIFIED)
                        stats.files_to_copy += 1
                        stats.bytes_to_copy += element.data.fileSize

            # compare\source
            elif not element.inSourceDir and element.inCompareDir:
                if config.mode == BACKUP_MODE.MIRROR:
                    if not config.compare_with_last_backup or not config.versioned:
                        newAction(ACTION.DELETE)
                        stats.files_to_delete += 1
                        stats.bytes_to_delete += element.data.fileSize
        # We need to print a newline because the progress bar ends with a \r,
        # otherwise the completed progress bar will be overwritten
        print("")
        self.actions = actions


class Action(NamedTuple):
    type: ACTION
    isDir: bool
    relPath: PurePath
    modTime: float
    htmlFlags: HTMLFLAG = HTMLFLAG.NONE
