#!/usr/bin/env python3
"""state_io.py - the one way agents touch shared state (Pattern 8).

Why this exists:
  * When every agent may write every file, nothing locks, so every agent
    copies the whole file before writing "to be safe". The fleet this was
    extracted from had accumulated hundreds of pre-write copies totalling
    over a hundred megabytes, and still lost writes. This module makes the
    ownership map in agents/REGISTRY.json ENFORCED: write_state() refuses a
    caller that is not the registered owner, writes are atomic (temp file in
    the same directory, then rename), and there is no backup path at all.
  * Timestamps typed by a model are wrong often enough to break liveness
    checks (one run was stamped nine hours in the future). append_event()
    stamps the clock itself and demotes anything the caller supplied to
    `reported_timestamp`.
  * Run numbers counted "in the agent's head" drift. log_run() derives the
    next number from the history.

Ownership map: agents/REGISTRY.json -> "state_files" -> {"<path>": {"mode", "owner"}}
  mode "append-only"   -> append_event() by anyone; write_state() refused
  mode "single-writer" -> write_state() by the owner (or one of its aliases
                          from REGISTRY["agent_aliases"]); append_event() refused
  mode "frozen"        -> nobody writes
A key ending in "/**" owns every file beneath that directory.

Escalations: only the registered owner of escalations.json (normally the
daily guard) writes it. Everyone else calls raise_escalation(), which puts a
typed message on the bus (agent_messages.jsonl, addressed to the owner); the
owner calls fold_escalations() each run. The briefing reads both, so nothing
waits on the fold.

Decisions: state/decisions/*.md notes with `for_agents:` and `propagated_to:`
frontmatter. pending_decisions(agent) lists the notes an agent has not yet
seen; mark_decision_delivered() records that it has.

Env overrides (used by tests): AGENT_STATE_DIR, AGENT_REGISTRY.

CLI:
  state_io.py owners
  state_io.py read  <file>
  state_io.py write <file> --agent A (--from-file f.json | --json '{...}')
  state_io.py append <file> --agent A --json '{...}'
  state_io.py log-run --agent A --json '{"summary":..,"decisions":[..]}'
  state_io.py next-run --agent A
  state_io.py send --from A --to B,C --subject S --body T [--type T] [--priority P]
  state_io.py inbox --agent A
  state_io.py ack --agent A --id MSG [--note N] [--disposition D]
  state_io.py escalate --agent A --severity S --title T --detail D [--run N] [--id ESC-...] [--extra '{...}']
  state_io.py fold-escalations --agent <owner>
  state_io.py decisions --agent A
  state_io.py deliver --agent A --note PATH

No dependencies beyond the standard library. Python 3.9+.
"""
from __future__ import annotations
import datetime, fcntl, hashlib, json, os, re, sys, tempfile

__all__ = ["read_state", "write_state", "append_event", "log_run", "next_run", "send_message", "inbox",
           "ack_message", "raise_escalation", "fold_escalations", "pending_decisions",
           "mark_decision_delivered", "owners", "OwnershipError", "UnregisteredStateError"]


class OwnershipError(PermissionError):
    """The caller is not allowed to write this file in this way."""


class UnregisteredStateError(KeyError):
    """The file is not in the registry's state_files map."""


# ----------------------------------------------------------------- locations
def _repo() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def state_dir() -> str:
    return os.path.expanduser(os.environ.get("AGENT_STATE_DIR") or os.path.join(_repo(), "state"))


def registry_path() -> str:
    return os.path.expanduser(os.environ.get("AGENT_REGISTRY") or os.path.join(_repo(), "agents", "REGISTRY.json"))


def decisions_dir() -> str:
    return os.path.join(state_dir(), "decisions")


def now_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm_agent(a) -> str:
    """Identity comparison is case-insensitive and treats '_' and '-' alike."""
    return str(a or "").strip().lower().replace("_", "-")


# ----------------------------------------------------------------- registry
def _registry() -> dict:
    with open(registry_path(), encoding="utf-8") as fh:
        return json.load(fh)


def _canon_name(name: str) -> str:
    """'escalations.json' and 'state/escalations.json' both mean 'escalations.json'."""
    n = name.strip()
    if n.startswith("state/"):
        n = n[len("state/"):]
    return n


def _path(name: str) -> str:
    return os.path.join(state_dir(), _canon_name(name))


