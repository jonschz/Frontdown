'''
Created on 02.09.2020

@author: Jonathan
'''

import logging
from pathlib import Path
import time
import shutil
from enum import Enum
from typing import Optional
from pydantic import BaseModel

from .basics import BackupError, constants, DRIVE_FULL_ACTION
from .statistics_module import stats, sizeof_fmt
from .config_files import ConfigFile, ConfigFileSource
from .file_methods import open_file
from .backup_procedures import BackupTree
from .htmlGeneration import generateActionHTML
from .applyActions import executeActionList


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
        fromConfigObject = 2

    def __init__(self, method: initMethod, logger: logging.Logger, params: object):
        """
            method:    an instance of backupJob.initMethod
            logger:    an instance of logging.Logger
            path: depending on `method`:
                `method == fromConfigFile`: the path to the config file (str or Path)
                `method == fromActionFile`: the path to the backup folder (containing the action file)
                `method == fromConfigObject`: an instance of `ConfigFile`
        """
        if method == self.initMethod.fromConfigFile:
            assert isinstance(params, str) or isinstance(params, Path)
            self.config = ConfigFile.loadUserConfigFile(params)
            self.initAfterConfigRead(logger)
        elif method == self.initMethod.fromActionFile:
            assert isinstance(params, str) or isinstance(params, Path)
            self.resumeFromActionFile(Path(params))
        elif method == self.initMethod.fromConfigObject:
            assert isinstance(params, ConfigFile)
            self.config = params
            self.initAfterConfigRead(logger)
        else:
            raise ValueError(f"Invalid parameter: {method=}")

    def initAfterConfigRead(self, logger: logging.Logger) -> None:
        logger.setLevel(self.config.log_level)
        # create root directory if necessary
        self.config.backup_root_dir.mkdir(parents=True, exist_ok=True)
        # os.makedirs(self.config.backup_root_dir, exist_ok=True)
        # Make sure that in the "versioned" mode, the backup path is unique: Use a timestamp (plus a suffix if necessary)
        if self.config.versioned:
            self.targetRoot = self.findTargetRoot()
        else:
            self.targetRoot = self.config.backup_root_dir

        # Add the file handler to the log file
        fileHandler = logging.FileHandler(self.targetRoot.joinpath(constants.LOG_FILENAME))
        fileHandler.setFormatter(constants.LOGFORMAT)
        logger.addHandler(fileHandler)

    def resumeFromActionFile(self, userConfigPath: Path) -> None:
        raise NotImplementedError("This feature is not yet re-implemented. Please see the comments for what is necessary")

        #  Problem 1: The statistics from the first phase are missing. We would have to save them in the metadata.
        #             They are required for checking if the scanning phase has finished correctly.
        #  Problem 2: There is no way to access the config file. We would need to copy the config file to the backup
        #             directory to load it, or pass it as an additional parameter
        # self.state = backupState.afterScan
        # self.backupDirectory = backupDirectory
        # # Load the copied config file
        # # Load the saved statistics
        # self.setupLogFile(logger)

    def performScanningPhase(self) -> None:
        self.compareRoot = self.findCompareRoot()
        # Prepare metadata.json; the 'successful' flag will be changed at the very end
        self.metadata = backupMetadata(name=self.targetRoot.name,
                                       successful=False,
                                       started=time.time(),
                                       sources=self.config.sources,
                                       compareBackup=self.compareRoot,
                                       backupDirectory=self.targetRoot)
        with self.targetRoot.joinpath(constants.METADATA_FILENAME).open("w") as outFile:
            outFile.write(self.metadata.json(indent=4))
            # json.dump(self.metadata, outFile, indent=4, default = dump_default)

        # Build a list of all files in source directory and compare directory
        logging.info("Building file set.")
        self.backupDataSets: list[BackupTree] = []

        for source in self.config.sources:
            dataSource = source.parseDataSource()
            if dataSource is not None:
                logging.info(f"Scanning source '{source.name}' at '{dataSource}'")
                self.backupDataSets.append(BackupTree.createAndScan(source.name, dataSource, self.targetRoot, self.compareRoot, source.exclude_paths))

        # Plot intermediate statistics
        logging.info("Scanning statistics:\n" + stats.scanning_protocol())

        # Generate actions for all data sets
        for dataSet in self.backupDataSets:
            if len(dataSet.fileDirSet) == 0:
                logging.warning(f"There are no files in the backup '{dataSet.name}'. No actions will be generated.")
                continue
            logging.info(f"Generating actions for backup '{dataSet.name}' with {len(dataSet.fileDirSet)} files.. ")
            dataSet.generateActions(self.config)

        logging.info("Statistics pre-exectution:\n" + stats.action_generation_protocol())

        if self.config.save_actionfile:
            # Write the action file
            actionFilePath = self.targetRoot.joinpath(constants.ACTIONS_FILENAME)
            logging.info(f"Saving the action file to {actionFilePath}")
            # returns a JSON array whose entries are JSON object with a property "name" and "actions"
            actionJson = "[\n" + ",\n".join(map(lambda s: s.to_action_json(), self.backupDataSets)) + "\n]"
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
            logging.critical("Too many errors have occured during scanning: "
                             f"{stats.scanning_errors} occured, {self.config.max_scanning_errors} permitted.")
            raise BackupError("Too many errors during scanning")

        logging.info("Scanning phase completed.")

    def performBackupPhase(self, checkConfigFlag: bool) -> None:
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

    @staticmethod
    def findMostRecentSuccessfulBackup(rootDir: Path, excludedDir: Optional[Path] = None) -> tuple[Optional[Path], Optional[backupMetadata]]:
        """
        Finds the most recent successful backup in `rootDir`, excluding `excludedDir`.
        Returns `None` if no successful backup exists.
        Both `rootDir` and `excludedDir` must be either absolute paths or relative to the same origin.
        """
        existingBackups: list[backupMetadata] = []

        for entry in rootDir.iterdir():
            # entry is relative to the origin of config.backup_root_dir, and absolute if the latter is
            if entry.is_dir() and excludedDir != entry:
                metadataPath = entry.joinpath(constants.METADATA_FILENAME)
                if metadataPath.is_file():
                    try:
                        existingBackups.append(backupMetadata.parse_file(metadataPath))
                    except IOError as e:
                        logging.error(f"Could not load metadata file of old backup '{entry}': {e}")
                else:
                    logging.warning(f"Directory {entry} in the backup directory does not appear to be a backup, "
                                    f"as it has no '{constants.METADATA_FILENAME}' file.")

        logging.debug(f"Found {len(existingBackups)} existing backups: {[m.name for m in existingBackups]}")

        for backup in sorted(existingBackups, key=lambda x: x.started, reverse=True):
            if backup.successful:
                return rootDir.joinpath(backup.name), backup
            else:
                logging.error(f"It seems the most recent backup '{backup.name}' failed or did not run, so it will be skipped. "
                              "The failed backup should probably be deleted.")
        else:
            # for-else is executed if the for loop runs to the end without a `return` or a `break` statement
            return None, None

    def findCompareRoot(self) -> Optional[Path]:
        """
        Returns the path of the most recent completed backup if it exists and comparing is enabled, or `None` otherwise.
        """
        # Find the directory of the backup to compare to - one level below backupDirectory
        # Scan for old backups, select the most recent successful backup for comparison
        if self.config.versioned and self.config.compare_with_last_backup:
            compareBackupPath, _ = self.findMostRecentSuccessfulBackup(self.config.backup_root_dir, excludedDir=self.targetRoot)
            if compareBackupPath is not None:
                logging.info(f"Chose old backup to compare to: {compareBackupPath}")
            else:
                logging.warning("No old backup found. Creating first backup.")
            return compareBackupPath
        else:
            return None

    def checkFreeSpace(self) -> None:
        """"Check if there is enough space on the target drive"""
        freeSpace = shutil.disk_usage(self.targetRoot).free
        if (freeSpace < stats.bytes_to_copy):
            baseMessage = (f"The target drive has {sizeof_fmt(freeSpace)} free space." +
                           f"The backup is expected to need another {sizeof_fmt(stats.bytes_to_copy)}. ")
            match self.config.target_drive_full_action:
                case DRIVE_FULL_ACTION.PROMPT:
                    answer = ''
                    while answer not in ['y', 'n']:
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
