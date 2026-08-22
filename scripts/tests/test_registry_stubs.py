"""Tests for scripts/registry_stubs.py - stubs as a view of the registry (Pattern 9)."""
import importlib, json, os, sys
import pytest

HERE = os.path.dirname(os.path.abspath(__file__)); SCRIPTS = os.path.dirname(HERE); sys.path.insert(0, SCRIPTS)

REG = {
    "_meta": {"schedule_tz": "Europe/London"},
    "agents": [
        {"id": "org-intel-market", "routine": "agents/intel.md", "beat": "market", "history_identity": "intel-market",
         "registration": {"cron": "0 23 * * 1-5", "enabled": True}},
        {"id": "org-intel-regulatory", "routine": "agents/intel.md", "beat": "regulatory", "history_identity": "intel-regulatory",
         "registration": {"cron": "30 0 * * 1-5", "enabled": True}},
        {"id": "org-daily-guard", "routine": "routines/daily-guard.md", "history_identity": "daily-guard",
         "description": "Daily guard + seal",
         "registration": {"cron": "15 7 * * *", "enabled": True}},
        {"id": "org-retired", "routine": "agents/old.md", "history_identity": "old",
         "registration": {"cron": "0 1 * * *", "enabled": False}},
        {"id": "org-manual", "routine": "agents/manual.md", "history_identity": "manual",
         "registration": {"cron": None, "enabled": True}},
    ],
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    reg = tmp_path / "REGISTRY.json"; reg.write_text(json.dumps(REG))
    monkeypatch.setenv("AGENT_REGISTRY", str(reg)); monkeypatch.setenv("AGENT_REPO_ROOT", "/srv/fleet")
    import registry_stubs; importlib.reload(registry_stubs)
    return dict(m=registry_stubs, tasks=tmp_path / "tasks")


def test_render_creates_stubs_for_scheduled_agents_only(env, capsys):
    m, tasks = env["m"], env["tasks"]
    assert m.main(["render", "--task-dir", str(tasks)]) == 0
    assert sorted(os.listdir(tasks)) == ["org-daily-guard", "org-intel-market", "org-intel-regulatory"]
    s = (tasks / "org-intel-market" / "SKILL.md").read_text()
    assert s.startswith("---\nname: org-intel-market\n")
    assert "/srv/fleet/agents/intel.md with beat=market." in s
    assert "state_io.py escalate --agent intel-market --severity CRITICAL" in s
    assert "This is a pointer stub." in s
    assert len(s.strip().splitlines()) <= m.STUB_MAX_LINES
    g = (tasks / "org-daily-guard" / "SKILL.md").read_text()
    assert "description: Daily guard + seal" in g and "beat=" not in g


def test_render_is_idempotent_and_refuses_to_clobber_a_grown_stub(env, capsys):
    m, tasks = env["m"], env["tasks"]
    m.main(["render", "--task-dir", str(tasks)])
    assert m.main(["render", "--task-dir", str(tasks)]) == 0
    out = capsys.readouterr().out
    assert out.count("ok ") == 3 and "created" not in out.splitlines()[-1]
    f = tasks / "org-intel-market" / "SKILL.md"
    grown = "---\nname: org-intel-market\ndescription: x\n---\n" + "\n".join(f"real instruction {i}" for i in range(30))
    f.write_text(grown)
    assert m.main(["render", "--task-dir", str(tasks)]) == 1
    assert "DRIFT" in capsys.readouterr().out
    assert f.read_text() == grown, "a grown file is somebody's edit; render must not overwrite it"
    assert m.main(["render", "--task-dir", str(tasks), "--force"]) == 0
    assert "beat=market" in f.read_text()


def test_check_reports_missing_drift_and_unknown(env, capsys):
    m, tasks = env["m"], env["tasks"]
    m.main(["render", "--task-dir", str(tasks)])
    assert m.main(["check", "--task-dir", str(tasks)]) == 0
    (tasks / "org-intel-regulatory" / "SKILL.md").unlink()
    (tasks / "org-daily-guard" / "SKILL.md").write_text("---\nname: org-daily-guard\n---\nsomething else entirely\n")
    (tasks / "org-rogue").mkdir(); (tasks / "org-rogue" / "SKILL.md").write_text("x")
    assert m.main(["check", "--task-dir", str(tasks)]) == 1
    out = capsys.readouterr().out
    assert "MISSING   org-intel-regulatory" in out
    assert "DRIFT     org-daily-guard" in out
    assert "UNKNOWN   org-rogue" in out


def test_crontab_lists_scheduled_agents_with_tz(env, capsys):
    m = env["m"]
    assert m.main(["crontab", "--runner", "agentctl run"]) == 0
    out = capsys.readouterr().out
    assert "CRON_TZ=Europe/London" in out
    assert "0 23 * * 1-5 cd /srv/fleet && agentctl run agents/intel.md beat=market   # org-intel-market" in out
    assert "org-retired" not in out and "org-manual" not in out
