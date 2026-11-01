#!/usr/bin/env python3
"""Explain the DWC3 event words the kernel prints.

    decode_usb_events.py ios-console.log

The kernel logs every DWC3 event as

    SWEET USB: event 0x%08x

and every control request as

    SWEET USB: setup %02x %02x %04x %04x len %u

This turns those into something readable, and says which control transfers
got a status stage in the wrong direction (patch 0112 fixed that).

The event word layout, as the kernel decodes it:

    bit  0       1 = device event (reset, connect), 0 = endpoint event
    bits 5:1     endpoint number
    bits 9:6     event type
    bits 15:12   event status
"""
import re
import sys

EVENT_RE = re.compile(r"SWEET USB: event 0x([0-9a-fA-F]{8})")
SETUP_RE = re.compile(
    r"SWEET USB: setup ([0-9a-fA-F]{2}) ([0-9a-fA-F]{2}) "
    r"([0-9a-fA-F]{4}) ([0-9a-fA-F]{4}) len (\d+)"
)

# Endpoint event types.  The kernel treats type 1 as a completed transfer
# (`if (type == 1) { /* XferComplete */ }`), so that is what this table says
# too; the names beyond that are the DWC3 documentation's.
EV_TYPES = {
    0: "XferComplete?",
    1: "XferComplete",
    2: "type 2",
    3: "XferNotReady",
}

# Event status values that matter for control transfers.
EV_STATUS = {
    0: "OK",
    1: "ShortPkt",
    2: "ControlStatus",
    3: "Stall",
}

# Class requests the kernel knows about.
CLASS_REQS = {
    (0x20, 0x20): "SET_LINE_CODING",
    (0x21, 0x21): "GET_LINE_CODING",
    (0x21, 0x22): "SET_CONTROL_LINE_STATE",
    (0x21, 0x23): "SEND_BREAK",
}


def describe(word):
    """Return a human readable line for one event word."""
    v = int(word, 16)
    if v & 1:
        # Device event: the type sits in bits 11:8.
        dev_type = (v >> 8) & 0xf
        names = {0: "Disconnect", 1: "USBReset"}
        return "device event: %s (0x%08x)" % (names.get(dev_type, "type %d" % dev_type), v)

    ep = (v >> 1) & 0x1f
    etype = (v >> 6) & 0xf
    status = (v >> 12) & 0xf
    what = EV_TYPES.get(etype, "type %d" % etype)
    st = EV_STATUS.get(status, "status %d" % status)
    out = "ep%d %s (%s)" % (ep, what, st)
    if etype == 3 and status == 2:
        # The control status phase.  The host expects the status to run
        # opposite to the data stage, and the endpoint number here is not
        # what the direction is derived from.
        out += "  <- control status phase"
    return out + "  [0x%08x]" % v


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    try:
        text = open(sys.argv[1], "r", encoding="utf-8", errors="replace").read()
    except OSError as e:
        print("cannot read %s: %s" % (sys.argv[1], e), file=sys.stderr)
        return 2

    print("== control requests ==")
    setups = []
    for m in SETUP_RE.finditer(text):
        bmt, req, value, index, length = m.groups()
        bmt_i = int(bmt, 16)
        req_i = int(req, 16)
        direction = "IN" if bmt_i & 0x80 else "OUT"
        kind = CLASS_REQS.get((bmt_i, req_i))
        if kind is None and (bmt_i & 0x60) == 0x00:
            kind = {6: "GET_DESCRIPTOR", 5: "SET_ADDRESS",
                    9: "SET_CONFIGURATION", 8: "GET_CONFIGURATION",
                    0: "GET_STATUS", 11: "SET_INTERFACE"}.get(req_i)
        elif kind is None:
            kind = "class request"
        setups.append((bmt_i, req_i, int(length)))
        print("  setup %s %s %s %s len %s  %-24s %s"
              % (bmt, req, value, index, length, kind, direction))

    print()
    print("== events ==")
    events = []
    for m in EVENT_RE.finditer(text):
        line = describe(m.group(1))
        events.append(line)
        print("  " + line)

    # Work out what the status stage should have been for each control
    # transfer, and say so when the kernel sent it the other way.
    print()
    print("== status stage directions ==")
    for bmt, req, length in setups:
        if length == 0:
            want = "IN"
            why = "no data stage"
        elif bmt & 0x80:
            want = "OUT"
            why = "IN data stage"
        else:
            want = "IN"
            why = "OUT data stage"
        print("  %-24s data=%-6s -> status must be %-3s (%s)"
              % (CLASS_REQS.get((bmt, req), "setup %02x %02x" % (bmt, req)),
                 "IN" if bmt & 0x80 else "OUT", want, why))

    # The control status phase is reported on an endpoint, and the kernel
    # used to take the direction straight from that number.  Compare what
    # the events show with what each request needed.
    print()
    print("== control status phases seen ==")
    status_eps = []
    for line in events:
        if "control status phase" in line:
            m = re.search(r"ep(\d+)", line)
            if m:
                status_eps.append(int(m.group(1)))
    if not status_eps:
        print("  none")
    else:
        for i, (bmt, req, length) in enumerate(setups):
            if i >= len(status_eps):
                break
            if length == 0:
                want_in = True
            else:
                want_in = not (bmt & 0x80)
            got_in = status_eps[i] == 1
            verdict = "OK" if got_in == want_in else "WRONG DIRECTION"
            print("  %-24s status on ep%d, wanted %-3s -> %s"
                  % (CLASS_REQS.get((bmt, req), "setup %02x %02x" % (bmt, req)),
                     status_eps[i], "IN" if want_in else "OUT", verdict))

    print()
    if not events:
        print("no DWC3 events in the log: the USB code never reached the "
              "controller, or the log does not cover that part of the boot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
