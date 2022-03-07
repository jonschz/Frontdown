import os, shutil
import random
from pathlib import Path
import string

def delete_all_but_latest_backup(target: Path):
    allBackups = [entry.name for entry in sorted(os.scandir(target), key = lambda x: x.name)]
    # delete all but the first (i.e. oldest) backup
    if len(allBackups) > 0:
        allBackups.pop(0)
        print(f"Deleting folders: {allBackups}")
        for newer in allBackups:
            shutil.rmtree(os.path.join(target, newer), ignore_errors=True)
# TODO:
# * generate the first backup automatically (without calling backup.py?)
# * make the following modifications:
#   * new file, modified file, deleted file, new folder, new sub-folder, new file in new folder
#   * inaccessible file?
def regenerate_test_structure():
    sources = 2
    levels = 3
    dirs_per_level = 2
    files_per_level = 2
    def generate(dir: Path, level: int):
        for j in range(dirs_per_level):
            newdir = dir.joinpath(f"S{s}L{level}D{j+1}")
            os.makedirs(newdir)
            if level < levels:
                generate(newdir, level+1)
        for j in range(files_per_level):
            newfile = dir.joinpath(f"S{s}L{level}F{j+1}.txt")
            with open(newfile, 'w') as file:
                content = ''.join(random.choice(string.ascii_lowercase) for i in range(100))
                newfile.write_text(content)

    currentPath = Path(__file__).parent.resolve()
    for s in range(1, sources + 1):
        top = currentPath.joinpath(f"source-{s}")
        if not top.exists():
            generate(top, 1)
    targetPath = currentPath.joinpath("target")
    os.makedirs(targetPath, exist_ok=True)
    
    delete_all_but_latest_backup(targetPath)

if __name__ == '__main__':
    regenerate_test_structure()