#!/usr/bin/env python3
"""validate_state.py - guard node for the state bus.

Validates the shape and the PLAUSIBILITY of the load-bearing state files.
Born from a production incident: a comma-parsing bug wrote
a platform metric at 9% of its true value, and the value was FRESH,
so no staleness check could catch it. Shape checks catch corruption;
magnitude checks catch confidently-wrong values; monotonic checks catch
counters that went backwards. All three are cheap invariants.

Checks:
  1. JSON parses: activity_log.json, escalations.json, platform_a_state.json,
     platform_b_state.json, outreach_tracker.json, market_state.json.
  2. activity_log entries carry timestamp/agent/action; escalation statuses
     and severities are in-enum.
  3. Dev metrics vs the stored baseline (state/validate_baseline.json):
     - run counts must never decrease (monotonic);
     - test counts must not move more than MAX_DELTA_PCT since last check;
     - test counts must never drop below MIN_FLOOR (a full suite cannot
       shrink to a triple-digit number overnight).
  4. Baseline is updated only for values that PASSED, so a bad value cannot
     poison the next comparison.
  5. Write-back enforcement: unattributable history entries, partial
     write-back (in the bus today but absent from history today), and agents
     silent beyond 3x their own observed cadence.

Exit 0 = clean. Exit 1 = findings printed one per line, prefixed FINDING:.
The state-housekeeping routine runs this weekly and escalates findings; it
is also safe to run ad hoc before quoting any number externally.

Usage: python3 scripts/validate_state.py [--state DIR]
"""
import json, os, sys, datetime

MAX_DELTA_PCT = 25.0
MIN_FLOOR = 1000          # set to a floor your metric genuinely cannot fall below
# The fleet's de facto conventions are looser than the ideal schema (lowercase
# severities and "info" are widespread). Accept those; flag only true anomalies
# so the weekly report stays short enough that the finding that matters is read.
SEVERITIES = {"low", "medium", "high", "critical", "info"}
STATUS_OK = ("open", "open_advisory", "resolved", "superseded", "stale",
             "closed", "merged")

def state_dir():
    if "--state" in sys.argv:
        return sys.argv[sys.argv.index("--state") + 1]
    return os.environ.get("AGENT_STATE_DIR") or os.path.expanduser(
        "~/<YOUR_REPO>/state")

SILENCE_MULTIPLE = 3      # flag when an agent's gap exceeds 3x its own normal
SILENCE_FLOOR_DAYS = 2    # never flag a daily agent for a single missed day

# history.jsonl grew two conventions over time: some agents key their identity
# as "agent", others as "cycle", and a minority timestamp with "ts" or "date".
# Normalise rather than flag 699 entries: the log is the record, and a guard
# that reports a convention split as hundreds of findings trains the reader to
# ignore it. The split is reported once, as a NOTE.
AGENT_KEYS = ("agent", "cycle", "agent_name")
TS_KEYS = ("timestamp", "ts", "date")
ALIASES = {}   # map any alternate names an agent has logged under, e.g.
               # {"market_monitor_v2": "market_monitor"}

def _agent_of(e):
    for k in AGENT_KEYS:
        v = e.get(k)
        if v:
            return ALIASES.get(str(v), str(v))
    return None

def _ts_of(e):
    for k in TS_KEYS:
        if e.get(k):
            return _parse_ts(e[k])
    return None

def _parse_ts(v):
    try:
        d = datetime.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None
    return d.replace(tzinfo=datetime.timezone.utc) if d.tzinfo is None else d

