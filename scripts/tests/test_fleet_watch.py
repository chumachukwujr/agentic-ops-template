"""Tests for scripts/fleet_watch.py - the registry-driven liveness check (Pattern 10)."""
import datetime, importlib, json, os, sys
import pytest

HERE = os.path.dirname(os.path.abspath(__file__)); SCRIPTS = os.path.dirname(HERE); sys.path.insert(0, SCRIPTS)

NOW = datetime.datetime(2026, 8, 22, 12, 0, tzinfo=datetime.timezone.utc)   # Saturday

REG = {
    "_meta": {"schedule_tz": "UTC"},
    "agent_aliases": {"intel": ["intel-market", "intel-research"], "daily-guard": []},
    "agents": [
        {"id": "intel-market", "history_identity": "intel-market", "history_aliases": ["market_monitor"],
         "registration": {"cron": "0 23 * * 1-5", "enabled": True}},
        {"id": "intel-research", "history_identity": "intel-research",
         "registration": {"cron": "0 9 * * 1-5", "enabled": True}},
        {"id": "daily-guard", "history_identity": "daily-guard",
         "registration": {"cron": "15 7 * * *", "enabled": True}},
        {"id": "housekeeping", "history_identity": "housekeeping",
         "registration": {"cron": "30 23 * * 0", "enabled": True}},
        {"id": "retired-task", "history_identity": "retired",
         "registration": {"cron": "0 1 * * *", "enabled": False}},
        {"id": "manual-task", "history_identity": None,
         "registration": {"cron": None, "enabled": True}},
    ],
    "state_files": {
        "state/history.jsonl": {"mode": "append-only", "owner": "all"},
        "state/agent_messages.jsonl": {"mode": "append-only", "owner": "all"},
    },
}


def H(agent, iso, run=1):
    return json.dumps({"timestamp": iso, "agent": agent, "run": run, "decisions": ["x"]}) + "\n"


@pytest.fixture
def env(tmp_path, monkeypatch):
    state = tmp_path / "state"; state.mkdir()
    reg = tmp_path / "REGISTRY.json"; reg.write_text(json.dumps(REG))
    monkeypatch.setenv("AGENT_STATE_DIR", str(state)); monkeypatch.setenv("AGENT_REGISTRY", str(reg))
    (state / "agent_messages.jsonl").write_text("")
    import fleet_watch; importlib.reload(fleet_watch)
    return dict(state=state, m=fleet_watch)


def healthy_history():
    return (H("market_monitor", "2026-08-22T03:10:00Z", 155) + H("intel-research", "2026-08-21T09:05:00Z", 40)
            + H("daily-guard", "2026-08-22T07:20:00Z", 10) + H("housekeeping", "2026-08-16T23:40:00Z", 9))


def test_previous_fires_weekday_evening(env):
    fires = env["m"].previous_fires("0 23 * * 1-5", NOW, n=2, tz="UTC")
    assert [f.isoformat() for f in fires] == ["2026-08-21T23:00:00+00:00", "2026-08-20T23:00:00+00:00"]


def test_previous_fires_respects_timezone(env):
    fires = env["m"].previous_fires("0 23 * * 1-5", NOW, n=1, tz="America/New_York")
    assert fires[0].isoformat() == "2026-08-22T03:00:00+00:00"      # Fri 23:00 ET


def test_sunday_cron_and_dow_7(env):
    assert env["m"].previous_fires("30 23 * * 7", NOW, n=1)[0].isoformat() == "2026-08-16T23:30:00+00:00"


def test_healthy_fleet_is_ok(env):
    m, state = env["m"], env["state"]
    (state / "history.jsonl").write_text(healthy_history())
    out = m.check(now=NOW)
    assert out["ok"], out


