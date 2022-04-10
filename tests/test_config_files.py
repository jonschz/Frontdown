from enum import Enum
from typing import Optional
import logging

from Frontdown import strip_comments_json
from Frontdown.config_files import ConfigFile
from pydantic import ValidationError

import pytest


class Err(Enum):
    missingEntry = 1
    extraEntry = 2
    wrongType = 3
    invalidEnum = 4


def generateConfig(err: Optional[Err] = None) -> str:
    return f"""
{{
    "sources": [
        {{ "name": "changed-target", "dir": "C:/anywhere", "exclude_paths": ["excluded*"]}}
    ],
    {"" if err == Err.missingEntry else '"backup_root_dir": "C:/elsewhere",'}
    "mode": "hardlink",
    {'"spurious_entry": 1,' if err == Err.extraEntry else ''}
    "versioned": true,
    "save_actionfile": {'2' if err == Err.wrongType else 'false'},
    "open_actionfile": false,
    "compare_with_last_backup": false,
    "compare_method": ["size", "bytes"],
    "exclude_actionhtml_actions": ["copy", {'"invalid"' if err == Err.invalidEnum else '"inNewDir"'}]
}}
"""


def test_correctConfig():
    configJSON = strip_comments_json.loads(generateConfig())
    ConfigFile.parse_obj(configJSON)
    # TODO think about asserting that no errors were logged

    # debug output etc.
    # testConfig = ConfigFile.parse_obj(configJSON)
    # print(testConfig)
    # print(testConfig.json(indent=1))
    # # we may also save this to a file in order to update default.config.json
    # # print(ConfigFile.export_default())


@pytest.mark.parametrize('err', (Err.missingEntry, Err.extraEntry, Err.wrongType, Err.invalidEnum))
def test_invalidConfig(err: Err):
    # print(generateConfig())
    configJSON = strip_comments_json.loads(generateConfig(err))
    with pytest.raises(ValidationError):
        ConfigFile.parse_obj(configJSON)


@pytest.fixture
def capture_error_logs(monkeypatch):
    # the config file parser logs some errors but does not throw exceptions
    # in the scenarios defined below
    log_entries: list[str] = []

    def fake_log_error(msg: str):
        log_entries.append(msg)

    monkeypatch.setattr(logging, 'error', fake_log_error)
    return log_entries


def test_expectedLoggedError(capture_error_logs):
    baseConfig = strip_comments_json.loads(generateConfig())
    assert isinstance(baseConfig, dict)
    configCopy = dict(baseConfig)
    configCopy['versioned'] = 'false'
    configCopy['compare_with_last_backup'] = 'false'
    configCopy['open_actionfile'] = 'true'
    ConfigFile.parse_obj(configCopy)
    assert (capture_error_logs ==
            ["Config error: if 'mode' is set to 'hardlink', 'versioned' is set to 'True' automatically.",
             "Config error: if 'mode' is set to 'hardlink', 'compare_with_last_backup' is set to 'True' automatically.",
             "Config error: if 'save_actionfile' is set to 'False', 'open_actionfile' is set to 'False' automatically."])


if __name__ == '__main__':
    test_correctConfig()
    test_invalidConfig(Err.invalidEnum)
