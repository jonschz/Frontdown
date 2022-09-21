# SPDX-License-Identifier: MIT

# This code is based on https://github.com/KasparNagu/PortableDevices,
# licensed under the MIT license.
# The modifications in this file are also licensed under the MIT license.

import ctypes
# re-export COMError
from _ctypes import COMError as COMError
import datetime
import comtypes
import comtypes.client
from typing import Any, BinaryIO, Final, Iterable, Optional

# In principle, one can auto-generate the headers from .gen using
#
# comtypes.client.GetModule("portabledeviceapi.dll")
# comtypes.client.GetModule("portabledevicetypes.dll")
# import comtypes.gen._1F001332_1A57_4934_BE31_AFFC99F4EE0A_0_1_0 as port
# import comtypes.gen._2B00BA2F_E750_4BEB_9235_97142EDE1D3E_0_1_0 as types
#
# However, in the header for portabledeviceapi.dll several parameters get the wrong in/out type,
# and some variable names (especially for PROPVARIANT) get extremely long. Therefore, the following
# headers are provided, which are fixed versions of the auto-generated ones.
from .gen import _1F001332_1A57_4934_BE31_AFFC99F4EE0A_0_1_0 as port
# this one matches the auto-generated
from .gen import _2B00BA2F_E750_4BEB_9235_97142EDE1D3E_0_1_0 as types

# convert from unsigned to signed integer because getErrorValue() returns a signed integer
ERROR_NOT_SUPPORTED = ctypes.c_int32(0x80070032).value
ERROR_NOT_FOUND = ctypes.c_int32(0x80070490).value

# display as unsigned hex instead of signed int


def errorCodeToHex(errorcode: int) -> str:
    return f"0x{(errorcode & 0xffffffff):X}"


def comErrorToStr(e: COMError) -> str:
    return f"{errorCodeToHex(e.hresult)} ({e.text})"


# Reference: https://www.pinvoke.net/default.aspx/Constants/PROPERTYKEY.html
# for copy-paste compatibility

# old code using strings
# def newGuid(*args: int) -> comtypes.GUID:
#     """
#     Construct a comtypes.GUID from a list of int parameters, compatible to usual C# syntax.

#     `args` must be of length 11. The first parameter must be a 32 bit unsigned integer,
#     the second and third 16 bit integers, the rest 8 bit.
#     """
#     assert len(args) == 11
#     assert all(isinstance(x, int) for x in args)
#     lastpart = ''.join(f"{argi:02X}" for argi in args[5:11])
#     guidstr = f"{{{args[0]:08X}-{args[1]:04X}-{args[2]:04X}-{args[3]:02X}{args[4]:02X}-{lastpart}}}"
#     # print(guidstr)
#     # print(args[11])
#     return comtypes.GUID(guidstr)

def newGuid(*args: int) -> comtypes.GUID:
    """
    Construct a comtypes.GUID from a list of int parameters, compatible to usual C# syntax.

    `args` must be of length 11. The first parameter must be a 32 bit unsigned integer,
    the second and third 16 bit integers, the rest 8 bit.
    """
    assert len(args) == 11
    assert all(isinstance(x, int) for x in args)
    guid = comtypes.GUID()
    guid.Data1 = ctypes.c_uint32(args[0])
    guid.Data2 = ctypes.c_uint16(args[1])
    guid.Data3 = ctypes.c_uint16(args[2])
    for i in range(8):
        guid.Data4[i] = ctypes.c_int8(args[3+i])
    return guid


# Use naive datetime (i.e. without timezone information) because Windows' VT_DATE does not specify timezones.
# Good reference: https://ericlippert.com/2003/09/16/erics-complete-guide-to-vt_date/
# The tested device does not provide sub-second accuracy, all values appear to be rounded to the closest second.
# This might be device-dependent, as double precision floats are definitely capable of providing millisecond accuracy.
VT_DATE_EPOCH: Final[datetime.datetime] = datetime.datetime(1899, 12, 30)


