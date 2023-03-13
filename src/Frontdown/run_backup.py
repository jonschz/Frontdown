import sys
import logging
from pathlib import Path
from typing import Optional, Union

from .basics import constants, BackupError
from .statistics_module import stats
from .backup_job import BackupJob
from . import power_mgmt


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


def main(initMethod: BackupJob.initMethod, logger: logging.Logger, params: object) -> int:

    # create the job
    try:
        job = BackupJob(initMethod, logger, params)
        # Prevent the system from entering sleep mode
        power_mgmt.prevent_sleep()
        job.performScanningPhase()
        job.performBackupPhase(checkConfigFlag=True)
        power_mgmt.enable_sleep()
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


def run(configFilePath: Optional[Union[str, Path]] = None) -> None:
    logger = setup_stats_and_logger()
    # Find the user config file
    if configFilePath is None:
        if len(sys.argv) < 2:
            logging.critical("Please specify the configuration file for the backup.")
            sys.exit(1)
        elif len(sys.argv) > 2:
            logging.critical("Please specify only one parameter (the configuration file).")
            sys.exit(1)
        else:
            configFilePath = sys.argv[1]

    # pass on the exit code
    sys.exit(main(BackupJob.initMethod.fromConfigFile, logger, configFilePath))
