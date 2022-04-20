import os
import sys
from pathlib import Path

import pre_run_cleanup
from Frontdown.backup_job import backupJob
import Frontdown.run_backup as run_backup


def run_integration_test() -> int:
    pre_run_cleanup.regenerate_test_structure()
    logger = run_backup.setup_stats_and_logger()
    # pass on exit code
    return run_backup.main(backupJob.initMethod.fromConfigFile, logger,
                           "./tests/integration_test/integration-test-config.json")


def test_integration_test():
    assert run_integration_test() == 0, "Integration test terminated with return code 1"
    # TODO: verify the structure of the generated directory
    # TODO: pytest warning on errors? Is there a warning between pass and fail?
    verify_test_result()


def verify_test_result():
    def hardlink_check(relPath: str | Path) -> bool:
        """Verify that two files in the targets are hardlinked"""
        return os.path.samefile(targets[0].joinpath(relPath), targets[1].joinpath(relPath))

    def check_level(dir: Path, level: int):
        if level < pre_run_cleanup.levels:
            for j in range(pre_run_cleanup.dirs_per_level):
                newdir = dir.joinpath(pre_run_cleanup.generateDirname(s, level, j))
                check_level(newdir, level+1)
        for j in range(pre_run_cleanup.files_per_level):
            newfile = dir.joinpath(pre_run_cleanup.generateFilename(s, level, j))
            assert hardlink_check(newfile), f"{newfile} is not hardlinked"

    # in the format yyyy_mm_dd, it is sufficient to sort alphabetically
    targets = sorted(Path("./tests/integration_test/target").iterdir(), key=lambda x: str(x))
    assert len(targets) == 2, "Unexpected number of targets"
    for s in range(pre_run_cleanup.sources):
        relpath = Path(f"test-source-{s+1}")
        check_level(relpath, 1)
        # the modified file must not be hardlinked to its source
        assert not hardlink_check(relpath.joinpath(pre_run_cleanup.filename_modified))
        # check if the deleted file is actually deleted, and that the new files exist
        newTargetPath = targets[1].joinpath(relpath)
        assert not newTargetPath.joinpath(pre_run_cleanup.filename_deleted).exists()
        assert newTargetPath.joinpath(pre_run_cleanup.new_file_name).exists()
        assert newTargetPath.joinpath(pre_run_cleanup.new_dir_name).joinpath(pre_run_cleanup.new_subfile_name).exists()


# this is needed for debugging / running the integration test from the vscode run configuration
if __name__ == '__main__':
    exitCode = run_integration_test()
    verify_test_result()
    sys.exit(exitCode)