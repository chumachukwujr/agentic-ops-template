#!/usr/bin/env python3
"""
rotate_state.py - state/ backup rotation with compressed, tiered archiving.

Tiers (rolling):
  WEEKLY  : loose backup files at the TOP LEVEL of state/ (name contains 'bak')
            older than KEEP_DAYS -> state/archive/<YYYY>/weekly/<YYYY>-W<ww>_state_backups.zip
            then the loose originals are deleted.
  MONTHLY : weekly zips whose ISO week ended > ~31d ago are bundled into
            state/archive/<YYYY>/<YYYY>-<MM>_state_backups.zip ; the weekly zips are deleted.
  YEARLY  : monthly zips whose month ended > ~366d ago are bundled into
            state/archive/<YYYY>_state_backups.zip ; the monthly zips are deleted.

SAFETY:
  - Only ever touches regular files at the TOP LEVEL of state/ whose name contains 'bak'.
    Live state files (activity_log.json, history.jsonl, escalations.json, *_dev_state.json,
    company_state.md, etc.) do NOT contain 'bak' and are never touched.
  - Never recurses into subdirectories (drafts/, archive/, or any per-workstream folder).
  - Deletes only AFTER the file is confirmed written into its zip.
  - Must run where deletes work: a native Claude Code routine / cron on the Mac, OR a
    sandboxed session that has been granted file-delete on the repo folder.
    In a FUSE-mounted sandbox WITHOUT that grant, os.remove() raises PermissionError;
    this script catches it, leaves the original in place, and reports it.

Usage:
  python3 rotate_state.py            # do the rotation
  python3 rotate_state.py --dry-run  # show what would happen, change nothing
"""
import os, sys, zipfile, datetime

def _resolve_state():
    # Allow override for execution elsewhere (e.g. a sandbox where ~ differs).
    for a in sys.argv:
        if a.startswith("--state="):
            return os.path.abspath(os.path.expanduser(a.split("=", 1)[1]))
    env = os.environ.get("AGENT_STATE_DIR")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    return os.path.expanduser("~/<YOUR_REPO>/state")

STATE = _resolve_state()
ARCHIVE = os.path.join(STATE, "archive")
KEEP_DAYS = 7            # loose backups younger than this stay live
MONTHLY_AFTER_DAYS = 31  # weekly zip eligible for monthly rollup once this old
YEARLY_AFTER_DAYS = 366  # monthly zip eligible for yearly rollup once this old
NOW = datetime.datetime.now()
DRY = "--dry-run" in sys.argv

def log(msg): print(msg)

def mtime(path): return datetime.datetime.fromtimestamp(os.path.getmtime(path))
def age_days(path): return (NOW - mtime(path)).days

def safe_remove(path):
    if DRY: return True
    try:
        os.remove(path); return True
    except PermissionError:
        log(f"  ! could not delete (no FS delete permission): {os.path.basename(path)}")
        return False

def add_to_zip(zpath, filepath, arcname):
    if DRY:
        log(f"  [dry] would add {arcname} -> {os.path.relpath(zpath, STATE)}")
        return True
    os.makedirs(os.path.dirname(zpath), exist_ok=True)
    with zipfile.ZipFile(zpath, "a", zipfile.ZIP_DEFLATED) as z:
        names = set(z.namelist())
        arc = arcname; i = 1
        while arc in names:  # avoid clobber on re-run
            arc = f"{arcname}.{i}"; i += 1
        z.write(filepath, arcname=arc)
    return True

def weekly():
    log("== WEEKLY: loose backup files -> weekly zips ==")
    n = 0
    if not os.path.isdir(STATE): return n
    for name in sorted(os.listdir(STATE)):
        p = os.path.join(STATE, name)
        if not os.path.isfile(p): continue
        if "bak" not in name.lower(): continue      # only backup files
        if age_days(p) <= KEEP_DAYS: continue        # keep recent backups live
        iso = mtime(p).isocalendar()
        y, w = iso[0], iso[1]
        zpath = os.path.join(ARCHIVE, str(y), "weekly", f"{y}-W{w:02d}_state_backups.zip")
        if add_to_zip(zpath, p, name) and safe_remove(p):
            n += 1
    log(f"  weekly: archived {n} loose backup files")
    return n

def _zip_end_date_from_week(fname):
    # fname like 2026-W26_state_backups.zip -> date of that ISO week's Sunday
    base = fname.split("_")[0]            # 2026-W26
    y, w = base.split("-W")
    monday = datetime.date.fromisocalendar(int(y), int(w), 1)
    return datetime.datetime.combine(monday + datetime.timedelta(days=6), datetime.time())

def monthly():
    log("== MONTHLY: aged weekly zips -> monthly zips ==")
    n = 0
    for y in sorted(os.listdir(ARCHIVE) if os.path.isdir(ARCHIVE) else []):
        wdir = os.path.join(ARCHIVE, y, "weekly")
        if not os.path.isdir(wdir): continue
        for fname in sorted(os.listdir(wdir)):
            if not fname.endswith(".zip"): continue
            fpath = os.path.join(wdir, fname)
            try: end = _zip_end_date_from_week(fname)
            except Exception: continue
            if (NOW - end).days <= MONTHLY_AFTER_DAYS: continue
            mlabel = f"{end.year}-{end.month:02d}"
            zpath = os.path.join(ARCHIVE, str(end.year), f"{mlabel}_state_backups.zip")
            if add_to_zip(zpath, fpath, fname) and safe_remove(fpath):
                n += 1
    log(f"  monthly: rolled {n} weekly zips")
    return n

def yearly():
    log("== YEARLY: aged monthly zips -> yearly zips ==")
    n = 0
    for y in sorted(os.listdir(ARCHIVE) if os.path.isdir(ARCHIVE) else []):
        ydir = os.path.join(ARCHIVE, y)
        if not os.path.isdir(ydir): continue
        for fname in sorted(os.listdir(ydir)):
            if not (fname.endswith(".zip") and "-" in fname and "W" not in fname): continue
            # monthly zip: YYYY-MM_state_backups.zip
            fpath = os.path.join(ydir, fname)
            base = fname.split("_")[0]
            try:
                yy, mm = base.split("-"); yy = int(yy); mm = int(mm)
                # end of month
                first_next = datetime.date(yy + (mm // 12), (mm % 12) + 1, 1)
                end = datetime.datetime.combine(first_next - datetime.timedelta(days=1), datetime.time())
            except Exception:
                continue
            if (NOW - end).days <= YEARLY_AFTER_DAYS: continue
            zpath = os.path.join(ARCHIVE, f"{yy}_state_backups.zip")
            if add_to_zip(zpath, fpath, fname) and safe_remove(fpath):
                n += 1
    log(f"  yearly: rolled {n} monthly zips")
    return n

if __name__ == "__main__":
    log(f"rotate_state.py {'(DRY RUN) ' if DRY else ''}@ {NOW.isoformat(timespec='seconds')}")
    log(f"state dir: {STATE}")
    w = weekly(); m = monthly(); yr = yearly()
    log(f"DONE. weekly={w} monthly={m} yearly={yr}. Archives under {os.path.relpath(ARCHIVE, STATE)}/")
