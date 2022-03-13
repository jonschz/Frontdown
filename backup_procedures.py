"""The high level methods for scanning and comparing directories.

Contains all higher-level methods and classes for scanning and comparing backup directories
as well as generating the actions for these. The actual execution of the actions is implemented
in applyActions.py.
"""

import sys, logging
from collections import OrderedDict
from typing import Optional, Sequence
from pathlib import Path
from pydantic import BaseModel, validator

from statistics_module import stats
from basics import ACTION, BACKUP_MODE, HTMLFLAG
from config_files import ConfigFile
from progressBar import ProgressBar
from file_methods import fileBytewiseCmp, relativeWalk, compare_pathnames, dirEmpty

# TODO:
# * migrate to pathlib, change all str to Path

# TODO: 
# * Think of a better name. BackupTree? BackupFolder? 
# * refactor to pydantic / dataclass

# terminology:
#   sourceDir           (e.g. "C:\\Users")
#   backup_root_dir     (e.g. "D:\\Backups")
#       compareRoot     (e.g. "2021-12-31")
#           compareDir  (e.g. "c-users")
#       targetRoot      (e.g. "2022-01-01")
#           targetDir   (e.g. "c-users")
class BackupData:
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
        self.name = name
        self.sourceDir = sourceDir
        # targetDir and compareDir are the target and compare of this particular folder structure
        self.targetDir = targetRoot.joinpath(name)
        
        self.compareDir = compareRoot.joinpath(name) if compareRoot is not None else None
        
        # Scan the files here
        self.fileDirSet = buildFileSet(self.sourceDir, self.compareDir, exclude_paths)
        
        self.actions: list[dict[str, object]] = []
        
    # Returns object as a dictionary; this is for action file saving where we don't want the fileDirSet
    def to_action_json(self):
        return {
            'name': self.name,
            'sourceDir': self.sourceDir,
            'targetDir': self.targetDir,
            'compareDir': self.compareDir,
            'actions': self.actions
        }
    # Needed to get the object back from the json file
    @classmethod
    def from_action_json(cls, json_dict):
        obj = cls.__new__(cls)  # Does not call __init__
        obj.name = json_dict["name"]
        obj.sourceDir = json_dict["sourceDir"]
        obj.targetDir = json_dict["targetDir"]
        obj.compareDir = json_dict["compareDir"]
        obj.actions = json_dict["actions"]
        obj.fileDirSet = []
        return obj

#TODO: try if a pydantic dataclass or an stdlib dataclass also does the job
#TODO: benchmark if creating 100k of these is a significant bottleneck
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

# Possible actions:
# - copy (always from source to target),
# - delete (always in target)
# - hardlink (always from compare directory to target directory)
# - rename (always in target) (2-variate) (only needed for move detection)
# not implemented right now:
# - hardlink2 (alway from compare directory to target directory) (2-variate) (only needed for move detection)

# TODO: refactor to pydantic
def Action(actionType, isDirectory, **params):
    return OrderedDict(type=actionType, isDir=isDirectory, params=params)

def filesEq(a: Path, b: Path, compare_methods: Sequence[str]) -> bool:
    try:
        
        aStat = a.stat()
        bStat = b.stat()

        for method in compare_methods:
            if method == "moddate":
                if aStat.st_mtime != bStat.st_mtime:
                    return False
            elif method == "size":
                if aStat.st_size != bStat.st_size:
                    return False
            elif method == "bytes":
                if not fileBytewiseCmp(a, b):
                    return False
            else:
                logging.critical("Compare method '" + method + "' does not exist")
                sys.exit(1)
        return True
    # Why is there no proper list of exceptions that may be thrown by filecmp.cmp and os.stat?
    except Exception as e: 
        logging.error(f"For files '{a}' and '{b}' either 'stat'-ing or comparing the files failed: {str(e)}")
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
                              f"Compare: {str(compare_pathnames(relPath, fileDirSet[insertIndex].path))}")
                insertIndex += 1
            if insertIndex < len(fileDirSet) and compare_pathnames(relPath, fileDirSet[insertIndex].path) == 0:
                fileDirSet[insertIndex].inCompareDir = True
            else:
                fileDirSet.insert(insertIndex, FileDirectory(path=relPath, isDirectory = isDir, inSourceDir = False, inCompareDir = True))
            insertIndex += 1

        for file in fileDirSet:
            logging.debug(file)
    return fileDirSet


def generateActions(backupDataSet: BackupData, config: ConfigFile):
    inNewDir = None
    actions = []
    progbar = ProgressBar(50, 1000, len(backupDataSet.fileDirSet))
    
    for i, element in enumerate(backupDataSet.fileDirSet):
        progbar.update(i)

        # source\compare
        if element.inSourceDir and not element.inCompareDir:
            stats.files_to_copy += 1
            stats.bytes_to_copy += element.fileSize
            #TODO refactor to element.path.is_relative_to, test properly
            if inNewDir != None and str(element.path).startswith(str(inNewDir)):
                actions.append(Action(ACTION.COPY, element.isDirectory, name=element.path, htmlFlags=HTMLFLAG.IN_NEW_DIR))
            else:
                if element.isDirectory:
                    inNewDir = element.path
                    actions.append(Action(ACTION.COPY, True, name=element.path, htmlFlags=HTMLFLAG.NEW_DIR))
                else:
                    actions.append(Action(ACTION.COPY, False, name=element.path, htmlFlags=HTMLFLAG.NEW))

        # source&compare
        elif element.inSourceDir and element.inCompareDir:
            if element.isDirectory:
                if config.versioned and config.compare_with_last_backup:
                    # Formerly, only empty directories were created. This step was changed, as we want to create all directories
                    # explicitly for setting their modification times later
                    if dirEmpty(backupDataSet.sourceDir.joinpath(element.path)):
                        actions.append(Action(ACTION.COPY, True, name=element.path, htmlFlags=HTMLFLAG.EMPTY_DIR))
                    else:
                        actions.append(Action(ACTION.COPY, True, name=element.path, htmlFlags=HTMLFLAG.EXISTING_DIR))
            else:
                assert backupDataSet.compareDir is not None
                # same
                if filesEq(backupDataSet.sourceDir.joinpath(element.path), backupDataSet.compareDir.joinpath(element.path), config.compare_method):
                    if config.mode == BACKUP_MODE.HARDLINK:
                        actions.append(Action(ACTION.HARDLINK, False, name=element.path))
                        stats.files_to_hardlink += 1
                        stats.bytes_to_hardlink += element.fileSize
                    #FIXME: For modes other than hardlink, nothing is done here. Is this intended? Probably need some action for the other modes
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
    