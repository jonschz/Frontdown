import os
import shutil
import logging
import stat
from typing import Iterator, Sequence

from .backup_procedures import Action, BackupTree
from .basics import ACTION, BackupError, datetimeToLocalTimestamp
from .statistics_module import stats
from .progressBar import ProgressBar


def iterate_actions(actions: Sequence[Action]) -> Iterator[Action]:
    yield from (action for action in actions if action.type != ACTION.DELETE)
    # Deletions must be executed in reverse order since the files in a directory must be deleted before the directory itself
    yield from (action for action in reversed(actions) if action.type == ACTION.DELETE)


def executeActionList(dataSet: BackupTree) -> None:

    if len(dataSet.actions) == 0:
        logging.warning("There is nothing to do for the target '%s'", dataSet.name)
        return
    logging.info("Applying actions for the target '%s'", dataSet.name)
    dataSet.targetDir.mkdir(parents=True, exist_ok=True)
    # os.makedirs(dataSet.targetDir, exist_ok=True)
    progbar = ProgressBar(50, 1000, len(dataSet.actions))

    # connection will just be an empty object if no connection is needed
    with dataSet.source.connection() as connection:
        # Phase 1: apply the actions
        for i, action in enumerate(iterate_actions(dataSet.actions)):
            progbar.update(i)
            to_path = dataSet.targetDir.joinpath(action.relPath)
            try:
                logging.debug(
                    "Applying action '%s' to file '%s'", action.type, action.relPath
                )
                if action.type == ACTION.COPY:
                    if action.isDir:
                        to_path.mkdir(parents=True, exist_ok=True)
                        # os.makedirs(toPath, exist_ok=True) # old code
                    else:
                        to_path.parent.mkdir(parents=True, exist_ok=True)
                        # os.makedirs(os.path.dirname(toPath), exist_ok=True)  # old code
                        connection.copyFile(action.relPath, action.modTime, to_path)
                        stats.bytes_copied += (
                            to_path.stat().st_size
                        )  # os.path.getsize(fromPath)    # If copy2 doesn't fail, getsize shouldn't either
                        stats.files_copied += 1
                elif action.type == ACTION.DELETE:
                    logging.debug("delete file %s", to_path)
                    if not to_path.exists():
                        logging.debug("file %s was already deleted", to_path)
                    elif to_path.is_file():
                        file_stat = to_path.stat()
                        if file_stat.st_mode & stat.S_IWUSR == 0:
                            # Try to add write permissions if necessary. Otherwise, deleting in Windows fails
                            logging.debug(
                                "File is read-only, try to add write permissions: '%s'",
                                to_path,
                            )
                            to_path.chmod(file_stat.st_mode | stat.S_IWUSR)
                        to_path.unlink()
                        stats.bytes_deleted += file_stat.st_size
                    elif to_path.is_dir():
                        shutil.rmtree(to_path)
                    stats.files_deleted += 1
                elif action.type == ACTION.HARDLINK:
                    assert dataSet.compareDir is not None  # for type checking
                    fromPath = dataSet.compareDir.joinpath(action.relPath)
                    logging.debug("hardlink from '%s' to '%s'", fromPath, to_path)
                    to_path.parent.mkdir(parents=True, exist_ok=True)
                    # toDirectory = toPath.parent
                    # os.makedirs(toDirectory, exist_ok=True)
                    to_path.hardlink_to(
                        fromPath
                    )  # for python < 3.10: os.link(fromPath, toPath)
                    stats.bytes_hardlinked += (
                        fromPath.stat().st_size
                    )  # If hardlink doesn't fail, getsize shouldn't either
                    stats.files_hardlinked += 1
                else:
                    raise BackupError(f"Unknown action type: {action.type}")
            except Exception as e:  # pylint: disable=broad-exception-caught
                # These are rather common errors like permission denied, we don't want a stack trace here
                logging.error(
                    "Error '%s' while applying action '%s' to file '%s'",
                    e,
                    action.type,
                    action.relPath,
                )
                stats.backup_errors += 1
    print("")  # so the progress output from before ends with a new line

    # Phase 2: Set the modification timestamps for all directories
    # This has to be done in a separate step, as copying into a directory will reset its modification timestamp
    logging.info(
        "Applying directory modification timestamps for the target '%s'", dataSet.name
    )
    progbar.update(0)
    for i, action in enumerate(dataSet.actions):
        progbar.update(i)
        if action.type == ACTION.DELETE or not action.isDir:
            continue
        try:
            to_path = dataSet.targetDir.joinpath(action.relPath)
            logging.debug("set modtime for '%s'", to_path)
            modtimestamp = datetimeToLocalTimestamp(action.modTime)
            os.utime(to_path, (modtimestamp, modtimestamp))
        except Exception as e:  # pylint: disable=broad-exception-caught
            logging.error(e)
            stats.backup_errors += 1
    print("")  # so the progress output from before ends with a new line


if __name__ == "__main__":
    raise NotImplementedError(
        "This feature has been discontinued due to large scale structural changes. "
        "See the comments for what is needed to re-implement."
    )
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
