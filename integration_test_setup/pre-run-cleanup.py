import os, shutil

TARGET_DIR = ".\\targets\\existing-target"

if __name__ == '__main__':
    list = [entry.name for entry in sorted(os.scandir(TARGET_DIR), key = lambda x: x.name)]
    # delete all but the first (i.e. oldest) backup
    list.pop(0)
    print(f"Deleting folders: {list}")
    for l in list:
        shutil.rmtree(os.path.join(TARGET_DIR, l), ignore_errors=True)