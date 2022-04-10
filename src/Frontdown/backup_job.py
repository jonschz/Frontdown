'''
Created on 02.09.2020

@author: Jonathan
'''

import os
import logging
import json
from pathlib import Path
import time
import shutil
from enum import Enum
from typing import Optional
from pydantic import BaseModel

from Frontdown.basics import  BackupError, constants, DRIVE_FULL_ACTION
from Frontdown.statistics_module import stats, sizeof_fmt
from Frontdown.config_files import ConfigFile, ConfigFileSource
from Frontdown.file_methods import open_file
from Frontdown.backup_procedures import BackupTree, generateActions
from Frontdown.htmlGeneration import generateActionHTML
from Frontdown.applyActions import executeActionList


#FIXME: temporary fix - long term solution is to change metadata to pydantic
def dump_default(obj):
    if hasattr(obj, 'dict'):
        return obj.dict()
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError()

class backupMetadata(BaseModel):
    name: str
    successful: bool
    started: float      # seconds since the epoch; time.time()
    sources: list[ConfigFileSource]
    # previously, if there was no compareBackup, it was exported as compareBackup: ''
    # this was now changed to compareBackup: null
    compareBackup: Optional[Path]
    backupDirectory: Path

class backupJob:
    class initMethod(Enum):
        fromConfigFile = 0
        fromActionFile = 1
