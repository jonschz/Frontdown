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


def regenerate_test_structure():
    sources = 2
    levels = 3
    dirs_per_level = 2
    files_per_level = 2
    filename_deleted = "deleted-file.txt"
    filename_modified = "modified-file.txt"

    def write_random_content(path: Path):
        with open(path, 'w') as file:
            content = ''.join(random.choice(string.ascii_lowercase) for i in range(100))
            file.write(content)

    def generate(dir: Path, level: int):
        for j in range(dirs_per_level):
            newdir = dir.joinpath(f"S{s+1}L{level}D{j+1}")
            os.makedirs(newdir)
            if level < levels:
                generate(newdir, level+1)
        for j in range(files_per_level):
            newfile = dir.joinpath(f"S{s+1}L{level}F{j+1}.txt")
            write_random_content(newfile)

    # erase the previous setup
    # TODO: Decide: Do this always? Or check if everything is there, and leave it in place?
    currentPath = Path(__file__).parent.resolve()
    for s in range(sources):
        shutil.rmtree(currentPath.joinpath(f"source-{s+1}"), ignore_errors=True)
    shutil.rmtree(currentPath.joinpath("./target"), ignore_errors=True)

    # generate the two source trees
    for s in range(sources):
        top = currentPath.joinpath(f"source-{s+1}")
        generate(top, 1)
        write_random_content(top.joinpath(filename_deleted))
        write_random_content(top.joinpath(filename_modified))

    # generate the target tree
    backupPath = currentPath.joinpath("./target")
    targetPath = backupPath.joinpath("./2022_03_07")
    os.makedirs(targetPath)
    for s in range(sources):
        source = currentPath.joinpath(f"./source-{s+1}")
        target = targetPath.joinpath(f"./test-source-{s+1}")
        shutil.copytree(source, target)
    shutil.copy2(currentPath.joinpath("metadata-integration-test.json"), targetPath.joinpath("metadata.json"))

    # make modifications:
    # new file, modified file, deleted file, new folder, new sub-folder, new file in new folder
    # Ideas: inaccessible file?
    targetPath.joinpath(filename_deleted)
    for s in range(sources):
        source = currentPath.joinpath(f"./source-{s+1}")
        source.joinpath(filename_deleted).unlink()
        write_random_content(source.joinpath(filename_modified))
        write_random_content(source.joinpath("new-file.txt"))
        subdir = source.joinpath("new-dir")
        subdir.mkdir()
        write_random_content(subdir.joinpath("new-subfile.txt"))

    delete_all_but_latest_backup(backupPath)


if __name__ == '__main__':
    regenerate_test_structure()