def _entry(name: str) -> tuple:
    reg = _registry()
    key = "state/" + _canon_name(name)
    files = reg.get("state_files", {})
    if key in files:
        return key, files[key]
    for k, v in files.items():                      # "state/corpus/**" covers state/corpus/anything
        if k.endswith("/**") and key.startswith(k[:-2]):
            return k, v
    raise UnregisteredStateError(
        f"{key} is not in {registry_path()} state_files - register it (with an owner) before writing")


def _is_owner(agent: str, owner) -> bool:
    if not owner:
        return False
    a, o = _norm_agent(agent), _norm_agent(owner)
    if a == o:
        return True
    for canon, als in _registry().get("agent_aliases", {}).items():
        if _norm_agent(canon) == o and a in {_norm_agent(x) for x in als}:
            return True
    return False


def owners() -> dict:
    return dict(_registry().get("state_files", {}))


# ----------------------------------------------------------------- locking and I/O
class _Lock:
    """Advisory flock. Lock files live in <state>/.locks/<basename>.lock so they never sit
    beside the state files - nothing for rotation or validators to trip over."""

    def __init__(self, path: str):
        d = os.path.join(os.path.dirname(os.path.abspath(path)), ".locks")
        os.makedirs(d, exist_ok=True)
        self.path = os.path.join(d, os.path.basename(path) + ".lock")

    def __enter__(self):
        self.fh = open(self.path, "a+")
        fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        self.fh.close()


def _append_line(path: str, obj: dict) -> None:
    line = json.dumps(obj, ensure_ascii=False)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with _Lock(path):
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())


def _atomic_write(path: str, text: str) -> None:
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    with _Lock(path):
        fd, tmp = tempfile.mkstemp(prefix=".state_io-", suffix=".tmp", dir=d)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


def _iter_jsonl(path: str):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


# ----------------------------------------------------------------- read / write
def read_state(name: str, default=None):
    p = _path(name)
    if not os.path.exists(p):
        return default
    with open(p, encoding="utf-8") as fh:
        if p.endswith(".json"):
            return json.load(fh)
        if p.endswith(".jsonl"):
            return list(_iter_jsonl(p))
        return fh.read()


def write_state(name: str, obj, owner: str) -> str:
    """Whole-file write by the registered owner. Atomic; recorded in _writes.jsonl."""
    key, ent = _entry(name)
    mode = ent.get("mode", "single-writer")
    if mode == "frozen":
        raise OwnershipError(f"{key} is FROZEN - no agent writes it (mode=frozen)")
    if mode == "append-only":
        raise OwnershipError(f"{key} is append-only - use append_event(), never a whole-file write")
    if not _is_owner(owner, ent.get("owner")):
        raise OwnershipError(f"{owner!r} is not the registered owner of {key} (owner={ent.get('owner')!r}); "
                             "send a bus message to the owner instead")
    p = _path(name)
    text = obj if isinstance(obj, str) else json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    _atomic_write(p, text)
    _append_line(os.path.join(state_dir(), "_writes.jsonl"),
                 {"timestamp": now_utc(), "file": _canon_name(name), "agent": owner,
                  "bytes": len(text.encode("utf-8"))})
    return p


def append_event(file: str, obj: dict, agent=None) -> dict:
    """Append one line to an append-only file. The timestamp is the clock's, never the caller's."""
    key, ent = _entry(file)
    if ent.get("mode") != "append-only":
        raise OwnershipError(f"{key} is not an append-only file (mode={ent.get('mode')!r}); "
                             "use write_state() as its owner")
    rec = dict(obj)
    if agent and "agent" not in rec:
        rec["agent"] = agent
    supplied = rec.pop("timestamp", None)
    stamped = {"timestamp": now_utc()}
    if supplied is not None:
        stamped["reported_timestamp"] = supplied
    stamped.update(rec)
    _append_line(_path(file), stamped)
    return stamped


# ----------------------------------------------------------------- run log
def _spellings(agent: str) -> set:
    """The identity plus its registered spelling variants (agents[].history_aliases).
    Not sibling beats: a beat's run counter is its own."""
    a = _norm_agent(agent)
    out = {a}
    try:
        for ent in _registry().get("agents", []):
            ident = _norm_agent(ent.get("history_identity"))
            als = {_norm_agent(x) for x in (ent.get("history_aliases") or [])}
            if a == ident or a in als:
                out |= {ident} | als
    except (OSError, ValueError):
        pass
    return {x for x in out if x}


def _last_numeric_run(agent: str) -> int:
    best = 0
    mine = _spellings(agent)
    for rec in _iter_jsonl(os.path.join(state_dir(), "history.jsonl")):
        if _norm_agent(rec.get("agent")) not in mine:
            continue
        r = rec.get("run")
        if isinstance(r, bool):
            continue
        if isinstance(r, int):
            best = max(best, r)
        elif isinstance(r, str) and r.strip().isdigit():
            best = max(best, int(r.strip()))
    return best


