from pre_run_cleanup import regenerate_test_structure
from Frontdown.run_backup import main


def run_integration_test() -> int:
    regenerate_test_structure()
    return main("./tests/integration_test/integration-test-config.json")


def test_integration_test():
    assert run_integration_test() == 0, "Integration test terminated with return code 1"
    # TODO: verify the structure of the generated directory
    # TODO: pytest warning on errors? Is there a warning between pass and fail?


if __name__ == '__main__':
    run_integration_test()
