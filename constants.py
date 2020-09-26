from logging import Formatter

LOG_FILENAME = "log.txt"
METADATA_FILENAME = "metadata.json"
ACTIONS_FILENAME = "actions.json"
ACTIONSHTML_FILENAME = "actions.html"
LOGFORMAT = Formatter(fmt='%(levelname)-8s %(asctime)-8s.%(msecs)03d: %(message)s', datefmt="%H:%M:%S")
DEFAULT_CONFIG_FILENAME = "default.config.json"

DRIVE_FULL_PROMPT = 'prompt'
DRIVE_FULL_ABORT = 'abort'
DRIVE_FULL_PROCEED = 'proceed'
DRIVE_FULL_ACTIONS = [DRIVE_FULL_PROMPT, DRIVE_FULL_ABORT, DRIVE_FULL_PROCEED]