def next_run(agent: str) -> int:
    """The run number log_run() will assign next."""
    return _last_numeric_run(agent) + 1


def log_run(agent: str, **fields) -> dict:
    """One history line per run. `decisions` is mandatory: it is the drift record."""
    decisions = fields.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        raise ValueError("log_run requires a non-empty `decisions` list")
    rec = {"agent": agent}
    if fields.get("run") is None:
        rec["run"] = _last_numeric_run(agent) + 1
    rec.update(fields)
    return append_event("history.jsonl", rec)


# ----------------------------------------------------------------- bus
def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "msg"


def send_message(sender: str, to, subject: str, body: str, priority: str = "normal", type=None, **extra) -> str:
    to_list = [to] if isinstance(to, str) else list(to)
    ts = now_utc()
    digest = hashlib.sha1(f"{sender}|{to_list}|{subject}|{body}|{ts}|{os.getpid()}|{os.urandom(4).hex()}"
                          .encode()).hexdigest()[:6]
    mid = f"msg-{ts[:10]}-{_slug(subject)}-{digest}"
    rec = {"id": mid, "from": sender, "to": to_list, "priority": priority, "subject": subject, "body": body}
    if type:
        rec["type"] = type
    rec.update(extra)
    append_event("agent_messages.jsonl", rec)
    return mid


def _identity_set(agent: str) -> set:
    """The agent itself, its canonical routine name, and every alias of that routine."""
    a = _norm_agent(agent)
    ids = {a}
    for canon, als in _registry().get("agent_aliases", {}).items():
        group = {_norm_agent(canon)} | {_norm_agent(x) for x in als}
        if a in group:
            ids |= group
    return ids


def _to_set(m: dict) -> set:
    to = m.get("to") or []
    return {_norm_agent(x) for x in ([to] if isinstance(to, str) else to)}


def inbox(agent: str) -> list:
    """Messages addressed to this agent (or its alias group) that it has not acked."""
    mine = _identity_set(agent)
    msgs, acks = {}, []
    for rec in _iter_jsonl(os.path.join(state_dir(), "agent_messages.jsonl")):
        if rec.get("type") == "ack":
            if rec.get("ack_of"):
                acks.append(rec)
        elif rec.get("id"):
            msgs[rec["id"]] = rec
    # An ack by an addressee clears the message for that addressee only.
    # An ack by anyone else (a human, a manual backfill) clears it for everyone.
    acked = set()
    for a_rec in acks:
        mid, by = a_rec["ack_of"], _norm_agent(a_rec.get("acked_by"))
        acked.add((mid, by) if by and by in _to_set(msgs.get(mid, {})) else (mid, "*"))
    out = []
    for mid, m in msgs.items():
        if not (mine & _to_set(m)):
            continue
        if (mid, "*") in acked or any((mid, i) in acked for i in mine):
            continue
        out.append(m)
    return out


def ack_message(agent: str, msg_id: str, note: str = "", disposition: str = "DONE") -> dict:
    rec = {"type": "ack", "ack_of": msg_id, "acked_by": agent, "acked_at": now_utc(),
           "disposition": disposition, "note": note}
    return append_event("agent_messages.jsonl", rec)


# ----------------------------------------------------------------- escalations
ESCALATIONS = "escalations.json"
ESC_OWNER_DEFAULT = "daily-guard"
ESC_HUMAN_OWNER = "<OWNER>"        # who must act on an escalation; set to your operator's handle


def _esc_owner() -> str:
    try:
        return _entry(ESCALATIONS)[1].get("owner") or ESC_OWNER_DEFAULT
    except UnregisteredStateError:
        return ESC_OWNER_DEFAULT


def _esc_id(agent: str, title: str, date: str, existing: list) -> str:
    tag = re.sub(r"[^A-Z0-9]", "", str(agent).upper()) or "AGENT"
    base = f"ESC-{date}-{tag}-{_slug(title).upper()[:28].strip('-')}"
    ids = {e.get("id") for e in existing if isinstance(e, dict)}
    cand, n = base, 2
    while cand in ids:
        cand, n = f"{base}-{n}", n + 1
    return cand


