#!/usr/bin/env python3
"""Boot a UniXNU image with fastboot and capture the iOS console log.

The phone enumerates as a CDC-ACM device (VID 0x1209, PID 0x0001) and
pushes the kernel console ring out of the bulk IN endpoint, so whatever
the COM port delivers is the text the panel would draw.  Windows binds
usbser.sys to it from the box, no extra driver needed.

With the 0101 control-transfer bug the port opens and the device then
drops off the bus (Win32 error 6 / 121): Windows sends SET_LINE_CODING
when it opens the port, the device answered the status stage in the
wrong direction, and the host gave up.  The 0112 binary patch fixes
that, and this script is how we check that it did - and how we get the
touch coordinates out of the kernel.

    python3 scripts/boot_and_capture.py D:/raphael-ios/boot/TEST_AF_cdcfix.img

Steps: wait for the phone in fastboot, boot the image, wait for the COM
port to show up, then read it until the timeout.  The log lands in
work/com_capture.log and the interesting lines are printed at the end.
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

FASTBOOT_CANDIDATES = [
    os.path.join(ROOT, "tools", "platform-tools", "fastboot.exe"),
    "C:/Users/JohnTech/WorkBuddy/2026-10-25-16-03-19/raphael-port/tools/"
    "platform-tools/fastboot.exe",
    "D:/raphael-ios/work/pt33/fastboot.exe",
]
FASTBOOT = next((p for p in FASTBOOT_CANDIDATES if os.path.exists(p)), None)
if FASTBOOT is None:
    print("no fastboot.exe found in: %s" % ", ".join(FASTBOOT_CANDIDATES))
    sys.exit(1)

OUT_LOG = "D:/raphael-ios/work/com_capture.log"


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def fastboot_devices():
    try:
        r = run([FASTBOOT, "devices"])
    except FileNotFoundError:
        return []
    out = []
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if line and not line.startswith("List of devices"):
            out.append(line.split()[0])
    return out


def wait_fastboot(timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        devs = fastboot_devices()
        if devs:
            return devs[0]
        time.sleep(2)
    return None


def find_com():
    from serial.tools import list_ports
    for p in list_ports.comports():
        if "VID:PID=1209:0001" in (p.hwid or "").upper():
            return p.device
    return None


def wait_com_gone(timeout):
    """Wait until the CDC-ACM port disappears.

    The phone may still be running the old kernel, in which case the port is
    already enumerated before the boot.  Catching that stale port would read
    the log of the previous run, so wait for it to go away first.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not find_com():
            return True
        time.sleep(2)
    return False


def read_com(port, seconds, out_path):
    """Open the port with the raw Win32 API and read until the timeout."""
    import ctypes
    from ctypes import wintypes

    GENERIC_READ = 0x80000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    OPEN_EXISTING = 3
    FILE_FLAG_OVERLAPPED = 0x40000000
    FILE_ATTRIBUTE_NORMAL = 0x00000080
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    path = "\\\\.\\" + port
    handle = INVALID_HANDLE_VALUE
    last_err = 0
    # The port shows up in the enumeration before the driver has finished
    # creating it, so the first open can fail with ERROR_FILE_NOT_FOUND.
    deadline = time.time() + 30
    while time.time() < deadline:
        handle = kernel32.CreateFileW(
            path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, None,
            OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
        if handle != INVALID_HANDLE_VALUE:
            break
        last_err = ctypes.get_last_error()
        time.sleep(1)
    if handle == INVALID_HANDLE_VALUE:
        raise OSError("CreateFileW(%s) failed: %d" % (path, last_err))

    buf = ctypes.create_string_buffer(4096)
    nread = wintypes.DWORD(0)
    deadline = time.time() + seconds
    total = 0
    with open(out_path, "wb") as f:
        while time.time() < deadline:
            if not kernel32.ReadFile(handle, buf, 4096, ctypes.byref(nread), None):
                err = ctypes.get_last_error()
                if err == 1167:      # ERROR_IO_PENDING
                    time.sleep(0.05)
                    continue
                raise OSError("ReadFile failed: %d" % err)
            if nread.value:
                chunk = buf.raw[:nread.value]
                f.write(chunk)
                f.flush()
                total += len(chunk)
    kernel32.CloseHandle(handle)
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--wait-fastboot", type=int, default=600)
    ap.add_argument("--wait-com", type=int, default=240)
    ap.add_argument("--read-seconds", type=int, default=60)
    ap.add_argument("--out", default=OUT_LOG)
    args = ap.parse_args()

    print("waiting for fastboot (up to %ds)..." % args.wait_fastboot, flush=True)
    print("  -> power the phone off, then hold VOLUME DOWN + POWER to enter fastboot")
    dev = wait_fastboot(args.wait_fastboot)
    if not dev:
        print("no device in fastboot")
        return 1
    print("device:", dev, flush=True)

    # The port of the previous run is still enumerated while the phone was
    # running the old kernel.  Drop it before the boot so that we do not
    # read a stale port.
    if find_com():
        print("waiting for the old COM port to disappear...", flush=True)
        wait_com_gone(60)

    print("booting %s ..." % args.image, flush=True)
    r = run([FASTBOOT, "-s", dev, "boot", args.image], timeout=300)
    print((r.stdout or "") + (r.stderr or ""), flush=True)

    print("waiting for the CDC-ACM port (up to %ds)..." % args.wait_com, flush=True)
    deadline = time.time() + args.wait_com
    port = None
    while time.time() < deadline:
        port = find_com()
        if port:
            break
        time.sleep(3)
    if not port:
        print("no COM port appeared -- the device still does not enumerate")
        return 2
    print("COM port:", port, flush=True)

    time.sleep(5)
    try:
        n = read_com(port, args.read_seconds, args.out)
        print("captured %d bytes -> %s" % (n, args.out))
    except OSError as e:
        print("read failed: %s" % e)
        print("  -> the port dropped as soon as it was opened: the 0112 fix")
        print("     (control transfer status stage direction) is NOT working")
        return 3

    try:
        data = open(args.out, "rb").read().decode("utf-8", "replace")
    except OSError:
        return 4
    lines = data.splitlines()
    print("--- last 40 lines ---")
    for line in lines[-40:]:
        print(line)

    groups = [
        ("SWEET HID", "touch and key events"),
        ("SWEET FB", "framebuffer state"),
        ("SWEET TOUCH", "touch controller"),
        ("SWEET USB", "usb state"),
        ("AppleCLCD", "panel geometry"),
    ]
    for needle, title in groups:
        keep = [l for l in lines if needle in l]
        if not keep:
            continue
        print("--- %d %s lines (%s) ---" % (len(keep), needle, title))
        for line in keep[-40:]:
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
