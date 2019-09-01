from logging import Formatter

LOG_FILENAME = "log.txt"
METADATA_FILENAME = "metadata.json"
ACTIONS_FILENAME = "actions.json"
ACTIONSHTML_FILENAME = "actions.html"
LOGFORMAT = Formatter(fmt='%(levelname)-8s %(asctime)-8s.%(msecs)03d: %(message)s', datefmt="%H:%M:%S")
DEFAULT_CONFIG_FILENAME = "default.config.json"
