from enum import Enum
from logging import Formatter

LOG_FILENAME = 'log.txt'
METADATA_FILENAME = 'metadata.json'
ACTIONS_FILENAME = 'actions.json'
ACTIONSHTML_FILENAME = 'actions.html'
LOGFORMAT = Formatter(fmt='%(levelname)-8s %(asctime)-8s.%(msecs)03d: %(message)s', datefmt='%H:%M:%S')
DEFAULT_CONFIG_FILENAME = 'default.config.json'

# from https://www.cosmicpython.com/blog/2020-10-27-i-hate-enums.html
class StrEnum(str, Enum):
    # so str(StrEnum.Entry1) == StrEnum.Entry1.value
    def __str__(self) -> str:
        return str.__str__(self)

class ACTIONS(StrEnum):
    COPY = 'copy'
    HARDLINK = 'hardlink'
    DELETE = 'delete'

class FLAGS(StrEnum):
    NEW = 'new'
    IN_NEW_DIR = 'inNewDir'
    MODIFIED = 'modified'
    EXISTING_DIR = 'existingDir'
    NEW_DIR = 'newDir'
    EMPTY_DIR = 'emptyDir'

class DRIVE_FULL_ACTIONS(StrEnum):
    PROMPT = 'prompt'
    ABORT = 'abort'
    PROCEED = 'proceed'