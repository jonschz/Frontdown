from __future__ import annotations

from json import JSONDecodeError
from typing import Any, Union
from pathlib import Path
import logging

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from . import strip_comments_json
from .basics import (
    ACTION,
    COMPARE_METHOD,
    HTMLFLAG,
    BACKUP_MODE,
    CONFIG_ACTION_ON_ERROR,
    LOG_LEVEL,
    BackupError,
)


class ConfigFileSource(BaseModel):
    name: str
    dir: str
    exclude_paths: list[str]

    # for legacy reasons - allow exclude-paths as an alias, as old metadata.json files still have this name
    @model_validator(mode="before")
    def legacy_alias_name(cls, values: dict[str, Any]) -> dict[str, Any]:
        if "exclude-paths" in values:
            values["exclude_paths"] = values["exclude-paths"]
            del values["exclude-paths"]
        return values


class ConfigFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    compare_method: list[COMPARE_METHOD] = Field(
        default_factory=lambda: [COMPARE_METHOD.MODDATE, COMPARE_METHOD.SIZE]
    )
    log_level: LOG_LEVEL = LOG_LEVEL.INFO
    save_actionhtml: bool = True
    open_actionhtml: bool = False
    # Actions and HTMLFlags to be excluded from the action html
    exclude_actionhtml_actions: list[Union[ACTION, HTMLFLAG]] = Field(
        default_factory=list
    )
    # maximum number of errors until the backup is called a failure (-1 to disable)
    max_scanning_errors: int = 50
    max_backup_errors: int = 50
    # Decides what to do if the target drive does not have enough space
    target_drive_full_action: CONFIG_ACTION_ON_ERROR = CONFIG_ACTION_ON_ERROR.PROMPT
    # Decide what to do if a source or the target are unavailable
    source_unavailable_action: CONFIG_ACTION_ON_ERROR = CONFIG_ACTION_ON_ERROR.PROMPT

    # TODO: can this be typed with a generic?
    @staticmethod
    def check_if_default(
        value: Any, info: ValidationInfo, conditionField: str, conditionValue: object
    ) -> Any:
        """
        Returns the field's default value and logs an error if
        ```
        (value != field.default) and (values[conditionField] == conditionValue).

        ```
        Otherwise returns `value`.
        """
        field = ConfigFile.model_fields.get(info.field_name or "", None)
        assert field is not None

        # field.default is typed Any, so this method must return Any as well
        if (
            (value != field.default)
            and (conditionField in info.data)
            and (info.data[conditionField] == conditionValue)
        ):
            logging.error(
                f"Config error: if '{conditionField}' is set to '{conditionValue}', "
                + f"'{info.field_name}' is set to '{field.default}' automatically."
            )
            return field.default
        else:
            return value

    @field_validator("versioned")
    def force_default_in_hardlink_mode(cls, value: bool, info: ValidationInfo) -> Any:
        # set `versioned` to True if `mode` == "hardlink"
        return cls.check_if_default(value, info, "mode", BACKUP_MODE.HARDLINK)

    @field_validator("compare_with_last_backup")
    def force_compare_for_versioned(cls, value: bool, info: ValidationInfo) -> Any:
        # set 'compare_with_last_backup' to True if 'versioned' == True
        return cls.check_if_default(value, info, "versioned", True)

    @field_validator("open_actionfile")
    def validate_open_actionfile(cls, value: bool, info: ValidationInfo) -> Any:
        # set 'open_actionfile' to False if 'save_actionfile' is False
        return cls.check_if_default(value, info, "save_actionfile", False)

    @field_validator("open_actionhtml")
    def validate_open_actionhtml(cls, value: bool, info: ValidationInfo) -> Any:
        # set 'open_actionhtml' to False if 'save_actionhtml' is False
        return cls.check_if_default(value, info, "save_actionhtml", False)

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
            userConfig = ConfigFile.model_validate(jsonObject)
            return userConfig
        except JSONDecodeError as e:
            logging.critical(f"The configuration file is not a valid JSON file:\n{e}")
            raise BackupError(e)
        except ValidationError as e:
            logging.critical(e)
            raise BackupError(e)

    @classmethod
    def export_default(cls) -> str:
        defaultFile = cls(
            # use parse_obj because Pylance does not understand optional aliases
            sources=[
                ConfigFileSource.model_validate(
                    {
                        "name": "source-1",
                        "dir": Path("path-of-first-source"),
                        "exclude_paths": ["excluded-path"],
                    }
                )
            ],
            backup_root_dir=Path("target-root-directory"),
        )
        return defaultFile.json(indent=1)
