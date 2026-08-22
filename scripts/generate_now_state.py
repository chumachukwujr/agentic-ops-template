#!/usr/bin/env python3
"""generate_now_state.py - the live-numbers note, generated from state (Pattern 11).

Canon holds facts that do not change; this file holds numbers that do. Every number the fleet
quotes about itself comes from here, produced from ground truth, on a schedule (the daily guard
runs it). Nobody hand-edits the output. To change a number, fix the state file it came from.

Rules this file enforces:
  - No hand-written numbers. If a number is not derivable from a state file it does not belong
    in the output.
  - Every section names the file it came from, so a wrong number is traceable in one step.
  - Ground truth beats summary blocks: where a file carries a hand-maintained total AND the
    underlying records are countable, count the records and report any disagreement.

Generic sections: escalations, fleet last-run table (from the registry), agent bus, decision-
capture freshness. Add your own domain metrics in domain_blocks() - that function is the only
place you should need to edit.

Usage:
    python3 scripts/generate_now_state.py            # write state/now/state.md
    python3 scripts/generate_now_state.py --dry-run  # print, do not write
    python3 scripts/generate_now_state.py --check    # exit 1 if the output would change
Env overrides: AGENT_STATE_DIR, AGENT_REGISTRY (same as state_io).
"""
from __future__ import annotations
import argparse, datetime as dt, json, os, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import state_io as sio  # noqa: E402

SEV_RANK = {"CRITICAL": 5, "URGENT": 5, "HIGH": 4, "MEDIUM": 3, "NORMAL": 2, "LOW": 1, "INFO": 0, "NONE": 0}
STALE_RUN_DAYS = 7            # flag an agent whose last run is older than this
CAPTURE_WARN_DAYS, CAPTURE_STALE_DAYS = 7, 14
SESSION_AGENT_MARKERS = ("session", "interactive", "chat")   # activity-log identities that mean "a human session wrote this"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def state_path(name: str) -> Path:
    return Path(sio.state_dir()) / name


def out_path() -> Path:
    return state_path("now") / "state.md"


def load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 - a broken file is reported, not raised
        return {"__error__": f"{type(e).__name__}: {e}"}


def _parse_ts(ts):
    try:
        d = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def _activity_entries() -> list:
    """The bus, in either shape: activity_log.jsonl (append-only) or the older activity_log.json array."""
    if state_path("activity_log.jsonl").exists():
        return list(sio._iter_jsonl(str(state_path("activity_log.jsonl"))))
    arr = load_json(state_path("activity_log.json"))
    return arr if isinstance(arr, list) else []


# ----------------------------------------------------------------- blocks
def escalations_block() -> list:
    raw = load_json(state_path("escalations.json"))
    items = raw if isinstance(raw, list) else []
    open_items = [i for i in items if isinstance(i, dict) and str(i.get("status", "")).upper().startswith("OPEN")]
    sev = Counter(str(i.get("severity") or "NONE").upper() for i in open_items)
    top = max(((SEV_RANK.get(s, 0), s) for s in sev), default=(0, "-"))
    lines = [f"- **Open escalations: {len(open_items)}** (of {len(items)} total)",
             f"- **Highest open severity: {top[1]}**"]
    if sev:
        lines.append("- By severity: " + " / ".join(f"{k} {v}" for k, v in sorted(sev.items(), key=lambda kv: -SEV_RANK.get(kv[0], 0))))
    for i in sorted(open_items, key=lambda x: -SEV_RANK.get(str(x.get("severity") or "NONE").upper(), 0))[:5]:
        lines.append(f"  - `{i.get('id', '?')}` [{str(i.get('severity') or '-').upper()}] {str(i.get('title') or i.get('detail') or '')[:88]}")
    return lines


def _last_runs() -> dict:
    last = {}
    for rec in sio._iter_jsonl(str(state_path("history.jsonl"))):
        a, ts = sio._norm_agent(rec.get("agent")), _parse_ts(rec.get("timestamp"))
        if a and ts and (a not in last or ts > last[a][0]):
            last[a] = (ts, rec)
    return last


def fleet_block() -> list:
    """One row per registered, enabled agent. Last run resolved through the agent's own identity
    and spelling variants first; the routine's alias group only if the agent never logged."""
    last = _last_runs()
    try:
        reg = sio._registry()
    except (OSError, ValueError) as e:
        return [f"- registry unreadable ({e}); {len(last)} identities in history"]
    aliases = reg.get("agent_aliases", {})
    tz = (reg.get("_meta") or {}).get("schedule_tz") or "UTC"
    now = _now()
    rows = [f"| Agent | Schedule ({tz}) | Last run (UTC) | Run # | Age |", "|---|---|---|---|---|"]
    covered, n = set(), 0
    for a in reg.get("agents", []):
        r = a.get("registration") or {}
        if not r.get("enabled"):
            continue
        n += 1
        ident = a.get("history_identity")
        ts, run, age = "never", "-", "-"
        if ident:
            own = {sio._norm_agent(ident)} | {sio._norm_agent(x) for x in (a.get("history_aliases") or [])}
            group = set(own)
            for canon, als in aliases.items():
                g = {sio._norm_agent(canon)} | {sio._norm_agent(x) for x in als}
                if own & g:
                    group |= g
            covered |= group
            cands = [last[i] for i in own if i in last] or [last[i] for i in group if i in last]
            if cands:
                when, rec = max(cands, key=lambda x: x[0])
                ts = when.strftime("%Y-%m-%d %H:%M")
                run = rec.get("run", "-")
                days = max(0, (now - when).days)
                age = f"{days}d" + (" (stale)" if days > STALE_RUN_DAYS else "")
        else:
            ts = "(no history identity)"
        rows.append(f"| {a.get('id')} | {r.get('schedule_human') or r.get('cron') or 'ad hoc'} | {ts} | {run} | {age} |")
    extra = sorted(k for k in last if k not in covered)
    head = [f"**{n} registered, enabled agents.** Source: `agents/REGISTRY.json`; last run from `state/history.jsonl` via each agent's identity group.", ""]
    tail = ["", "Not in the registry but present in history: " + ", ".join(f"`{k}`" for k in extra) + "."] if extra else []
    return head + rows + tail


