import os
from pathlib import Path
import shutil
import logging
from Frontdown.backup_procedures import BackupTree
from Frontdown.basics import ACTION
from Frontdown.file_methods import hardlink, filesize_and_permission_check
from Frontdown.statistics_module import stats
from Frontdown.progressBar import ProgressBar


def executeActionList(dataSet: BackupTree) -> None:
    logging.info(f"Applying actions for the target '{dataSet.name}'")
    if len(dataSet.actions) == 0:
        logging.warning(f"There is nothing to do for the target '{dataSet.name}'")
        return

    os.makedirs(dataSet.targetDir, exist_ok=True)
    progbar = ProgressBar(50, 1000, len(dataSet.actions))
    # Phase 1: apply the actions
    for i, action in enumerate(dataSet.actions):
        progbar.update(i)

        actionType = action.type
        name = action.name
        assert isinstance(name, Path)
        toPath = dataSet.targetDir.joinpath(name)
        try:
            if actionType == ACTION.COPY:
                fromPath = dataSet.sourceDir.joinpath(name)
                logging.debug(f"copy from '{fromPath}' to '{toPath}")
                # TODO: remove the manual checks for isFile etc., switch to action["isDir"]; test for regressions
                if os.path.isfile(fromPath):
                    os.makedirs(os.path.dirname(toPath), exist_ok=True)
                    shutil.copy2(fromPath, toPath)
                    stats.bytes_copied += os.path.getsize(fromPath)    # If copy2 doesn't fail, getsize shouldn't either
                    stats.files_copied += 1
                elif os.path.isdir(fromPath):
                    os.makedirs(toPath, exist_ok=True)
                else:
                    # We know there is a problem, because isfile and isdir both return false. Most likely permissions or a missing file,
                    # in which case the error handling is done in the permission check. If not, throw a general error
                    accessible, _ = filesize_and_permission_check(fromPath)
                    if accessible:
                        logging.error(f"Entry '{fromPath}' exists but is neither a file nor a directory.")
                        stats.backup_errors += 1
            elif actionType == ACTION.DELETE:
                logging.debug(f"delete file {toPath}")
                stats.files_deleted += 1
                if os.path.isfile(toPath):
                    stats.bytes_deleted += os.path.getsize(toPath)
                    os.remove(toPath)
                elif os.path.isdir(toPath):
                    shutil.rmtree(toPath)
            elif actionType == ACTION.HARDLINK:
                assert dataSet.compareDir is not None   # for type checking
                fromPath = dataSet.compareDir.joinpath(name)
                logging.debug(f"hardlink from '{fromPath}' to '{toPath}'")
                toDirectory = toPath.parent
                os.makedirs(toDirectory, exist_ok=True)
                # TODO: change to os.link(), check for regressions, then delete hardlink() code
                hardlink(str(fromPath), str(toPath))    # type: ignore
                stats.bytes_hardlinked += fromPath.stat().st_size   # If hardlink doesn't fail, getsize shouldn't either
                stats.files_hardlinked += 1
            else:
                logging.error(f"Unknown action type: {actionType}")
        except Exception as e:
            logging.error(e)
            stats.backup_errors += 1
    print("")  # so the progress output from before ends with a new line

    # Phase 2: Set the modification timestamps for all directories
    # This has to be done in a separate step, as copying into a directory will reset its modification timestamp
    logging.info(f"Applying directory modification timestamps for the target '{dataSet.name}'")
    progbar.update(0)
    for i, action in enumerate(dataSet.actions):
        progbar.update(i)
        if not action.isDir:
            continue
        try:
            fromPath = dataSet.sourceDir.joinpath(action.name)
            toPath = dataSet.targetDir.joinpath(action.name)
            logging.debug(f"set modtime for '{toPath}'")
            # TODO: look up the Path. methods for this
            modTime = os.path.getmtime(fromPath)
            os.utime(toPath, (modTime, modTime))
        except Exception as e:
            logging.error(e)
            stats.backup_errors += 1
    print("")  # so the progress output from before ends with a new line


if __name__ == '__main__':
    raise NotImplementedError("This feature has been discontinued due to large scale structural changes. See the comments for what is needed to re-implement.")
#    See the implementation of backupJob.resumeFromActionFile to see what is missing
#
#    New pseudocode:
#
# < copy code from main >


#     Old code:
#
#     if len(sys.argv) < 2:
#         quit("Please specify a backup metadata directory path")
#     stats.reset()
#     metadataDirectory = sys.argv[1]
#
#     fileHandler = logging.FileHandler(os.path.join(metadataDirectory, LOG_FILENAME))
#     fileHandler.setFormatter(LOGFORMAT)
#     logging.getLogger().addHandler(fileHandler)
#
#     logging.warning("Launching applyActions is a deprecated feature. Use with caution!")
#
#     logging.info("Apply action file in backup directory " + metadataDirectory)
#
#     dataSets = []
#     with open(os.path.join(metadataDirectory, ACTIONS_FILENAME)) as actionFile:
#         jsonData = json.load(actionFile)
#         for jsonEntry in jsonData:
#             dataSets.append(BackupData.from_action_json(jsonEntry))
#
#     for dataSet in dataSets:
#         executeActionList(dataSet)
#
#     print(stats.backup_protocol())
