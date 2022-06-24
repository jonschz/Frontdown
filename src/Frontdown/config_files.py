from __future__ import annotations

from json import JSONDecodeError
import re
from typing import Any, Optional, Union
from pathlib import Path, PurePosixPath
import logging

from pydantic import BaseModel, Field, ValidationError, Extra, validator, fields, root_validator
from pydantic.error_wrappers import _display_error_loc

from .file_methods import DataSource, MountedDataSource, FTPDataSource

from . import strip_comments_json
from .basics import ACTION, COMPARE_METHOD, HTMLFLAG, BACKUP_MODE, DRIVE_FULL_ACTION, LOG_LEVEL, BackupError


class ConfigFileSource(BaseModel):
    name: str
    dir: str
    exclude_paths: list[str]

    # for legacy reasons - allow exclude-paths as an alias, as old metadata.json files still have this name
    @root_validator(pre=True)
    def legacy_alias_name(cls, values: dict[str, Any]) -> dict[str, Any]:
        if 'exclude-paths' in values:
            values['exclude_paths'] = values['exclude-paths']
            del values['exclude-paths']
        return values

    def parseDataSource(self) -> Optional[DataSource]:
        # FTP
        # test paths:
        # ftp://user:pythontest@192.168.200.104:12345/
        # ftp://user:pythontest@192.168.200.104:12345
        # ftp://user:pythontest@192.168.200.104:12345/path/to/something
        if self.dir.startswith('ftp://'):
            try:
                if self.dir.find('@') > -1:
                    # Regex documentation:
                    # - first group: match anything after ftp:// until an (optional) colon or the mandatory @
                    # - second group: optional; matches :passwd until the mandatory @, does not capture the colon.
                    #   If there are multiple colons, the first will separate user and passwd, all the others will be part of passwd
                    # - third group: match anything from the @ to the next colon, forward slash, or end
                    # - fourth group: optional; matches :12345 until the end or forward slash, does not capture the colon
                    #   (because the fourth group is marked as optional while the third is not, the fourth group will not participate if no colon is present)
                    # - fifth group: optional; matches a forward slash and anything after that excluding @, but does not capture the forward slash;
                    #   the exclusion of @ ensures that certain erroneous expressions with two @ symbols do not match
                    serverData = re.fullmatch('^ftp://([^:@/]+)(?::([^@]+))?@([^:@/]+)(?::(\\d+))?(?:/([^@]*))?$', self.dir)
                    assert serverData is not None
                    # setting the default value explicitly improves type checking
                    matchgroups = serverData.groups(default=None)
                    assert len(matchgroups) == 5
                    username, password, host, port, path = matchgroups
                    # use construct here, because otherwise the validator for PurePath initialises a PureWindowsPath
                    return FTPDataSource.construct(host=host,
                                                   rootDir=PurePosixPath('' if path is None else path),
                                                   username=username,
                                                   password=password,
                                                   port=None if port is None else int(port))
                else:
                    # Scheme 2: ftp://host:port/path, and both user and password can be provided by other named parameters
                    serverData = re.fullmatch('^ftp://([^:/]+)(?::(\\d+))?(?:/([^@]*))?$', self.dir)
                    assert serverData is not None
                    matchgroups = serverData.groups(default=None)
                    assert len(matchgroups) == 3
                    host, port, path = matchgroups
                    # TODO implement extra parameters for user and password
                    return FTPDataSource.construct(host=host,
                                                   rootDir=PurePosixPath('' if path is None else path),
                                                   username=None,
                                                   password=None,
                                                   port=None if port is None else int(port))
            except AssertionError:
                logging.error(f"FTP URL '{self.dir}' does not match the pattern 'ftp://user:password@host:port/path'"
                              " or 'ftp://host:port/path'.")
                return None
        else:
            # Anything that does not start with ftp:// is assumed to be a directory
            dir = Path(self.dir)
            if not dir.is_dir():
                logging.error(f"The source path '{dir}' does not exist and will be skipped.")
                return None
            return MountedDataSource.construct(rootDir=dir)


