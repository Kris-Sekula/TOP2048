"""
#    TOP2049 Open Source programming suite
#
#    Direct WinUSB access for Windows (no libusb).
#
#    Why: the TOP programmer's device descriptor claims 25 configurations
#    (bNumConfigurations = 25) but only has one. libusb on Windows tries to
#    read all 25 configuration descriptors, fails, and drops the device
#    ("failed to initialize device"), so PyUSB never sees it.
#    WinUSB itself only uses configuration 0 and works fine.
#
#    Requires the WinUSB driver bound to the device (e.g. with Zadig).
#
#    Self-test:  python -m libtoprammer.winusb_direct
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
"""

import ctypes
import ctypes.wintypes as wt
import re
import winreg

__all__ = [ "WinUsbError", "find_devices" ]


class WinUsbError(Exception):
	pass


# ---------------------------------------------------------------- Win32 API

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_sapi = ctypes.WinDLL("setupapi", use_last_error=True)
_wusb = ctypes.WinDLL("winusb", use_last_error=True)
_ole = ctypes.WinDLL("ole32")

class GUID(ctypes.Structure):
	_fields_ = [ ("Data1", wt.DWORD), ("Data2", wt.WORD),
		     ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8) ]

class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
	_fields_ = [ ("cbSize", wt.DWORD), ("InterfaceClassGuid", GUID),
		     ("Flags", wt.DWORD), ("Reserved", ctypes.c_size_t) ]

class USB_INTERFACE_DESCRIPTOR(ctypes.Structure):
	_pack_ = 1
	_fields_ = [ ("bLength", ctypes.c_ubyte), ("bDescriptorType", ctypes.c_ubyte),
		     ("bInterfaceNumber", ctypes.c_ubyte), ("bAlternateSetting", ctypes.c_ubyte),
		     ("bNumEndpoints", ctypes.c_ubyte), ("bInterfaceClass", ctypes.c_ubyte),
		     ("bInterfaceSubClass", ctypes.c_ubyte), ("bInterfaceProtocol", ctypes.c_ubyte),
		     ("iInterface", ctypes.c_ubyte) ]

class WINUSB_PIPE_INFORMATION(ctypes.Structure):
	_fields_ = [ ("PipeType", ctypes.c_int), ("PipeId", ctypes.c_ubyte),
		     ("MaximumPacketSize", ctypes.c_ushort), ("Interval", ctypes.c_ubyte) ]

HANDLE = ctypes.c_void_p
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 1
FILE_SHARE_WRITE = 2
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
FILE_FLAG_OVERLAPPED = 0x40000000
PIPE_TRANSFER_TIMEOUT = 0x03
USB_PIPE_TYPE_BULK = 2

_sapi.SetupDiGetClassDevsW.restype = HANDLE
_sapi.SetupDiGetClassDevsW.argtypes = [ ctypes.POINTER(GUID), wt.LPCWSTR, wt.HWND, wt.DWORD ]
_sapi.SetupDiEnumDeviceInterfaces.restype = wt.BOOL
_sapi.SetupDiEnumDeviceInterfaces.argtypes = [ HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID),
					       wt.DWORD, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA) ]
_sapi.SetupDiGetDeviceInterfaceDetailW.restype = wt.BOOL
_sapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [ HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
						    ctypes.c_void_p, wt.DWORD,
						    ctypes.POINTER(wt.DWORD), ctypes.c_void_p ]
_sapi.SetupDiDestroyDeviceInfoList.restype = wt.BOOL
_sapi.SetupDiDestroyDeviceInfoList.argtypes = [ HANDLE ]

_k32.CreateFileW.restype = HANDLE
_k32.CreateFileW.argtypes = [ wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p,
			      wt.DWORD, wt.DWORD, HANDLE ]
_k32.CloseHandle.restype = wt.BOOL
_k32.CloseHandle.argtypes = [ HANDLE ]

_ole.CLSIDFromString.argtypes = [ wt.LPCWSTR, ctypes.POINTER(GUID) ]

