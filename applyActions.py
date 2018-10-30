import os, sys

import json
import shutil
import logging

from constants import *

# From here: https://github.com/sid0/ntfs/blob/master/ntfsutils/hardlink.py
import ctypes
from ctypes import WinError
from ctypes.wintypes import BOOL
CreateHardLink = ctypes.windll.kernel32.CreateHardLinkW
CreateHardLink.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p]
CreateHardLink.restype = BOOL

def hardlink(source, link_name):
    res = CreateHardLink(link_name, source, None)
    if res == 0:
        raise WinError()

def executeActionList(sourceDirectory, targetDirectory, compareDirectory, actions):
    logging.info("Apply actions.")

    lastProgress = 0
    percentSteps = 5
    for i, action in enumerate(actions):
        progress = int(i/len(actions)*100.0/percentSteps + 0.5) * percentSteps
        if lastProgress != progress:
            print(str(progress) + "%  ", end="", flush = True)
        lastProgress = progress

        actionType = action["type"]
        params = action["params"]
        try:
            if actionType == "copy":
                fromPath = os.path.join(sourceDirectory, params["name"])
                toPath = os.path.join(targetDirectory, params["name"])
                logging.debug('copy from "' + fromPath + '" to "' + toPath + '"')

                if os.path.isfile(fromPath):
                    os.makedirs(os.path.dirname(toPath), exist_ok = True)
                    shutil.copy2(fromPath, toPath)
                elif os.path.isdir(fromPath):
                    os.makedirs(toPath, exist_ok = True)
            elif actionType == "delete":
                path = os.path.join(targetDirectory, params["name"])
                logging.debug('delete file "' + path + '"')

                if os.path.isfile(path):
                    os.remove(path)
                elif os.path.isdir(path):
                    shutil.rmtree(path)
            elif actionType == "hardlink":
                fromPath = os.path.join(compareDirectory, params["name"])
                toPath = os.path.join(targetDirectory, params["name"])
                logging.debug('hardlink from "' + fromPath + '" to "' + toPath + '"')
                toDirectory = os.path.dirname(toPath)
                os.makedirs(toDirectory, exist_ok = True)
                hardlink(fromPath, toPath)
            else:
                logging.error("Unknown action type: " + actionType)
        except OSError as e:
            logging.error(e)
        except IOError as e:
            logging.error(e)


