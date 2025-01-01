# import ctypes
from io import TextIOWrapper
import io
import os
from pathlib import Path
from typing import Optional

from . import PortableDevices as PD

from .PortableDevices import comErrorToStr

import logging


def recursePDContent(pdc: PD.BasePortableDeviceContent, parentPath: str, logfile: TextIOWrapper | None, *, verbose: bool = False) -> None:
    try:
        for c in pdc.getChildren():
            thisPath = f"{parentPath}/{c.name}"
            if logfile:
                logfile.write(thisPath+'\n')
            if verbose:
                print(thisPath)
                print(c.name)
                print(c.filesize)
            recursePDContent(c, parentPath=thisPath, logfile=logfile, verbose=verbose)
    except PD.COMError as e:
        error(f"COMError in getChildren() of {parentPath}: {comErrorToStr(e)}", logfile)
        return


def log(msg: str, logfile: Optional[TextIOWrapper]) -> None:
    if logfile:
        logfile.write(msg+'\n')


numErrors = 0


def error(msg: str, logfile: Optional[TextIOWrapper]) -> None:
    global numErrors
    numErrors += 1
    print(f"Error: {msg}")
    log(f"Error: {msg}\n", logfile)


def copyPDContent(pdc: PD.PortableDeviceContent, parentPath: str, targetPath: Path, logfile: TextIOWrapper | None, *, verbose: bool = False) -> None:

    name = pdc.name
    assert isinstance(name, str)
    thisSourcePath = f"{parentPath}/{name}"
    thisTargetPath = targetPath.joinpath(name)
    log(thisSourcePath+'\n', logfile)
    # if verbose:
    #     print(thisSourcePath)
    #     print(pdc.moddate)
    if pdc.isFolder:
        if verbose:
            print(f"Creating {thisTargetPath}")
        # make folder and recurse into it
        thisTargetPath.mkdir(exist_ok=True)
        try:
            for c in pdc.getChildren():
                copyPDContent(c, parentPath=thisSourcePath, targetPath=thisTargetPath, logfile=logfile, verbose=verbose)
        except PD.COMError as e:
            error(f"COMError in getChildren() of {thisSourcePath}: {comErrorToStr(e)}", logfile)
    else:
        if verbose:
            print(f"Copying {thisSourcePath} to {thisTargetPath}")
        with thisTargetPath.open('wb') as outfile:
            pdc.downloadStream(outfile)
    # modification timestamp
    # TODO do we have the modtime down to the millisecond?
    if pdc.moddate:
        print(pdc.moddate.strftime('%Y%m%d%H%M%S.%f'))
        winTimestamp = pdc.moddate.timestamp()
        os.utime(thisTargetPath, (winTimestamp, winTimestamp))


def listDevices() -> None:
    manager = PD.PortableDeviceManager()
    for device in manager.getPortableDevices():
        print(device.getDescription())


def scanAllDevices() -> None:
    manager = PD.PortableDeviceManager()
    devs = list(manager.getPortableDevices())
    with open('log.txt', 'w', encoding='utf-8') as logfile:
        for device in devs:
            recursePDContent(device.getContent(), '', logfile)

        scanningMsg = f"Total scanning errors: {numErrors}"
        print(scanningMsg)
        logfile.write(f"\n{scanningMsg}\n")


def main() -> None:
    loglevel = logging.INFO
    # loglevel = logging.DEBUG
    logging.basicConfig(level=loglevel)
    dev = None
    manager = None
    try:
        # import sys
        # import example
        # example.main([sys.argv[0], 'ls'])
        # example.main([sys.argv[0], 'ls', 'SM-G920F/Phone/WhatsApp/Media/WhatsApp Images'])
        deviceName = "FP4"
        dir = "Interner gemeinsamer Speicher/Documents"
        path = f"{dir}/testfile.txt"
        # path = "Interner gemeinsamer Speicher/Signal/signal-2022-09-16-14-48-47.backup"

        # deviceName = "Maxtor"
        # path = "E:/Program Files"

        manager = PD.PortableDeviceManager()

        # temp
        devs = list(manager.getPortableDevices())
        for d in devs:
            print(f"device description: {d.getDescription()}")
            print(f"device friendly name: {d.getName()}")

        dev = manager.getDeviceByName(deviceName)
        assert dev is not None, "Device not found"

        print(dev.getDescription())
        dev_dir = dev.getContent().getPath(path)
        print(dev_dir)

        # recursePDContent(pdc=dev.getContent(), parentPath=dev.getDescription(), logfile=None, verbose=True)

        # copy whole device content
        # copyTarget = Path('.\\copytest')
        # copyTarget.mkdir(exist_ok=True)
        # copyPDContent(pdc=dev.getContent(), parentPath='', targetPath=copyTarget, logfile=logfile, verbose=True)

        # display one file
        # devpath = dev.getContent().getPath(path)
        # assert devpath is not None
        # print(f"{devpath.moddate}: {devpath.name}")

        # # download a file
        # with open('testfile', 'wb') as outfile:
        #     devpath = dev.getContent().getPath(path)
        #     assert devpath is not None
        #     t1 = time.perf_counter()
        #     devpath.downloadStream(outfile)
        #     t2 = time.perf_counter()
        #     print(f"Time: {t2-t1}")

        # Upload a file
        dev_dir = dev.getContent().getPath(dir)
        assert dev_dir is not None
        content = b"This is some test content"
        dev_dir.uploadStream("testfile2.txt", io.BytesIO(content), len(content))

    except PD.COMError as e:
        print(f"COMError: {comErrorToStr(e)}")
        # if dev is not None:
        #     try:
        #         dev.resetDevice()
        #     except ValueError as e:
        #         print(e)

        # this is called automatically when the deviceManager goes out of scope. Calling twice leads to access violations
        # manager.deviceManager.Release()


if __name__ == "__main__":
    main()
