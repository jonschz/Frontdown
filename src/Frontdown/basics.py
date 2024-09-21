from datetime import datetime, timedelta, tzinfo
from enum import Enum
from functools import cache
from logging import Formatter
from typing import Final, Optional


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
    MODDATE = 'moddate'     # modification date
    SIZE = 'size'
    BYTES = 'bytes'         # compare the entire file contents
    # HASH = "hash"         # (not implemented)


# Implemented actions:
# - copy (always from source to target),
# - delete (always in target)
# - hardlink (always from compare directory to target directory)
# Not implemented:
# - rename (always in target) (2-variate) (only needed for move detection)
# - hardlink2 (alway from compare directory to target directory) (2-variate) (only needed for move detection)
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


class CONFIG_ACTION_ON_ERROR(StrEnum):
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


# Timestamp related code

@cache  # the local timezone should only be computed once
def localTimezone() -> tzinfo:
    tz = datetime.now().astimezone().tzinfo
    assert tz is not None, "Could not determine local timezone"
    return tz


def timestampToDatetime(timestamp: float, tz: Optional[tzinfo] = None) -> datetime:
    """Returns an aware `datetime` instance. If `tz` is provided, uses that timezone, otherwise uses the local timezone."""
    # Alternative:
    #
    # return datetime.fromtimestamp(timestamp).astimezone()
    #
    # The major disadvantage is that it raises an OSError for timestamp < 86400.0 on Windows.
    # It is noteworthy that the alternative uses the date at `timestamp`, not the current date, to decide whether we are in DST.
    # In any case, the results always yield equivalent times (e.g. 09:00:00+1 or 08:00:00+2)
    # To test this:
    #
    # import random
    # minstamp = 86400
    # nowstamp = datetime.now().timestamp()
    # for i in range(1000000):
    #     r = random.random() * (nowstamp-minstamp) + minstamp
    #     tz1 = timezone(timedelta(hours=1))
    #     tz2 = timezone(timedelta(hours=-1))
    #     d1 = datetime.fromtimestamp(r, tz1)
    #     d2 = datetime.fromtimestamp(r, tz2)
    #     d3 = datetime.fromtimestamp(r).astimezone()
    #     assert d1 == d2 == d3
    #     assert abs(r - d1.timestamp()) < 1e-6
    #     assert d1.timestamp() == d2.timestamp() == d3.timestamp()
    # print("Finished")
    #
    return datetime.fromtimestamp(timestamp, tz=tz if tz is not None else localTimezone())


# Timstamps which differ by less than 1 microsecond are considered to be equal
MAXTIMEDELTA: Final[timedelta] = timedelta(microseconds=1)


def datetimeToLocalTimestamp(d: datetime) -> float:
    """Returns a `float` timestamp, to be used e.g. for `os.utime()`. Uses local timezone if tz is None."""
    return d.astimezone(localTimezone()).timestamp()
