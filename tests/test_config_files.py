from enum import Enum
from typing import Any, Optional
import logging

from pydantic import ValidationError

from Frontdown import strip_comments_json
from Frontdown.config_files import ConfigFile, ConfigFileSource
from Frontdown.data_sources import DataSource, MountedDataSource, FTPDataSource

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


@pytest.mark.parametrize('err', tuple(Err))
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
             "Config error: if 'versioned' is set to 'True', 'compare_with_last_backup' is set to 'True' automatically.",
             "Config error: if 'save_actionfile' is set to 'False', 'open_actionfile' is set to 'False' automatically."])


# It seems that pathlib.Path() does not do any consistency checks on Windows
# TODO test the behaviour on Unix
mountedSources = [
    'C:\\'
]

FTPSources: list[tuple[str, dict[str, Any],
                       tuple[Optional[str], Optional[str], Optional[int], Optional[str], Optional[str]]]] = [
    ('ftp://127.0.0.1', {}, ('127.0.0.1', '.', None, None, None)),
    ('ftp://python.test', {}, ('python.test', '.', None, None, None)),
    ('ftp://python.test/dir', {}, ('python.test', 'dir', None, None, None)),
    ('ftp://user@python.test', {}, ('python.test', '.', None, 'user', None)),
    ('ftp://user@python.test/', {}, ('python.test', '.', None, 'user', None)),
    ('ftp://user@python.test/dir', {}, ('python.test', 'dir', None, 'user', None)),
    ('ftp://user:passwd@python.test/dir', {}, ('python.test', 'dir', None, 'user', 'passwd')),
    ('ftp://user:passwd@python.test:12345/dir', {}, ('python.test', 'dir', 12345, 'user', 'passwd')),
    ('ftp://user:passwd@127.0.0.1:12345/dir', {}, ('127.0.0.1', 'dir', 12345, 'user', 'passwd')),
]

erroneousSources = [
    # with multiple @ symbols it is unclear which part is what
    'ftp://abc@def@ghi',
    'ftp://abc@def@ghi/dir',
    # non-integers in the port
    'ftp://user:passwd@python.test:12345a',
    'ftp://user:passwd@python.test:12345a/dir'
]


def test_dataSourceParsing():
    for path in mountedSources:
        dataSource = DataSource.parseConfigFileSource(ConfigFileSource(name='', dir=path, exclude_paths=[]))
        assert isinstance(dataSource, MountedDataSource)

    for dir, extraDict, result in FTPSources:
        extraDict.update({'name': '', 'dir': dir, 'exclude_paths': []})
        dataSource = DataSource.parseConfigFileSource(ConfigFileSource(**extraDict))
        assert isinstance(dataSource, FTPDataSource)
        assert result == (dataSource.host, str(dataSource.rootDir), dataSource.port, dataSource.username, dataSource.password)

    for path in erroneousSources:
        with pytest.raises(ValueError):
            DataSource.parseConfigFileSource(ConfigFileSource(name='', dir=path, exclude_paths=[]))


if __name__ == '__main__':
    test_correctConfig()
    test_invalidConfig(Err.invalidEnum)