def vtdateToDatetime(vtdate: float) -> datetime.datetime:
    return VT_DATE_EPOCH + datetime.timedelta(days=vtdate)


def PropertyKey(*args: int) -> 'ctypes._Pointer[port._tagpropertykey]':
    propkey = comtypes.pointer(port._tagpropertykey())
    assert len(args) == 12
    assert all(isinstance(x, int) for x in args)
    propkey.contents.fmtid = newGuid(*args[0:11])
    propkey.contents.pid = ctypes.c_ulong(args[11])
    return propkey


# e.g. public static PropertyKey WPD_OBJECT_NAME = PropertyKey(0xEF6B490D, 0x5CD8, 0x437A, 0xAF, 0xFC, 0xDA, 0x8B, 0x60, 0xEE, 0x4A, 0x3C, 4);
WPD_OBJECT_PARENT_ID = PropertyKey(0xEF6B490D, 0x5CD8, 0x437A, 0xAF, 0xFC, 0xDA, 0x8B, 0x60, 0xEE, 0x4A, 0x3C, 3)
WPD_OBJECT_NAME = PropertyKey(0xEF6B490D, 0x5CD8, 0x437A, 0xAF, 0xFC, 0xDA, 0x8B, 0x60, 0xEE, 0x4A, 0x3C, 4)
WPD_OBJECT_CONTENT_TYPE = PropertyKey(0xEF6B490D, 0x5CD8, 0x437A, 0xAF, 0xFC, 0xDA, 0x8B, 0x60, 0xEE, 0x4A, 0x3C, 7)
WPD_OBJECT_SIZE = PropertyKey(0xEF6B490D, 0x5CD8, 0x437A, 0xAF, 0xFC, 0xDA, 0x8B, 0x60, 0xEE, 0x4A, 0x3C, 11)
WPD_OBJECT_ORIGINAL_FILE_NAME = PropertyKey(0xEF6B490D, 0x5CD8, 0x437A, 0xAF, 0xFC, 0xDA, 0x8B, 0x60, 0xEE, 0x4A, 0x3C, 12)
WPD_OBJECT_DATE_MODIFIED = PropertyKey(0xEF6B490D, 0x5CD8, 0x437A, 0xAF, 0xFC, 0xDA, 0x8B, 0x60, 0xEE, 0x4A, 0x3C, 19)

WPD_DEVICE_SERIAL_NUMBER = PropertyKey(0x26D4979A, 0xE643, 0x4626, 0x9E, 0x2B, 0x73, 0x6D, 0xC0, 0xC9, 0x2F, 0xDC, 9)
WPD_DEVICE_DATETIME = PropertyKey(0x26D4979A, 0xE643, 0x4626, 0x9E, 0x2B, 0x73, 0x6D, 0xC0, 0xC9, 0x2F, 0xDC, 11)
WPD_DEVICE_FRIENDLY_NAME = PropertyKey(0x26D4979A, 0xE643, 0x4626, 0x9E, 0x2B, 0x73, 0x6D, 0xC0, 0xC9, 0x2F, 0xDC, 12)

WPD_RESOURCE_DEFAULT = PropertyKey(0xE81E79BE, 0x34F0, 0x41BF, 0xB5, 0x3F, 0xF1, 0xA0, 0x6A, 0xE8, 0x78, 0x42, 0)
WPD_PROPERTY_COMMON_COMMAND_CATEGORY = PropertyKey(0xF0422A9C, 0x5DC8, 0x4440, 0xB5, 0xBD, 0x5D, 0xF2, 0x88, 0x35, 0x65, 0x8A, 1001)
WPD_PROPERTY_COMMON_COMMAND_ID = PropertyKey(0xF0422A9C, 0x5DC8, 0x4440, 0xB5, 0xBD, 0x5D, 0xF2, 0x88, 0x35, 0x65, 0x8A, 1002)
WPD_PROPERTY_COMMON_HRESULT = PropertyKey(0xF0422A9C, 0x5DC8, 0x4440, 0xB5, 0xBD, 0x5D, 0xF2, 0x88, 0x35, 0x65, 0x8A, 1003)
WPD_COMMAND_COMMON_RESET_DEVICE = PropertyKey(0xF0422A9C, 0x5DC8, 0x4440, 0xB5, 0xBD, 0x5D, 0xF2, 0x88, 0x35, 0x65, 0x8A, 2)

