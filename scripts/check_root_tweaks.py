#!/usr/bin/env python3
"""Check the iOS root for the bring-up tweaks, by reading the files.

The CI log says the tweaks ran.  A log line proves a script started; only
the image proves it finished.  This reads the image directly, through a
small HFS+ reader, and checks the files the tweaks are supposed to have
changed:

  /System/Library/xpc/launchd.plist
      com.apple.CommCenter must be gone.  There is no baseband on this
      phone, so CommCenter crash-loops and Setup blocks forever on its
      CoreTelephony XPC.  That was the wall between image v13 and v14
      upstream.  _PanicOnCrash must have become _PanicOnCrasX, so a
      crashing daemon does not take the system down with it.
  /private/var/mobile/Library/Preferences/com.apple.purplebuddy.plist
      SetupDone / SetupFinishedAllSteps / SetupVersion: Setup is skipped
      instead of waiting for a migration that will never finish.
  /private/var/mobile/Library/Preferences/com.apple.migration.plist
      LastSystemVersion: DataMigration must not run for an hour on every
      boot.
  /private/var/containers/Data/System/<id>/Library/internal/data_ark.plist
      the activation seed mobileactivationd needs.

    python3 scripts/check_root_tweaks.py IMAGE.simg
"""
import os
import plistlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_root as vr
from hfsplus import HFSPlusVolume

LAUNCHD = "/System/Library/xpc/launchd.plist"
PURPLEBUDDY = ("/private/var/mobile/Library/Preferences/"
               "com.apple.purplebuddy.plist")
MIGRATION = ("/private/var/mobile/Library/Preferences/"
             "com.apple.migration.plist")
ARK = ("/private/var/containers/Data/System/"
       "D90C94C4-F94E-4FCF-8A28-A93BE3846D8E/Library/internal/"
       "data_ark.plist")

failures = []


def report(ok, label, detail=""):
    print("  [%s] %-32s %s" % ("OK  " if ok else "FAIL", label, detail))
    if not ok:
        failures.append(label)


def read_plist(vol, path):
    data = vol.read_path(path)
    if not data:
        return None
    try:
        return plistlib.loads(data)
    except Exception as e:
        print("   (cannot parse %s: %s)" % (path, e))
        return None


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    path = sys.argv[1]
    print("== %s ==" % path)

    img = vr.SparseImage(path)
    vol = HFSPlusVolume(img, volume_start=1024)

    # --- launchd.plist ---------------------------------------------------
    pl = read_plist(vol, LAUNCHD)
    if pl is None:
        report(False, "launchd.plist", "cannot read it")
    else:
        jobs = pl.get("LaunchDaemons", {})
        labels = list(jobs.keys())
        # Upstream removes the job whose Label is exactly
        # "com.apple.CommCenter" -- the two helpers have their own labels
        # (CommCenterMobileHelper, CommCenterRootHelper) and stay.
        comm = [l for l, j in jobs.items()
                if isinstance(j, dict) and j.get("Label") == "com.apple.CommCenter"]
        if comm:
            report(False, "CommCenter removed", "still there: %s"
                   % ", ".join(comm))
        else:
            report(True, "CommCenter removed", "no com.apple.CommCenter job")
        old = [l for l, j in jobs.items()
               if isinstance(j, dict) and j.get("_PanicOnCrash")]
        new = [l for l, j in jobs.items()
               if isinstance(j, dict) and j.get("_PanicOnCrasX")]
        if old:
            report(False, "_PanicOnCrasX", "%d job(s) still panic" % len(old))
        elif new:
            report(True, "_PanicOnCrasX", "%d job(s) renamed" % len(new))
        else:
            report(False, "_PanicOnCrasX", "no renamed job found")

    # --- Setup skipped ---------------------------------------------------
    pb = read_plist(vol, PURPLEBUDDY)
    if pb is None:
        report(False, "Setup skipped", "cannot read the preferences")
    else:
        want = {"SetupDone": True, "SetupFinishedAllSteps": True,
                "SetupVersion": 11}
        missing = [k for k, v in want.items() if pb.get(k) != v]
        if missing:
            report(False, "Setup skipped", "wrong: %s" % ", ".join(missing))
        else:
            report(True, "Setup skipped", "SetupDone / FinishedAllSteps / v11")

    # --- DataMigration ---------------------------------------------------
    mg = read_plist(vol, MIGRATION)
    if mg is None:
        report(False, "DataMigration", "cannot read the preferences")
    elif mg.get("LastSystemVersion"):
        report(True, "DataMigration",
               "LastSystemVersion=%s" % mg.get("LastSystemVersion"))
    else:
        report(False, "DataMigration", "LastSystemVersion missing")

    # --- activation ------------------------------------------------------
    ark = read_plist(vol, ARK)
    if ark is None:
        report(False, "activation seed", "cannot read data_ark.plist")
    elif ark.get("-ActivationState") == "Activated":
        report(True, "activation seed", "-ActivationState=Activated")
    else:
        report(False, "activation seed",
               "-ActivationState=%s" % ark.get("-ActivationState"))

    print()
    if failures:
        print("%d check(s) FAILED: %s" % (len(failures), ", ".join(failures)))
        return 1
    print("all checks passed: the image carries the bring-up tweaks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