_wusb.WinUsb_Initialize.restype = wt.BOOL
_wusb.WinUsb_Initialize.argtypes = [ HANDLE, ctypes.POINTER(HANDLE) ]
_wusb.WinUsb_Free.restype = wt.BOOL
_wusb.WinUsb_Free.argtypes = [ HANDLE ]
_wusb.WinUsb_QueryInterfaceSettings.restype = wt.BOOL
_wusb.WinUsb_QueryInterfaceSettings.argtypes = [ HANDLE, ctypes.c_ubyte,
						 ctypes.POINTER(USB_INTERFACE_DESCRIPTOR) ]
_wusb.WinUsb_QueryPipe.restype = wt.BOOL
_wusb.WinUsb_QueryPipe.argtypes = [ HANDLE, ctypes.c_ubyte, ctypes.c_ubyte,
				    ctypes.POINTER(WINUSB_PIPE_INFORMATION) ]
_wusb.WinUsb_SetPipePolicy.restype = wt.BOOL
_wusb.WinUsb_SetPipePolicy.argtypes = [ HANDLE, ctypes.c_ubyte, wt.ULONG, wt.ULONG, ctypes.c_void_p ]
_wusb.WinUsb_ReadPipe.restype = wt.BOOL
_wusb.WinUsb_ReadPipe.argtypes = [ HANDLE, ctypes.c_ubyte, ctypes.c_void_p, wt.ULONG,
				   ctypes.POINTER(wt.ULONG), ctypes.c_void_p ]
_wusb.WinUsb_WritePipe.restype = wt.BOOL
_wusb.WinUsb_WritePipe.argtypes = [ HANDLE, ctypes.c_ubyte, ctypes.c_void_p, wt.ULONG,
				    ctypes.POINTER(wt.ULONG), ctypes.c_void_p ]
_wusb.WinUsb_ResetPipe.restype = wt.BOOL
_wusb.WinUsb_ResetPipe.argtypes = [ HANDLE, ctypes.c_ubyte ]


def _err(what):
	e = ctypes.get_last_error()
	return WinUsbError("%s failed: [WinError %d] %s" % (what, e, ctypes.FormatError(e).strip()))

def _guid(s):
	g = GUID()
	if _ole.CLSIDFromString(s, ctypes.byref(g)) != 0:
		raise WinUsbError("bad GUID %r" % s)
	return g

def _interface_paths(guid):
	"Device paths of all present devices exposing interface 'guid'."
	paths = []
	hdi = _sapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None,
					 DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
	if hdi is None or hdi == INVALID_HANDLE_VALUE:
		return paths
	try:
		idx = 0
		while True:
			ifd = SP_DEVICE_INTERFACE_DATA()
			ifd.cbSize = ctypes.sizeof(ifd)
			if not _sapi.SetupDiEnumDeviceInterfaces(hdi, None, ctypes.byref(guid),
								 idx, ctypes.byref(ifd)):
				break
			idx += 1
			need = wt.DWORD(0)
			_sapi.SetupDiGetDeviceInterfaceDetailW(hdi, ctypes.byref(ifd), None, 0,
							      ctypes.byref(need), None)
			if not need.value:
				continue
			buf = ctypes.create_string_buffer(need.value)
			# SP_DEVICE_INTERFACE_DETAIL_DATA_W.cbSize: 8 on 64-bit, 6 on 32-bit
			ctypes.cast(buf, ctypes.POINTER(wt.DWORD))[0] = \
				8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
			if _sapi.SetupDiGetDeviceInterfaceDetailW(hdi, ctypes.byref(ifd), buf,
								 need, None, None):
				paths.append(ctypes.wstring_at(ctypes.addressof(buf) + 4))
	finally:
		_sapi.SetupDiDestroyDeviceInfoList(hdi)
	return paths

GUID_DEVINTERFACE_USB_DEVICE = "{A5DCBF10-6530-11D2-901F-00C04FB951ED}"