# copied from https://github.com/geersch/WPD/tree/master/src/part-2
folderType = newGuid(0x27E2E392, 0xA111, 0x48E0, 0xAB, 0x0C, 0xE1, 0x77, 0x05, 0xA0, 0x5F, 0x85)
functionalType = newGuid(0x99ED0160, 0x17FF, 0x4C44, 0x9D, 0x98, 0x1D, 0x7A, 0x6F, 0x94, 0x19, 0x21)

# This is an educated guess based on the documentation and previous code
WPD_DEVICE_OBJECT_ID = "DEVICE"

# PROPVARIANT data types
# from the documentation (https://docs.microsoft.com/en-us/windows/win32/api/propidlbase/ns-propidlbase-propvariant)
VT_DATE = 7
VT_ERROR = 10
VT_UI8 = 21
VT_LPWSTR = 31


# TODO: contemplate a change to class architecture
# 1) Either subclass IPortableDeviceValues with a second constructor
# 2) Or encapsulate an IPortableDeviceValues in the subclass
def createPortableDeviceValues() -> Any:
    return comtypes.client.CreateObject(
        types.PortableDeviceValues,
        clsctx=comtypes.CLSCTX_INPROC_SERVER,
        interface=port.IPortableDeviceValues)


def createPortableDeviceKeyCollection() -> Any:
    return comtypes.client.CreateObject(
        types.PortableDeviceKeyCollection,
        clsctx=comtypes.CLSCTX_INPROC_SERVER,
        interface=port.IPortableDeviceKeyCollection)


# TODO WIP
class PortableDeviceValues:
    """Encapsulates a POINTER(IPortableDeviceValues)."""

    def __init__(self, values: Any | None) -> None:
        self.portableDeviceValues = values if values is not None else createPortableDeviceValues()


