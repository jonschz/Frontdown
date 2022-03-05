'''
Created on 02.09.2020

@author: Jonathan
'''

# import os
import logging #@UnusedImport
import json
import time
import shutil

from constants import * #@UnusedWildImport
from statistics_module import sizeof_fmt #stats is already implicit in backup_procedures
import strip_comments_json as configjson
from htmlGeneration import generateActionHTML
from backup_procedures import * #@UnusedWildImport
from applyActions import executeActionList
from enum import Enum

# TODO: Do we still need this?
class backupState(Enum):
    start = 0
    afterScan = 1
    finished = 2

# This exception should be raised if a serious problem with the backup appears, but the code
# is working as intended. This is to differentiate backup errors from programming errors.
class BackupError(Exception):
    pass

class backupJob:
    '''
    classdocs
    '''
    class initMethod(Enum):
        fromConfigFile = 0
        fromActionFile = 1
# needs:
# - probably status: has the scanning phase run yet?
# - constructor from
#    - config file
#    - action+metadata file
#
    def __init__(self, method, logger, path):
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
            raise ValueError("Invalid parameter for 'method': " + method)

    def loadFromConfigFile(self, logger, userConfigPath):
        self.state = backupState.start
        # Locate and load config file
        if not os.path.isfile(userConfigPath):
            logging.critical("Configuration file '" + userConfigPath + "' does not exist.")
            raise BackupError
                    
        self.config = self.loadUserConfig(userConfigPath)
    
        logger.setLevel(self.config["log_level"])
    
        # create root directory if necessary
        os.makedirs(self.config["backup_root_dir"], exist_ok = True)
    
        # Make sure that in the "versioned" mode, the backup path is unique: Use a timestamp (plus a suffix if necessary)
        if self.config["versioned"]:
            self.backupDirectory = self.findTargetDirectory()
        else:
            self.backupDirectory = self.config["backup_root_dir"]
    
        # At this point: config is read, backup directory is set, now start the actual work
        self.setupLogFile(logger)
        
        
    def resumeFromActionFile(self, logger, backupDirectory):
        raise Exception("This feature is not yet implemented. Please see the comments for what is necessary")
        
        #    Problem 1: The statistics from the first phase are missing. We would have to save them in the metadata
