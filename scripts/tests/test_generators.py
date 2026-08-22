"""Tests for the GENERATED tier (Pattern 11): generate_now_state.py and generate_resume_prompt.py."""
import datetime, importlib, json, os, sys
import pytest

HERE = os.path.dirname(os.path.abspath(__file__)); SCRIPTS = os.path.dirname(HERE); sys.path.insert(0, SCRIPTS)

REG = {
    "_meta": {"schedule_tz": "UTC"},
    "agent_aliases": {"intel": ["intel-market"]},
    "agents": [
        {"id": "org-intel-market", "history_identity": "intel-market", "history_aliases": ["market_monitor"],
         "registration": {"cron": "0 23 * * 1-5", "schedule_human": "weeknights 23:00", "enabled": True}},
        {"id": "org-daily-guard", "history_identity": "daily-guard",
         "registration": {"cron": "15 7 * * *", "enabled": True}},
        {"id": "org-old", "history_identity": "old", "registration": {"cron": "0 1 * * *", "enabled": False}},
    ],
    "state_files": {
        "state/history.jsonl": {"mode": "append-only", "owner": "all"},
        "state/agent_messages.jsonl": {"mode": "append-only", "owner": "all"},
        "state/now/**": {"mode": "single-writer", "owner": "daily-guard"},
    },
}


def H(agent, iso, run):
    return json.dumps({"timestamp": iso, "agent": agent, "run": run, "decisions": ["x"]}) + "\n"


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "repo"; (root / "config" / "canon").mkdir(parents=True)
    state = root / "state"; state.mkdir()
    reg = root / "REGISTRY.json"; reg.write_text(json.dumps(REG))
    monkeypatch.setenv("AGENT_STATE_DIR", str(state)); monkeypatch.setenv("AGENT_REGISTRY", str(reg))
    monkeypatch.setenv("AGENT_REPO_ROOT", str(root))
    import state_io, generate_now_state, generate_resume_prompt
    for m in (state_io, generate_now_state, generate_resume_prompt):
        importlib.reload(m)
    return dict(root=root, state=state, now=generate_now_state, resume=generate_resume_prompt)


def seed_state(state):
    (state / "history.jsonl").write_text(H("market_monitor", "2026-08-22T03:10:00Z", 155) + H("daily-guard", "2026-08-22T07:20:00Z", 10)
                                         + H("stray-session", "2026-08-01T00:00:00Z", 1))
    (state / "escalations.json").write_text(json.dumps([
        {"id": "ESC-1", "status": "OPEN", "severity": "HIGH", "title": "decide the threshold"},
        {"id": "ESC-2", "status": "open_advisory", "severity": "low", "title": "fyi"},
        {"id": "ESC-3", "status": "RESOLVED", "severity": "CRITICAL", "title": "done"}]))
    (state / "agent_messages.jsonl").write_text(
        json.dumps({"timestamp": "2026-08-20T00:00:00Z", "id": "msg-1", "from": "intel", "to": ["daily-guard"], "subject": "s1"}) + "\n"
        + json.dumps({"timestamp": "2026-08-20T00:00:00Z", "id": "msg-2", "from": "intel", "to": ["daily-guard"], "subject": "s2"}) + "\n"
        + json.dumps({"type": "ack", "ack_of": "msg-2", "acked_by": "daily-guard"}) + "\n")
    (state / "activity_log.jsonl").write_text(
        json.dumps({"timestamp": "2026-08-21T10:00:00Z", "agent": "operator_session", "action": "set the threshold"}) + "\n")


# ---------------------------------------------------------------- now state
def test_now_state_sections_are_derived_from_files(env):
    seed_state(env["state"])
    text = env["now"].build()
    assert "generated: true" in text and "DO NOT HAND-EDIT" in text
    assert "**Open escalations: 2** (of 3 total)" in text and "**Highest open severity: HIGH**" in text
    assert "**2 registered, enabled agents.**" in text
    assert "| org-intel-market | weeknights 23:00 | 2026-08-22 03:10 | 155 |" in text
    assert "org-old" not in text
    assert "Not in the registry but present in history: `stray-session`." in text
    assert "**Unacked bus messages: 1** (of 2 total, 1 acked)" in text
    assert "activity-log session entry" in text and "set the threshold" in text