# TODO the structure here is not very well defined - the parameter propertiesToRead is assumed to always have the properties
# that are being read anyway. Think about what a good abstraction could be. Maybe split into two classes? Define desired attributes
# as tuples / dicts which can be added in a natural way? Like PortableDeviceContent([WPD_..., WPD_...]).
class PortableDeviceContent:
    """
    This class is _NOT_ an abstraction of IPortableDeviceContent, but rather of a content object
    (e.g. returned by EnumObjects)

    New behaviour: Tries to read the given properties on initialisation. Init fails (likely with a ComError) if the read fails.
    """

    def __init__(
            self,
            objectID: str,
            content: Any,                  # POINTER(IPortableDeviceContent)
            properties: Any = None,        # POINTER(IPortableDeviceProperties) | None
            propertiesToRead: Any = None,  # POINTER(IPortableDeviceKeyCollection) | None
            *,
            errorIfModdateUnavailable: bool = False
    ):
        self.objectID = objectID
        assert isinstance(objectID, str | ctypes.c_wchar_p), f"objectID must be str or c_wchar_p, got {type(objectID)=} instead"
        self.content: Any = content
        self.properties: Any = properties if properties else content.Properties()
        self.propertiesToRead: Any = propertiesToRead if propertiesToRead else self.defaultPropertiesToRead()
        self.readProperties(errorIfModdateUnavailable=errorIfModdateUnavailable)

    @classmethod
    def defaultPropertiesToRead(cls):
        propertiesToRead = createPortableDeviceKeyCollection()
        # Generate the list of properties we want to read from the device
        propertiesToRead.Add(WPD_OBJECT_NAME)
        propertiesToRead.Add(WPD_OBJECT_ORIGINAL_FILE_NAME)
        propertiesToRead.Add(WPD_OBJECT_CONTENT_TYPE)
        propertiesToRead.Add(WPD_OBJECT_DATE_MODIFIED)
        propertiesToRead.Add(WPD_OBJECT_SIZE)
        # Reading WPD_DEVICE_... works in principle if objectID == WPD_DEVICE_OBJECT_ID;
        # however, my device does not provide DEVICE_DATETIME
        # propertiesToRead.Add(WPD_DEVICE_DATETIME)
        # propertiesToRead.Add(WPD_DEVICE_SERIAL_NUMBER)
        return propertiesToRead

    def readProperties(self, errorIfModdateUnavailable: bool = False) -> None:
        """
        Sets self.name, self.contentType, self.isFolder,
        self.moddate (time.Datetime or None)
        """
        values = self.properties.GetValues(self.objectID, self.propertiesToRead)    # POINTER(IPortableDeviceValues)
        objectName = values.GetStringValue(WPD_OBJECT_NAME)
        self.contentType = values.GetGuidValue(WPD_OBJECT_CONTENT_TYPE)
        self.isFolder = self.contentType in [folderType, functionalType]
        assert isinstance(objectName, str)
        self.name = objectName
        # If WPD_OBJECT_ORIGINAL_FILE_NAME is defined, read it and replace the name.
        # Earlier code used self.isFolder here, but many folders have an ORIGINAL_FILE_NAME set as well.
        # Read using GetValue so we don't get an exception if the value is unavailable, but still get
        # a COMError if something else goes wrong.
        originalFilenamePROPVAR = values.GetValue(WPD_OBJECT_ORIGINAL_FILE_NAME)
        if originalFilenamePROPVAR.vt != VT_ERROR:
            assert originalFilenamePROPVAR.vt == VT_LPWSTR
            originalFilename = originalFilenamePROPVAR.DUMMYUNIONNAME.pwszVal
            assert isinstance(originalFilename, str)
            self.name = originalFilename
        filesizePROPVAR = values.GetValue(WPD_OBJECT_SIZE)
        if filesizePROPVAR.vt != VT_ERROR:
            assert filesizePROPVAR.vt == VT_UI8
            filesize = filesizePROPVAR.DUMMYUNIONNAME.uhVal
            assert isinstance(filesize, int)
            self.filesize = filesize
        else:
            self.filesize = 0   # set filesize to zero if unavailable
        # WPD_OBJECT_DATE_MODIFIED can only be read using a PROPVARIANT
        moddatePROPVAR = values.GetValue(WPD_OBJECT_DATE_MODIFIED)
        if moddatePROPVAR.vt == VT_ERROR:
            if errorIfModdateUnavailable:
                errcode = values.GetErrorValue(WPD_OBJECT_DATE_MODIFIED)
                if errcode == ERROR_NOT_SUPPORTED or errcode == ERROR_NOT_FOUND:
                    errmsg = f"Entry '{self.name}' does not have a modification timestamp"
                else:
                    errmsg = f"Unexpected error while accessing moddate: {errorCodeToHex(errcode)}"
                raise ValueError(errmsg)
            else:
                self.moddate = None
        else:
            assert moddatePROPVAR.vt == VT_DATE
            # Experiment results on WPD_OBJECT_DATE_MODIFIED:
            # - It DOES depend on the timezone setting of the portable device.
            # - It DOES NOT depend on the local time or timezone of the computer.
            # - It DOES NOT depend on the local time of the device (only on the timezone).
            #
            # Unfortunately, WPD does not have an interface to query the device's timezone.
            # If the device supports it, one could query WPD_DEVICE_DATETIME and guess the timezone
            # based on the difference between the device's and the computer's time (though this might
            # still be wrong if the DST rules differ between the device's and the computer's timezone).
            # For now, we model the time as a naive datetime object.
            self.moddate = vtdateToDatetime(moddatePROPVAR.DUMMYUNIONNAME.dblVal)

    def getChildIDs(self) -> Iterable[str]:
        """
        Yields the IDs returned by IPortableDeviceContent.EnumObjects()
        """
        # IPortableDeviceContent documentation: first parameter zero DWORD, last parameter NULL pointer
        # ctypes documentation: specify None for NULL pointers
        enumObjectIDs = self.content.EnumObjects(ctypes.c_ulong(0), self.objectID, None)
        while True:
            # Changing this number does not appear to affect anything
            numObject = ctypes.c_ulong(16)  # block size, so to speak
            objectIDArray = (ctypes.c_wchar_p * numObject.value)()
            numFetched = ctypes.pointer(ctypes.c_ulong(0))
            # be sure to change the IEnumPortableDeviceObjectIDs 'Next'
            # function in the generated code to have objectids as inout
            enumObjectIDs.Next(
                numObject,
                ctypes.cast(objectIDArray, ctypes.POINTER(ctypes.c_wchar_p)),
                numFetched)
            if numFetched.contents.value == 0:
                break
            for i in range(0, numFetched.contents.value):
                curObjectID = objectIDArray[i]
                assert isinstance(curObjectID, str), f"Unexpected type of object ID: {type(curObjectID)=}"
                yield curObjectID

    def getChildren(self) -> 'Iterable[PortableDeviceContent]':
        """
        Yields the results of IPortableDeviceContent.EnumObjects() as PortableDeviceContent classes.
        The latter have their properties scanned on initialisation. If an error happens while scanning the properties
        of the children, this iterator will raise an exception and terminate.
        """
        for childID in self.getChildIDs():
            yield PortableDeviceContent(childID, self.content, self.properties, self.propertiesToRead)

    def getChild(self, name: str) -> 'PortableDeviceContent | None':
        # using a filter and next lazily evaluates getChildren() and terminates early if a match is found
        matches = filter(lambda c: c.name == name, self.getChildren())
        return next(matches, None)

    def getPath(self, path: str) -> 'PortableDeviceContent | None':
        cur: PortableDeviceContent | None = self
        for p in path.split("/"):
            if cur is None:
                return None
            cur = cur.getChild(p)
        return cur

    def __repr__(self):
        return "<PortableDeviceContent %s: %s>" % (
            self.objectID, self.name)

    def uploadStream(self, fileName, inputStream, streamLen):
        objectProperties = createPortableDeviceValues()

        objectProperties.SetStringValue(WPD_OBJECT_PARENT_ID, self.objectID)
        objectProperties.SetUnsignedLargeIntegerValue(
            WPD_OBJECT_SIZE, streamLen)
        objectProperties.SetStringValue(
            WPD_OBJECT_ORIGINAL_FILE_NAME, fileName)
        objectProperties.SetStringValue(WPD_OBJECT_NAME, fileName)
        optimalTransferSizeBytes = ctypes.pointer(ctypes.c_ulong(0))
        # ctypes.POINTER expects a subclass of _CData which IStream is not
        pFileStream: Any = ctypes.POINTER(port.IStream)()   # type:ignore
        # be sure to change the IPortableDeviceContent
        # 'CreateObjectWithPropertiesAndData' function in the generated code to
        # have IStream ppData as 'in','out'
        fileStream = self.content.CreateObjectWithPropertiesAndData(
            objectProperties,
            pFileStream,
            optimalTransferSizeBytes,
            ctypes.POINTER(
                ctypes.c_wchar_p)())
        fileStream = pFileStream.value
        blockSize = optimalTransferSizeBytes.contents.value
        curWritten = 0
        while True:
            toRead = streamLen - curWritten
            block = inputStream.read(
                toRead if toRead < blockSize else blockSize)
            if len(block) <= 0:
                break
            stringBuf = ctypes.create_string_buffer(block)
            written = fileStream.RemoteWrite(
                ctypes.cast(
                    stringBuf,
                    ctypes.POINTER(
                        ctypes.c_ubyte)),
                len(block))
            curWritten += written
            if(curWritten >= streamLen):
                break
        STGC_DEFAULT = 0
        fileStream.Commit(STGC_DEFAULT)

    def downloadStream(self, outputStream: BinaryIO) -> None:
        resources = self.content.Transfer()
        STGM_READ = ctypes.c_uint(0)
        optimalTransferSizeBytes = ctypes.pointer(ctypes.c_ulong(0))
        # ctypes.POINTER expects a subclass of _CData which IStream is not
        pFileStream: Any = ctypes.POINTER(port.IStream)()    # type:ignore
        optimalTransferSizeBytes, pFileStream = resources.GetStream(
            self.objectID, WPD_RESOURCE_DEFAULT, STGM_READ, optimalTransferSizeBytes, pFileStream)
        blockSize = optimalTransferSizeBytes.contents.value
        fileStream = pFileStream.value
        buf = (ctypes.c_ubyte * blockSize)()
        # make sure all RemoteRead parameters are in
        while True:
            buf, len = fileStream.RemoteRead(buf, ctypes.c_ulong(blockSize))
            if len == 0:
                break
            # bug fixed: this used to read the buffer past EOF if the file size was not a multiple of blockSize
            outputStream.write(bytearray(buf)[0:len])


