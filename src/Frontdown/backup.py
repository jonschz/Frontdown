from pathlib import Path
import sys
import logging

from Frontdown.basics import constants
from Frontdown.statistics_module import stats
from Frontdown.backup_job import BackupError, backupJob

# WIP
# - migrate various TODOnotes in different files here
# - Progress bar: show progress proportional to size, not number of files
#   - benchmark: proceed with tests
#   - see comments below for status quo
#   - wrap all OS / file system calls with custom functions; these calls will perform long path modifications,
#   - OS checks and so forth, like: if (os == Windows): os.scandir("\\\\?\\" + path)

# Planning of the progress bar upgrade:
# Test results yield:
#  1 ms overhead duration per copied file
# .6 ms overhead per hardlinked file (close enough to 1 ms)
# 10 ms / megabyte of copied data
# so for each file, the progress bar should count one unit plus one unit for each 100 kib
# Question: How do we manage this information efficiently?
# Major problem: If we want to run the actions independently, we will either have to
# a) scan the entire set of files to compute the total amount beforehand or
# b) scan the file sizes during the scanning phase, don't save them in the action file, and provide a legacy
#    progress bar in case we run the action file separately
# c) save the total file size, total expected hardlink size, and total expected copy size in the action file
# Further potential problem: We might run above or finish below 100 % if the true file size differs
# from the expected one; ideas? Maybe dynamically update the top cap by comparing the real file size with the expected one?

# Short TODOs
# - make installable, separate tests, venv
# - Tests for error handling: no permissions to delete, permissions to scan but not to copy
# - Think about which modes make sense with "versioned" and which don't,
#    think about whether some config entries can be removed
# - test the behaviour of directory junctions and see if it could run into infinite loops
#   - think about what the expected behavior for directory junctions is. Possible idea: Do not follow, throw warning / error

# Bugs
# - Number of files copied does not match in production
#   -> log all files to be copied, and all files that are actually copied, find the difference
# - Check if wildcards (abc\\def*) are still needed to exclude a folder and all its contents
# - number of backup errors is not counted / display correctly (not sure about the details)
#   - test this: run phase 1, delete a file, run phase 2; possible as integration test?
# - Long paths: What is the status quo after pathlib migration?
#   - split backup_procedures into two files, one with low-level operations, one with high-level objects
#       - partially done
#         scanning of long directories might also be affected and new bugs may be introduced, see e.g.
#     https://stackoverflow.com/questions/29557760/long-paths-in-python-on-windows
#     pseudocode in applyAction.py:
#     if (os == Windows) and (len(fromPath) >= MAX_PATH) # MAX_PATH == 260 including null terminator, so we need >=
#     fromPath = '\\\\?\\' + fromPath
#     same with toPath

# Old bugs (might no longer exist / not to be fixed soon)
# - bug: metadata is not updated if the backup is run from applyActions.py
# - debug the issue where empty folders are not recognized as "copy (empty)", on family PC

# Larger ideas / bigger projects
# - In the action html: a new top section with statistics and metadata
# - Simple optional GUI using wxPython? Maybe with progress bar and current file
#   - alternatively / in addition: Visual indicator on console if the backup is stuck; maybe some sort of blinking in the progress bar?
#   - warning when a big file is about to be copied? Asyncio copy + warning if the process is taking much longer than expected?
# - compare statistics how many GiBs and files were planned vs how many were actually copied
#    - once we have this feature, we can include it into considering whether a backup was successful
# - Multithreading the scanning phase so source and compare are scanned at the same time 
#    - should improve the speed a lot!
#    - Concurrent is enough, probably don't need parallel
#    - asyncio?
# - Move detection
#    - list / hashed dict of all files either in in source\compare or compare\source, larger than some minimum size,
#       then match based on some criteria below
#    - minimum size: 1 Mib?
#    - criteria: file type, file size, potentially moddate, other metadata?, optional binary compare
#    - test if moddate changes on moving / renaming a file
#       - if yes: compare file size + file extension + binary compare
# - Tree display for html? Is it easy? Low priority
#    - alternative: indentation based on folder depth? Should be easier
# - change user interface:
#     - allow all settings to be set via command line, remove full dependency on config files, at least for one source
#     - check if sufficient data is given to run without config file
#     - use the existing code to diff large folders (think about most sensible interface choice)
#     - a way to merge an existing backup efficiently into another one
# - statistics at the end for plausibility checks, possibly in file size (e.g. X GBit checked, Y GBit copied, Z GBit errors)
# - pfirsich's notes_todo.txt
# - re-implement applying action files

