"""The high level methods for scanning and comparing directories.

Contains all higher-level methods and classes for scanning and comparing backup directories
as well as generating the actions for these. The actual execution of the actions is implemented
in applyActions.py.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any, NamedTuple, Optional
from pathlib import Path, PurePath
from pydantic import BaseModel, Field

from .statistics_module import stats
from .basics import ACTION, BACKUP_MODE, HTMLFLAG
from .config_files import ConfigFile
from .data_sources import DataSource
from .progressBar import ProgressBar
from .file_methods import FileMetadata, relativeWalkMountedDir, compare_pathnames


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
    def modTime(self) -> datetime:
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
    def createAndScan(cls, source: DataSource, targetRoot: Path, compareRoot: Optional[Path]) -> BackupTree:
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
        inst = cls.construct(name=source.config.name, source=source, targetDir=targetRoot.joinpath(source.config.name),
                             compareDir=compareRoot.joinpath(source.config.name) if compareRoot is not None else None,
                             fileDirSet=[])
        # Scan the files here
        inst.buildFileSet(source.config.exclude_paths)
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
        with self.source.connection() as connection:
            for fileData in connection.scan(excludePaths):
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
        # `newDir` is used to decide if the current file or directory is located in a directory not present in the compare backup.
        # It is set to the most recent directory found in 'source' but not in 'compare'.
        # We check for all new files and directories if they are a sub-file or sub-directory of `newDir`.
        # If the current element is a new directory that is *not* a sub-directory of the current `newDir`, `newDir` will be updated.
        # This way, if we encounter a new directory, `newDir` will not be updated until we have exausted its entire contents.
        newDir: Optional[PurePath] = None

        for i, element in enumerate(self.fileDirSet):
            def newAction(type: ACTION, htmlFlags: HTMLFLAG = HTMLFLAG.NONE) -> None:
                """Helper method to insert a new action; reduces redundant code"""
                actions.append(Action(type=type, isDir=element.isDirectory, relPath=element.relPath, modTime=element.modTime, htmlFlags=htmlFlags))

            def inNewDir() -> bool:
                """Checks if the current element is located in the current `newDir`"""
                return newDir is not None and element.relPath.is_relative_to(newDir)

            progbar.update(i)

            # source\compare
            if element.inSourceDir and not element.inCompareDir:
                # directory
                if element.isDirectory:
                    # empty
                    if self.source.dirEmpty(element.relPath):
                        if config.copy_empty_dirs:
                            newAction(ACTION.COPY, HTMLFLAG.EMPTY_DIR)
                    # full, in new directory
                    elif inNewDir():
                        newAction(ACTION.COPY, HTMLFLAG.IN_NEW_DIR)
                    # full, in existing directory
                    else:
                        newDir = element.relPath
                        newAction(ACTION.COPY, HTMLFLAG.NEW_DIR)
                # file
                else:
                    stats.files_to_copy += 1
                    stats.bytes_to_copy += element.data.fileSize
                    if inNewDir():
                        newAction(ACTION.COPY, HTMLFLAG.IN_NEW_DIR)
                    else:
                        newAction(ACTION.COPY, HTMLFLAG.NEW)

            # source&compare
            elif element.inSourceDir and element.inCompareDir:
                # directory
                if element.isDirectory:
                    if config.versioned and config.compare_with_last_backup:
                        # Formerly, only empty directories were created. This was changed because we want to create
                        # all directories explicitly for setting their modification times later
                        if self.source.dirEmpty(element.relPath):
                            if config.copy_empty_dirs:
                                newAction(ACTION.COPY, HTMLFLAG.EMPTY_DIR)
                        else:
                            newAction(ACTION.COPY, HTMLFLAG.EXISTING_DIR)
                # file
                else:
                    # for type checking; if element.inCompareDir is True, self.compareDir can't be None, but mypy can't detect this
                    assert self.compareDir is not None
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
    modTime: datetime
    htmlFlags: HTMLFLAG = HTMLFLAG.NONE