def _append_escalation(owner: str, payload: dict) -> dict:
    existing = read_state(ESCALATIONS, default=[])
    if not isinstance(existing, list):
        raise ValueError("escalations.json is not a list")
    ts = payload.get("opened") or now_utc()
    date = ts[:10]
    if payload.get("id") and any(isinstance(e, dict) and e.get("id") == payload["id"] for e in existing):
        raise ValueError(f"escalation id {payload['id']!r} already exists in escalations.json")
    entry = {"id": payload.get("id") or _esc_id(payload.get("agent", owner), payload.get("title", ""), date, existing),
             "date": date, "opened": ts, "agent": payload.get("agent", owner),
             "severity": payload.get("severity", "MEDIUM"), "status": "OPEN", "owner": ESC_HUMAN_OWNER,
             "title": payload.get("title", ""), "detail": payload.get("detail", "")}
    for k, v in payload.items():          # the payload overrides the defaults (owner, status, extra fields)
        if k != "type":
            entry[k] = v
    existing.append(entry)
    write_state(ESCALATIONS, existing, owner=owner)
    return entry


def raise_escalation(agent: str, severity: str, title: str, detail: str, **extra) -> str:
    """The owner appends directly. Anyone else sends a typed bus message the owner folds."""
    owner = _esc_owner()
    payload = {"agent": agent, "severity": severity, "title": title, "detail": detail, "opened": now_utc()}
    payload.update(extra)
    if _is_owner(agent, owner):
        return _append_escalation(agent, payload)["id"]
    return send_message(agent, [owner], f"[{severity}] {title}", detail, priority="high",
                        type="escalation", payload=payload)


def fold_escalations(owner: str) -> list:
    if not _is_owner(owner, _esc_owner()):
        raise OwnershipError(f"{owner!r} is not the escalations owner ({_esc_owner()!r})")
    folded = []
    for m in inbox(owner):
        if m.get("type") != "escalation":
            continue
        payload = dict(m.get("payload") or {})
        payload.setdefault("agent", m.get("from"))
        payload.setdefault("title", m.get("subject"))
        payload.setdefault("detail", m.get("body"))
        entry = _append_escalation(owner, payload)
        entry["bus_message"] = m["id"]
        ack_message(owner, m["id"], note=f"folded into escalations.json as {entry['id']}", disposition="FOLDED")
        folded.append(entry)
    return folded


# ----------------------------------------------------------------- decisions (state/decisions/*.md)
_FM = re.compile(r"^---\n(.*?)\n---\n", re.S)


def _parse_frontmatter(text: str) -> dict:
    m = _FM.match(text)
    out = {}
    if not m:
        return out
    for line in m.group(1).splitlines():
        if ":" not in line or line.startswith((" ", "\t", "-")):
            continue
        k, v = line.split(":", 1)
        v = v.strip()
        if v.lower() in ("true", "false"):
            out[k.strip()] = v.lower() == "true"
        elif v.startswith("[") and v.endswith("]"):
            out[k.strip()] = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
        else:
            out[k.strip()] = v.strip("'\"")
    return out


def pending_decisions(agent: str) -> list:
    """Decision notes targeted at this agent (for_agents: true or a list naming it) that do not
    yet list it in propagated_to. `delivered: true` means SOME agent has seen it; propagated_to
    is the per-agent truth."""
    a = _norm_agent(agent)
    d = decisions_dir()
    out = []
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".md"):
            continue
        p = os.path.join(d, fn)
        with open(p, encoding="utf-8") as fh:
            fm = _parse_frontmatter(fh.read())
        fa = fm.get("for_agents")
        if fa is True:
            targeted = True
        elif isinstance(fa, list):
            targeted = a in {_norm_agent(x) for x in fa}
        else:
            targeted = False
        if not targeted:
            continue
        prop = fm.get("propagated_to") or []
        if isinstance(prop, str):
            prop = [prop]
        if a in {_norm_agent(x) for x in prop}:
            continue
        out.append(p)
    return out


def mark_decision_delivered(path: str, agent: str) -> None:
    """Append `agent` to propagated_to and set delivered: true. Frontmatter only; body untouched."""
    with _Lock(path):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        m = _FM.match(text)
        if not m:
            raise ValueError(f"{path} has no frontmatter")
        new_lines, seen_prop, seen_del = [], False, False
        for line in m.group(1).splitlines():
            if line.startswith("propagated_to:"):
                cur = _parse_frontmatter(f"---\n{line}\n---\n").get("propagated_to") or []
                if isinstance(cur, str):
                    cur = [cur]
                if agent not in cur:
                    cur.append(agent)
                new_lines.append("propagated_to: [" + ", ".join(cur) + "]")
                seen_prop = True
            elif line.startswith("delivered:"):
                new_lines.append("delivered: true")
                seen_del = True
            else:
                new_lines.append(line)
        if not seen_prop:
            new_lines.append(f"propagated_to: [{agent}]")
        if not seen_del:
            new_lines.append("delivered: true")
        new_text = "---\n" + "\n".join(new_lines) + "\n---\n" + text[m.end():]
        d = os.path.dirname(path) or "."
        fd, tmp = tempfile.mkstemp(prefix=".state_io-", suffix=".tmp", dir=d)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(new_text)
        os.replace(tmp, path)