# Notes for meta script / phone backup
#    - wait for phone to connect
#    - backup from C, D, phone to F
#     - wait for H to connect
#    - backup from C, D, F, phone to H
# -> open problems:
#    - how to do phone most efficiently?
#        - could mirror phone to some folder, then hardlink backup from there to F\\Frontdown and H\\Frontdown
#            - Advantage: works; Disadvantage: Double memory usage and every new file copied twice
#        - could to a versioned backup of phone to F and independently H
#            - Advantage: most elegant and clear; Disadvantage: Wacky phase of comparing and copying from phone must be done twice, prob. slow, battery usage
#        - could to a versioned backup of phone to a seperate folder and backup that folder
#            - Advantage: none of the disadvantages above; Disadvantage: How to tell Frontdown to copy the lastest backup from a different backup?


# Done:
# - test run with full backup
# - support multiple sources or write a meta-file to launch multiple instances
# - start the backup in a sub-folder, so we can support multiple sources and log/metadata files don't look like part of the backup
# - Fix json errors being incomprehensible, because the location specified does not match the minified json (pfirsich)
# - Fixed a well hidden bug where some folders would not be recognized as existing in the compare directory due to an sorting / comparing error
# - Introduced proper error handling for inaccessible files
# - Put exludePaths as parameters to relativeWalk to be able to supress Access denied errors and speed up directory scanning
# - track statistics: how many GB copied, GB hardlinked, how many file errors, ...?
# - more accurate condition for failure / success other than the program not having crashed (pfirsich)
#   - In the action html: a new top section with statistics
# - option to deactivate copy (empty folder) in HTML
# - Show "amount to hardlink" and "amount to copy" after scanning
#   - especially important if we do scanning and saving separately
#   - second step: Compute if there is enough free disk space, throw an error if not
# - Restructuring:
#   - lots of code migrated to object-oriented
#   - split the main method into two, one for scanning, one for applying
#   - refactor the applyActions file; move everything but its __main__ code elsewhere, move everything from backup into a new file
#     backup_job.py, make an object oriented model, have backup and applyActions call methods from backup_job.py
#   - remove exit() statements to call backups from meta .py files. Instead, use exceptions and have a nonzero return value of main()
#   - import config files via pydantic
# - auto-generation of the integration test (see comments in pre-run-cleanup.py)
# - flag to enable / disable copying empty folders




# Backup Modes: Concepts and plans
# -------------
# === SAVE ===
# Write all files that are in source, but are not already existing in compare (in that version)
# source\compare: copy
# source&compare:
#   same: ignore
#   different: copy
# compare\source: ignore

# --- move detection:
# The same, except if files in source\compare and compare\source are equal, don't copy,
# but rather rename compare\source (old backup) to source\compare (new backup)

# === MIRROR ===
# End up with a complete copy of source in compare
# source\compare: copy
# source&compare:
#   same: ignore
#   different: copy
# compare\source: delete

# --- move detection:
# The same, except if files in source\compare and compare\source are equal, don't delete and copy, but rename


# === HARDLINK ===
# (Attention: here the source is compared against an older backup!)
# End up with a complete copy of source in compare, but have hardlinks to already existing versions in other backups, if it exists
# source\compare: copy
#   same: hardlink to new backup from old backup
#   different: copy
# compare\source: ignore

# --- move detection:
# The same, except if files in source\compare and compare\source are equal, don't copy,
# but rather hardlink from compare\source (old backup) to source\compare (new backup)


def main(userConfigPath: str):
    # Reset statistics (important if main is run multiple times in a meta script)
    stats.reset()
    
    # Setup logger
    # remove all existing handlers and create one for strerr
    # this is important for multiple calls of main from a meta file
    logging.basicConfig(force=True)
    logger = logging.getLogger()
    logger.handlers[0].setFormatter(constants.LOGFORMAT)
    
    #create the job
    try:
        job = backupJob(backupJob.initMethod.fromConfigFile, logger, Path(userConfigPath))
        job.performScanningPhase()
        job.performBackupPhase(checkConfigFlag=True)
    except BackupError:
        # These errors have already been handled and can be discarded
        return 1
    except Exception as e:
        # These errors are unexpected and hint at programming errors. Thus, they should be re-raised
        # for debugging
        logging.critical(f"An exception occured and the backup will be terminated.")
        logging.exception(e)
        raise
    
    return 0

if __name__ == '__main__':
    # Find and load the user config file
    if len(sys.argv) < 2:
        logging.critical("Please specify the configuration file for your backup.")
        sys.exit(1)

    # pass on exit code
    sys.exit(main(sys.argv[1]))