def test_now_state_write_and_check(env, capsys):
    seed_state(env["state"])
    m, state = env["now"], env["state"]
    assert m.main([]) == 0
    out = state / "now" / "state.md"
    assert out.exists() and "## Fleet" in out.read_text()
    assert m.main(["--check"]) == 0
    (state / "escalations.json").write_text("[]")
    assert m.main(["--check"]) == 1
    assert "DRIFT" in capsys.readouterr().err


def test_now_state_reads_array_bus_when_no_jsonl(env):
    seed_state(env["state"])
    (env["state"] / "activity_log.jsonl").unlink()
    (env["state"] / "activity_log.json").write_text(json.dumps([{"timestamp": "2026-08-10T00:00:00Z", "agent": "chat", "action": "older capture"}]))
    assert "older capture" in env["now"].build()


def test_now_state_no_capture_at_all(env):
    (env["state"] / "history.jsonl").write_text("")
    assert "No session capture found at all" in env["now"].build()


# ---------------------------------------------------------------- resume prompt
CANON = "---\ntitle: Entities\ntier: canon\nlast_verified: {lv}\nttl_days: {ttl}\nowner: operator\n---\n\n# Entities\n\n## 1. Legal names\n\nThe entity list.\n\n## 2. Identifiers\n\nSecret-ish.\n"
AP = "---\nlast_verified: 2026-08-01\nttl_days: 365\n---\n\n# Anti-patterns\n\n1. **Quoting a metric without reconciling\n   it.** Body. **Rule:** reconcile.\n2. **Second one.** Body.\n"


def test_ttl_flag_states(env):
    r = env["resume"]
    today = datetime.date.today()
    fresh = CANON.format(lv=(today - datetime.timedelta(days=5)).isoformat(), ttl=30)
    stale = CANON.format(lv=(today - datetime.timedelta(days=45)).isoformat(), ttl=30)
    assert r.ttl_flag("entities.md", fresh).startswith("entities.md: current")
    assert "**SUSPECT**" in r.ttl_flag("entities.md", stale)
    assert "no TTL frontmatter" in r.ttl_flag("x.md", "# no frontmatter\n")


def test_section_and_anti_pattern_titles(env):
    r = env["resume"]
    t = CANON.format(lv="2026-01-01", ttl=30)
    assert r.section(t, 1) == "## 1. Legal names\n\nThe entity list.\n"
    assert r.section(t, 9) == ""
    assert r.anti_pattern_titles(AP) == ["#1 Quoting a metric without reconciling it", "#2 Second one"]


def test_resume_prompt_composes_and_flags(env, capsys):
    root, state, r = env["root"], env["state"], env["resume"]
    today = datetime.date.today()
    (root / "CONTEXT.md").write_text("# Context\n\nWhat this is.\n")
    (root / "config" / "canon" / "entities.md").write_text(CANON.format(lv=(today - datetime.timedelta(days=90)).isoformat(), ttl=30))
    (root / "config" / "canon" / "anti-patterns.md").write_text(AP)
    seed_state(state)
    assert env["now"].main([]) == 0
    text = r.build()
    assert "- entities.md: **SUSPECT**" in text
    assert "- voice.md: not found" in text
    assert "## A. Operating context (verbatim: CONTEXT.md)\n\n# Context\n\nWhat this is." in text
    assert "## B. entities.md (sections 1)\n\n## 1. Legal names\n\nThe entity list.\n" in text
    assert "Secret-ish" not in text, "only the selected sections are pulled"
    assert "- #1 Quoting a metric without reconciling it" in text
    assert "### Escalations\n- **Open escalations: 2**" in text
    assert r.main([]) == 0
    out = state / "now" / "resume_prompt.md"
    assert out.exists() and r.main(["--check"]) == 0
    (root / "CONTEXT.md").write_text("# Context\n\nChanged.\n")
    assert r.main(["--check"]) == 1


def test_resume_prompt_size_cap(env, monkeypatch):
    root, r = env["root"], env["resume"]
    (root / "CONTEXT.md").write_text("x" * 50_000)
    with pytest.raises(SystemExit):
        r.write()
