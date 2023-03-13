import os

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


def prevent_sleep() -> None:
    if os.name == 'nt':
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def enable_sleep() -> None:
    if os.name == 'nt':
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS)
