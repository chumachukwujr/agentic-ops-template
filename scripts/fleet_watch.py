#!/usr/bin/env python3
"""fleet_watch.py - per-agent liveness from the registry (Pattern 10, the local half).

Run by the daily guard every morning. Reads:
  agents/REGISTRY.json          cron + enabled + history identity per agent (+ agent_aliases)
  state/history.jsonl           last run per identity (timestamps are clock-stamped by state_io)
  state/agent_messages.jsonl    bus messages and acks
  state/decisions/*.md          for_agents / propagated_to frontmatter

Findings (JSON on stdout; exit 1 if any):
  missed_runs            an enabled, scheduled agent has no run since its 2nd-last expected fire
                         (one missed fire is tolerated - laptops sleep; two is a silence)
  unacked_messages       a bus message unacked by an addressee for longer than --stale-hours
  undelivered_decisions  decision notes not propagated to an agent --stale-hours after their date

What this cannot see: a fleet whose host is asleep or out of credit never runs the guard, so it
never runs this check. That failure class is the external dead-man's switch's job (heartbeat.sh).

Usage: python3 scripts/fleet_watch.py [--now ISO8601] [--grace-hours 3] [--stale-hours 48]
Env overrides: AGENT_STATE_DIR, AGENT_REGISTRY (same as state_io). The cron timezone comes from
REGISTRY["_meta"]["schedule_tz"]; default UTC.
"""
from __future__ import annotations
import argparse, datetime, json, os, sys
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import state_io as sio  # noqa: E402

UTC = datetime.timezone.utc


# ----------------------------------------------------------------- tiny cron
def _field(spec: str, lo: int, hi: int) -> set:
    out = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, step = part.split("/")
            step = int(step)
        if part == "*":
            rng = range(lo, hi + 1)
        elif "-" in part:
            a, b = part.split("-")
            rng = range(int(a), int(b) + 1)
        else:
            rng = range(int(part), int(part) + 1)
        out |= {x for x in rng if (x - lo) % step == 0}
    return out


def _matches(cron: str, t: datetime.datetime) -> bool:
    m, h, dom, mon, dow = cron.split()
    dows = _field(dow, 0, 7)
    if 7 in dows:
        dows.add(0)
    return (t.minute in _field(m, 0, 59) and t.hour in _field(h, 0, 23) and t.day in _field(dom, 1, 31)
            and t.month in _field(mon, 1, 12) and ((t.weekday() + 1) % 7) in dows)


def previous_fires(cron: str, now: datetime.datetime, n: int = 2, tz: str = "UTC", max_days: int = 14) -> list:
    """The last n cron fire times at or before `now`, as UTC datetimes (cron is local time in tz)."""
    local = now.astimezone(ZoneInfo(tz)).replace(second=0, microsecond=0)
    out, t = [], local
    limit = local - datetime.timedelta(days=max_days)
    while t >= limit and len(out) < n:
        if _matches(cron, t):
            out.append(t.astimezone(UTC))
        t -= datetime.timedelta(minutes=1)
    return out


# ----------------------------------------------------------------- helpers
def _parse(ts):
    try:
        d = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except Exception:
        return None


def _last_runs() -> dict:
    last = {}
    for rec in sio._iter_jsonl(os.path.join(sio.state_dir(), "history.jsonl")):
        a, t = sio._norm_agent(rec.get("agent")), _parse(rec.get("timestamp"))
        if a and t and (a not in last or t > last[a][0]):
            last[a] = (t, rec.get("run"))
    return last