#                         They are required for checking if the scanning phase has finished correctly.
        #    Problem 2: There is no way to access the config file. We would need to copy the config file to the backup
        #                directory to load it, or pass it as an additional parameter
        self.state = backupState.afterScan
        self.backupDirectory = backupDirectory
        # Load the copied config file
        # Load the saved statistics
        self.setupLogFile(logger)
    
    
    
    def setupLogFile(self, logger):
        # Add the file handler to the log file
        fileHandler = logging.FileHandler(os.path.join(self.backupDirectory, LOG_FILENAME))
        fileHandler.setFormatter(LOGFORMAT)
        logger.addHandler(fileHandler)

    def performScanningPhase(self):
        self.compareBackup = self.findCompareBackup()
        
        # Prepare metadata.json; the 'successful' flag will be changed at the very end
        self.metadata = {
                'name': os.path.basename(self.backupDirectory),
                'successful': False,
                'started': time.time(),
                'sources': self.config["sources"],
                'compareBackup': self.compareBackup,
                'backupDirectory': self.backupDirectory,
            }
        with open(os.path.join(self.backupDirectory, METADATA_FILENAME), "w") as outFile:
            json.dump(self.metadata, outFile, indent=4)
    
        # Build a list of all files in source directory and compare directory
        # TODO: Include/exclude empty folders
        logging.info("Building file set.")
        self.backupDataSets = []
        for source in self.config["sources"]:
            # Folder structure: backupDirectory\source["name"]\files
            if not os.path.isdir(source["dir"]):
                logging.error("The source path \"" + source["dir"] + "\" is not valid and will be skipped.")
                continue
            logging.info("Scanning source \"" + source["name"] + "\" at " + source["dir"])
            fileDirSet = buildFileSet(source["dir"], os.path.join(self.compareBackup, source["name"]), source["exclude-paths"])
            self.backupDataSets.append(BackupData(source["name"], source["dir"], self.backupDirectory, self.compareBackup, fileDirSet))
        
        # Plot intermediate statistics
        logging.info("Scanning statistics:\n" + stats.scanning_protocol())
        
        # Generate actions for all data sets
        for dataSet in self.backupDataSets:
            if len(dataSet.fileDirSet) == 0:
                logging.warning("There are no files in the backup \"" + dataSet.name +"\". No actions will be generated.")
                continue
            logging.info("Generating actions for backup \""+dataSet.name + "\" with "+ str(len(dataSet.fileDirSet)) + " files.. ")
            dataSet.actions = generateActions(dataSet, self.config)
        
        logging.info("Statistics pre-exectution:\n" + stats.action_generation_protocol())
            
        if self.config["save_actionfile"]:
            # Write the action file
            actionFilePath = os.path.join(self.backupDirectory, ACTIONS_FILENAME)
            logging.info("Saving the action file to " + actionFilePath)
            # returns a JSON array whose entries are JSON object with a property "name" and "actions"
            actionJson = "[\n" + ",\n".join(map(lambda s:json.dumps(s.to_action_json()), self.backupDataSets)) + "\n]"
            with open(actionFilePath, "w") as actionFile:
                actionFile.write(actionJson)
    
            if self.config["open_actionfile"]:
                open_file(actionFilePath)
    
                
        if self.config["save_actionhtml"]:
            # Write HTML actions
            actionHtmlFilePath = os.path.join(self.backupDirectory, ACTIONSHTML_FILENAME)
            templateFilePath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.html")
            generateActionHTML(actionHtmlFilePath, templateFilePath, self.backupDataSets, self.config["exclude_actionhtml_actions"])
    
            if self.config["open_actionhtml"]:
                open_file(actionHtmlFilePath)
            
        # Check for success, abort if needed    
        scanning_successful = (self.config["max_scanning_errors"] == -1
                                or stats.scanning_errors <= self.config["max_scanning_errors"])
        if not scanning_successful:
            logging.critical("Too many errors have occured during scanning: %i occured, %i permitted.\n"
                            % (stats.scanning_errors, self.config["max_scanning_errors"]) + 
                            "The backup can be resumed manually.")
            raise BackupError("Too many errors during scanning")
        
        logging.info("Scanning phase completed.")
        
    
    def performBackupPhase(self, checkConfigFlag):
        """
        This method runs the backup phase if either checkConfigFlag is set to false,
        or if config["apply_actions"] is set to true.
        """
        if checkConfigFlag and not self.config["apply_actions"]:
            logging.info("As 'apply_actions' is set to false, no actions are performed.")
            return
        
        self.checkFreeSpace()
        logging.info("Starting to apply the actions:")
        for dataSet in self.backupDataSets:
            executeActionList(dataSet)
        
        # Final steps
        logging.debug("Writing \"success\" flag to the metadata file")
        
        # We only need to check for backup errors here, as we check for too many scanning errors in performScanningPhase
        backup_successful = (self.config["max_backup_errors"] == -1 or stats.backup_errors <= self.config["max_backup_errors"])

        # We deliberately do not set "successful" to true if we only ran a scan and not a full backup
        self.metadata["successful"] = backup_successful
    
        with open(os.path.join(self.backupDirectory, METADATA_FILENAME), "w") as outFile:
            json.dump(self.metadata, outFile, indent=4)
        
        if backup_successful:
            logging.info("Job finished successfully.")
        else:
            logging.critical("The number of errors was higher than the threshold. It will considered to have failed. "
                            + "The threshold can be increased in the configuration file.")
        
        logging.info("Final statistics:\n" + stats.full_protocol())
        #TODO: new feature - compare statistics how much was planned vs how much was actually done
        # once we have this feature, we can include it into considering whether a backup was successful



    def loadUserConfig(self, userConfigPath):
        """
        Loads the provided config file, checks for mandatory keys and adds missing keys from the default file.
        """
        defaultConfigPath = os.path.join(os.path.dirname(__file__), DEFAULT_CONFIG_FILENAME)
        with open(defaultConfigPath, encoding="utf-8") as configFile:
            config = configjson.load(configFile)
        with open(userConfigPath, encoding="utf-8") as userConfigFile:
            try:
                userConfig = configjson.load(userConfigFile)
            except json.JSONDecodeError as e:
                logging.critical("Parsing of the user configuration file failed: " + str(e))
                raise BackupError
        # Now that the user config file can be loaded, sanity check it
        for k, v in userConfig.items():
            if k not in config:
                logging.critical("Unknown key '" + k + "' in the passed configuration file '" + userConfigPath + "'")
                raise BackupError
            else:
                config[k] = v
        for mandatory in ["sources", "backup_root_dir"]:
            if mandatory not in userConfig:
                logging.critical("Please specify the mandatory key '" + mandatory + "' in the passed configuration file '" + userConfigPath + "'")
                raise BackupError
        
        if not config["target_drive_full_action"] in list(DRIVE_FULL_ACTIONS):
            logging.error("Invalid value in config file for 'target_drive_full_action': %s\nDefaulting to 'abort'" % config["target_drive_full_action"])
            config["target_drive_full_action"] = DRIVE_FULL_ACTIONS.ABORT
        
        if config["mode"] == "hardlink":
            config["versioned"] = True
            config["compare_with_last_backup"] = True
        return config
    
    def findTargetDirectory(self):
        backupDirectory = os.path.join(self.config["backup_root_dir"], time.strftime(self.config["version_name"]))
        suffixNumber = 1
        while True:
            try:
                path = backupDirectory
                if suffixNumber > 1: path = path + "_" + str(suffixNumber)
                os.makedirs(path)
                backupDirectory = path
                break
            except FileExistsError:
                suffixNumber += 1
                logging.error("Target Backup directory '" + path + "' already exists. Appending suffix '_" + str(suffixNumber) + "'")
        return backupDirectory
    
    def findCompareBackup(self):
        """Locates the most recent previous complete backup."""
        # Find the folder of the backup to compare to - one level below backupDirectory
        # Scan for old backups, select the most recent successful backup for comparison
        if self.config["versioned"] and self.config["compare_with_last_backup"]:
            oldBackups = []
            for entry in os.scandir(self.config["backup_root_dir"]):
                # backupDirectory is already created at this point; so we need to make sure we don't compare to ourselves
                if entry.is_dir() and os.path.join(self.config["backup_root_dir"], entry.name) != self.backupDirectory: 
                    metadataFile = os.path.join(self.config["backup_root_dir"], entry.name, METADATA_FILENAME)
                    if os.path.isfile(metadataFile):
                        with open(metadataFile) as inFile:
                            oldBackups.append(json.load(inFile))
    
            logging.debug("Found " + str(len(oldBackups)) + " old backups: " + str(oldBackups))
    
            for backup in sorted(oldBackups, key = lambda x: x['started'], reverse = True):
                if backup["successful"]:
                    compareBackup = os.path.join(self.config["backup_root_dir"], backup['name'])
                    logging.info("Chose old backup to compare to: " + compareBackup)
                    return compareBackup
                else:
                    logging.error("It seems the most recent backup '" + backup["name"] + "' failed, so it will be skipped. " 
                                + "The failed backup should probably be deleted.")
            else:
                logging.warning("No old backup found. Creating first backup.")
            return ""
        
    def checkFreeSpace(self):
        """"Check if there is enough space on the target drive"""
        freeSpace = shutil.disk_usage(self.backupDirectory).free
        if (freeSpace < stats.bytes_to_copy):
            if self.config["target_drive_full_action"] == DRIVE_FULL_ACTIONS.PROMPT:
                answer = ''
                while not answer.lower() in ["y", "n"]:
                    answer = input("The target drive has %s free space. The backup is expected to need another %s. Proceed anyway? (y/n)"
                                 % (sizeof_fmt(freeSpace), sizeof_fmt(stats.bytes_to_copy)))
                if answer.lower() == 'n':
                    logging.critical("The backup was interrupted by the user.")
                    raise BackupError
            elif self.config["target_drive_full_action"] == DRIVE_FULL_ACTIONS.ABORT:
                logging.critical("The target drive has %s free space. The backup is expected to need another %s. The backup will be aborted."
                                 % (sizeof_fmt(freeSpace), sizeof_fmt(stats.bytes_to_copy)))
                raise BackupError
            elif self.config["target_drive_full_action"] == DRIVE_FULL_ACTIONS.PROCEED:
                logging.error("The target drive has %s free space. The backup is expected to need another %s. The backup will try to proceed anyway."
                             % (sizeof_fmt(freeSpace), sizeof_fmt(stats.bytes_to_copy)))
            else:
                # this should never be reached, as it is checked while loading the config file
                raise ValueError("Invalid value in config file for 'target_drive_full_action': %s" % self.config["target_drive_full_action"])
        