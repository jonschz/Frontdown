'''
Created on 01.09.2019

@author: Jonathan
'''

import os
from backup_procedures import relativeWalk

root_dir = "C:\\Users\\Jonathan\\Documents\\Backup-Lösung\\Test Setup\\long_paths"

name25 = "abcdefghijklmnopqrstuvwxy" 
name50 = "abcdefghijklmnopqrstuvwxyABCDEFGHIJKLMNOPQRSTUVWXY"
path242 = "C:\\Users\\Jonathan\\Documents\\Backup-Lösung\\Test Setup\\long_paths\\abcdefghijklmnopqrstuvwxyABCDEFGHIJKLMNOPQRSTUVWXY\\abcdefghijklmnopqrstuvwxyABCDEFGHIJKLMNOPQRSTUVWXY\\abcdefghijklmnopqrstuvwxyABCDEFGHIJKLMNOPQRSTUVWXY\\abcdefghijklmnopqrstuvwxy"
path217 = "C:\\Users\\Jonathan\\Documents\\Backup-Lösung\\Test Setup\\long_paths\\abcdefghijklmnopqrstuvwxyABCDEFGHIJKLMNOPQRSTUVWXY\\abcdefghijklmnopqrstuvwxyABCDEFGHIJKLMNOPQRSTUVWXY\\abcdefghijklmnopqrstuvwxyABCDEFGHIJKLMNOPQRSTUVWXY\\"
path246 = "C:\\Users\\Jonathan\\Documents\\Backup-Lösung\\Test Setup\\long_paths\\abcdefghijklmnopqrstuvwxyABCDEFGHIJKLMNOPQRSTUVWXY\\abcdefghijklmnopqrstuvwxyABCDEFGHIJKLMNOPQRSTUVWXY\\abcdefghijklmnopqrstuvwxyABCDEFGHIJKLMNOPQRSTUVWXY\\abcdefghijklmnopqrstuvwxy\\abcd"
path294 = "C:\\Users\\Jonathan\\Documents\\Backup-Lösung\\Test Setup\\long_paths\\abcdefghijklmnopqrstuvwxyABCDEFGHIJKLMNOPQRSTUVWXY\\abcdefghijklmnopqrstuvwxyABCDEFGHIJKLMNOPQRSTUVWXY\\abcdefghijklmnopqrstuvwxyABCDEFGHIJKLMNOPQRSTUVWXY\\abcdefghijklmnopqrstuvwxy\\abcdefghijklmnopqrstuvwxyABCDEFGHIJKLMNOPQRSTUVWXY"
## Test results -- folder:
# os.path.makedirs() creates folders until the path length is
# according to Windows document: the maximum length for a directory created by the API is 260 - 12 = 246,
# verified by experiment; creating a longer folder results in either WinError 206 "filename too long"
#  if the total length is below 260, or WinError 3 "Cannot find path" if the total length is equal or above 260

## Test results -- file:
# creating a file at the maximum depth is no problem if the total length is 259 or below,
# if the total length is equal or above 260, we get Errno 2 "no such file or directory"

## Test result extended API -- folders
# Using \\?\ works fine and can create folders deeper than the limit

## Test results -- file
# Without \\?\, we cannot access files on the lowest level
# With \\?\, creating files works just fine

## Test results -- scanning
# in the current implementation of relativeWalk, too long files and folder within a folder of the correct size
# are being scanned, and an error is produced in filesize_and_permission_check.
# os.scandir(path) displays folders and files that are too long just fine, as long as path is short enough
# if path is too long, we get WinError 3 Cannot find path
# With the prefix "\\?\", scanning works fine -- luckily, both if path ends on '\' or not!

if __name__ == '__main__':
# Create starting point deep folder
#     current_path = root_dir
#     for i in range(1,10):
#         current_path = os.path.join(current_path, name50)
#         os.makedirs(current_path, exist_ok=True)

# Work at the lowest level and test the limits of folders
#     os.makedirs(os.path.join(path242, name50[:16]))

# Work at the lowest level and test the limits of files
#     filepath = os.path.join(path246, "longtest.txt")
#     print("length: %i" % len(filepath))
#     file = open(filepath, 'w+')
#     file.close()

# Work at the lowest level and test the extended API, folders:
#     folderpath = os.path.join(path242, name50)
#     os.makedirs("\\\\?\\" + folderpath, exist_ok=True)

# Work below the 260 limit and test both the normal and the extended API, files:
# #    filepath = os.path.join(path294, "l")
    filepath = "\\\\?\\" +  os.path.join(path246, "toolongfilename.txt")
    print("length: %i" % len(filepath))
    file = open(filepath, 'w+')
    file.close()
    
# Try directory scanning
#     paths = relativeWalk(path217, [])
#     paths = os.scandir(path294)
    paths = os.scandir("\\\\?\\" + path294)
    for path in paths:
        print(path)