# ----------------------------------------------------------------- checks
def check(now=None, grace_hours: float = 3.0, stale_hours: float = 48.0) -> dict:
    now = now or datetime.datetime.now(UTC)
    reg = sio._registry()
    tz = (reg.get("_meta") or {}).get("schedule_tz") or "UTC"
    try:
        ZoneInfo(tz)
    except Exception:  # noqa: BLE001 - an unset or misspelt timezone must not take the watchdog down
        print(f"fleet_watch: schedule_tz {tz!r} is not a valid IANA zone; treating crons as UTC", file=sys.stderr)
        tz = "UTC"
    last = _last_runs()
    grace = datetime.timedelta(hours=grace_hours)

    missed = []
    for a in reg.get("agents", []):
        r = a.get("registration") or {}
        if not r.get("enabled") or not r.get("cron") or not a.get("history_identity"):
            continue
        # strict: this beat's identity and its spelling variants. A sibling beat's run must not mask a miss.
        ids = {sio._norm_agent(a["history_identity"])} | {sio._norm_agent(x) for x in (a.get("history_aliases") or [])}
        runs = [last[i] for i in ids if i in last]
        last_run = max(runs, key=lambda x: x[0]) if runs else None
        fires = previous_fires(r["cron"], now - grace, n=2, tz=tz)
        if len(fires) < 2:
            continue
        if last_run is None or last_run[0] < fires[1]:
            missed.append({"agent": a["id"], "identity": a["history_identity"], "cron": r["cron"],
                           "expected_fires": [f.strftime("%Y-%m-%dT%H:%M:%SZ") for f in fires],
                           "last_run": last_run[0].strftime("%Y-%m-%dT%H:%M:%SZ") if last_run else None,
                           "last_run_number": last_run[1] if last_run else None})

    unacked = []
    msgs, acks = {}, []
    for rec in sio._iter_jsonl(os.path.join(sio.state_dir(), "agent_messages.jsonl")):
        if rec.get("type") == "ack":
            acks.append(rec)
        elif rec.get("id"):
            msgs[rec["id"]] = rec
    acked_pairs = set()
    for ak in acks:
        mid, by = ak.get("ack_of"), sio._norm_agent(ak.get("acked_by"))
        to = sio._to_set(msgs.get(mid, {}))
        acked_pairs.add((mid, by) if by and by in to else (mid, "*"))
    for mid, m in msgs.items():
        t = _parse(m.get("timestamp"))
        if not t:
            continue
        age_h = (now - t).total_seconds() / 3600
        if age_h <= stale_hours or (mid, "*") in acked_pairs:
            continue
        to = m.get("to") or []
        to = [to] if isinstance(to, str) else to
        waiting = [x for x in to if (mid, sio._norm_agent(x)) not in acked_pairs]
        if waiting:
            unacked.append({"id": mid, "from": m.get("from"), "waiting_on": waiting,
                            "subject": m.get("subject"), "age_hours": round(age_h, 1)})

    undelivered = []
    enabled = [a for a in reg.get("agents", []) if (a.get("registration") or {}).get("enabled") and a.get("history_identity")]
    canon_names = []
    for a in enabled:
        # decisions are delivered to the routine's canonical name, not to each beat identity
        ident = sio._norm_agent(a["history_identity"])
        canon = ident
        for c, als in reg.get("agent_aliases", {}).items():
            if ident == sio._norm_agent(c) or ident in {sio._norm_agent(x) for x in als}:
                canon = sio._norm_agent(c)
        if canon not in canon_names:
            canon_names.append(canon)
    if os.path.isdir(sio.decisions_dir()):
        for canon in canon_names:
            old = []
            for p in sio.pending_decisions(canon):
                with open(p, encoding="utf-8") as fh:
                    fm = sio._parse_frontmatter(fh.read())
                d = _parse(str(fm.get("date") or fm.get("last_verified") or os.path.basename(p)[:10]) + "T00:00:00Z")
                if d and (now - d).total_seconds() / 3600 > stale_hours:
                    old.append(os.path.basename(p))
            if old:
                undelivered.append({"agent": canon, "notes": old})

    return {"checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "missed_runs": missed,
            "unacked_messages": unacked, "undelivered_decisions": undelivered,
            "ok": not (missed or unacked or undelivered)}


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--now")
    ap.add_argument("--grace-hours", type=float, default=3.0, help="how late a run may start and still count")
    ap.add_argument("--stale-hours", type=float, default=48.0, help="age at which an unacked message or undelivered note is a finding")
    a = ap.parse_args(argv)
    out = check(now=_parse(a.now) if a.now else None, grace_hours=a.grace_hours, stale_hours=a.stale_hours)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
