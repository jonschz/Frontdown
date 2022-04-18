import os
from pathlib import Path
import shutil
import logging
from .backup_procedures import BackupTree
from .basics import ACTION, BackupError
from .file_methods import hardlink
from .statistics_module import stats
from .progressBar import ProgressBar


def executeActionList(dataSet: BackupTree) -> None:
    def checkConsistency(path: Path, *, expectedDir: bool) -> None:
        """
        Checks if `path` is a directory if `expectedDir == True` or if `path` is a file if `expectedDir == False`.
        Throws a matching exception if something does not match.
        """
        # avoid two calling both is_dir() and is_file() if everything is as expected
        if (expectedDir and path.is_dir()) or (not expectedDir and path.is_file()):
            return
        if (expectedDir and path.is_file()):
            raise BackupError(f"Expected '{path}' to be a directory, got a file instead")
        if (not expectedDir and path.is_dir()):
            raise BackupError(f"Expected '{path}' to be a file, got a directory instead")
        if not path.exists():
            raise BackupError(f"The {'directory' if expectedDir else 'file'} '{path}' does not exist or cannot be accessed")
        # path exists, but is_dir() and is_file() both return False
        raise BackupError(f"Entry '{fromPath}' exists but is neither a file nor a directory.")

    if len(dataSet.actions) == 0:
        logging.warning(f"There is nothing to do for the target '{dataSet.name}'")
        return
    logging.info(f"Applying actions for the target '{dataSet.name}'")
    os.makedirs(dataSet.targetDir, exist_ok=True)
    progbar = ProgressBar(50, 1000, len(dataSet.actions))
    # Phase 1: apply the actions
    for i, action in enumerate(dataSet.actions):
        progbar.update(i)
        toPath = dataSet.targetDir.joinpath(action.name)
        try:
            if action.type == ACTION.COPY:
                fromPath = dataSet.sourceDir.joinpath(action.name)
                logging.debug(f"copy from '{fromPath}' to '{toPath}")
                if action.isDir:
                    checkConsistency(fromPath, expectedDir=True)
                    os.makedirs(toPath, exist_ok=True)
                else:
                    checkConsistency(fromPath, expectedDir=False)
                    os.makedirs(os.path.dirname(toPath), exist_ok=True)
                    shutil.copy2(fromPath, toPath)
                    stats.bytes_copied += os.path.getsize(fromPath)    # If copy2 doesn't fail, getsize shouldn't either
                    stats.files_copied += 1
            elif action.type == ACTION.DELETE:
                logging.debug(f"delete file {toPath}")
                if toPath.is_file():
                    stats.bytes_deleted += os.path.getsize(toPath)
                    os.remove(toPath)
                elif toPath.is_dir():
                    shutil.rmtree(toPath)
                stats.files_deleted += 1
            elif action.type == ACTION.HARDLINK:
                assert dataSet.compareDir is not None   # for type checking
                fromPath = dataSet.compareDir.joinpath(action.name)
                logging.debug(f"hardlink from '{fromPath}' to '{toPath}'")
                toDirectory = toPath.parent
                os.makedirs(toDirectory, exist_ok=True)
                # TODO: change to toPath.hardlink_to(fromPath), (note the correct order!), check for regressions, then delete hardlink() code,
                # or use os.link(fromPath, toPath) (toPath.hardlink_to(fromPath) is new in Python 3.10)
                hardlink(str(fromPath), str(toPath))    # type: ignore
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
            fromPath = dataSet.sourceDir.joinpath(action.name)
            toPath = dataSet.targetDir.joinpath(action.name)
            logging.debug(f"set modtime for '{toPath}'")
            modTime = fromPath.stat().st_mtime
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
