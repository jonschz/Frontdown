from typing import Optional, Union
import pydantic
import strip_comments_json
from pydantic import BaseModel, Field
import constants

# Try two things:
#   1) pydantic approach (https://pydantic-docs.helpmanual.io/usage/exporting_models/)
#   2) for LL: probably contains all that is needed for e.g. sending and reconstructing cards by id;
#       see examples "Serialising self-reference or other models" and "Serialising subclasses"

class ActionParameters(BaseModel):
    name: str
    htmlFlags: Optional[str]

class Action(BaseModel):
    type: str
    isDir: bool
    params: ActionParameters

class BackupDataSet(BaseModel):
    name: str
    sourceDir: str
    targetDir: str
    compareDir: str
    actions: list[Action]

class BackupDataRootList(BaseModel):
    __root__: list[BackupDataSet]

def testReadActions():
    testActionList = BackupDataRootList.parse_file(".\\integration_test_setup\\targets\\existing-target\\2022_03_03\\actions.json").__root__
    print(testActionList)
    # option 1 to get the dict
    dictList1 = BackupDataRootList(__root__=testActionList).dict()['__root__']
    # print(json.dumps(dictList1, indent=1))
    # option 2:
    dictList2 = [d.dict() for d in testActionList]
    # print(json.dumps(dictList2, indent=1))
    print(f"\n{dictList1 == dictList2}")


class ConfigFileSource(BaseModel):
    name: str
    dir: str
    #FIXME better to rename than to keep using alias
    exclude_paths: list[str] = Field(..., alias='exclude-paths')


class ConfigFileData(BaseModel):
    # sources and backup_root_dir are mandatory, so they do not get a default
    sources: list[ConfigFileSource]
    backup_root_dir: str
    # Enums work out of the box!
    mode: constants.BACKUP_MODE = Field(constants.BACKUP_MODE.HARDLINK)  
    versioned: bool = Field(True)
    version_name: str = Field("%Y_%m_%d")
    compare_with_last_backup: bool = Field(True)
    save_actionfile: bool = Field(True)
    open_actionfile: bool = Field(False)
    apply_actions: bool = Field(True)
    #TODO migrate to Enum
    # must use default_factory for lists, otherwise we get a shared mutable
    #// ordered list of possible elements "moddate" (modification date), "size", "bytes" (full comparison), "hash" (not yet implemented)
    compare_method: list[str] = Field(default_factory=lambda: ["moddate", "size"])
    #TODO migrate to Enum
    #// Log level, possible options: "ERROR", "WARNING", "INFO", "DEBUG"
    log_level: str = Field("INFO")
    save_actionhtml: bool = Field(True)
    open_actionhtml: bool = Field(False)
    #// "copy", "hardlink", "delete", "new", "inNewDir", "modified", "existingDir", "newDir", "emptyDir"
    # works natively as well!
    exclude_actionhtml_actions: list[Union[constants.ACTION, constants.HTMLFLAG]] = Field(default_factory=list)
    max_scanning_errors: int = Field(
        50, description = "maximum number of errors until the backup is called a failure (-1 to disable)")
    max_backup_errors: int = Field(50)
    target_drive_full_action: constants.DRIVE_FULL_ACTION = Field(
        constants.DRIVE_FULL_ACTION.PROMPT,
        description = "Decides what to do if the target drive is too full. Options: proceed, prompt, abort")

def testReadConfig():
    # with open("default.config.json") as configFile:
    with open("test-config.json") as configFile:
        testConfig = ConfigFileData.parse_obj(strip_comments_json.load(configFile))
        print(testConfig)
        # print(json.dumps(testConfig.dict(), indent=1))

if __name__ == '__main__':
    # testReadActions(s)
    testReadConfig()