from typing import Optional
from pydantic import BaseModel

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
    testActionList = BackupDataRootList.parse_file(".\\integration_test_setup\\target\\2022_03_07\\actions.json").__root__
    print(testActionList)
    # option 1 to get the dict
    dictList1 = BackupDataRootList(__root__=testActionList).dict()['__root__']
    # print(json.dumps(dictList1, indent=1))
    # option 2:
    dictList2 = [d.dict() for d in testActionList]
    # print(json.dumps(dictList2, indent=1))
    print(f"\n{dictList1 == dictList2}")

if __name__ == '__main__':
    testReadActions()