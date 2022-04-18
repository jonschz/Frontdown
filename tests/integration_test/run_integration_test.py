import sys

from pre_run_cleanup import regenerate_test_structure
from Frontdown.backup_job import backupJob
import Frontdown.run_backup as run_backup


def run_integration_test() -> int:
    regenerate_test_structure()
    logger = run_backup.setup_stats_and_logger()
    # pass on exit code
    return run_backup.main(backupJob.initMethod.fromConfigFile, logger,
                           "./tests/integration_test/integration-test-config.json")


def test_integration_test():
    assert run_integration_test() == 0, "Integration test terminated with return code 1"
    # TODO: verify the structure of the generated directory
    # TODO: pytest warning on errors? Is there a warning between pass and fail?


# this is needed for debugging / running the integration test from the vscode run configuration
if __name__ == '__main__':
    sys.exit(run_integration_test())
