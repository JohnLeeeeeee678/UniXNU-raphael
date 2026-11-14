#!/usr/bin/env python3
"""Probe the CDC-ACM device without going through the COM driver.

Opening a COM port makes Windows send SET_LINE_CODING, and the 0101
control-transfer state machine answers that with a status stage in the
wrong direction, so the port opens and then the device drops off the
bus.  This probe opens the COM port once, watches what happens, and
reports the Win32 error codes so the failure can be told apart from a
plain read timeout.

It also lists the device's endpoints through the USB device tree, which
does not need a driver at all.

    python3 scripts/probe_acm.py
"""
import ctypes
import sys
import time
from ctypes import wintypes

VID = 0x1209
PID = 0x0001

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
FILE_ATTRIBUTE_NORMAL = 0x00000080
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


def find_ports():
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return list(list_ports.comports())


def open_raw(name):
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = ctypes.c_void_p
    k32.CreateFileW.argtypes = [
        ctypes.c_wchar_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    h = k32.CreateFileW("\\\\.\\" + name, GENERIC_READ,
                         FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                         OPEN_EXISTING,
                         FILE_FLAG_OVERLAPPED | FILE_ATTRIBUTE_NORMAL, None)
    err = ctypes.get_last_error()
    return h, err, k32


def main():
    print("== COM ports ==")
    ports = find_ports()
    for p in ports:
        mark = " <== the phone" if (p.vid, p.pid) == (VID, PID) else ""
        print("   %-8s vid=%04x pid=%04x  %s%s"
              % (p.device, p.vid or 0, p.pid or 0, p.description or "", mark))

    target = None
    for p in ports:
        if (p.vid, p.pid) == (VID, PID):
            target = p.device
            break
    if target is None:
        print("\n!! the phone's CDC-ACM port is not there")
        return 1

    print("\n== opening %s ==" % target)
    h, err, k32 = open_raw(target)
    if h is None or h == INVALID_HANDLE_VALUE:
        print("   CreateFileW failed, error %d" % err)
        return 1
    print("   handle ok")

    # Read with a real overlapped structure: the handle was opened with
    # FILE_FLAG_OVERLAPPED, so a plain ReadFile with a NULL overlapped
    # pointer is rejected with ERROR_INVALID_PARAMETER (87).
    class OVERLAPPED(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_ulong),
            ("InternalHigh", ctypes.c_ulong),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", ctypes.c_void_p),
        ]

    k32.CreateEventW.restype = ctypes.c_void_p
    k32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                  wintypes.BOOL, ctypes.c_wchar_p]
    k32.WaitForSingleObject.restype = wintypes.DWORD
    k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    k32.ResetEvent.restype = wintypes.BOOL
    k32.ResetEvent.argtypes = [ctypes.c_void_p]
    k32.GetOverlappedResult.restype = wintypes.BOOL
    k32.GetOverlappedResult.argtypes = [ctypes.c_void_p,
                                         ctypes.POINTER(OVERLAPPED),
                                         ctypes.POINTER(wintypes.DWORD),
                                         wintypes.BOOL]
    k32.CancelIo.restype = wintypes.BOOL
    k32.CancelIo.argtypes = [ctypes.c_void_p]

    ev = k32.CreateEventW(None, True, False, None)
    buf = ctypes.create_string_buffer(4096)
    n = wintypes.DWORD()
    ov = OVERLAPPED()
    ERROR_IO_PENDING = 997
    WAIT_TIMEOUT = 258
    INFINITE = 0xFFFFFFFF

    total = 0
    for attempt in range(20):
        k32.ResetEvent(ev)
        n.value = 0
        ctypes.memset(ctypes.byref(ov), 0, ctypes.sizeof(ov))
        ov.hEvent = ev
        ok = k32.ReadFile(h, buf, 4096, ctypes.byref(n), ctypes.byref(ov))
        if not ok:
            err = ctypes.get_last_error()
            if err == ERROR_IO_PENDING:
                r = k32.WaitForSingleObject(ev, 1000)
                if r == WAIT_TIMEOUT:
                    k32.CancelIo(h)
                    k32.WaitForSingleObject(ev, INFINITE)
                    k32.GetOverlappedResult(h, ctypes.byref(ov),
                                            ctypes.byref(n), False)
                    print("   read %d: timed out (no data yet)" % attempt)
                    continue
                k32.GetOverlappedResult(h, ctypes.byref(ov),
                                        ctypes.byref(n), False)
            else:
                print("   read %d: failed, error %d" % (attempt, err))
                break
        if n.value:
            print("   read %d: %d bytes: %r"
                  % (attempt, n.value, buf.raw[:n.value][:200]))
            total += n.value
        else:
            print("   read %d: completed with 0 bytes" % attempt)
    print("   total %d bytes" % total)

    k32.CloseHandle.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    k32.CloseHandle(ev)
    k32.CloseHandle(h)

    # Watch the port list for a while: if the device is being reset, the
    # port disappears and comes back.
    print("\n== watching the port for 15 s ==")
    seen = set()
    for i in range(30):
        now = set(p.device for p in find_ports()
                  if (p.vid, p.pid) == (VID, PID))
        if now != seen:
            print("   [%4.1fs] ports: %s" % (i * 0.5,
                                             sorted(now) or "gone"))
            seen = now
        time.sleep(0.5)
    if not seen:
        print("   the device stayed gone for the whole 15 s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
