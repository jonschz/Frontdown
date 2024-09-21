import os
import shutil
import random
from pathlib import Path
import string


def delete_all_but_latest_backup(target: Path):
    allBackups = [entry.name for entry in sorted(os.scandir(target), key=lambda x: x.name)]
    # delete all but the first (i.e. oldest) backup
    if len(allBackups) > 0:
        allBackups.pop(0)
        print(f"Deleting folders: {allBackups}")
        for newer in allBackups:
            shutil.rmtree(os.path.join(target, newer), ignore_errors=True)


sources = 2
levels = 3
dirs_per_level = 2
files_per_level = 2
filename_deleted = "deleted-file.txt"
filename_modified = "modified-file.txt"
# test utf-8 support
new_file_names = ["new-file.txt", "파일.txt"]
new_dir_name = "new-dir"
new_subfile_name = "new-subfile.txt"


def generateDirname(sourceInd: int, level: int, dirInd: int) -> str:
    return f"S{sourceInd+1}L{level}D{dirInd+1}"


def generateFilename(sourceInd: int, level: int, fileInd: int) -> str:
    return f"S{sourceInd+1}L{level}F{fileInd+1}.txt"


def regenerate_test_structure():

    def write_random_content(path: Path):
        with open(path, 'w') as file:
            content = ''.join(random.choice(string.ascii_lowercase) for i in range(100))
            file.write(content)

    def generate(dir: Path, level: int):
        for j in range(dirs_per_level):
            newdir = dir.joinpath(generateDirname(s, level, j))
            os.makedirs(newdir)
            if level < levels:
                generate(newdir, level+1)
        for j in range(files_per_level):
            newfile = dir.joinpath(generateFilename(s, level, j))
            write_random_content(newfile)

    integrationTestDir = Path("./tests/integration_test").resolve()
    # erase the previous setup
    for s in range(sources):
        sourcePath = integrationTestDir.joinpath(f"source-{s+1}")
        if sourcePath.exists():
            shutil.rmtree(sourcePath)

    targetPath = integrationTestDir.joinpath("target")
    if targetPath.exists():
        shutil.rmtree(targetPath)

    # generate the two source trees
    for s in range(sources):
        top = integrationTestDir.joinpath(f"source-{s+1}")
        generate(top, 1)
        write_random_content(top.joinpath(filename_deleted))
        write_random_content(top.joinpath(filename_modified))

    # generate the target tree
    backupPath = integrationTestDir.joinpath("./target")
    targetPath = backupPath.joinpath("./2022_03_07")
    os.makedirs(targetPath)
    for s in range(sources):
        source = integrationTestDir.joinpath(f"./source-{s+1}")
        target = targetPath.joinpath(f"./test-source-{s+1}")
        shutil.copytree(source, target)
    shutil.copy2(integrationTestDir.joinpath("metadata-integration-test.json"), targetPath.joinpath("metadata.json"))

    # make modifications:
    # new file, modified file, deleted file, new folder, new sub-folder, new file in new folder
    # Ideas: inaccessible file?
    targetPath.joinpath(filename_deleted)
    for s in range(sources):
        source = integrationTestDir.joinpath(f"./source-{s+1}")
        source.joinpath(filename_deleted).unlink()
        write_random_content(source.joinpath(filename_modified))
        for newFile in new_file_names:
            write_random_content(source.joinpath(newFile))
        subdir = source.joinpath(new_dir_name)
        subdir.mkdir()
        write_random_content(subdir.joinpath(new_subfile_name))

    delete_all_but_latest_backup(backupPath)


if __name__ == '__main__':
    regenerate_test_structure()