class PortableDevice:
    def __init__(self, manager: 'PortableDeviceManager', id):
        self.id = id
        self._description: str | None = None
        self._friendlyname: str | None = None
        self.device = None
        self.manager = manager

    @property
    def deviceManager(self) -> Any:
        """
        Returns a POINTER(IPortableDeviceManager).
        """
        return self.manager.deviceManager

    @property
    def description(self) -> str:
        if self._description:
            return self._description

        nameLen = ctypes.pointer(ctypes.c_ulong(0))
        self.deviceManager.GetDeviceDescription(
            self.id,
            ctypes.POINTER(ctypes.c_ushort)(),
            nameLen)
        name = ctypes.create_unicode_buffer(nameLen.contents.value)
        self.deviceManager.GetDeviceDescription(
            self.id,
            ctypes.cast(name, ctypes.POINTER(ctypes.c_ushort)),
            nameLen)
        desc = name.value
        assert isinstance(desc, str)
        self._description = desc
        return desc

    def getDevice(self) -> Any:
        """
        Returns a POINTER(IPortableDevice).
        """
        if self.device:
            return self.device
        clientInformation = comtypes.client.CreateObject(
            types.PortableDeviceValues,
            clsctx=comtypes.CLSCTX_INPROC_SERVER,
            interface=port.IPortableDeviceValues)
        self.device: Any = comtypes.client.CreateObject(
            port.PortableDevice,
            clsctx=comtypes.CLSCTX_INPROC_SERVER,
            interface=port.IPortableDevice)
        self.device.Open(self.id, clientInformation)
        return self.device

    def releaseDevice(self):
        if self.device:
            self.device.Release()
            self.device = None

    def resetDevice(self) -> None:
        values = createPortableDeviceValues()
        # pid is a DWORD: https://docs.microsoft.com/en-us/windows/win32/wpd_sdk/propertykeys-and-guids-in-windows-portable-devices
        values.SetGuidValue(WPD_PROPERTY_COMMON_COMMAND_CATEGORY, WPD_COMMAND_COMMON_RESET_DEVICE.contents.fmtid)
        values.SetUnsignedIntegerValue(WPD_PROPERTY_COMMON_COMMAND_ID, WPD_COMMAND_COMMON_RESET_DEVICE.contents.pid)
        result = self.getDevice().SendCommand(0, values)
        errorcode = result.GetErrorValue(WPD_PROPERTY_COMMON_HRESULT)
        if errorcode != 0:
            raise ValueError(f"Reset failed with error code 0x{errorCodeToHex(errorcode)}")

    def getContent(self) -> PortableDeviceContent:
        return PortableDeviceContent(WPD_DEVICE_OBJECT_ID, self.getDevice().Content())

    def getName(self) -> str:
        """Returns the friendly name if available, otherwise returns the device description."""
        content = self.getContent()
        propertiesToRead = createPortableDeviceKeyCollection()
        propertiesToRead.Add(WPD_DEVICE_FRIENDLY_NAME)
        values = content.properties.GetValues(content.objectID, propertiesToRead)    # POINTER(IPortableDeviceValues)
        friendlynamePROPVAR = values.GetValue(WPD_DEVICE_FRIENDLY_NAME)
        if friendlynamePROPVAR.vt != VT_ERROR:
            assert friendlynamePROPVAR.vt == VT_LPWSTR
            self._friendlyname = friendlynamePROPVAR.DUMMYUNIONNAME.pwszVal
        else:
            self._friendlyname = self.description
        return self._friendlyname

    def __repr__(self) -> str:
        return "<PortableDevice: %s>" % self.description


