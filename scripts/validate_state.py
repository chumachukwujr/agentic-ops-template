#!/usr/bin/env python3
"""validate_state.py - guard node for the state bus.

Validates the shape and the PLAUSIBILITY of the load-bearing state files.
Born from a production incident: a comma-parsing bug wrote
a platform metric at 9% of its true value, and the value was FRESH,
so no staleness check could have caught it. Shape checks catch corruption;
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
     - test counts must never drop below MIN_FLOOR.
  4. Baseline is updated only for values that PASSED, so a bad value cannot
     poison the next comparison.

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
                                f"not development reality")
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

    json.dump(new_baseline, open(bpath, "w"), indent=2)

    if findings:
        print("\n".join(findings))
        print(f"\n{len(findings)} finding(s). Baseline updated for passing values only.")
        return 1
    print(f"validate_state: clean. {len(docs)} files, baseline {bpath}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
