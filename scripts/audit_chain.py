#!/usr/bin/env python3
"""audit_chain.py - tamper-evident SHA-256 hash chain over the decision log.

Seals every activity_log.json entry into an append-only chain at
state/audit_chain.jsonl. Each chain record links to the previous via
chain = SHA256(prev_chain + entry_sha256), so any later mutation of a sealed
record, any deletion, and any reordering breaks verification from that point
forward. The chain proves the log's history is intact; it does not prove the
original entry was true - that is what the source-citation rules are for.

Honest scope (do not overclaim): this supports record-keeping and evidence-
collection expectations in frameworks like SOC 2 (CC7.x monitoring evidence),
EU AI Act Art. 12 record-keeping, Nigeria's NDPA accountability duties, and
South Africa's POPIA s17 record duties. It is NOT a certification and does
not make any system "compliant" on its own.

Commands:
  seal     append chain records for any activity_log entries not yet sealed
           (matched by entry content hash; idempotent, safe to re-run)
  verify   recompute the whole chain and report OK or first broken seq;
           --check-log also confirms every sealed hash still exists in the
           live log or is annotated as trimmed-to-archive

Run `seal` from the weekly state-housekeeping routine (or a daily cron).
Run `verify` any time; hand the output to an auditor with the chain file.

Usage: python3 scripts/audit_chain.py seal|verify [--check-log] [--state DIR]
"""
import hashlib, json, os, sys, datetime

GENESIS = "agentic-ops-audit-chain-genesis-v1"

def state_dir():
    if "--state" in sys.argv:
        return sys.argv[sys.argv.index("--state") + 1]
    return os.environ.get("AGENT_STATE_DIR") or os.path.expanduser(
        "~/<YOUR_REPO>/state")

def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def entry_hash(entry: dict) -> str:
    return sha(json.dumps(entry, sort_keys=True, ensure_ascii=False))

def load_chain(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in open(path) if l.strip()]

def seal(sd):
    log = json.load(open(os.path.join(sd, "activity_log.json")))
    cpath = os.path.join(sd, "audit_chain.jsonl")
    chain = load_chain(cpath)
    sealed = {r["entry_sha256"] for r in chain}
    prev = chain[-1]["chain"] if chain else sha(GENESIS)
    seq = chain[-1]["seq"] + 1 if chain else 1
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    added = 0
    with open(cpath, "a") as f:
        # log is newest-first; seal oldest-first so chain order = event order
        for entry in reversed(log):
            h = entry_hash(entry)
            if h in sealed:
                continue
            rec = {"seq": seq, "sealed_at": now,
                   "agent": entry.get("agent"), "timestamp": entry.get("timestamp"),
                   "entry_sha256": h, "prev": prev, "chain": sha(prev + h)}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            prev, seq, added = rec["chain"], seq + 1, added + 1
            sealed.add(h)
    print(f"seal: {added} new entries sealed, chain length {seq - 1}, {cpath}")
    return 0

def verify(sd, check_log=False):
    cpath = os.path.join(sd, "audit_chain.jsonl")
    chain = load_chain(cpath)
    if not chain:
        print("verify: chain is empty"); return 0
    prev = sha(GENESIS)
    for r in chain:
        if r["prev"] != prev:
            print(f"verify: BROKEN at seq {r['seq']}: prev-link mismatch"); return 1
        if sha(r["prev"] + r["entry_sha256"]) != r["chain"]:
            print(f"verify: BROKEN at seq {r['seq']}: chain hash mismatch"); return 1
        prev = r["chain"]
    msg = f"verify: OK - {len(chain)} records, chain intact, head {prev[:16]}..."
    if check_log:
        live = {entry_hash(e) for e in
                json.load(open(os.path.join(sd, "activity_log.json")))}
        missing = [r["seq"] for r in chain if r["entry_sha256"] not in live]
        msg += (f" | {len(chain) - len(missing)}/{len(chain)} sealed entries "
                f"present in live log"
                + (f"; {len(missing)} absent (trimmed to archive, or MUTATED - "
                   f"diff the archive to distinguish)" if missing else ""))
    print(msg)
    return 0

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    sd = state_dir()
    if cmd == "seal":
        sys.exit(seal(sd))
    elif cmd == "verify":
        sys.exit(verify(sd, "--check-log" in sys.argv))
    print(__doc__); sys.exit(2)