class PortableDeviceManager:
    def __init__(self) -> None:
        self.deviceManager: Any = comtypes.client.CreateObject(
            port.PortableDeviceManager,
            clsctx=comtypes.CLSCTX_INPROC_SERVER,
            interface=port.IPortableDeviceManager)

    def getPortableDevices(self) -> list[PortableDevice]:
        pnpDeviceIDCount = ctypes.pointer(ctypes.c_ulong(0))
        self.deviceManager.GetDevices(
            ctypes.POINTER(ctypes.c_wchar_p)(),
            pnpDeviceIDCount)
        if(pnpDeviceIDCount.contents.value == 0):
            return []
        pnpDeviceIDs = (ctypes.c_wchar_p * pnpDeviceIDCount.contents.value)()
        self.deviceManager.GetDevices(
            ctypes.cast(
                pnpDeviceIDs,
                ctypes.POINTER(ctypes.c_wchar_p)),
            pnpDeviceIDCount)
        return [PortableDevice(manager=self, id=curId) for curId in pnpDeviceIDs]

    def getDeviceByName(self, name: str) -> Optional[PortableDevice]:
        """Searches for a device given a description or a friendly name."""
        results = [dev for dev in self.getPortableDevices() if name == dev.description or name == dev.getName()]
        if len(results) == 0:
            return None
        elif len(results) == 1:
            return results[0]
        else:
            raise ValueError(f"Multiple devices match '{name}'.")

    def getContentFromDevicePath(self, path: str) -> PortableDeviceContent | None:
        """
        The format for `path` is `DeviceDescription/path/on/device`, e.g. `SM-G920F/Phone/Android`.
        """
        parts = path.split("/")
        dev = self.getDeviceByName(parts[0])
        if not dev:
            return None
        if len(parts) > 1:
            cont = dev.getContent().getPath("/".join(parts[1:]))
        else:
            cont = dev.getContent()
        return cont


# for legacy code
_SingletonDeviceManager: Optional[PortableDeviceManager] = None


# to access PortableDevices.DeviceManager
def __getattr__(name: str) -> Any:
    global _SingletonDeviceManager
    if name == 'deviceManager':
        return None if _SingletonDeviceManager is None else _SingletonDeviceManager.deviceManager
    raise AttributeError(f"module 'PortableDevices' has no attribute '{name}'")


def getPortableDevices():
    global _SingletonDeviceManager
    if _SingletonDeviceManager is None:
        _SingletonDeviceManager = PortableDeviceManager()
    return _SingletonDeviceManager.getPortableDevices()


def getContentFromDevicePath(path):
    global _SingletonDeviceManager
    if _SingletonDeviceManager is None:
        _SingletonDeviceManager = PortableDeviceManager()
    return _SingletonDeviceManager.getContentFromDevicePath(path)