def bus_block() -> list:
    msgs, acked = {}, set()
    for rec in sio._iter_jsonl(str(state_path("agent_messages.jsonl"))):
        if rec.get("type") == "ack":
            if rec.get("ack_of"):
                acked.add(rec["ack_of"])
        elif rec.get("id"):
            msgs[rec["id"]] = rec
    unacked = [m for mid, m in msgs.items() if mid not in acked]
    lines = [f"- **Unacked bus messages: {len(unacked)}** (of {len(msgs)} total, {len(acked)} acked)"]
    for m in unacked[:5]:
        lines.append(f"  - `{m.get('id', '?')}` {m.get('from', '?')} -> {m.get('to', '?')}: {str(m.get('subject', ''))[:70]}")
    return lines


def capture_block() -> list:
    """How long since a human decision was WRITTEN BACK, by either path: a capture file in
    state/decisions/ or a bus entry from an interactive session. A long silence does not prove
    nothing was decided; it proves the fleet would not know."""
    newest, kind, name = None, None, None
    d = state_path("decisions")
    if d.is_dir():
        for f in d.glob("*.md"):
            ts = dt.datetime.fromtimestamp(f.stat().st_mtime, dt.timezone.utc)
            if newest is None or ts > newest:
                newest, kind, name = ts, "decision capture", f.name
    for rec in _activity_entries():
        ident = str(rec.get("agent", "")).lower()
        if not any(k in ident for k in SESSION_AGENT_MARKERS):
            continue
        ts = _parse_ts(rec.get("timestamp"))
        if ts and (newest is None or ts > newest):
            newest, kind, name = ts, "activity-log session entry", str(rec.get("action", ""))[:70]
    if newest is None:
        return ["- **No session capture found at all.** Decisions made in interactive sessions are not reaching disk."]
    days = max(0, (_now() - newest).days)
    flag = ""
    if days > CAPTURE_STALE_DAYS:
        flag = "  **STALE - assume decisions have been made that canon has not seen.**"
    elif days > CAPTURE_WARN_DAYS:
        flag = "  (over a week)"
    return [f"- Last session capture: **{days}d ago** ({newest:%Y-%m-%d}, {kind}).{flag}", f"  - `{name}`",
            "- This counter measures write-back, not activity. It is the only signal that a decision may exist which canon has not seen."]


def domain_blocks() -> list:
    """Your metrics. Return a list of (heading, lines) tuples. Each line must be derived from a
    state file and say which one. Example shape:

        d = load_json(state_path("market_state.json"))
        return [("Market", [f"- Scans: **{d.get('_scan_number', 0)}** (`state/market_state.json`)"])]
    """
    return []


# ----------------------------------------------------------------- build
def build() -> str:
    now = _now()
    sources = ["agents/REGISTRY.json", "state/escalations.json", "state/history.jsonl",
               "state/agent_messages.jsonl", "state/decisions/", "state/activity_log.jsonl (or .json)"]
    L = ["---", "title: State", "tier: now", f"last_verified: {now:%Y-%m-%d}", "ttl_days: 1",
         "source_of_truth: scripts/generate_now_state.py", "generated: true", "---", "",
         "# State - generated", "", f"**generated_at:** {now:%Y-%m-%dT%H:%M:%SZ}  ",
         "**generator:** `scripts/generate_now_state.py`", "",
         "> **DO NOT HAND-EDIT.** Overwritten on every guard run. To change a number, fix the state file it "
         "came from. This file is the only place any fleet number should be quoted from.", "",
         "**Sources read:**", ""]
    L += [f"- `{s}`" for s in sources]
    for heading, lines in domain_blocks():
        L += ["", f"## {heading}", ""] + list(lines)
    L += ["", "## Escalations", ""] + escalations_block()
    L += ["", "## Fleet - registered agents and last run", ""] + fleet_block()
    L += ["", "## Agent bus", ""] + bus_block()
    L += ["", "## Session-capture freshness", ""] + capture_block()
    L += ["", "---", "", "Canon: `config/canon/` - Rules: `routines/rules/` - Context: `CONTEXT.md`", ""]
    return "\n".join(L)


def _strip_volatile(s: str) -> str:
    return "\n".join(l for l in s.split("\n") if not l.startswith(("**generated_at:", "last_verified:")))


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    text = build()
    out = out_path()
    if a.dry_run:
        print(text)
        return 0
    if a.check:
        cur = out.read_text(encoding="utf-8") if out.exists() else ""
        if _strip_volatile(cur) != _strip_volatile(text):
            print("DRIFT: state/now/state.md is out of date", file=sys.stderr)
            return 1
        print("state/now/state.md current")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    sio._atomic_write(str(out), text)
    print(f"wrote {out} ({len(text.encode()):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