# needs:
# - probably status: has the scanning phase run yet?
# - constructor from
#    - config file
#    - action+metadata file
#
    def __init__(self, method: initMethod, logger: logging.Logger, path: Path):
        """
            method:    an instance of backupJob.initMethod
            logger:    an instance of logging.Logger
            path: depending on method:
                method = fromConfigFile: the path to the config file
                method = fromActionFile: the path to the backup folder (containing the action file)
        """
        if method == self.initMethod.fromConfigFile:
            self.loadFromConfigFile(logger, path)
        elif method == self.initMethod.fromActionFile:
            self.resumeFromActionFile(logger, path)
        else:
            raise ValueError(f"Invalid parameter: {method=}")

    def loadFromConfigFile(self, logger: logging.Logger, userConfigPath: Path):
        # Locate and load config file
        if not os.path.isfile(userConfigPath):
            logging.critical(f"Configuration file '{userConfigPath}' does not exist.")
            raise BackupError
        
        self.config = ConfigFile.loadUserConfig(userConfigPath)
    
        logger.setLevel(self.config.log_level)
    
        # TODO check + error log if the backup root does not exist
        # create root directory if necessary
        os.makedirs(self.config.backup_root_dir, exist_ok = True)
    
        # Make sure that in the "versioned" mode, the backup path is unique: Use a timestamp (plus a suffix if necessary)
        if self.config.versioned:
            self.targetRoot = self.findTargetRoot()
        else:
            self.targetRoot = self.config.backup_root_dir
    
        # At this point: config is read, backup directory is set, now start the actual work
        self.setupLogFile(logger)
        
        
    def resumeFromActionFile(self, logger, backupDirectory):
        raise NotImplementedError("This feature is not yet implemented. Please see the comments for what is necessary")
        
        #  Problem 1: The statistics from the first phase are missing. We would have to save them in the metadata.
        #             They are required for checking if the scanning phase has finished correctly.
        #  Problem 2: There is no way to access the config file. We would need to copy the config file to the backup
        #             directory to load it, or pass it as an additional parameter
        # self.state = backupState.afterScan
        # self.backupDirectory = backupDirectory
        # # Load the copied config file
        # # Load the saved statistics
        # self.setupLogFile(logger)

    def setupLogFile(self, logger: logging.Logger):
        # Add the file handler to the log file
        fileHandler = logging.FileHandler(self.targetRoot.joinpath(constants.LOG_FILENAME))
        fileHandler.setFormatter(constants.LOGFORMAT)
        logger.addHandler(fileHandler)

    def performScanningPhase(self):
        self.compareRoot = self.findCompareRoot()
        
        # Prepare metadata.json; the 'successful' flag will be changed at the very end
        #TODO change basename to pathlib
        self.metadata = backupMetadata(name = os.path.basename(self.targetRoot),
                                       successful = False,
                                       started = time.time(),
                                       sources = self.config.sources,
                                       compareBackup = self.compareRoot,
                                       backupDirectory = self.targetRoot)
        #         '
        #         ',
        #         ',
        #         'backupDirectory': self.targetRoot,)
        # self.metadata = {
        #         'name': os.path.basename(self.targetRoot),
        #         'successful': False,
        #         'started': time.time(),
        #         'sources': self.config.sources,
        #         'compareBackup': self.compareRoot,
        #         'backupDirectory': self.targetRoot,
        #     }
        with self.targetRoot.joinpath(constants.METADATA_FILENAME).open("w") as outFile:
            outFile.write(self.metadata.json(indent=4))
            # json.dump(self.metadata, outFile, indent=4, default = dump_default)
    
        # Build a list of all files in source directory and compare directory
        logging.info("Building file set.")
        self.backupDataSets: list[BackupTree] = []
        for source in self.config.sources:
            # Folder structure: backupDirectory\source.name\files
            if not os.path.isdir(source.dir):
                logging.error(f"The source path '{source.dir}' does not exist and will be skipped.")
                continue
            logging.info(f"Scanning source '{source.name}' at {source.dir}")
            self.backupDataSets.append(BackupTree(source.name, source.dir, self.targetRoot, self.compareRoot, source.exclude_paths))
        
        # Plot intermediate statistics
        logging.info("Scanning statistics:\n" + stats.scanning_protocol())
        
        # Generate actions for all data sets
        for dataSet in self.backupDataSets:
            if len(dataSet.fileDirSet) == 0:
                logging.warning(f"There are no files in the backup '{dataSet.name}'. No actions will be generated.")
                continue
            logging.info(f"Generating actions for backup '{dataSet.name}' with {len(dataSet.fileDirSet)} files.. ")
            dataSet.actions = generateActions(dataSet, self.config)
        
        logging.info("Statistics pre-exectution:\n" + stats.action_generation_protocol())
            
        if self.config.save_actionfile:
            # Write the action file
            actionFilePath = self.targetRoot.joinpath(constants.ACTIONS_FILENAME)
            logging.info(f"Saving the action file to {actionFilePath}")
            # returns a JSON array whose entries are JSON object with a property "name" and "actions"
            actionJson = "[\n" + ",\n".join(map(lambda s:json.dumps(s.to_action_json(), default=dump_default), self.backupDataSets)) + "\n]"
            with open(actionFilePath, "w") as actionFile:
                actionFile.write(actionJson)
    
            if self.config.open_actionfile:
                open_file(actionFilePath)
    
                
        if self.config.save_actionhtml:
            # Write HTML actions
            actionHtmlFilePath = self.targetRoot.joinpath(constants.ACTIONSHTML_FILENAME)
            templateFilePath = Path(__file__).parent.joinpath(constants.HTMLTEMPLATE_FILENAME)
            generateActionHTML(actionHtmlFilePath, templateFilePath, self.backupDataSets, self.config.exclude_actionhtml_actions)
    
            if self.config.open_actionhtml:
                open_file(actionHtmlFilePath)
            
        # Check for success, abort if needed. -1 == any amount of errors allowed
        scanning_successful = (self.config.max_scanning_errors == -1
                                or stats.scanning_errors <= self.config.max_scanning_errors)
        if not scanning_successful:
            logging.critical("Too many errors have occured during scanning: "  +
                             f"{stats.scanning_errors} occured, {self.config.max_scanning_errors} permitted.")
            raise BackupError("Too many errors during scanning")
        
        logging.info("Scanning phase completed.")
        
    
    def performBackupPhase(self, checkConfigFlag: bool):
        """
        This method runs the backup phase if either checkConfigFlag is set to false,
        or if.config.apply_actions is set to true. This is so we can resume the backup when called from an action file.
        """
        if checkConfigFlag and not self.config.apply_actions:
            logging.info("As 'apply_actions' is set to false, no actions are performed.")
            return
        
        self.checkFreeSpace()
        logging.info("Starting to apply the actions:")
        for dataSet in self.backupDataSets:
            executeActionList(dataSet)
        
        # Final steps
        logging.debug("Writing 'success' flag to the metadata file")
        
        # We only need to check for backup errors here, as we check for too many scanning errors in performScanningPhase
        backup_successful = (self.config.max_backup_errors == -1 or stats.backup_errors <= self.config.max_backup_errors)

        # We deliberately do not set "successful" to true if we only ran a scan and not a full backup.
        # If the backup is never run and the flag were set to True, future backups will try to use the
        # non-executed backup as a reference for comparisons
        self.metadata.successful = backup_successful
    
        with self.targetRoot.joinpath(constants.METADATA_FILENAME).open("w") as outFile:
            outFile.write(self.metadata.json(indent=4))
        
        if backup_successful:
            logging.info("Job finished successfully.")
        else:
            logging.critical("The number of errors was higher than the threshold. It will considered to have failed. "
                            + "The threshold can be increased in the configuration file.")
        
        logging.info("Final statistics:\n" + stats.full_protocol())


    def findTargetRoot(self) -> Path:
        # generate the target directory based on config.version_name, and append a suffix if it exists
        suffixNumber = 1
        while True:
            dirname = time.strftime(self.config.version_name)
            if suffixNumber > 1:
                dirname += f"_{suffixNumber}"
            targetRoot = self.config.backup_root_dir.joinpath(dirname)
            try:
                targetRoot.mkdir(exist_ok=False)
                break
            except FileExistsError:
                suffixNumber += 1
                logging.error(f"Target backup directory '{targetRoot}' already exists. Appending suffix '_{suffixNumber}'")
        return targetRoot
    
    def findCompareRoot(self) -> Optional[Path]:
        """Locates the most recent previous complete backup."""
        # Find the folder of the backup to compare to - one level below backupDirectory
        # Scan for old backups, select the most recent successful backup for comparison
        if self.config.versioned and self.config.compare_with_last_backup:
            oldBackups: list[dict[str, object]] = []
            #TODO migrate to backup_root_dir.iterdir()
            #TODO load old metadata files using backupMetadata class
            for entry in os.scandir(self.config.backup_root_dir):
                # backupDirectory is already created at this point; so we need to make sure we don't compare to ourselves
                if entry.is_dir() and os.path.join(self.config.backup_root_dir, entry.name) != self.targetRoot: 
                    metadataFile = os.path.join(self.config.backup_root_dir, entry.name, constants.METADATA_FILENAME)
                    if os.path.isfile(metadataFile):
                        with open(metadataFile) as inFile:
                            oldBackups.append(json.load(inFile))
    
            logging.debug("Found " + str(len(oldBackups)) + " old backups: " + str(oldBackups))

            # TODO: remove 'type: ignore' once metadata is implemented as dataclass / pydantic
            for backup in sorted(oldBackups, key = lambda x: x['started'], reverse = True): # type: ignore
                if backup["successful"]:
                    compareBackup = self.config.backup_root_dir.joinpath(backup['name'])
                    logging.info(f"Chose old backup to compare to: {compareBackup}")
                    return compareBackup
                else:
                    logging.error("It seems the most recent backup '" + backup["name"] + "' failed, so it will be skipped. " 
                                + "The failed backup should probably be deleted.")
            else:
                logging.warning("No old backup found. Creating first backup.")
            return None
        
    def checkFreeSpace(self):
        """"Check if there is enough space on the target drive"""
        freeSpace = shutil.disk_usage(self.targetRoot).free
        if (freeSpace < stats.bytes_to_copy):
            baseMessage = (f"The target drive has {sizeof_fmt(freeSpace)} free space." +
                           f"The backup is expected to need another {sizeof_fmt(stats.bytes_to_copy)}. ")
            match self.config.target_drive_full_action:
                case DRIVE_FULL_ACTION.PROMPT:
                    answer = ''
                    while not answer in ['y', 'n']:
                        answer = input(baseMessage + "Proceed anyway? (y/n)").lower()
                    if answer == 'n':
                        logging.critical("The backup was interrupted by the user.")
                        raise BackupError
                case DRIVE_FULL_ACTION.ABORT:
                    logging.critical(baseMessage + "In accordance with the settings, the backup will be aborted.")
                    raise BackupError
                case DRIVE_FULL_ACTION.PROCEED:
                    logging.error(baseMessage + "In accordance with the settings, the backup will try to proceed anyway.")
                case _:
                    # this should never be reached, as it is checked while loading the config file
                    raise ValueError(f"Invalid value: {self.config.target_drive_full_action=}")
        