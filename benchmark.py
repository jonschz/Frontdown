"""
    These benchmarks generate data needed to make the progress bar smoother:
    - time to create a hardlink
    - time to create a folder
    - time to create an empty file
    - time to copy 1 MiB of data
"""

import os
import glob
from file_methods import hardlink
from timeit import default_timer as timer
from shutil import copy2

root_dir = ".\\local_full_tests\\benchmark"


def setup_many_files():
    # create 1000 empty files
    for i in range(1, 1000):
        path = os.path.join(root_dir, "source-many", "%d.txt" % i)
        file = open(path, 'w+')
        file.close()
        

def setup_1mb_files():
    # create 100 1 MiB files
    buf = [0]*int(1024*1024)
    for i in range(1, 100):
        path = os.path.join(root_dir, "source-mib", "%d.txt" % i)
        file = open(path, 'wb+')
        file.write(bytearray(buf))
        file.close()        


def clear_dest():
    files = glob.glob(os.path.join(root_dir, "dest") + '\\*')
    for f in files:
        os.remove(f)
    
# one run: .6689 s, 0.6173 s, 0.5897 s, 0.5969 s.
# good guess: .6 seconds for 1k hardlinks, so .6 ms per hardlink
def benchmark_hardlink():
    # tempc
    clear_dest()
    start = timer()
    for i in range(1, 1000):
        source = os.path.join(root_dir, "source-many", "%d.txt" % i)
        dest = os.path.join(root_dir, "dest", "%d.txt" % i)
        hardlink(source, dest)
    end = timer()
    print("1k hardlinks: ")
    print(end - start, " seconds")

# several runs, 1.09, 1.06, 1.07, 1.04, 1.02, 1.11
# pessimistic average would be 1.1 s / 1000 copies, so 1.1 ms / copy
def benchmark_many_empty_copies():
    clear_dest()
    start = timer()
    for i in range(1, 1000):
        source = os.path.join(root_dir, "source-many", "%d.txt" % i)
        dest = os.path.join(root_dir, "dest", "%d.txt" % i)
        copy2(source, dest)
    end = timer()
    print("1k empty copies: ")
    print(end - start, " seconds")

#TODO proceed here: benchmark large file and get duration per megabyte

# several runs: 0.960, 0.960, 0.988, 1.02, 1.00
# average: 1 s / 100 copies, so 10 ms / megabyte
def benchmark_1mb_files():
    clear_dest()
    start = timer()
    for i in range(1, 100):
        source = os.path.join(root_dir, "source-mib", "%d.txt" % i)
        dest = os.path.join(root_dir, "dest", "%d.txt" % i)
        copy2(source, dest)
    end = timer()
    print("100 1 MiB copies: ")
    print(end - start, " seconds")
    
if __name__ == '__main__':
#     setup_1mb_files()
#     setup_many_files()
#     clear_dest()
#     benchmark_hardlink()
#     benchmark_many_empty_copies()
    benchmark_1mb_files()