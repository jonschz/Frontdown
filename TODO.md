# TODO Notes

## WIP
- continue pathlib migration
- migrate various TODOnotes in different files here
- Progress bar: show progress proportional to size, not number of files
  - benchmark: proceed with tests
  - see block below for status quo
  - wrap all OS / file system calls with custom functions; these calls will perform long path modifications,
  - OS checks and so forth, like: if (os == Windows): os.scandir("\\\\?\\" + path)

### Planning of the progress bar upgrade
- Test results yield:
  - 1 ms overhead duration per copied file
  - .6 ms overhead per hardlinked file (close enough to 1 ms)
  - 10 ms / megabyte of copied data

  so for each file, the progress bar should count one unit plus one unit for each 100 kib
- Question: How do we manage this information efficiently?
- Major problem: If we want to run the actions independently, we will either have to
  1. scan the entire set of files to compute the total amount beforehand or
  1. scan the file sizes during the scanning phase, don't save them in the action file, and provide a legacy
   progress bar in case we run the action file separately
  1. save the total file size, total expected hardlink size, and total expected copy size in the action file
- Further potential problem: We might run above or finish below 100 % if the true file size differs
- from the expected one; ideas? Maybe dynamically update the top cap by comparing the real file size with the expected one?

## Short TODOs
- Migrate statistics away from a singleton to a property of backupJob
- Tests for error handling: no permissions to delete, permissions to scan but not to copy
- Think about which modes make sense with "versioned" and which don't,
   think about whether some config entries can be removed
- test the behaviour of directory junctions and see if it could run into infinite loops
  - think about what the expected behavior for directory junctions is. Possible idea: Do not follow, throw warning / error

## Known Bugs
- vscode sometimes displays a coverage error in pytest that does not show up when pytest is run in powershell
- Number of files copied does not match number of expected files in production
  - log all files to be copied, and all files that are actually copied, find the difference
- Check if wildcards at the end (abc/def-) are still needed to exclude a folder and all its contents
- number of backup errors is not counted / display correctly (not sure about the details)
  - test this: run phase 1, delete a file, run phase 2; possible as integration test?

## Larger ideas / bigger projects
- In the action html: a new top section with statistics and metadata
- Simple optional GUI using wxPython? Maybe with progress bar and current file
  - alternatively / in addition: Visual indicator on console if the backup is stuck; maybe some sort of blinking in the progress bar?
  - warning when a big file is about to be copied? Asyncio copy + warning if the process is taking much longer than expected?
- compare statistics how many GiBs and files were planned vs how many were actually copied
   - once we have this feature, we can include it into considering whether a backup was successful
- Multithreading the scanning phase so source and compare are scanned at the same time
   - should improve the speed a lot!
   - Concurrent is enough, probably don't need parallel
   - asyncio?
- Long paths: What is the status quo after pathlib migration?
  - split backup_procedures into two files, one with low-level operations, one with high-level objects
    - partially done
    - scanning of long directories might also be affected and new bugs may be introduced, see e.g. https://stackoverflow.com/questions/29557760/long-paths-in-python-on-windows
    - pseudocode in applyAction.py:
      ```python
      if (os == Windows) and (len(fromPath) >= MAX_PATH) # MAX_PATH == 260 including null terminator, so we need >=
      fromPath = '\\\\?\\' + fromPath
      ```
      same with toPath
- Move detection
   - list / hashed dict of all files either in in source\compare or compare\source, larger than some minimum size,
      then match based on some criteria below
   - minimum size: 1 Mib?
   - criteria: file type, file size, potentially moddate, other metadata?, optional binary compare
   - test if moddate changes on moving / renaming a file
      - if yes: compare file size + file extension + binary compare
- Tree display for html? Is it easy? Low priority
   - alternative: indentation based on folder depth? Should be easier
   - take inspiration from TreeSizeFree
- Command line interface
    - allow all settings to be set via command line, remove full dependency on config files, at least for one source
    - check if sufficient data is given to run without config file
    - use the existing code to diff large folders (think about most sensible interface choice)
- statistics at the end for plausibility checks, possibly in file size (e.g. X GBit checked, Y GBit copied, Z GBit errors)
- pfirsich's notes_todo.txt
- re-implement applying action files

### Notes for meta script / phone backup
   - wait for phone to connect
   - backup from C, D, phone to F
    - wait for H to connect
   - backup from C, D, F, phone to H
