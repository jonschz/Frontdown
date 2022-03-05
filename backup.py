import sys #@UnusedImport
import logging

from constants import LOGFORMAT
from statistics_module import stats
from backup_job import BackupError, backupJob

# Restructuring:
#
# idea: split the main method into two, one for scanning, one for applying;
# store more information in the metadata file if needed
# refactor the applyActions file; move everything but its __main__ code elsewhere, move everything from backup into a new file
# backup_job.py, make an object oriented model, have backup and applyActions call methods from backup_job.py
# also remove exit() statements, in case we want to call from meta py files. Instead, use exceptions and have a nonzero return
# value of main()


# Work in progress:
# - Statistics module: show progress proportional to size, not number of files
#	 - benchmark: done
#    - see comments below for status quo
# - Refactoring plus implementation of large paths:
# 	- split backup_procedures into two files, one with low-level operations, one with high-level objects
#      - partially done
# 	- wrap all OS / file system calls with custom functions; these calls will perform long path modifications,
#		OS checks and so forth, like: if (os == Windows): os.scandir("\\\\?\\" + path)
#     Old comment:
#     scanning of long directories might also be affected and new bugs may be introduced, see e.g.
#     https://stackoverflow.com/questions/29557760/long-paths-in-python-on-windows
#     pseudocode in applyAction.py:
#     if (os == Windows) and (len(fromPath) >= MAX_PATH) # MAX_PATH == 260 including null terminator, so we need >=
#     fromPath = '\\\\?\\' + fromPath
#     same with toPath

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
#	progress bar in case we run the action file separately
# c) save the total file size, total expected hardlink size, and total expected copy size in the action file
# Further potential problem: We might run above or finish below 100 % if the true file size differs
# from the expected one; ideas? Maybe dynamically update the top cap by comparing the real file size with the expected one?


# Running TODO
# - try pydantic to import config files -> might also be a good choice for the LL project
# - various TODO notes in different files
# - bug: metadata is not updated if the backup is run from applyActions.py
# - debug the issue where empty folders are not recognized as "copy (empty)", on family PC
# - backup errors does not count / display right; test manually (e.g. delete a file between scan and backup)
# - should a success flag be set if applyActions==false? 
# - 	maybe a new flag "no_action_applied"?
# - Detailed tests for the new error handling
#	 - check: no permissions to delete, permissions to scan but not to copy
# - Progress bars: display the current file to see which files take long; make performance tests for 100.000's of "print" commands
# - Think about which modes make sense with "versioned" and which don't, and remove "versioned" (and potentially "compare_with_last_backup" from the config file
# - Implement statistics for deletions? Might be hard: We could compute the size of everything to be deleted a priori, but how do we check what is actually being deleted, especially if we delete entire folders at once?
# - test the behaviour of directory junctions and see if it could run into infinite loops

# Ideas
# - Multithreading the scanning phase so source and compare are scanned at the same time 
#	 - should improve the speed a lot!
#    - Concurrent is enough, probably don't need parallel
# - In the action html: a new top section with statistics
# - give an option to use the most recent backup as a backup reference even if it has failed; this is e.g. good if the computer has crashed
# - change user interface:
#	 - allow all settings to be set via command line, remove full dependency on config files, at least for one source
#	 - check if sufficient data is given to run without config file
#	 - allow efficient diffing of large folders (think about most sensible interface choice)
#	 - a way to merge an existing backup efficiently into another one
# - object-oriented rewrite of the entire code? Large scale refactor
# - statistics at the end for plausibility checks, possibly in file size (e.g. X GBit checked, Y GBit copied, Z GBit errors)
# - exclude directories: make sure if a directory is excluded, the contents is excluded, too (maybe not as important; wildcards seem to work)
# - more accurate condition for failure / success other than the program not having crashed (pfirsich)
# - archive bit as means of comparison (probably doesn't integrate well into the concept)
# - pfirsich's notes_todo.txt

# - Meta Script TODO notes:
#    - wait for phone to connect
#    - backup from C, D, phone to F
#	 - wait for H to connect
#    - backup from C, D, F, phone to H
# -> open problems:
#    - how to do phone most efficiently?
#		- could mirror phone to some folder, then hardlink backup from there to F\\Frontdown and H\\Frontdown
#			- Advantage: works; Disadvantage: Double memory usage and every new file copied twice
#		- could to a versioned backup of phone to F and independently H
#			- Advantage: most elegant and clear; Disadvantage: Wacky phase of comparing and copying from phone must be done twice, prob. slow, battery usage
#		- could to a versioned backup of phone to a seperate folder and backup that folder
#			- Advantage: none of the disadvantages above; Disadvantage: How to tell Frontdown to copy the lastest backup from a different backup?


# Done:
# - test run with full backup
# - support multiple sources or write a meta-file to launch multiple instances
# - start the backup in a sub-folder, so we can support multiple sources and log/metadata files don't look like part of the backup
# - Fix json errors being incomprehensible, because the location specified does not match the minified json (pfirsich)
# - Fixed a well hidden bug where some folders would not be recognized as existing in the compare directory due to an sorting / comparing error
# - Introduced proper error handling for inaccessible files
# - Put exludePaths as parameters to relativeWalk to be able to supress Access denied errors and speed up directory scanning
# - track statistics: how many GB copied, GB hardlinked, how many file errors, ...?
#    - In the action html: a new top section with statistics
# - option to deactivate copy (empty folder) in HTML
# - Show "amount to hardlink" and "amount to copy" after scanning
#    - especially important if we do scanning and saving separately
#    - second step: Compute if there is enough free disk space, throw an error if not

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










def main(userConfigPath):
	# Reset statistics (important if main is run multiple times in a meta script)
	stats.reset()
	
	# Setup logger
	# remove all existing handlers and create one for strerr
	# this is important for multiple calls of main from a meta file
	logging.basicConfig(force=True)
	logger = logging.getLogger()
	logger.handlers[0].setFormatter(LOGFORMAT)
	
	#create the job
	try:
		job = backupJob(backupJob.initMethod.fromConfigFile, logger, userConfigPath)
		job.performScanningPhase()
		job.performBackupPhase(checkConfigFlag=True)
	except BackupError:
		# These errors have already been handled and can be discarded
		return 1
	except Exception as e:
		# These errors are unexpected and hint at programming errors. Thus, they should be re-raised
		# for debugging
		logging.critical(f"Unexpected critical error: {e}")
		raise
	
	return 0

if __name__ == '__main__':
	# Find and load the user config file
	if len(sys.argv) < 2:
		logging.critical("Please specify the configuration file for your backup.")
		sys.exit(1)

	# pass on exit code
	sys.exit(main(sys.argv[1]))
