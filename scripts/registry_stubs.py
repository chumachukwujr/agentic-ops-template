#!/usr/bin/env python3
"""registry_stubs.py - the scheduler stubs are a VIEW of agents/REGISTRY.json (Pattern 9).

The registry says who runs, when, under which identity, and which routine file (plus optional
beat) each registration executes. This script turns that into whatever your scheduler needs,
so the scheduler never becomes a second source of truth:

  registry_stubs.py list                           one line per registration
  registry_stubs.py render --task-dir DIR          write <DIR>/<id>/SKILL.md pointer stubs
  registry_stubs.py check  --task-dir DIR          registry-aware drift check (exit 1 on findings)
  registry_stubs.py crontab [--runner CMD]         crontab lines for a plain cron scheduler

render never overwrites a stub that has grown into a real prompt: that is somebody's edit and
the only copy of it. It reports DRIFT and leaves the file alone (see Pattern 4). --force
overrides, for the case where you have already diffed and merged.

Env overrides: AGENT_REGISTRY (path to the registry), AGENT_REPO_ROOT (absolute path used in
the stubs; default is this repo).
"""
from __future__ import annotations
import argparse, json, os, sys

STUB_MAX_LINES = 14          # a healthy stub is short; length is the drift signal
STUB_MARK = "This is a pointer stub."


def repo_root() -> str:
    return os.path.expanduser(os.environ.get("AGENT_REPO_ROOT")
                              or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def registry_path() -> str:
    return os.path.expanduser(os.environ.get("AGENT_REGISTRY") or os.path.join(repo_root(), "agents", "REGISTRY.json"))


def load_registry() -> dict:
    with open(registry_path(), encoding="utf-8") as fh:
        return json.load(fh)


def scheduled(reg: dict) -> list:
    """Registrations that should exist in the scheduler: enabled, with a cron and a routine."""
    return [a for a in reg.get("agents", [])
            if (a.get("registration") or {}).get("enabled") and (a.get("registration") or {}).get("cron")
            and a.get("routine")]


def render_stub(a: dict, root: str) -> str:
    r = a.get("registration") or {}
    routine = a["routine"]
    path = os.path.join(root, routine)
    beat = a.get("beat")
    ident = a.get("history_identity") or a["id"]
    desc = a.get("description") or f"{a['id']} - {r.get('schedule_human') or r.get('cron')}"
    if beat:
        exec_line = f"Read and execute the routine at {path} with beat={beat}."
    else:
        exec_line = f"Read and execute the routine at {path}."
    base = os.path.basename(routine)
    return (
        f"---\nname: {a['id']}\ndescription: {desc}\n---\n\n"
        f"{exec_line} Follow it end-to-end. That file is authoritative; do not summarise or substitute for it.\n"
        f"Working directory: {root}\n\n"
        f"{STUB_MARK} Edit the canonical routine, never this file.\n"
        f"If the routine file is unreachable, run:\n"
        f"  python3 {root}/scripts/state_io.py escalate --agent {ident} --severity CRITICAL "
        f"--title \"{base} unreachable\" --detail \"stub {a['id']} could not read {routine}\"\n"
        f"and stop without doing other work.\n")


def is_stub(text: str, routine: str) -> bool:
    n = len(text.strip().splitlines())
    return STUB_MARK in text and routine in text and n <= STUB_MAX_LINES


def cmd_list(reg: dict) -> int:
    tz = (reg.get("_meta") or {}).get("schedule_tz") or "UTC"
    print(f"{'id':34} {'identity':22} {'cron ('+tz+')':18} {'enabled':8} routine")
    for a in reg.get("agents", []):
        r = a.get("registration") or {}
        beat = f" beat={a['beat']}" if a.get("beat") else ""
        print(f"{a.get('id',''):34} {str(a.get('history_identity') or '-'):22} {str(r.get('cron') or '-'):18} "
              f"{str(bool(r.get('enabled'))):8} {a.get('routine','-')}{beat}")
    return 0


def cmd_render(reg: dict, task_dir: str, force: bool) -> int:
    root = repo_root()
    drift = 0
    for a in scheduled(reg):
        d = os.path.join(task_dir, a["id"])
        f = os.path.join(d, "SKILL.md")
        new = render_stub(a, root)
        if os.path.exists(f):
            with open(f, encoding="utf-8") as fh:
                cur = fh.read()
            if cur == new:
                print(f"ok        {a['id']}")
                continue
            if not is_stub(cur, a["routine"]) and not force:
                print(f"DRIFT     {a['id']}: live file is not a stub ({len(cur.splitlines())} lines); "
                      f"diff it against {a['routine']} and merge by hand, or re-run with --force")
                drift += 1
                continue
            print(f"updated   {a['id']}")
        else:
            print(f"created   {a['id']}")
        os.makedirs(d, exist_ok=True)
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(new)
    return 1 if drift else 0


def cmd_check(reg: dict, task_dir: str) -> int:
    findings = []
    want = {a["id"]: a for a in scheduled(reg)}
    for aid, a in want.items():
        f = os.path.join(task_dir, aid, "SKILL.md")
        if not os.path.exists(f):
            findings.append(f"MISSING   {aid}: no stub at {f}")
            continue
        with open(f, encoding="utf-8") as fh:
            cur = fh.read()
        if not is_stub(cur, a["routine"]):
            findings.append(f"DRIFT     {aid}: stub is {len(cur.splitlines())} lines or does not point at {a['routine']}")
        elif a.get("beat") and f"beat={a['beat']}" not in cur:
            findings.append(f"DRIFT     {aid}: stub does not carry beat={a['beat']}")
    if os.path.isdir(task_dir):
        for name in sorted(os.listdir(task_dir)):
            if name.startswith(".") or name in want:
                continue
            if os.path.exists(os.path.join(task_dir, name, "SKILL.md")):
                findings.append(f"UNKNOWN   {name}: scheduled but not in the registry (or disabled there)")
    for line in findings:
        print(line)
    if not findings:
        print("stubs match the registry")
    return 1 if findings else 0


def cmd_crontab(reg: dict, runner: str) -> int:
    root = repo_root()
    tz = (reg.get("_meta") or {}).get("schedule_tz") or "UTC"
    print(f"# generated from {registry_path()} - schedule_tz={tz}; set CRON_TZ or TZ accordingly")
    print(f"CRON_TZ={tz}")
    for a in scheduled(reg):
        r = a["registration"]
        beat = f" beat={a['beat']}" if a.get("beat") else ""
        print(f"{r['cron']} cd {root} && {runner} {a['routine']}{beat}   # {a['id']}")
    return 0


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    s = sub.add_parser("render"); s.add_argument("--task-dir", required=True); s.add_argument("--force", action="store_true")
    s = sub.add_parser("check"); s.add_argument("--task-dir", required=True)
    s = sub.add_parser("crontab"); s.add_argument("--runner", default="<AGENT_RUNNER>",
                                                 help="command that executes a routine file, e.g. your agent CLI")
    a = ap.parse_args(argv)
    reg = load_registry()
    if a.cmd == "list":
        return cmd_list(reg)
    if a.cmd == "render":
        return cmd_render(reg, os.path.expanduser(a.task_dir), a.force)
    if a.cmd == "check":
        return cmd_check(reg, os.path.expanduser(a.task_dir))
    return cmd_crontab(reg, a.runner)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
