from pathlib import Path
import sys
import logging

from .basics import constants, BackupError
from .statistics_module import stats
from .backup_job import backupJob


def main(userConfigPath: str) -> int:
    # Reset statistics (important if main is run multiple times in a meta script)
    stats.reset()

    # Setup logger
    # remove all existing handlers and create one for strerr
    # this is important for multiple calls of main from a meta file
    logging.basicConfig(force=True)
    logger = logging.getLogger()
    logger.handlers[0].setFormatter(constants.LOGFORMAT)

    # create the job
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
        logging.critical("An exception occured and the backup will be terminated.")
        logging.exception(e)
        raise

    return 0


def run() -> None:
    # Find and load the user config file
    if len(sys.argv) < 2:
        logging.critical("Please specify the configuration file for your backup.")
        sys.exit(1)

    # pass on exit code
    sys.exit(main(sys.argv[1]))
