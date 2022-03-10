from __future__ import annotations

from json import JSONDecodeError
from typing import Union
from pathlib import Path

import strip_comments_json
# import pydantic
from pydantic import BaseModel, Field, ValidationError, Extra, validator, fields
from pydantic.error_wrappers import _display_error_loc
from basics import ACTION, HTMLFLAG, BACKUP_MODE, DRIVE_FULL_ACTION, LOG_LEVEL, BackupError
import logging

class ConfigFileSource(BaseModel):
    name: str
    dir: Path
    exclude_paths: list[str]
    # exclude_paths: list[str] = Field(..., alias='exclude-paths') # old, inconvenient name

class ConfigFile(BaseModel, extra=Extra.forbid):
    # disallow unknown keys via extra=Extra.forbid
    # sources and backup_root_dir are mandatory, so they do not get a default
    sources: list[ConfigFileSource]
    backup_root_dir: Path
    # Enums work out of the box!
    mode: BACKUP_MODE = BACKUP_MODE.HARDLINK
    versioned: bool = True
    version_name: str = "%Y_%m_%d"
    compare_with_last_backup: bool = True
    save_actionfile: bool = True
    open_actionfile: bool = False
    apply_actions: bool = True
    #TODO migrate to Enum
    # must use default_factory for lists, otherwise we get a shared mutable
    #// ordered list of possible elements "moddate" (modification date), "size", "bytes" (full comparison), "hash" (not yet implemented)
    compare_method: list[str] = Field(default_factory=lambda: ["moddate", "size"])
    #TODO migrate to Enum
    # Log level, possible options: "CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"
    log_level: LOG_LEVEL = LOG_LEVEL.INFO
    save_actionhtml: bool = True
    open_actionhtml: bool = False
    # works natively as well!
    # Actions and HTMLFlags to be excluded from the action html
    exclude_actionhtml_actions: list[Union[ACTION, HTMLFLAG]] = Field(default_factory=list)
    # maximum number of errors until the backup is called a failure (-1 to disable)
    max_scanning_errors: int = 50
    max_backup_errors: int = 50
    # Decides what to do if the target drive is too full. Options: proceed, prompt, abort")
    target_drive_full_action: DRIVE_FULL_ACTION = DRIVE_FULL_ACTION.PROMPT
    
    # validator: set these fields to the default values for hardlink mode
    @validator('versioned', 'compare_with_last_backup')
    def force_default_in_hardlink_mode(cls, v: bool, values: dict[str, object], field: fields.ModelField):
        if (v != field.default) and ('mode' in values) and (values['mode'] == BACKUP_MODE.HARDLINK):
            logging.error(f"In backup mode '{values['mode']}', '{field.alias}' is set to '{field.default}' automatically.")
            return field.default
        else:
            return v

    @staticmethod
    def _validationErrorToStr(e: ValidationError) -> str:
        """
        A slightly decluttered version of ValidationError.__str__
        """
        errors =e.errors()
        return (
            f"{len(errors)} errors in the configuration file:\n" +
            "\n".join(f"{_display_error_loc(e)}\n  {e['msg']}" for e in errors)
    )

    @classmethod
    # missing Self type, to be introduced in Python 3.11. Not a problem if we don't subclass this
    def loadUserConfig(cls, userConfigPath: Path) -> ConfigFile:
        """
        Loads the provided config file, checks for mandatory keys and adds missing keys from the default file.
        """
        try:
            with userConfigPath.open(encoding="utf-8") as userConfigFile:
                userConfigJSON = strip_comments_json.load(userConfigFile)
                userConfig = ConfigFile.parse_obj(userConfigJSON)
                return userConfig
        except JSONDecodeError as e:
            logging.critical(f"The configuration file is not a valid JSON file:\n{e}")
            raise BackupError(e)
        except ValidationError as e:
            logging.critical(cls._validationErrorToStr(e))
            raise BackupError(e)
    
    @classmethod
    def export_default(cls) -> str:
        defaultFile = cls(sources=[ConfigFileSource(name="source-1", dir=Path("path-of-first-source"), exclude_paths=["excluded-path"])],
                          backup_root_dir=Path("target-root-directory"))
        return defaultFile.json(indent=1)


def testReadConfig():
    try:
        with open("./integration_test_setup/test-config.json") as configFile:
            configJSON = strip_comments_json.load(configFile)
            testConfig = ConfigFile.parse_obj(configJSON)
            print(testConfig)
            # print(json.dumps(testConfig.dict(), indent=1))
    except ValidationError as e:
        print(ConfigFile._validationErrorToStr(e))
    print(ConfigFile.export_default())



if __name__ == '__main__':
    testReadConfig()