-> open problems:
   - how to do phone most efficiently?
       - could mirror phone to some folder, then hardlink backup from there to F\\Frontdown and H\\Frontdown
           - Advantage: works; Disadvantage: Double memory usage and every new file copied twice
       - could to a versioned backup of phone to F and independently H
           - Advantage: most elegant and clear; Disadvantage: Wacky phase of comparing and copying from phone must be done twice, prob. slow, battery usage
       - could to a versioned backup of phone to a seperate folder and backup that folder
           - Advantage: none of the disadvantages above; Disadvantage: How to tell Frontdown to copy the lastest backup from a different backup?


## Done
- Restructuring:
  - relative imports: from Frontdown.basics -> from .basics
  - put the entry points into separate files outside the package
- test run with full backup
- support multiple sources or write a meta-file to launch multiple instances
- start the backup in a sub-folder, so we can support multiple sources and log/metadata files don't look like part of the backup
- Fix json errors being incomprehensible, because the location specified does not match the minified json (pfirsich)
- Fixed a well hidden bug where some folders would not be recognized as existing in the compare directory due to an sorting / comparing error
- Introduced proper error handling for inaccessible files
- Put exludePaths as parameters to relativeWalk to be able to supress Access denied errors and speed up directory scanning
- track statistics: how many GB copied, GB hardlinked, how many file errors, ...?
- more accurate condition for failure / success other than the program not having crashed (pfirsich)
  - In the action html: a new top section with statistics
- option to deactivate copy (empty folder) in HTML
- Show "amount to hardlink" and "amount to copy" after scanning
  - especially important if we do scanning and saving separately
  - second step: Compute if there is enough free disk space, throw an error if not
- Restructuring:
  - lots of code migrated to object-oriented
  - split the main method into two, one for scanning, one for applying
  - refactor the applyActions file; move everything but its `__main__` code elsewhere, move everything from backup into a new file
    backup_job.py, make an object oriented model, have backup and applyActions call methods from backup_job.py
  - remove exit() statements to call backups from meta .py files. Instead, use exceptions and have a nonzero return value of main()
  - import config files via pydantic
- auto-generation of the integration test (see comments in pre-run-cleanup.py)
- flag to enable / disable copying empty folders
- make installable, separate tests, venv
- Merge an existing backup automatically into another backup of the same source
  - Use case: Keep two backups of the data in different cities, copy the latest version of the backup during a visit
  - Could be an entry point different from backup.py; probably write as script, not as part of the module
- Verification of the integration test


## Old bugs (might no longer exist / not to be fixed soon)
- bug: metadata is not updated if the backup is run from applyActions.py
- debug the issue where empty folders are not recognized as "copy (empty)", on family PC

## Pfirsich's TODO notes

### TODOs

- Caching (optimization for fileDirSet construction and action generation)
- Hashes - Has to be implemented after caching, since they are pointless before that
  - Benchmark this properly!
- Docs & proper readme

If anyone ever uses this (1.0):

- Integration Tests (partially done)
- Implement move detection (but only if someone complains in the issue tracker)

### Possible features/changes

- Custom comparison methods for single files? (also include "always" then, I'm primarily thinking about TrueCrypt containers)
- With hashes and move detection: Don't just take into consideration the last backup, but N earlier backups
  - This sounds cool, since hardlinkbackup does this, but I don't think that this is any useful to be honest, since you would have to have a file, delete it and then have it again somehow. Even if this does happen, it does so very rarely.
- New folders tend to bloat the action list overview a lot (especially if they include .git folders) - Maybe add an option to simplify these?
  - covered in my todo for tree style view
- Maybe add useful excludes to the default.config.json? Such as: (last four are my settings)
    ```json
    "-/RECYCLER/",
    "-/AppData/Roaming/Mozilla/Firefox/Profiles/-/parent.lock",
    "-/desktop.ini",
    "-/Windows/Temp/",
    "hiberfil.sys",
    "pagefile.sys",
    "AppData/Local/-",
    "AppData/LocalLow/-",
    "Thumbs.db",
    "ntuser.dat-"
    ```
- Volume Shadow Copy to copy open files?


### Notes on action list generation
- with compare_method = ["moddate", "size", "bytes"]: 2m 10s for 7100 files
- skipping the copying of directories only gains 4 seconds
- 6 of 6 ctrl+c aborts ended in filecmp.cmp, so that is probably the slowest part
- compared_method = ["moddate", "size"] only takes a couple of seconds -> hashing is needed, which might still be slower