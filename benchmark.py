'''
Created on 01.09.2019

@author: Jonathan
'''

import os
import glob
from applyActions import hardlink
from timeit import default_timer as timer
from shutil import copy2

root_dir = "C:\\Users\\Jonathan\\Documents\\Backup-Lösung\\Test Setup\\benchmark"


def setup_benchmark():
    # create 1000 empty files
    for i in range(1, 1000):
        path = os.path.join(root_dir, "source-many", "%d.txt" % i)
        file = open(path, 'w+')
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

if __name__ == '__main__':
#     setup_benchmark()
#     clear_dest()
#     benchmark_hardlink()
    benchmark_many_empty_copies()