def _registry_interface_guids(vid, pid):
	"""DeviceInterfaceGUIDs written by Zadig/libwdi for this VID/PID,
	for every instance Windows has seen."""
	guids = set()
	base = r"SYSTEM\CurrentControlSet\Enum\USB\VID_%04X&PID_%04X" % (vid, pid)
	try:
		k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
	except OSError:
		return guids
	with k:
		i = 0
		while True:
			try:
				inst = winreg.EnumKey(k, i)
			except OSError:
				break
			i += 1
			try:
				with winreg.OpenKey(k, inst + r"\Device Parameters") as dp:
					for name in ("DeviceInterfaceGUIDs", "DeviceInterfaceGUID"):
						try:
							val, _t = winreg.QueryValueEx(dp, name)
						except OSError:
							continue
						if isinstance(val, str):
							val = [ val ]
						guids.update(g for g in val if g)
			except OSError:
				pass
	return guids

def _present_vidpids():
	"(vid, pid, path) of present USB devices (from the generic USB interface)."
	result = []
	for p in _interface_paths(_guid(GUID_DEVINTERFACE_USB_DEVICE)):
		m = re.search(r"vid_([0-9a-f]{4})&pid_([0-9a-f]{4})", p, re.I)
		if m:
			result.append((int(m.group(1), 16), int(m.group(2), 16), p))
	return result

def _instance_key(path):
	"'\\\\?\\usb#vid_2471&pid_0853#a&2293570a&0&10#{guid}' -> 'vid_2471&pid_0853#a&2293570a&0&10'"
	parts = path.lower().split("#")
	return "#".join(parts[1:3]) if len(parts) >= 3 else path.lower()


# ------------------------------------------------------------- device class

class Endpoint(object):
	def __init__(self, info):
		self.bEndpointAddress = info.PipeId
		self.wMaxPacketSize = info.MaximumPacketSize
		self.type = info.PipeType
		self.bInterval = info.Interval

class WinUsbDevice(object):
	"Minimal PyUSB-like device object backed by WinUSB."

	def __init__(self, vid, pid, usbDevPath):
		self.idVendor = vid
		self.idProduct = pid
		self.usbDevPath = usbDevPath
		self.openPaths = []
		self.hFile = None
		self.hUsb = None
		self.interface = None
		self.endpoints = []
		self.__timeouts = {}

	def __repr__(self):
		return "WinUsbDevice(%04x:%04x %s)" % (self.idVendor, self.idProduct, self.usbDevPath)

	def open(self):
		if self.hUsb:
			return
		errors = []
		for path in self.openPaths + [ self.usbDevPath ]:
			h = _k32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE,
					     FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING,
					     FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OVERLAPPED, None)
			if h is None or h == INVALID_HANDLE_VALUE:
				errors.append(str(_err("CreateFile(%s)" % path)))
				continue
			hu = HANDLE()
			if not _wusb.WinUsb_Initialize(h, ctypes.byref(hu)):
				errors.append(str(_err("WinUsb_Initialize(%s)" % path)))
				_k32.CloseHandle(h)
				continue
			self.hFile, self.hUsb = h, hu
			break
		if not self.hUsb:
			raise WinUsbError("Cannot open %04x:%04x with WinUSB "
					  "(is the WinUSB driver installed with Zadig, "
					  "and is TopWin closed?)\n  " %
					  (self.idVendor, self.idProduct) + "\n  ".join(errors))
		desc = USB_INTERFACE_DESCRIPTOR()
		if not _wusb.WinUsb_QueryInterfaceSettings(self.hUsb, 0, ctypes.byref(desc)):
			raise _err("WinUsb_QueryInterfaceSettings")
		self.interface = desc
		self.endpoints = []
		for i in range(desc.bNumEndpoints):
			pi = WINUSB_PIPE_INFORMATION()
			if _wusb.WinUsb_QueryPipe(self.hUsb, 0, i, ctypes.byref(pi)):
				self.endpoints.append(Endpoint(pi))

	def close(self):
		if self.hUsb:
			_wusb.WinUsb_Free(self.hUsb)
			self.hUsb = None
		if self.hFile:
			_k32.CloseHandle(self.hFile)
			self.hFile = None
		self.__timeouts = {}

	def bulkEndpoint(self, dirIn):
		"First bulk endpoint in the requested direction (descriptor order)."
		for ep in self.endpoints:
			if ep.type == USB_PIPE_TYPE_BULK and \
			   bool(ep.bEndpointAddress & 0x80) == bool(dirIn):
				return ep
		return None

	def __setTimeout(self, ep, timeoutMs):
		if self.__timeouts.get(ep) == timeoutMs:
			return
		v = wt.ULONG(int(timeoutMs))
		if not _wusb.WinUsb_SetPipePolicy(self.hUsb, ep, PIPE_TRANSFER_TIMEOUT,
						  ctypes.sizeof(v), ctypes.byref(v)):
			raise _err("WinUsb_SetPipePolicy")
		self.__timeouts[ep] = timeoutMs

	def write(self, ep, data, timeoutMs):
		self.open()
		data = bytes(data)
		self.__setTimeout(ep, timeoutMs)
		buf = ctypes.create_string_buffer(data, len(data))
		done = wt.ULONG(0)
		if not _wusb.WinUsb_WritePipe(self.hUsb, ep, buf, len(data),
					      ctypes.byref(done), None):
			raise _err("WinUsb_WritePipe(0x%02x)" % ep)
		return done.value

	def read(self, ep, size, timeoutMs):
		self.open()
		self.__setTimeout(ep, timeoutMs)
		buf = ctypes.create_string_buffer(size)
		done = wt.ULONG(0)
		if not _wusb.WinUsb_ReadPipe(self.hUsb, ep, buf, size,
					     ctypes.byref(done), None):
			raise _err("WinUsb_ReadPipe(0x%02x)" % ep)
		return buf.raw[:done.value]

	def clearHalt(self, ep):
		self.open()
		if not _wusb.WinUsb_ResetPipe(self.hUsb, ep):
			raise _err("WinUsb_ResetPipe(0x%02x)" % ep)


