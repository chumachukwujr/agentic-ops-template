"""Tests for scripts/state_io.py - the enforced single-writer helper (Pattern 8).

Run:  python3 -m pytest scripts/tests -q
Every test runs against a throw-away state dir and registry under tmp_path.
"""
import importlib, json, os, subprocess, sys
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

REGISTRY = {
    "agent_aliases": {
        "intel": ["intel-market", "intel-regulatory"],
        "outreach": ["outreach-am", "outreach-pm"],
        "daily-guard": [],
    },
    "agents": [
        {"id": "intel-market", "history_identity": "intel-market", "history_aliases": ["intel_market", "market-monitor"]},
        {"id": "intel-regulatory", "history_identity": "intel-regulatory"},
        {"id": "daily-guard", "history_identity": "daily-guard"},
    ],
    "state_files": {
        "state/history.jsonl":        {"mode": "append-only", "owner": "all"},
        "state/activity_log.jsonl":   {"mode": "append-only", "owner": "all"},
        "state/agent_messages.jsonl": {"mode": "append-only", "owner": "all"},
        "state/_writes.jsonl":        {"mode": "append-only", "owner": "all"},
        "state/escalations.json":     {"mode": "single-writer", "owner": "daily-guard"},
        "state/market_state.json":    {"mode": "single-writer", "owner": "intel"},
        "state/outreach_tracker.json": {"mode": "single-writer", "owner": "outreach"},
        "state/company_state.md":     {"mode": "single-writer", "owner": "briefing"},
        "state/corpus/**":            {"mode": "single-writer", "owner": "curator"},
        "state/legacy.json":          {"mode": "frozen", "owner": None},
    },
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    state = tmp_path / "state"; state.mkdir()
    reg = tmp_path / "REGISTRY.json"; reg.write_text(json.dumps(REGISTRY))
    monkeypatch.setenv("AGENT_STATE_DIR", str(state))
    monkeypatch.setenv("AGENT_REGISTRY", str(reg))
    import state_io
    importlib.reload(state_io)
    return dict(state=state, reg=reg, m=state_io)


def lines(p):
    return [json.loads(l) for l in open(p) if l.strip()]


# ---------------------------------------------------------------- write / read
def test_owner_write_is_atomic_and_leaves_no_copies(env):
    m, state = env["m"], env["state"]
    m.write_state("market_state.json", {"deals": [1, 2]}, owner="intel")
    assert m.read_state("market_state.json") == {"deals": [1, 2]}
    leftovers = [f for f in os.listdir(state) if ".tmp" in f or "bak" in f]
    assert leftovers == [], "no temp or backup files may remain after a write"


def test_alias_of_owner_may_write(env):
    m = env["m"]
    m.write_state("market_state.json", {"scan": 7}, owner="intel-market")      # alias of intel
    assert m.read_state("market_state.json")["scan"] == 7


def test_non_owner_is_refused(env):
    m = env["m"]
    with pytest.raises(m.OwnershipError):
        m.write_state("market_state.json", {"x": 1}, owner="outreach")


def test_state_prefix_and_case_are_normalised(env):
    m = env["m"]
    m.write_state("state/market_state.json", {"a": 1}, owner="Intel")
    assert m.read_state("market_state.json") == {"a": 1}


def test_append_only_file_refuses_whole_file_write(env):
    m = env["m"]
    with pytest.raises(m.OwnershipError):
        m.write_state("history.jsonl", "anything", owner="daily-guard")


def test_frozen_file_refuses_everyone(env):
    m = env["m"]
    with pytest.raises(m.OwnershipError):
        m.write_state("legacy.json", {}, owner="daily-guard")


def test_unregistered_file_is_refused(env):
    m = env["m"]
    with pytest.raises(m.UnregisteredStateError):
        m.write_state("not_registered.json", {}, owner="daily-guard")


def test_directory_ownership_covers_files_beneath(env):
    m = env["m"]
    p = m.write_state("corpus/batch_01.jsonl", "line\n", owner="curator")
    assert os.path.exists(p)
    with pytest.raises(m.OwnershipError):
        m.write_state("corpus/batch_01.jsonl", "x", owner="intel")


def test_write_records_sidecar_and_lock_lives_apart(env):
    m, state = env["m"], env["state"]
    m.write_state("company_state.md", "# brief\n", owner="briefing")
    w = lines(state / "_writes.jsonl")
    assert w[-1]["file"] == "company_state.md" and w[-1]["agent"] == "briefing" and w[-1]["bytes"] == 8
    assert (state / ".locks" / "company_state.md.lock").exists()
    assert not any(f.endswith(".lock") for f in os.listdir(state))


def test_markdown_is_written_verbatim(env):
    m = env["m"]
    m.write_state("company_state.md", "# brief\n\nline\n", owner="briefing")
    assert m.read_state("company_state.md") == "# brief\n\nline\n"


# ---------------------------------------------------------------- append_event
def test_append_stamps_clock_and_demotes_supplied_timestamp(env):
    m, state = env["m"], env["state"]
    rec = m.append_event("activity_log.jsonl", {"timestamp": "2099-01-01T00:00:00Z", "action": "x"}, agent="intel")
    assert rec["reported_timestamp"] == "2099-01-01T00:00:00Z"
    assert rec["timestamp"] != "2099-01-01T00:00:00Z" and rec["timestamp"].endswith("Z")
    assert rec["agent"] == "intel"
    assert lines(state / "activity_log.jsonl")[0] == rec


def test_append_to_single_writer_file_is_refused(env):
    m = env["m"]
    with pytest.raises(m.OwnershipError):
        m.append_event("market_state.json", {"x": 1}, agent="intel")


# ---------------------------------------------------------------- log_run
def test_log_run_requires_decisions(env):
    m = env["m"]
    with pytest.raises(ValueError):
        m.log_run("intel-market", summary="ran")
    with pytest.raises(ValueError):
        m.log_run("intel-market", summary="ran", decisions=[])


def test_log_run_derives_run_number_across_spellings(env):
    m, state = env["m"], env["state"]
    (state / "history.jsonl").write_text(
        json.dumps({"timestamp": "2026-01-01T00:00:00Z", "agent": "intel_market", "run": 41}) + "\n"
        + json.dumps({"timestamp": "2026-01-02T00:00:00Z", "agent": "market-monitor", "run": "42"}) + "\n"
        + json.dumps({"timestamp": "2026-01-02T00:00:00Z", "agent": "intel-regulatory", "run": 900}) + "\n")
    assert m.next_run("intel-market") == 43          # spellings count, sibling beats do not
    rec = m.log_run("intel-market", summary="scan", decisions=["flat market, no escalation"])
    assert rec["run"] == 43 and rec["agent"] == "intel-market"
    assert m.next_run("intel-market") == 44


def test_log_run_keeps_an_explicit_run(env):
    m = env["m"]
    rec = m.log_run("daily-guard", run=5, decisions=["x"])
    assert rec["run"] == 5


# ---------------------------------------------------------------- bus
def test_send_inbox_ack_roundtrip(env):
    m = env["m"]
    mid = m.send_message("intel", ["outreach", "daily-guard"], "new lead", "details")
    assert [x["id"] for x in m.inbox("outreach-am")] == [mid]        # alias group sees it
    assert [x["id"] for x in m.inbox("daily-guard")] == [mid]
    assert m.inbox("intel") == []
    m.ack_message("outreach", mid, note="filed")
    assert m.inbox("outreach") == [], "an addressee's ack clears it for that addressee"
    assert [x["id"] for x in m.inbox("daily-guard")] == [mid], "but not for the other addressee"
    m.ack_message("human", mid, note="manual backfill")
    assert m.inbox("daily-guard") == [], "a non-addressee ack clears it for everyone"


# ---------------------------------------------------------------- escalations
def test_non_owner_escalation_goes_to_bus_and_owner_folds_it(env):
    m, state = env["m"], env["state"]
    ref = m.raise_escalation("intel", "HIGH", "listing below threshold", "the numbers", run=3)
    assert ref.startswith("msg-")
    assert not (state / "escalations.json").exists(), "a non-owner must not write escalations.json"
    folded = m.fold_escalations("daily-guard")
    assert len(folded) == 1
    e = folded[0]
    assert e["agent"] == "intel" and e["severity"] == "HIGH" and e["run"] == 3 and e["status"] == "OPEN"
    assert e["id"].startswith("ESC-") and e["bus_message"] == ref
    assert m.read_state("escalations.json")[0]["id"] == e["id"]
    assert m.inbox("daily-guard") == [], "folding acks the request"


def test_owner_escalates_directly_with_stable_ids(env):
    m = env["m"]
    a = m.raise_escalation("daily-guard", "MEDIUM", "Daily guard: 2 findings", "f1\nf2", findings=["f1", "f2"])
    b = m.raise_escalation("daily-guard", "MEDIUM", "Daily guard: 2 findings", "again")
    esc = m.read_state("escalations.json")
    assert [e["id"] for e in esc] == [a, b] and a != b and b.endswith("-2")
    assert esc[0]["findings"] == ["f1", "f2"]
    with pytest.raises(ValueError):
        m.raise_escalation("daily-guard", "LOW", "dup", "x", id=a)


def test_fold_by_non_owner_is_refused(env):
    m = env["m"]
    with pytest.raises(m.OwnershipError):
        m.fold_escalations("intel")


# ---------------------------------------------------------------- decisions
NOTE = "---\ntitle: retire the old threshold\nfor_agents: [intel, outreach]\ndelivered: false\n---\n\nBody.\n"


def test_pending_decisions_and_delivery_are_per_agent(env):
    m, state = env["m"], env["state"]
    d = state / "decisions"; d.mkdir()
    (d / "2026-08-20_threshold.md").write_text(NOTE)
    (d / "2026-08-21_everyone.md").write_text("---\nfor_agents: true\n---\nbody\n")
    (d / "2026-08-21_other.md").write_text("---\nfor_agents: [curator]\n---\nbody\n")
    assert [os.path.basename(p) for p in m.pending_decisions("intel")] == ["2026-08-20_threshold.md", "2026-08-21_everyone.md"]
    m.mark_decision_delivered(str(d / "2026-08-20_threshold.md"), "intel")
    text = (d / "2026-08-20_threshold.md").read_text()
    assert "propagated_to: [intel]" in text and "delivered: true" in text and text.endswith("Body.\n")
    assert [os.path.basename(p) for p in m.pending_decisions("intel")] == ["2026-08-21_everyone.md"]
    assert [os.path.basename(p) for p in m.pending_decisions("outreach")] == ["2026-08-20_threshold.md", "2026-08-21_everyone.md"], \
        "delivered: true does not clear it for other agents"


# ---------------------------------------------------------------- CLI
def test_cli_refusal_exits_2(env):
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "state_io.py"), "write", "market_state.json",
                        "--agent", "outreach", "--json", "{}"], capture_output=True, text=True,
                       env={**os.environ, "AGENT_STATE_DIR": str(env["state"]), "AGENT_REGISTRY": str(env["reg"])})
    assert r.returncode == 2 and "REFUSED" in r.stderr


def test_cli_owner_write_and_next_run(env):
    e = {**os.environ, "AGENT_STATE_DIR": str(env["state"]), "AGENT_REGISTRY": str(env["reg"])}
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "state_io.py"), "write", "market_state.json",
                        "--agent", "intel", "--json", '{"scan": 1}'], capture_output=True, text=True, env=e)
    assert r.returncode == 0, r.stderr
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "state_io.py"), "next-run", "--agent", "intel"],
                       capture_output=True, text=True, env=e)
    assert r.stdout.strip() == "1"
