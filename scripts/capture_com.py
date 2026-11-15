#!/usr/bin/env python3
"""Read the iOS console log out of the phone's CDC-ACM port.

The device is already running the kernel; this only opens the COM port
and reads it.  Handy when the phone was booted by hand and the log is
still live.

    python3 scripts/capture_com.py --seconds 60 --out D:/raphael-ios/work/com_ag.log
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from boot_and_capture import find_com, read_com  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--out", default="D:/raphael-ios/work/com_capture.log")
    ap.add_argument("--port", default=None)
    ap.add_argument("--wait", type=int, default=0,
                    help="seconds to wait for the port to appear")
    args = ap.parse_args()

    port = args.port
    deadline = time.time() + args.wait
    while not port and time.time() < deadline:
        port = find_com()
        if not port:
            time.sleep(2)
    if not port:
        port = find_com()
    if not port:
        print("no CDC-ACM port (VID:PID=1209:0001) found")
        return 1
    print("COM port:", port, flush=True)

    try:
        n = read_com(port, args.seconds, args.out)
    except OSError as e:
        print("read failed: %s" % e)
        return 3
    print("captured %d bytes -> %s" % (n, args.out))

    data = open(args.out, "rb").read().decode("utf-8", "replace")
    lines = data.splitlines()
    print("--- %d lines, last 40 ---" % len(lines))
    for line in lines[-40:]:
        print(line)
    groups = {
        "SWEET HID": "SWEET HID",
        "SWEET FB": "SWEET FB",
        "SWEET TOUCH": "SWEET TOUCH",
        "AppleCLCD": "AppleCLCD",
        "AppleHID": "AppleHID",
    }
    for label, key in groups.items():
        keep = [l for l in lines if key in l]
        if keep:
            print("--- %s: %d lines ---" % (label, len(keep)))
            for line in keep[-40:]:
                print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
