"""Disconnect removes EVERY chat's watcher on this computer — decided, not leaked.

⭐⭐ THE OWNER'S DECISION, 2026-09-23. On a computer that serves several chats from
one shared HERMES_HOME, `superresearch-agent disconnect` removes the shared
`sr-stream` job and EVERY `sr-stream-<slug>` job, not only the calling chat's.
That stays. Disconnect is a full teardown of this computer's connection — the
skill, the session and the bridge go — so no other chat's watcher could work
afterwards anyway, and narrowing the sweep would only leave orphaned jobs firing
"Script not found" on every tick.

⛔ WHAT CHANGED IS WHAT IT SAYS. The confirm a person answers before a full
removal now names every chat, in BOTH places it is asked — SKILL.md's routing row
and the router's own question — so somebody running several chats off one
computer hears it before saying yes, and hears it the same way from either door.
"""

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from facade import connect  # noqa: E402

_SR = HERE / "facade" / "skill" / "scripts" / "sr.py"
_spec = importlib.util.spec_from_file_location("sr_disconnect_0923", _SR)
sr = importlib.util.module_from_spec(_spec)
sys.modules["sr_disconnect_0923"] = sr
_spec.loader.exec_module(sr)

SKILL = HERE / "facade" / "skill" / "SKILL.md"


def _jobs(tmp_path, jobs):
    cron = tmp_path / ".hermes" / "cron"
    cron.mkdir(parents=True)
    (cron / "jobs.json").write_text(json.dumps({"jobs": jobs, "updated_at": 1}),
                                    encoding="utf-8")
    return cron / "jobs.json"


def test_disconnect_removes_every_chats_watcher_on_this_computer(tmp_path):
    """EXECUTED, on the real jobs.json shape: two chats' watchers and one job that
    is not ours. Both chats' jobs go; the unrelated job stays.

    ⛔ THE TWO CHAT JOBS ARE IDENTIFIED DIFFERENTLY ON PURPOSE. One carries its
    generated `sr_poll_<slug>.py` shim, the other is identified by its NAME alone.
    A sweep narrowed on either clause — the name or the script — keeps one of them,
    which is exactly the orphan firing "Script not found" the decision exists to
    prevent. With both jobs shaped the same, dropping either clause alone would be
    an equivalent change and nothing here would notice."""
    jobs_file = _jobs(tmp_path, [
        {"name": "memory-dreaming", "script": "dream.py", "enabled": True},
        {"name": "sr-stream-telegram_aaa111", "script": "sr_poll_telegram_aaa111.py"},
        {"name": "sr-stream-whatsapp_bbb222"},
    ])
    assert connect._remove_stream_cron(tmp_path) is True
    left = json.loads(jobs_file.read_text(encoding="utf-8"))["jobs"]
    assert [j["name"] for j in left] == ["memory-dreaming"], left
    # ⛔ AND THE JOB THAT IS NOT OURS IS UNTOUCHED, field for field
    assert left[0] == {"name": "memory-dreaming", "script": "dream.py", "enabled": True}


def test_the_skill_confirm_names_every_chat():
    """⛔ FAILS WITHOUT THE CHANGE. The row said "fully remove skill + bridge?" —
    true of the calling chat and silent about every other chat on the computer."""
    row = next(ln for ln in SKILL.read_text(encoding="utf-8").splitlines()
               if "remove / uninstall / disconnect Super Research entirely" in ln)
    assert "every chat's watcher" in row, row
    assert "from this computer" in row, row


def test_the_routers_confirm_names_every_chat_too():
    """⛔ ONE QUESTION, ONE ANSWER. The router asks the same confirm for "uninstall
    Super Research" through `sr.py do`; if only SKILL.md changed, the two doors
    would disagree about what a full removal takes."""
    argv, lines = sr._nl_resolve("uninstall super research")
    assert argv is None, argv
    said = " ".join(lines)
    assert "every chat’s watcher" in said, said
    assert "from this computer" in said, said
    assert "Sign-out keeps everything installed" in said


def test_the_docstring_records_the_decision_not_an_open_question():
    """The comment that sat on the sweep called it "an owner question … raised
    rather than changed". It is decided now, and the source says so."""
    doc = connect._is_stream_job.__doc__ or ""
    assert "owner decision, 2026-09-23" in doc
    assert "Raised rather than changed" not in doc
    assert "OWNER QUESTION" not in doc
