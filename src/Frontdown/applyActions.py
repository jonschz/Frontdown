import os
import shutil
import logging
from .backup_procedures import BackupTree
from .basics import ACTION, BackupError
from .statistics_module import stats
from .progressBar import ProgressBar


def executeActionList(dataSet: BackupTree) -> None:

    if len(dataSet.actions) == 0:
        logging.warning(f"There is nothing to do for the target '{dataSet.name}'")
        return
    logging.info(f"Applying actions for the target '{dataSet.name}'")
    dataSet.targetDir.mkdir(parents=True, exist_ok=True)
    # os.makedirs(dataSet.targetDir, exist_ok=True)
    progbar = ProgressBar(50, 1000, len(dataSet.actions))

    # connection will just be an empty object if no connection is needed
    with dataSet.source.connection() as connection:
        # Phase 1: apply the actions
        for i, action in enumerate(dataSet.actions):
            progbar.update(i)
            toPath = dataSet.targetDir.joinpath(action.relPath)
            try:
                logging.debug(f"Applying action '{action.type}' to file '{action.relPath}'")
                if action.type == ACTION.COPY:
                    if action.isDir:
                        # TODO: is this consistency check important, or can we skip it?
                        # checkConsistency(fromPath, expectedDir=True)
                        toPath.mkdir(parents=True, exist_ok=True)
                        # os.makedirs(toPath, exist_ok=True) # old code
                    else:
                        toPath.parent.mkdir(parents=True, exist_ok=True)
                        # os.makedirs(os.path.dirname(toPath), exist_ok=True)  # old code
                        connection.copyFile(action.relPath, action.modTime, toPath)
                        stats.bytes_copied += toPath.stat().st_size  # os.path.getsize(fromPath)    # If copy2 doesn't fail, getsize shouldn't either
                        stats.files_copied += 1
                elif action.type == ACTION.DELETE:
                    logging.debug(f"delete file {toPath}")
                    if toPath.is_file():
                        stats.bytes_deleted += toPath.stat().st_size  # os.path.getsize(toPath)
                        toPath.unlink()
                        # os.remove(toPath)
                    elif toPath.is_dir():
                        shutil.rmtree(toPath)
                    stats.files_deleted += 1
                elif action.type == ACTION.HARDLINK:
                    assert dataSet.compareDir is not None   # for type checking
                    fromPath = dataSet.compareDir.joinpath(action.relPath)
                    logging.debug(f"hardlink from '{fromPath}' to '{toPath}'")
                    toPath.parent.mkdir(parents=True, exist_ok=True)
                    # toDirectory = toPath.parent
                    # os.makedirs(toDirectory, exist_ok=True)
                    toPath.hardlink_to(fromPath)    # for python < 3.10: os.link(fromPath, toPath)
                    stats.bytes_hardlinked += fromPath.stat().st_size   # If hardlink doesn't fail, getsize shouldn't either
                    stats.files_hardlinked += 1
                else:
                    raise BackupError(f"Unknown action type: {action.type}")
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
            toPath = dataSet.targetDir.joinpath(action.relPath)
            logging.debug(f"set modtime for '{toPath}'")
            os.utime(toPath, (action.modTime, action.modTime))
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