def find_devices(match=None):
	"""Return WinUsbDevice objects for present USB devices.
	'match' is called with each candidate (has idVendor/idProduct)
	and should return a true value for wanted devices."""
	devs = []
	for vid, pid, path in _present_vidpids():
		d = WinUsbDevice(vid, pid, path)
		if match is not None and not match(d):
			continue
		# Prefer the interface GUID that Zadig registered for WinUSB.
		key = _instance_key(path)
		for g in _registry_interface_guids(vid, pid):
			try:
				for p in _interface_paths(_guid(g)):
					if _instance_key(p) == key and p not in d.openPaths:
						d.openPaths.append(p)
			except WinUsbError:
				pass
		devs.append(d)
	return devs


if __name__ == "__main__":
	devs = find_devices(lambda d: (d.idVendor, d.idProduct) == (0x2471, 0x0853))
	if not devs:
		raise SystemExit("TOP programmer 2471:0853 not found")
	d = devs[0]
	print("Found", d)
	for p in d.openPaths:
		print("  WinUSB interface path:", p)
	d.open()
	print("Interface %d, %d endpoint(s):" % (d.interface.bInterfaceNumber, len(d.endpoints)))
	for ep in d.endpoints:
		print("  ep 0x%02x type %d maxpkt %d" % (ep.bEndpointAddress, ep.type, ep.wMaxPacketSize))
	out, inp = d.bulkEndpoint(False), d.bulkEndpoint(True)
	print("Using bulk OUT 0x%02x, bulk IN 0x%02x" % (out.bEndpointAddress, inp.bEndpointAddress))
	# Same first request TopWin/toprammer send: read the version string
	d.write(out.bEndpointAddress, b"\x0e\x11\x00\x00", 2000)
	d.write(out.bEndpointAddress, b"\x07", 2000)
	data = d.read(inp.bEndpointAddress, 64, 2000)
	print("Version reply:", data.rstrip(b"\x00 ").decode("ascii", "replace"))
	d.close()