# ----------------------------------------------------------------- CLI
def _main(argv: list) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="state_io.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("owners")
    s = sub.add_parser("read"); s.add_argument("file")
    s = sub.add_parser("write"); s.add_argument("file"); s.add_argument("--agent", required=True)
    s.add_argument("--from-file"); s.add_argument("--json")
    s = sub.add_parser("append"); s.add_argument("file"); s.add_argument("--agent", required=True)
    s.add_argument("--json", required=True)
    s = sub.add_parser("log-run"); s.add_argument("--agent", required=True); s.add_argument("--json", required=True)
    s = sub.add_parser("next-run"); s.add_argument("--agent", required=True)
    s = sub.add_parser("send"); s.add_argument("--from", dest="sender", required=True)
    s.add_argument("--to", required=True); s.add_argument("--subject", required=True)
    s.add_argument("--body", required=True); s.add_argument("--type"); s.add_argument("--priority", default="normal")
    s = sub.add_parser("inbox"); s.add_argument("--agent", required=True)
    s = sub.add_parser("ack"); s.add_argument("--agent", required=True); s.add_argument("--id", required=True)
    s.add_argument("--note", default=""); s.add_argument("--disposition", default="DONE")
    s = sub.add_parser("escalate"); s.add_argument("--agent", required=True)
    s.add_argument("--severity", required=True); s.add_argument("--title", required=True)
    s.add_argument("--detail", required=True); s.add_argument("--run", type=int)
    s.add_argument("--id", dest="esc_id"); s.add_argument("--extra", help="JSON object merged into the escalation")
    s = sub.add_parser("fold-escalations"); s.add_argument("--agent", required=True)
    s = sub.add_parser("decisions"); s.add_argument("--agent", required=True)
    s = sub.add_parser("deliver"); s.add_argument("--agent", required=True); s.add_argument("--note", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "owners":
            for k, v in owners().items():
                print(f"{k:42} {v.get('mode', 'single-writer'):14} {v.get('owner')}")
        elif a.cmd == "read":
            v = read_state(a.file)
            print(v if isinstance(v, str) else json.dumps(v, indent=2, ensure_ascii=False))
        elif a.cmd == "write":
            if a.from_file:
                with open(a.from_file, encoding="utf-8") as fh:
                    raw = fh.read()
                obj = json.loads(raw) if a.file.endswith(".json") else raw
            elif a.json is not None:
                obj = json.loads(a.json) if a.file.endswith(".json") else a.json
            else:
                raise ValueError("write needs --from-file or --json")
            print(write_state(a.file, obj, owner=a.agent))
        elif a.cmd == "append":
            print(json.dumps(append_event(a.file, json.loads(a.json), agent=a.agent), ensure_ascii=False))
        elif a.cmd == "log-run":
            print(json.dumps(log_run(a.agent, **json.loads(a.json)), ensure_ascii=False))
        elif a.cmd == "next-run":
            print(next_run(a.agent))
        elif a.cmd == "send":
            print(send_message(a.sender, [x.strip() for x in a.to.split(",")], a.subject, a.body,
                               priority=a.priority, type=a.type))
        elif a.cmd == "inbox":
            print(json.dumps(inbox(a.agent), indent=2, ensure_ascii=False))
        elif a.cmd == "ack":
            print(json.dumps(ack_message(a.agent, a.id, note=a.note, disposition=a.disposition), ensure_ascii=False))
        elif a.cmd == "escalate":
            extra = json.loads(a.extra) if a.extra else {}
            if a.run is not None:
                extra["run"] = a.run
            if a.esc_id:
                extra["id"] = a.esc_id
            print(raise_escalation(a.agent, a.severity, a.title, a.detail, **extra))
        elif a.cmd == "fold-escalations":
            print(json.dumps(fold_escalations(a.agent), indent=2, ensure_ascii=False))
        elif a.cmd == "decisions":
            for p in pending_decisions(a.agent):
                print(p)
        elif a.cmd == "deliver":
            mark_decision_delivered(a.note, a.agent)
            print("delivered")
        return 0
    except (OwnershipError, UnregisteredStateError, ValueError) as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
