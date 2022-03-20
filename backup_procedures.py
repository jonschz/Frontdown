"""The high level methods for scanning and comparing directories.

Contains all higher-level methods and classes for scanning and comparing backup directories
as well as generating the actions for these. The actual execution of the actions is implemented
in applyActions.py.
"""
from __future__ import annotations
import sys, logging
from typing import NamedTuple, Optional
from pathlib import Path
from pydantic import BaseModel, validator, Field

from statistics_module import stats
from basics import ACTION, BACKUP_MODE, COMPARE_METHOD, HTMLFLAG
from config_files import ConfigFile
from progressBar import ProgressBar
from file_methods import fileBytewiseCmp, relativeWalk, compare_pathnames, dirEmpty

# TODO (whole file):
# * migrate to pathlib, change all str to Path

#TODO: benchmark if creating 100k of these is a significant bottleneck. If yes,
# try if a pydantic dataclass or an stdlib dataclass also does the job. Also consider using construct() 
class FileDirectory(BaseModel):
    path: Path
    inSourceDir: bool
    inCompareDir: bool
    isDirectory: bool
    fileSize: int = 0        # zero for directories
    @validator('fileSize')
    def validate_file_size(cls, v: int, values: dict[str, object]) -> int:
        if 'isDirectory' in values and values['isDirectory']:
            return 0
        else:
            return v
    """An object representing a directory or file which was scanned for the purpose of being backed up.
    
    These objects are supposed to be listed in instances of BackupData.FileDirSet; see the documentation
    for further details.
    
    Attributes:
        path: Path
            The path of the object relative to some backup root folder.
        isDirectory: bool
            True if the object is a directory, False if it is a file
        inSourceDir: bool
            Whether the file or folder is present in the source directory
            (at <BackupData.sourceDir>\\<path>)
        inCompareDir: bool
            Whether the file or folder is present in the compare directory
            (at <BackupData.compareDir>\\<path>)
        fileSize: Integer
            The size of the file in bytes, or 0 if it is a directory
    
    """        
    def __str__(self):
        inStr = []
        if self.inSourceDir:
            inStr.append("source dir")
        if self.inCompareDir:
            inStr.append("compare dir")
        return f"{self.path} {'(directory)' if self.isDirectory else ''} ({','.join(inStr)})"


