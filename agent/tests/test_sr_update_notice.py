"""The once-daily skill-update notice cron script (sr_update_notice.py).

2026-07-06 (user directive): the agent must check once a day and tell the user
when a newer skill version is published. Pins the contract: fresh check via
/version?fresh=1, ONE nudge per new version (silent when current / already
announced), and 3-strike self-removal of its own cron entry when the bridge
is gone (post-disconnect hygiene — no "Script not found" spam).
"""

import importlib.util
import json
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr_update_notice.py"
    spec = importlib.util.spec_from_file_location("sr_update_notice_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _wire(mod, tmp_path, monkeypatch, *, body=None, boom=False):
    """Point state at tmp, fake the bridge /version response."""
    state = tmp_path / ".sr_update_notice.state.json"
    monkeypatch.setattr(mod, "_state_path", lambda: state)

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(body or {}).encode()

    def _open(url, timeout=0):
        assert "fresh=1" in url, "the daily check must be a FRESH PyPI read"
        if boom:
            raise OSError("bridge gone")
        return _Resp()

    monkeypatch.setattr(mod.urllib.request, "urlopen", _open)
    return state


def test_nudges_once_per_new_version(tmp_path, monkeypatch, capsys):
    mod = _load()
    _wire(mod, tmp_path, monkeypatch, body={"agent": "0.1.23", "agentLatest": "0.1.24"})
    assert mod.main() == 0
    out = capsys.readouterr().out
    assert "v0.1.23" in out and "v0.1.24" in out and "update" in out
    # Same version again → silent (announced ledger).
    assert mod.main() == 0
    assert capsys.readouterr().out == ""


def test_newer_version_re_announces(tmp_path, monkeypatch, capsys):
    mod = _load()
    state = _wire(mod, tmp_path, monkeypatch, body={"agent": "0.1.23", "agentLatest": "0.1.25"})
    state.write_text(json.dumps({"announced": "0.1.24"}), "utf-8")
    assert mod.main() == 0
    assert "v0.1.25" in capsys.readouterr().out


def test_silent_when_current_or_garbage(tmp_path, monkeypatch, capsys):
    mod = _load()
    for body in (
        {"agent": "0.1.24", "agentLatest": "0.1.24"},   # current
        {"agent": "0.1.24", "agentLatest": None},        # no publish info
        {"agent": "", "agentLatest": "0.1.25"},          # unknown installed
        {"agent": "0.1.24", "agentLatest": "garbage"},   # unparseable
    ):
        _wire(mod, tmp_path, monkeypatch, body=body)
        assert mod.main() == 0
        assert capsys.readouterr().out == "", body


def test_three_strikes_self_removes_cron_entry(tmp_path, monkeypatch, capsys):
    mod = _load()
    state = _wire(mod, tmp_path, monkeypatch, boom=True)
    # Fake HERMES_HOME with our job + a stranger's job.
    home = tmp_path / "hermes"
    (home / "cron").mkdir(parents=True)
    jobs = {"jobs": [{"name": "sr-update-notice", "script": "sr_update_notice.py"},
                     {"name": "someone-elses-job", "script": "other.py"}]}
    (home / "cron" / "jobs.json").write_text(json.dumps(jobs), "utf-8")
    monkeypatch.setattr(mod, "_hermes_home", lambda: home)

    for i in (1, 2):
        assert mod.main() == 0
        assert capsys.readouterr().out == ""          # always silent
        assert json.loads(state.read_text("utf-8"))["strikes"] == i
        assert len(json.loads((home / "cron" / "jobs.json").read_text("utf-8"))["jobs"]) == 2

    assert mod.main() == 0                             # strike 3 → self-remove
    assert capsys.readouterr().out == ""
    kept = json.loads((home / "cron" / "jobs.json").read_text("utf-8"))["jobs"]
    assert [j["name"] for j in kept] == ["someone-elses-job"]  # only OUR entry dropped
    assert not state.exists()                          # state cleaned too


def test_bridge_recovery_resets_strikes(tmp_path, monkeypatch, capsys):
    mod = _load()
    state = _wire(mod, tmp_path, monkeypatch, boom=True)
    assert mod.main() == 0                             # strike 1
    _wire(mod, tmp_path, monkeypatch, body={"agent": "0.1.24", "agentLatest": ""})
    monkeypatch.setattr(mod, "_state_path", lambda: state)
    assert mod.main() == 0                             # bridge back → reset
    assert json.loads(state.read_text("utf-8"))["strikes"] == 0
    capsys.readouterr()


def test_arm_directive_ships_with_the_stream_arm():
    # The daily job arms via the same do-not-relay block as the streaming
    # watchdog — both branches of _prepare_stream_arm carry its directive.
    sr_path = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts" / "sr.py"
    src = sr_path.read_text(encoding="utf-8")
    assert src.count('script="sr_update_notice.py" name="sr-update-notice"') == 2
    assert 'schedule="every 1d"' in src
