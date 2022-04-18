import sys
import logging

from .basics import constants, BackupError
from .statistics_module import stats
from .backup_job import backupJob


def setup_stats_and_logger() -> logging.Logger:
    # Reset statistics (important if main is run multiple times in a meta script)
    stats.reset()

    # Setup logger
    # remove all existing handlers and create one for strerr
    # this is important for multiple calls of main from a meta file
    logging.basicConfig(force=True)
    logger = logging.getLogger()
    logger.handlers[0].setFormatter(constants.LOGFORMAT)
    return logger


def main(initMethod: backupJob.initMethod, logger: logging.Logger, params: object) -> int:

    # create the job
    try:
        job = backupJob(initMethod, logger, params)
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
    logger = setup_stats_and_logger()
    # Find and load the user config file
    if len(sys.argv) < 2:
        logging.critical("Please specify the configuration file for your backup.")
        sys.exit(1)

    # pass on exit code
    sys.exit(main(backupJob.initMethod.fromConfigFile, logger, sys.argv[1]))
