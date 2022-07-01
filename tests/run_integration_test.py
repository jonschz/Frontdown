import os
import sys
from pathlib import Path
from threading import Thread
from datetime import datetime, timezone

import pre_run_cleanup
from Frontdown.config_files import ConfigFile
from Frontdown.backup_job import backupJob
import Frontdown.run_backup as run_backup

import stat
from pyftpdlib.authorizers import DummyAuthorizer
import pyftpdlib.handlers
from pyftpdlib.filesystems import FilesystemError, AbstractedFS
from pyftpdlib.servers import FTPServer


# A bit of an ugly hack to get pyftpdlib to support microseconds
def format_mlsx_modified(self, basedir, listing, perms, facts, ignore_err=True):
    assert isinstance(basedir, str), basedir

    # datetime.fromtimestamp() defaults to local timezone if tz is set to None
    tz = timezone.utc if self.cmd_channel.use_gmt_times else None
    permdir = ''.join([x for x in perms if x not in 'arw'])
    permfile = ''.join([x for x in perms if x not in 'celmp'])
    if ('w' in perms) or ('a' in perms) or ('f' in perms):
        permdir += 'c'
    if 'd' in perms:
        permdir += 'p'
    show_type = 'type' in facts
    show_perm = 'perm' in facts
    show_size = 'size' in facts
    show_modify = 'modify' in facts
    show_create = 'create' in facts
    show_mode = 'unix.mode' in facts
    show_uid = 'unix.uid' in facts
    show_gid = 'unix.gid' in facts
    show_unique = 'unique' in facts
    for basename in listing:
        retfacts = dict()
        file = os.path.join(basedir, basename)
        # in order to properly implement 'unique' fact (RFC-3659,
        # chapter 7.5.2) we are supposed to follow symlinks, hence
        # use os.stat() instead of os.lstat()
        try:
            st = self.stat(file)
        except (OSError, FilesystemError):
            if ignore_err:
                continue
            raise
        # type + perm
        # same as stat.S_ISDIR(st.st_mode) but slightly faster
        isdir = (st.st_mode & 61440) == stat.S_IFDIR
        if isdir:
            if show_type:
                if basename == '.':
                    retfacts['type'] = 'cdir'
                elif basename == '..':
                    retfacts['type'] = 'pdir'
                else:
                    retfacts['type'] = 'dir'
            if show_perm:
                retfacts['perm'] = permdir
        else:
            if show_type:
                retfacts['type'] = 'file'
            if show_perm:
                retfacts['perm'] = permfile
        if show_size:
            retfacts['size'] = st.st_size  # file size
        # last modification time
        if show_modify:
            try:
                retfacts['modify'] = datetime.fromtimestamp(st.st_mtime, tz=tz).strftime('%Y%m%d%H%M%S.%f')
            # it could be raised if last mtime happens to be too old
            # (prior to year 1900)
            except ValueError:
                pass
        if show_create:
            # on Windows we can provide also the creation time
            try:
                retfacts['create'] = datetime.fromtimestamp(st.st_ctime, tz=tz).strftime('%Y%m%d%H%M%S.%f')
            except ValueError:
                pass
        # UNIX only
        if show_mode:
            retfacts['unix.mode'] = oct(st.st_mode & 511)
        if show_uid:
            retfacts['unix.uid'] = st.st_uid
        if show_gid:
            retfacts['unix.gid'] = st.st_gid

        # We provide unique fact (see RFC-3659, chapter 7.5.2) on
        # posix platforms only; we get it by mixing st_dev and
        # st_ino values which should be enough for granting an
        # uniqueness for the file listed.
        # The same approach is used by pure-ftpd.
        # Implementors who want to provide unique fact on other
        # platforms should use some platform-specific method (e.g.
        # on Windows NTFS filesystems MTF records could be used).
        if show_unique:
            retfacts['unique'] = "%xg%x" % (st.st_dev, st.st_ino)

        # facts can be in any order but we sort them by name
        factstring = "".join(["%s=%s;" % (x, retfacts[x])
                              for x in sorted(retfacts.keys())])
        line = "%s %s\r\n" % (factstring, basename)
        yield line.encode('utf8', self.cmd_channel.unicode_errors)


