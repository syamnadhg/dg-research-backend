"""The app's telemetry intake must take every research id this machine sends.

⛔⛔ ONE REFUSED FIELD REFUSES THE WHOLE BATCH, AND THE BATCH COMES BACK. The
app's intake answers 400 for a batch holding one field it does not accept, and
`telemetry.flush` puts a refused batch back and resends it on every flush. So an
id this machine sends and the app refuses silences every event from that
computer, chat_ runs and errors included, until the event is 30 days old.

Wave 13 widened the machine's guard to the chat assistant's `agent-` ids and
left the app's intake as it was; the spool-only pins in
`test_incognito_run_id_and_logs_109.py` could not see it. This pin runs the
machine's real emit and flush, with the app's real `project()`
(src/lib/ingest-limits.ts) run under node as the sink.

⭐ It is its own file so the machine's mutation harnesses, which run the spool
pins, do not depend on which web checkout is on disk.
"""
import json
import subprocess

import pytest

import telemetry as tm
from _domshim import NODE
from conftest import web_file

AGENT = "agent-1b6398fe35be4559"   # "agent-" + uuid4().hex[:16], the bridge's shape
CHAT = "chat_1790692602555_1"

JUDGE = """
import { project } from "./ingest-limits.ts";
let body = "";
for await (const chunk of process.stdin) body += chunk;
const r = project(JSON.parse(body));
console.log(JSON.stringify({ ok: r.ok, reason: r.reason ?? null, events: r.events ?? [] }));
"""


@pytest.fixture
def spool(tmp_path, monkeypatch):
    """A real telemetry spool in a scratch home, with the background flush
    stood down so only this test delivers it."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("SR_WORKER_ID", raising=False)
    monkeypatch.setenv("SR_TELEMETRY", "1")
    monkeypatch.setattr(tm, "_install_uuid", lambda: "iuid-test")
    monkeypatch.setattr(tm, "_build", lambda: "0.1.14")
    monkeypatch.setattr(tm, "flush_in_background", lambda *a, **k: None)


@pytest.fixture
def app(tmp_path):
    """The app's intake as a `post(batch) -> bool`, and every verdict it gave."""
    assert NODE, "node runs the app's intake; without it this pin measures nothing"
    limits = web_file("the app's telemetry intake", "src/lib/ingest-limits.ts")
    cat = web_file("the app's telemetry catalogue", "src/lib/telemetry-catalogue.json")
    here = tmp_path / "web"
    here.mkdir()
    src = limits.read_text(encoding="utf-8")
    plain = 'import catalogue from "./telemetry-catalogue.json";'
    assert src.count(plain) == 1, "the intake's catalogue import moved; re-aim this pin"
    # node needs the JSON import attribute that the app's bundler supplies itself.
    (here / "ingest-limits.ts").write_text(
        src.replace(plain, plain[:-1] + ' with { type: "json" };'), encoding="utf-8")
    (here / "telemetry-catalogue.json").write_bytes(cat.read_bytes())
    (here / "judge.mjs").write_text(JUDGE, encoding="utf-8")
    verdicts = []

    def post(batch):
        out = subprocess.run(
            [NODE, "--experimental-strip-types", "--no-warnings", "judge.mjs"],
            cwd=here, input=json.dumps({"v": tm.CATALOGUE_VERSION, "events": batch}),
            capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert out.returncode == 0, out.stderr
        verdicts.append(json.loads(out.stdout.strip().splitlines()[-1]))
        return verdicts[-1]["ok"]  # the route answers 400 when this is false

    post.verdicts = verdicts
    return post


def test_the_apps_intake_takes_every_id_this_machine_sends(spool, app):
    tm.tm_emit(tm.Ev.RUN_STARTED, research_id=AGENT)
    tm.tm_emit(tm.Ev.RUN_STARTED, research_id=CHAT)
    landed = tm.flush(post=app, deadline_sec=60)
    assert app.verdicts and app.verdicts[-1]["ok"], app.verdicts
    sent = [e["d"].get("research_id") for e in app.verdicts[-1]["events"]]
    assert sent == [AGENT, CHAT], app.verdicts
    assert landed == 2
    assert not list(tm.spool_path().parent.glob("pending-*")), "events still owed"
