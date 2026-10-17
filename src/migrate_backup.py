import logging
import sys
from pathlib import Path

from Frontdown import run_backup
from Frontdown.backup_job import BackupJob
from Frontdown.basics import BACKUP_MODE
from Frontdown.config_files import ConfigFile, ConfigFileSource

if __name__ == "__main__":
    logger = run_backup.setup_stats_and_logger()
    # Find and load the user config file
    if len(sys.argv) != 3:
        logging.critical("Please specify a source and target backup directory")
        sys.exit(1)
    sourcePath = Path(sys.argv[1])
    targetPath = Path(sys.argv[2])

    assert sourcePath.is_dir()

    originBackupPath, originBackupMetadata = BackupJob.findMostRecentSuccessfulBackup(
        sourcePath
    )
    if originBackupPath is None:
        logging.critical(
            "Could not find any successful backups in %s. Aborting", sourcePath
        )
        sys.exit(1)

    assert originBackupMetadata is not None

    # excludePaths can be left empty as the files in the backup have already been filtered
    sources = [
        ConfigFileSource(
            name=s.name, dir=str(originBackupPath.joinpath(s.name)), exclude_paths=[]
        )
        for s in originBackupMetadata.sources
    ]
    # Known issue: This script is incompatible with custom version_name
    # Fixing this requires saving version_name to metadata.json
    config = ConfigFile(
        sources=sources,
        backup_root_dir=targetPath,
        mode=BACKUP_MODE.HARDLINK,
        open_actionhtml=True,
    )

    sys.exit(run_backup.main(BackupJob.initMethod.fromConfigObject, logger, config))