class FTPServerThread(Thread):
    def run(self):
        AbstractedFS.format_mlsx = format_mlsx_modified
        authorizer = DummyAuthorizer()
        authorizer.add_user("user", "pythontest", "./tests/integration_test/source-2", perm="elr")
        handler = pyftpdlib.handlers.FTPHandler
        # this is needed so we don't have mismatching times later
        handler.use_gmt_times = False
        handler.debug = False
        handler.authorizer = authorizer
        server = FTPServer(("127.0.0.1", 12346), handler)
        server.debug = False
        server.serve_forever(handle_exit=True)


def run_integration_test(openHTML: bool = False) -> int:
    # We set up two directory structures.
    # test-source-1  will be backed up directly, test-source-2 will be backed up through an FTP server
    pre_run_cleanup.regenerate_test_structure()
    ftpserver = FTPServerThread(daemon=True)
    ftpserver.start()
    logger = run_backup.setup_stats_and_logger()
    # doing it this way skips very little code
    # TODO: excluded files and folders in the integration test
    jsonContents = '''
{
    "sources": [
        {
            "name": "test-source-1",
            "dir": "./tests/integration_test/source-1",
            // verify that both the legacy exclude-paths and the new exclude_paths work
            "exclude_paths": []
        },
//        {
//            "name": "test-source-2",
//            "dir": "./tests/integration_test/source-2",
//            "exclude-paths": []
//        },
        {
            "name": "test-source-2",
            "dir": "ftp://user:pythontest@127.0.0.1:12346/",
            "exclude-paths": []
        }
    ],
    "backup_root_dir": "./tests/integration_test/target",
    "mode": "hardlink",
    "copy_empty_dirs": true,
    "save_actionfile": true,
    "open_actionfile": false,
    "apply_actions": true,
    "compare_method": ["moddate", "size"],
    "log_level": "DEBUG",
    "save_actionhtml": true,
    "open_actionhtml": false,
    "exclude_actionhtml_actions": [],
    "target_drive_full_action": "abort"
}
    '''
    config = ConfigFile.loadJson(jsonContents)
    config.open_actionhtml = openHTML
    return run_backup.main(backupJob.initMethod.fromConfigObject, logger, config)
    # return run_backup.main(backupJob.initMethod.fromConfigFile, logger,
    #                        "./tests/integration_test/integration-test-config.json")


def test_integration_test():
    assert run_integration_test() == 0, "Integration test terminated with return code 1"
    verify_test_result()


def verify_test_result():
    def hardlink_check(relPath: str | Path, expected: bool = True) -> None:
        """Verify that two files in the targets are hardlinked"""
        paths = [targets[i].joinpath(relPath) for i in range(2)]
        success = (expected == os.path.samefile(*paths))
        if not success:
            if expected:
                raise AssertionError(f"File {relPath} is not hardlinked, but expected to be.\n"
                                     f"Moddates: {[str(datetime.fromtimestamp(p.stat().st_mtime)) for p in paths]}")
            else:
                raise AssertionError(f"File {relPath} is hardlinked, but expected not to be.")

    def check_level(dir: Path, level: int):
        if level < pre_run_cleanup.levels:
            for j in range(pre_run_cleanup.dirs_per_level):
                newdir = dir.joinpath(pre_run_cleanup.generateDirname(s, level, j))
                check_level(newdir, level+1)
        for j in range(pre_run_cleanup.files_per_level):
            newfile = dir.joinpath(pre_run_cleanup.generateFilename(s, level, j))
            hardlink_check(newfile)

    # in the format yyyy_mm_dd it is sufficient to sort alphabetically
    targets = sorted(Path("./tests/integration_test/target").iterdir(), key=lambda x: str(x))
    assert len(targets) == 2, "Unexpected number of targets"
    for s in range(pre_run_cleanup.sources):
        relpath = Path(f"test-source-{s+1}")
        check_level(relpath, 1)
        # the modified file must not be hardlinked to its source
        hardlink_check(relpath.joinpath(pre_run_cleanup.filename_modified), expected=False)
        # check if the deleted file is actually deleted, and that the new files exist
        newTargetPath = targets[1].joinpath(relpath)
        assert not newTargetPath.joinpath(pre_run_cleanup.filename_deleted).exists()
        assert newTargetPath.joinpath(pre_run_cleanup.new_file_name).exists()
        assert newTargetPath.joinpath(pre_run_cleanup.new_dir_name).joinpath(pre_run_cleanup.new_subfile_name).exists()


# this is needed for debugging / running the integration test from the vscode run configuration
if __name__ == '__main__':
    # show the action HTML when run from vscode
    exitCode = run_integration_test(openHTML=True)
    verify_test_result()
    sys.exit(exitCode)