# terminology:
#   sourceDir           (e.g. "C:\\Users")
#   backup_root_dir     (e.g. "D:\\Backups")
#       compareRoot     (e.g. "2021-12-31")
#           compareDir  (e.g. "c-users")
#       targetRoot      (e.g. "2022-01-01")
#           targetDir   (e.g. "c-users")
class BackupTree(BaseModel):
    name: str
    sourceDir: Path
    targetDir: Path
    compareDir: Optional[Path]
    fileDirSet: list[FileDirectory]
    actions: list[Action] = Field(default_factory=list)
    """
    Collects any data needed to perform the backup from one source folder.
    """
    def __init__(self, name: str, sourceDir: Path, targetRoot: Path, compareRoot: Optional[Path], exclude_paths: list[str]):
        """
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
        super().__init__(name=name, sourceDir=sourceDir, targetDir=targetRoot.joinpath(name),
                         compareDir = compareRoot.joinpath(name) if compareRoot is not None else None,
                         fileDirSet = [])
        # Scan the files here
        self.fileDirSet = buildFileSet(self.sourceDir, self.compareDir, exclude_paths)

    # Returns object as a dictionary; this is for action file saving where we don't want the fileDirSet
    def to_action_json(self):
        return self.dict(exclude={'fileDirSet'})
    # Needed to get the object back from the json file
    @classmethod
    def from_action_json(cls, json_dict):
        # untested code; as fileDirSet is not saved, we add a dummy here
        json_dict['fileDirSet'] = []
        return cls(**json_dict)


# Possible actions:
# - copy (always from source to target),
# - delete (always in target)
# - hardlink (always from compare directory to target directory)
# - rename (always in target) (2-variate) (only needed for move detection)
# not implemented right now:
# - hardlink2 (alway from compare directory to target directory) (2-variate) (only needed for move detection)

class Action(NamedTuple):
    type: ACTION
    isDir: bool
    name: Path
    htmlFlags: HTMLFLAG = HTMLFLAG.NONE

def filesEq(a: Path, b: Path, compare_methods: list[COMPARE_METHOD]) -> bool:
    try:
        
        aStat = a.stat()
        bStat = b.stat()

        for method in compare_methods:
            if method == COMPARE_METHOD.MODDATE:
                if aStat.st_mtime != bStat.st_mtime:
                    return False
            elif method == COMPARE_METHOD.SIZE:
                if aStat.st_size != bStat.st_size:
                    return False
            elif method == COMPARE_METHOD.BYTES:
                if not fileBytewiseCmp(a, b):
                    return False
            else:
                logging.critical("Compare method '" + method + "' does not exist")
                sys.exit(1)
        return True
    # Why is there no proper list of exceptions that may be thrown by filecmp.cmp and os.stat?
    except Exception as e: 
        logging.error(f"For files '{a}' and '{b}' either 'stat'-ing or comparing the files failed: {e}")
        # If we don't know, it has to be assumed they are different, even if this might result in more file operations being scheduled
        return False
        

def buildFileSet(sourceDir: Path, compareDir: Optional[Path], excludePaths: list[str]):
    logging.info(f"Reading source directory {sourceDir}")
    # Build the set for the source directory
    fileDirSet: list[FileDirectory] = []
    for relPath, isDir, filesize in relativeWalk(sourceDir, excludePaths):
        # update statistics
        if isDir:
            stats.folders_in_source += 1
        else:
            stats.files_in_source += 1
        stats.bytes_in_source += filesize
        fileDirSet.append(FileDirectory(path=relPath, isDirectory = isDir, inSourceDir = True, inCompareDir = False, fileSize = filesize))
    
    if compareDir is not None:
        logging.info(f"Comparing with compare directory {compareDir}")
        insertIndex = 0
        # Logic:
        # The (relative) paths in relativeWalk are sorted as they are created, where each folder is immediately followed by its subfolders.
        # This makes comparing folders including subfolders very efficient - We walk consecutively through sourceDir and compareDir and 
        # compare both directories on the way. If an entry exists in compareDir but not in sourceDir, we add it to fileDirSet in the right place.
        # This requires that the compare function used is consistent with the ordering - a folder must be followed by its subfolders immediately.
        # This is violated by locale.strcoll, because in it "test test2" comes before "test\\test2", causing issues in specific cases.
        
        for relPath, isDir, filesize in relativeWalk(compareDir):
            # Debugging
            #logging.debug("name: " + name + "; sourcePath: " + fileDirSet[insertIndex].path + "; Compare: " + str(compare_pathnames(name, fileDirSet[insertIndex].path)))
            # update statistics
            if isDir: stats.folders_in_compare += 1
            else: stats.files_in_compare += 1
            stats.bytes_in_compare += filesize
            
            # Compare to source directory
            while insertIndex < len(fileDirSet) and compare_pathnames(relPath, fileDirSet[insertIndex].path) > 0:
                # Debugging
                logging.debug(f"name: {relPath}; sourcePath: {fileDirSet[insertIndex].path}; " +
                              f"Compare: {compare_pathnames(relPath, fileDirSet[insertIndex].path)}")
                insertIndex += 1
            if insertIndex < len(fileDirSet) and compare_pathnames(relPath, fileDirSet[insertIndex].path) == 0:
                fileDirSet[insertIndex].inCompareDir = True
            else:
                fileDirSet.insert(insertIndex, FileDirectory(path=relPath, isDirectory = isDir, inSourceDir = False, inCompareDir = True))
            insertIndex += 1

        for file in fileDirSet:
            logging.debug(file)
    return fileDirSet


def generateActions(backupDataSet: BackupTree, config: ConfigFile):
    actions = []
    progbar = ProgressBar(50, 1000, len(backupDataSet.fileDirSet))
    # newDir is set to the last directory found in 'source' but not in 'compare'
    # This is used to discriminate 'copy' from 'copy_inNewDir'
    newDir: Optional[Path] = None
    
    for i, element in enumerate(backupDataSet.fileDirSet):
        progbar.update(i)

        # source\compare
        if element.inSourceDir and not element.inCompareDir:
            stats.files_to_copy += 1
            stats.bytes_to_copy += element.fileSize
            if newDir is not None and element.path.is_relative_to(newDir):
                actions.append(Action(ACTION.COPY, element.isDirectory, name=element.path, htmlFlags=HTMLFLAG.IN_NEW_DIR))
            else:
                if element.isDirectory:
                    newDir = element.path
                    actions.append(Action(ACTION.COPY, True, name=element.path, htmlFlags=HTMLFLAG.NEW_DIR))
                else:
                    actions.append(Action(ACTION.COPY, False, name=element.path, htmlFlags=HTMLFLAG.NEW))

        # source&compare
        elif element.inSourceDir and element.inCompareDir:
            # directory
            if element.isDirectory:
                if config.versioned and config.compare_with_last_backup:
                    # Formerly, only empty directories were created. This step was changed, as we want to create 
                    # all directories explicitly for setting their modification times later
                    if dirEmpty(backupDataSet.sourceDir.joinpath(element.path)):
                        if config.copy_empty_dirs:
                            actions.append(Action(ACTION.COPY, True, name=element.path, htmlFlags=HTMLFLAG.EMPTY_DIR))
                    else:
                        actions.append(Action(ACTION.COPY, True, name=element.path, htmlFlags=HTMLFLAG.EXISTING_DIR))
            # file
            else:
                assert backupDataSet.compareDir is not None
                # same
                if filesEq(backupDataSet.sourceDir.joinpath(element.path), backupDataSet.compareDir.joinpath(element.path), config.compare_method):
                    if config.mode == BACKUP_MODE.HARDLINK:
                        actions.append(Action(ACTION.HARDLINK, False, name=element.path))
                        stats.files_to_hardlink += 1
                        stats.bytes_to_hardlink += element.fileSize
                    #TODO: Think about the expected behaviour of the following settings:
                    #   versioned=true, compare_with_last_backup=true, and mode = COPY / MIRROR
                # different
                else:
                    actions.append(Action(ACTION.COPY, False, name=element.path, htmlFlags=HTMLFLAG.MODIFIED))
                    stats.files_to_copy += 1
                    stats.bytes_to_copy += element.fileSize

        # compare\source
        elif not element.inSourceDir and element.inCompareDir:
            if config.mode == BACKUP_MODE.MIRROR:
                if not config.compare_with_last_backup or not config.versioned:
                    actions.append(Action(ACTION.DELETE, element.isDirectory, name=element.path))
                    stats.files_to_delete += 1
                    stats.bytes_to_delete += element.fileSize
    print("") # so the progress output from before ends with a new line
    return actions
    