def test_one_missed_fire_is_tolerated_two_is_a_finding(env):
    m, state = env["m"], env["state"]
    # market ran Wed night only: missed Thu 23:00 and Fri 23:00 -> finding. research ran Fri 09:00 -> fine.
    (state / "history.jsonl").write_text(healthy_history().replace("2026-08-22T03:10:00Z", "2026-08-19T23:10:00Z"))
    out = m.check(now=NOW)
    ids = [x["agent"] for x in out["missed_runs"]]
    assert ids == ["intel-market"]
    assert out["missed_runs"][0]["last_run"] == "2026-08-19T23:10:00Z"
    # only one miss: ran Thu night, missed Fri -> tolerated
    (state / "history.jsonl").write_text(healthy_history().replace("2026-08-22T03:10:00Z", "2026-08-20T23:10:00Z"))
    assert m.check(now=NOW)["ok"]


def test_sibling_beat_does_not_mask_a_miss(env):
    m, state = env["m"], env["state"]
    (state / "history.jsonl").write_text(healthy_history().replace(H("intel-research", "2026-08-21T09:05:00Z", 40), ""))
    out = m.check(now=NOW)
    assert [x["agent"] for x in out["missed_runs"]] == ["intel-research"]
    assert out["missed_runs"][0]["last_run"] is None


def test_disabled_and_unscheduled_agents_are_skipped(env):
    m, state = env["m"], env["state"]
    (state / "history.jsonl").write_text(healthy_history())
    assert m.check(now=NOW)["ok"]


def test_unacked_message_older_than_stale_hours(env):
    m, state = env["m"], env["state"]
    (state / "history.jsonl").write_text(healthy_history())
    msgs = [
        {"timestamp": "2026-08-19T12:00:00Z", "id": "msg-old", "from": "intel", "to": ["daily-guard", "intel"], "subject": "old"},
        {"timestamp": "2026-08-22T06:00:00Z", "id": "msg-new", "from": "intel", "to": ["daily-guard"], "subject": "new"},
        {"type": "ack", "ack_of": "msg-old", "acked_by": "intel", "acked_at": "2026-08-19T13:00:00Z"},
    ]
    (state / "agent_messages.jsonl").write_text("".join(json.dumps(x) + "\n" for x in msgs))
    out = m.check(now=NOW)
    assert [x["id"] for x in out["unacked_messages"]] == ["msg-old"]
    assert out["unacked_messages"][0]["waiting_on"] == ["daily-guard"]
    assert m.check(now=NOW, stale_hours=200)["ok"]


def test_undelivered_decision_is_grouped_by_canonical_routine(env):
    m, state = env["m"], env["state"]
    (state / "history.jsonl").write_text(healthy_history())
    d = state / "decisions"; d.mkdir()
    (d / "2026-08-18_threshold.md").write_text("---\ndate: 2026-08-18\nfor_agents: [intel]\n---\nbody\n")
    (d / "2026-08-22_fresh.md").write_text("---\ndate: 2026-08-22\nfor_agents: true\n---\nbody\n")
    out = m.check(now=NOW)
    assert out["undelivered_decisions"] == [{"agent": "intel", "notes": ["2026-08-18_threshold.md"]}]


def test_cli_exit_code(env, capsys):
    m, state = env["m"], env["state"]
    (state / "history.jsonl").write_text(healthy_history())
    assert m.main(["--now", NOW.isoformat()]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    (state / "history.jsonl").write_text("")
    assert m.main(["--now", NOW.isoformat()]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and len(out["missed_runs"]) == 4


def test_invalid_schedule_tz_falls_back_to_utc(env, tmp_path, monkeypatch, capsys):
    m, state = env["m"], env["state"]
    reg = dict(REG); reg["_meta"] = {"schedule_tz": "<IANA timezone placeholder>"}
    (tmp_path / "REGISTRY.json").write_text(json.dumps(reg))
    (state / "history.jsonl").write_text(healthy_history())
    out = m.check(now=NOW)
    assert out["ok"], out
    assert "not a valid IANA zone" in capsys.readouterr().err