class ConfigFile(BaseModel, extra=Extra.forbid):
    # disallow unknown keys via extra=Extra.forbid
    # sources and backup_root_dir are mandatory, so they do not get a default
    sources: list[ConfigFileSource]
    backup_root_dir: Path
    # StrEnum and pydantic are compatible out of the box, including errors for invalid strings
    mode: BACKUP_MODE = BACKUP_MODE.HARDLINK
    versioned: bool = True
    version_name: str = "%Y_%m_%d"
    compare_with_last_backup: bool = True
    copy_empty_dirs: bool = True
    save_actionfile: bool = True
    open_actionfile: bool = False
    apply_actions: bool = True
    # use a list instead of a set because the entries are ordered
    compare_method: list[COMPARE_METHOD] = Field(default_factory=lambda: [COMPARE_METHOD.MODDATE, COMPARE_METHOD.SIZE])
    log_level: LOG_LEVEL = LOG_LEVEL.INFO
    save_actionhtml: bool = True
    open_actionhtml: bool = False
    # Actions and HTMLFlags to be excluded from the action html
    exclude_actionhtml_actions: list[Union[ACTION, HTMLFLAG]] = Field(default_factory=list)
    # maximum number of errors until the backup is called a failure (-1 to disable)
    max_scanning_errors: int = 50
    max_backup_errors: int = 50
    # Decides what to do if the target drive does not have enough space
    target_drive_full_action: DRIVE_FULL_ACTION = DRIVE_FULL_ACTION.PROMPT

    @staticmethod
    def check_if_default(value: Any, field: fields.ModelField, values: dict[str, object],
                         conditionField: str, conditionValue: object) -> Any:
        """
            Sets `value` to `field.default` and logs an error if
            ```
            (value != field.default) and (values[conditionField] == conditionValue).

            ```
            Then returns `value`.
        """
        # field.default is typed Any, so this method must return Any as well
        if (value != field.default) and (conditionField in values) and (values[conditionField] == conditionValue):
            logging.error(f"Config error: if '{conditionField}' is set to '{conditionValue}', "
                          + f"'{field.alias}' is set to '{field.default}' automatically.")
            return field.default
        else:
            return value

    # validator: set these fields to the default values for hardlink mode
    @validator('versioned', 'compare_with_last_backup')
    def force_default_in_hardlink_mode(cls, value: bool, field: fields.ModelField, values: dict[str, object]) -> Any:
        # set 'versioned' and 'compare_with_last_backup' to True if mode == 'hardlink'
        return cls.check_if_default(value, field, values, 'mode', BACKUP_MODE.HARDLINK)

    @validator('open_actionfile')
    def validate_open_actionfile(cls, value: bool, field: fields.ModelField, values: dict[str, object]) -> Any:
        # set 'open_actionfile' to False if 'save_actionfile' is False
        return cls.check_if_default(value, field, values, 'save_actionfile', False)

    @validator('open_actionhtml')
    def validate_open_actionhtml(cls, value: bool, field: fields.ModelField, values: dict[str, object]) -> Any:
        # set 'open_actionhtml' to False if 'save_actionhtml' is False
        return cls.check_if_default(value, field, values, 'save_actionhtml', False)

    @staticmethod
    def _validationErrorToStr(e: ValidationError) -> str:
        """
        A slightly decluttered version of ValidationError.__str__
        """
        errors = e.errors()
        return (f"{len(errors)} error{'' if len(errors)==1 else 's'} in the configuration file:\n" +
                "\n".join(f"{_display_error_loc(e)}\n  {e['msg']}" for e in errors))

    @classmethod
    # missing Self type, to be introduced in Python 3.11. Not a problem if we don't subclass this
    def loadUserConfigFile(cls, userConfigPath: Union[str, Path]) -> ConfigFile:
        """
        Loads the provided config file, checks for mandatory keys and adds missing keys from the default file.
        """
        # Locate and load config file
        try:
            with Path(userConfigPath).open(encoding="utf-8") as userConfigFile:
                return cls.loadJson(userConfigFile.read())
        except FileNotFoundError as e:
            logging.critical(f"Configuration file '{userConfigPath}' does not exist.")
            raise BackupError(e)

    @classmethod
    def loadJson(cls, jsonStr: str) -> ConfigFile:
        try:
            jsonObject = strip_comments_json.loads(jsonStr)
            userConfig = ConfigFile.parse_obj(jsonObject)
            return userConfig
        except JSONDecodeError as e:
            logging.critical(f"The configuration file is not a valid JSON file:\n{e}")
            raise BackupError(e)
        except ValidationError as e:
            logging.critical(cls._validationErrorToStr(e))
            raise BackupError(e)

    @classmethod
    def export_default(cls) -> str:
        defaultFile = cls(
            # use parse_obj because Pylance does not understand optional aliases
            sources=[ConfigFileSource.parse_obj({'name': "source-1", 'dir': Path("path-of-first-source"), 'exclude_paths': ["excluded-path"]})],
            backup_root_dir=Path("target-root-directory"))
        return defaultFile.json(indent=1)
