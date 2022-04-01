from enum import Enum
from logging import Formatter

# This exception should be raised if a serious problem with the backup appears, but the code
# is working as intended. This is to differentiate backup errors from programming errors.
class BackupError(Exception):
    pass

class constants:
    LOG_FILENAME = 'log.txt'
    METADATA_FILENAME = 'metadata.json'
    ACTIONS_FILENAME = 'actions.json'
    ACTIONSHTML_FILENAME = 'actions.html'
    HTMLTEMPLATE_FILENAME = 'template.html'
    LOGFORMAT = Formatter(fmt='%(levelname)-8s %(asctime)-8s.%(msecs)03d: %(message)s', datefmt='%H:%M:%S')

# from https://www.cosmicpython.com/blog/2020-10-27-i-hate-enums.html
class StrEnum(str, Enum):
    def __str__(self) -> str:
        """
        This assures `str(StrEnum(x)) == StrEnum(x).value`.
        """
        return str.__str__(self)

class BACKUP_MODE(StrEnum):
    HARDLINK = 'hardlink'
    MIRROR = 'mirror'
    SAVE = 'save'

class COMPARE_METHOD(StrEnum):
    MODDATE = "moddate" # modification date
    SIZE = "size"
    BYTES = "bytes" # full comparison
    # HASH = "hash" (not implemented)

class ACTION(StrEnum):
    COPY = 'copy'
    HARDLINK = 'hardlink'
    DELETE = 'delete'

class HTMLFLAG(StrEnum):
    NEW = 'new'
    IN_NEW_DIR = 'inNewDir'
    MODIFIED = 'modified'
    EXISTING_DIR = 'existingDir'
    NEW_DIR = 'newDir'
    EMPTY_DIR = 'emptyDir'
    NONE = ''

class DRIVE_FULL_ACTION(StrEnum):
    PROMPT = 'prompt'
    ABORT = 'abort'
    PROCEED = 'proceed'

# from logging._nameToLevel 
class LOG_LEVEL(StrEnum):
    CRITICAL = 'CRITICAL'
    ERROR = 'ERROR'
    WARNING = 'WARNING'
    INFO = 'INFO'
    DEBUG = 'DEBUG'