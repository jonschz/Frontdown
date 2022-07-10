from typing import Optional, Union


# Based on https://stackoverflow.com/a/1094933/
def sizeof_fmt(numBytes: Union[int, float], suffix: str = 'B') -> str:
    """Convertes a number of bytes into a human-readable string"""
    value = float(numBytes)
    # give bytes with zero decimals, everything else with one
    if abs(value) < 1024.0:
        return f"{value:3.0f} {suffix}"
    for unit in ['Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi']:
        value /= 1024.0
        # fix the bug explained in https://stackoverflow.com/a/63839503/:
        # display 1023.95 Kib as 1 MiB, not as 1024.0 KiB
        if abs(value) < 1024.0 - .05:
            return f"{value:3.1f} {unit}{suffix}"
    return f"{value:3.1f} Yi{suffix}"


# Statistics dictionary; will be updated by various functions
class statistics_module:
    INDENT = 4
    LABEL_WIDTH = 20

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        # scanning phase
        self.scanning_errors = 0        # covers folder and file errors, because they cannot always be distinguished
        self.bytes_in_source = 0
        self.bytes_in_compare = 0
        self.files_in_source = 0
        self.files_in_compare = 0
        self.folders_in_source = 0
        self.folders_in_compare = 0
        # action generation phase
        self.files_to_copy = 0
        self.bytes_to_copy = 0
        self.files_to_hardlink = 0
        self.bytes_to_hardlink = 0
        self.files_to_delete = 0
        self.bytes_to_delete = 0
        # backup phase
        self.backup_errors = 0
        self.bytes_copied = 0
        self.files_copied = 0
        self.bytes_hardlinked = 0
        self.files_hardlinked = 0
        self.files_deleted = 0
        self.bytes_deleted = 0

    @classmethod
    def rows(cls, data: list[Optional[tuple[str, str]]]) -> str:
        """Takes a list of tuples `(label, data)`, returns a formatted string skipping all `None` entries.
        The string is indented according to `statistics_module.INDENT`, and the label is padded to the right
        if it is shorter than `statistics_module.LABEL_WIDTH`."""
        def formatRow(row: tuple[str, str]) -> str:
            return (' ' * cls.INDENT) + (row[0] + ':').ljust(cls.LABEL_WIDTH, " ") + row[1]
        return '\n'.join([formatRow(row) for row in data if row is not None])

    def scanning_protocol(self) -> str:
        return self.rows([("Source", f"{self.folders_in_source} folders, {self.files_in_source} files, {sizeof_fmt(self.bytes_in_source)}"),
                          ("Compare", f"{self.folders_in_compare} folders, {self.files_in_compare} files, {sizeof_fmt(self.bytes_in_compare)}"),
                          ("Scan errors", f"{self.scanning_errors}")])
        # return (f"\tSource:\t\t\t{self.folders_in_source} folders, {self.files_in_source} files, {sizeof_fmt(self.bytes_in_source)}"
        #         f"\n\tCompare:\t\t{self.folders_in_compare} folders, {self.files_in_compare} files, {sizeof_fmt(self.bytes_in_compare)}"
        #         f"\n\tScan errors:\t\t{self.scanning_errors}")

    def action_generation_protocol(self) -> str:
        return self.rows([("To copy", f"{self.files_to_copy} files, {sizeof_fmt(self.bytes_to_copy)}"),
                          ("To hardlink", f"{self.files_to_hardlink} files, {sizeof_fmt(self.bytes_to_hardlink)}"),
                          (None if self.files_to_delete == 0 else ("To delete", f"{self.files_to_delete} files, {sizeof_fmt(self.bytes_to_delete)}"))])

    def backup_protocol(self) -> str:
        return self.rows([("Copied", f"{self.files_copied} files, {sizeof_fmt(self.bytes_copied)}"),
                          ("Hardlinked", f"{self.files_hardlinked} files, {sizeof_fmt(self.bytes_hardlinked)}"),
                          # check for files_to_delete here in case all deletions have failed
                          (None if self.files_to_delete == 0 else ("Deleted", f"{self.files_deleted} files, {sizeof_fmt(self.bytes_deleted)}")),
                          ("Backup Errors", f"{self.backup_errors}")])

    def full_protocol(self) -> str:
        return "\n\n".join((self.scanning_protocol(), self.action_generation_protocol(), self.backup_protocol()))


# TODO contemplate a more elegant solution than a singleton
# global variable to be changed by the other functions
stats = statistics_module()