def check_writeback(sd, activity_log):
    """Enforce the write-back step the prompts only request.

    A weaker or hurried model completes an agent's work and silently skips the
    final logging step. The run then looks identical to one that never happened.
    Three derivable checks, no schedule table needed:

      a) history lines with no `agent` field are unattributable
      b) an agent in activity_log today with no history.jsonl line today did a
         PARTIAL write-back (the routine requires both)
      c) an agent silent for more than SILENCE_MULTIPLE times its own observed
         cadence has either stopped running or stopped logging; both need a look

    Cadence is measured over DISTINCT ACTIVE DAYS, not raw intervals, so agents
    that legitimately write several lines per run are not mis-measured.
    """
    import collections
    out = []
    hpath = os.path.join(sd, "history.jsonl")
    if not os.path.exists(hpath):
        return ["FINDING: history.jsonl missing; write-back cannot be verified"]

    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.date()
    days = collections.defaultdict(set)
    unattributed = 0
    by_key = collections.Counter()
    for line in open(hpath):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        d = _ts_of(e)
        agent = _agent_of(e)
        by_key["agent" if e.get("agent") else "cycle" if e.get("cycle") else "none"] += 1
        if not agent:
            if d and (now - d).days <= 14:
                unattributed += 1
            continue
        if d:
            days[agent].add(d.date())

    if by_key["agent"] and by_key["cycle"]:
        out.append(f"NOTE: history.jsonl uses two identity conventions "
                   f"({by_key['agent']} entries key on 'agent', {by_key['cycle']} on "
                   f"'cycle'). Normalised here; worth converging at source so future "
                   f"tooling does not have to special-case it")
    if unattributed:
        out.append(f"FINDING: {unattributed} history.jsonl entries in the last 14 days "
                   f"identify no agent under any known key; those runs cannot be "
                   f"attributed and are invisible to write-back and drift checks")

    # (b) partial write-back: in the bus today, absent from history today
    if isinstance(activity_log, list):
        logged_today = {a for a, ds in days.items() if today in ds}
        bus_today = set()
        for e in activity_log[:60]:
            d = _ts_of(e)
            a = _agent_of(e)
            if d and d.date() == today and a:
                bus_today.add(a)
        # Only scheduled agents owe a history line. An identity that has never
        # written to history.jsonl is an interactive session, not a run, so the
        # check calibrates itself off observed behaviour instead of an
        # exemption list somebody has to remember to update.
        for a in sorted(bus_today - logged_today):
            if a in days:
                out.append(f"FINDING: {a} wrote to activity_log today but has no "
                           f"history.jsonl entry today; write-back is partial "
                           f"(the run log step was skipped)")

    # (c) silence relative to the agent's own cadence
    for agent, dayset in sorted(days.items()):
        ds = sorted(dayset)
        recent = [d for d in ds if (today - d).days <= 14]
        if len(recent) < 3:
            continue                      # too little history to judge
        gaps = [(recent[i] - recent[i - 1]).days for i in range(1, len(recent))]
        med = sorted(gaps)[len(gaps) // 2]
        since = (today - ds[-1]).days
        threshold = max(SILENCE_MULTIPLE * max(med, 1), SILENCE_FLOOR_DAYS)
        if since > threshold:
            out.append(f"FINDING: {agent} last logged {since}d ago against a normal "
                       f"cadence of ~{med}d; it has either stopped running or stopped "
                       f"logging. Check the scheduler before assuming a quiet week")
    return out

def main():
    sd = state_dir()
    findings = []
    docs = {}

    # -- 1. shape: everything parses --------------------------------------
    for name in ("activity_log.json", "escalations.json", "platform_a_state.json",
                 "platform_b_state.json", "outreach_tracker.json", "market_state.json"):
        p = os.path.join(sd, name)
        if not os.path.exists(p):
            findings.append(f"FINDING: {name} missing from {sd}")
            continue
        try:
            docs[name] = json.load(open(p))
        except Exception as e:
            findings.append(f"FINDING: {name} does not parse: {e}")

    # -- 2. required fields / enums ---------------------------------------
    log = docs.get("activity_log.json")
    if isinstance(log, list):
        for i, e in enumerate(log[:50]):   # newest 50 is the live window
            missing = [k for k in ("timestamp", "agent", "action") if k not in e]
            if missing:
                findings.append(f"FINDING: activity_log[{i}] missing {missing} "
                                f"(agent={e.get('agent')!r})")
    esc = docs.get("escalations.json")
    if isinstance(esc, list):
        for e in esc:
            sev = str(e.get("severity", "")).lower()
            if sev and sev not in SEVERITIES:
                findings.append(f"FINDING: escalation {e.get('id')} has "
                                f"unknown severity {e['severity']!r}")
            st = str(e.get("status", "")).lower()
            if st and not st.startswith(STATUS_OK):
                findings.append(f"FINDING: escalation {e.get('id')} has "
                                f"unknown status {e['status']!r}")

    # -- 3. dev metrics: monotonic + magnitude ----------------------------
    bpath = os.path.join(sd, "validate_baseline.json")
    baseline = json.load(open(bpath)) if os.path.exists(bpath) else {}
    new_baseline = dict(baseline)
    for name, key in (("platform_a_state.json", "platform_a"),
                      ("platform_b_state.json", "platform_b")):
        d = docs.get(name)
        if not isinstance(d, dict):
            continue
        s = d.get("dev_state_summary", {})
        tests, runs = s.get("latest_test_count"), s.get("latest_run_count")
        prior = baseline.get(key, {})
        ok = True
        if isinstance(tests, int):
            if tests < MIN_FLOOR:
                findings.append(f"FINDING: {key} test count {tests} is below the "
                                f"{MIN_FLOOR} floor - a full suite cannot be this "
                                f"small; almost certainly a parse/sync failure, "
                                f"not reality")
                ok = False
            pt = prior.get("tests")
            if isinstance(pt, int) and pt > 0:
                delta = abs(tests - pt) / pt * 100
                if delta > MAX_DELTA_PCT:
                    findings.append(f"FINDING: {key} test count moved "
                                    f"{pt} -> {tests} ({delta:.0f}%), over the "
                                    f"{MAX_DELTA_PCT:.0f}% guard; verify against "
                                    f"the change docs before quoting")
                    ok = False
        if isinstance(runs, int):
            pr = prior.get("runs")
            if isinstance(pr, int) and runs < pr:
                findings.append(f"FINDING: {key} run count went backwards "
                                f"{pr} -> {runs}; run counters are monotonic")
                ok = False
        if ok and isinstance(tests, int) and isinstance(runs, int):
            new_baseline[key] = {
                "tests": tests, "runs": runs,
                "checked": datetime.datetime.now(datetime.timezone.utc)
                           .isoformat(timespec="seconds")}

    # -- 4. write-back enforcement -----------------------------------------
    findings.extend(check_writeback(sd, log))

    json.dump(new_baseline, open(bpath, "w"), indent=2)

    real = [f for f in findings if f.startswith("FINDING:")]
    if findings:
        print("\n".join(findings))
    if real:
        print(f"\n{len(real)} finding(s). Baseline updated for passing values only.")
        return 1
    print(f"validate_state: clean ({len(docs)} files checked, "
          f"{len(findings)} informational note(s)). Baseline {bpath}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
