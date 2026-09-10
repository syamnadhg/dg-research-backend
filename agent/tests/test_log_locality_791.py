"""Where the agent's log lives, where it goes, and the two homes that must not
drift apart (wave 7.9-1, 2026-09-06).

⛔⛔ `agent doctor` TOLD PEOPLE THE OPPOSITE OF WHAT THE PRODUCT DOES. Under the
log row it printed "not sent with a support bundle — this file stays on this
host". The first half is true: the research computer's collector refuses anything
outside its own log root, and that refusal is what the app's consent promise is
gated on. The second half stopped being true the day `--agent-log` shipped
(2026-08-26) — that flag reads THIS EXACT PATH, `config.log_path()`, the identical
call the doctor row makes, and posts its tail to the app.

⛔⛔ AND THE TRUE HALF IS HOW THE FALSE HALF SURVIVED. One sentence, two claims,
joined by a dash; the checked half made the unchecked half sound checked. The
suite pinned only the true clause, so the false one could be deleted or rewritten
with nothing going red — which is exactly why this file adds the guard WITH the
fix rather than leaving the sentence free to drift back.

⛔⛔ THE SECOND HALF OF THIS FILE IS THE FLEET'S TWO HOMES. The agent's log path
is `Path.home()/.super-agent/bridge.log` and reads no variable of its own. The
fleet's own client starts the bridge with the child's stdout/stderr redirected to
`$HERMES_HOME/.super-agent/bridge.log`. Those are the same file today only because
`provision-user-helper.sh` sets HERMES_HOME and HOME to the same literal, nine
lines apart, for two unrelated reasons — and the comment beside the HOME line
records the belief that they are independent. The fleet's OTHER profile, the
systemd unit, sets HERMES_HOME to `/home/u-%i/.hermes` and no HOME at all. Nothing
anywhere asserted the pairing, on either side.

⛔ SPLIT THEM AND THE FAILURE IS SILENT IN THE WORST DIRECTION: `--agent-log`
answers 200 with `sent: false` and "the agent's log on this host was empty",
naming a file that is genuinely empty while the real one fills up elsewhere.
"""

import argparse
import contextlib
import io
import logging
from pathlib import Path
from types import SimpleNamespace


from facade import cli, config


def _doctor(monkeypatch, tmp_path, *, hermes_home=None, home=None):
    path = tmp_path / "bridge.log"
    path.write_bytes(b"x")
    monkeypatch.setattr(cli.config, "log_path", lambda: path)
    monkeypatch.setattr(cli.config, "VERBOSE", False)
    monkeypatch.setattr(cli.requests, "get", lambda *a, **k: SimpleNamespace(status_code=200))
    monkeypatch.setattr(cli, "_bridge_get", lambda p: (200, {"authed": False}))
    monkeypatch.setattr(cli.AccountSession, "load", staticmethod(lambda: None))
    # ⛔⛔ PINNED, NOT INHERITED. A fixture that left this to the environment would
    # pass or fail on whether the developer running it happens to have HERMES_HOME
    # set — the same trap a visibility fixture fell into one wave ago.
    monkeypatch.delenv(config.HERMES_HOME_ENV, raising=False)
    if hermes_home is not None:
        monkeypatch.setenv(config.HERMES_HOME_ENV, str(hermes_home))
    if home is not None:
        monkeypatch.setattr(Path, "home", staticmethod(lambda: Path(home)))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.cmd_doctor(argparse.Namespace())
    return buf.getvalue()


# ── the doctor stops claiming the file stays here ────────────────────────────

def test_doctor_no_longer_says_the_log_stays_on_this_host(monkeypatch, tmp_path):
    """⛔⛔ THE SENTENCE ITSELF. It was true when written and false since
    2026-08-26, on the one screen somebody opens because something has already
    gone wrong."""
    out = _doctor(monkeypatch, tmp_path)
    assert "stays on this host" not in out


def test_doctor_still_says_it_is_not_in_the_bundle(monkeypatch, tmp_path):
    """⛔ THE HALF THAT WAS ALWAYS TRUE STAYS. The archive is built on the research
    computer and cannot reach this file; somebody who sent a bundle and assumed
    this went with it would be waiting on evidence nobody has."""
    out = _doctor(monkeypatch, tmp_path)
    assert "not sent with a support bundle" in out


def test_doctor_says_where_the_bundle_is_built(monkeypatch, tmp_path):
    """⛔ WHY, not just what. "Not in the bundle" and "only if you ask" are
    different claims, and a reader given one fills in the other — wrongly, in both
    directions."""
    out = _doctor(monkeypatch, tmp_path)
    assert "built on the" in out and "research computer" in out


def test_doctor_names_the_flag_that_sends_it(monkeypatch, tmp_path):
    """⛔ THE ACTIONABLE HALF. A person told the file is not in the bundle and
    nothing else concludes it cannot be sent — which is what the old sentence said
    out loud."""
    out = _doctor(monkeypatch, tmp_path)
    assert "--agent-log" in out
    assert "only when you ask" in out


def test_doctor_still_does_not_point_at_the_bare_send_command(monkeypatch, tmp_path):
    """⛔ THE SIBLING RULE SURVIVES THE REPAIR. A guard bans that command's name
    from this block, because the reverse rule — no send refusal may point at
    `doctor` — was written against a sentence that pointed the wrong way. The flag
    is the precise thing and it collides with nothing."""
    out = _doctor(monkeypatch, tmp_path)
    # ⛔⛔ SLICED BY LINE, NOT BY SUBSTRING. The inherited version cut at the
    # first "bridge" — which is inside the log PATH itself (`bridge.log`) on the
    # very first line — so the "block" it searched ended before every sentence it
    # was guarding. It could not have failed. Take the log row and the indented
    # continuation lines that belong to it.
    lines = out.splitlines()
    start = next(i for i, ln in enumerate(lines) if str(tmp_path / "bridge.log") in ln)
    block = []
    for ln in lines[start + 1:]:
        if ln.strip() and not ln.startswith("      "):
            break
        block.append(ln)
    assert block, out
    assert any("--agent-log" in ln for ln in block), block
    assert not any("send-logs" in ln for ln in block), block


# ── the two homes ─────────────────────────────────────────────────────────────

def test_no_hermes_home_is_not_a_split(monkeypatch):
    """The ordinary host. The variable is unset and there is nothing to say."""
    monkeypatch.delenv(config.HERMES_HOME_ENV, raising=False)
    assert config.home_split() is None


def test_an_empty_hermes_home_is_not_a_split(monkeypatch):
    """An exported-but-empty variable is a shell artefact, not a second home."""
    monkeypatch.setenv(config.HERMES_HOME_ENV, "   ")
    assert config.home_split() is None


def test_the_same_directory_is_not_a_split(monkeypatch, tmp_path):
    """⛔ THE FLEET AS IT IS TODAY. Both variables point at one directory, and a
    guard that fired here would fire on every fleet box every day — one people
    learn to scroll past before the day it means something."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setenv(config.HERMES_HOME_ENV, str(tmp_path))
    assert config.home_split() is None


def test_a_trailing_slash_is_not_a_split(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setenv(config.HERMES_HOME_ENV, str(tmp_path) + "/")
    assert config.home_split() is None


def test_a_symlink_to_the_same_directory_is_not_a_split(monkeypatch, tmp_path):
    """⛔ RESOLVED ON BOTH SIDES. The fleet's roots are bind mounts and its HOME is
    written by a shell; comparing the strings would cry wolf on a layout that is
    in fact identical."""
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: real))
    monkeypatch.setenv(config.HERMES_HOME_ENV, str(link))
    assert config.home_split() is None


def test_a_different_directory_IS_a_split(monkeypatch, tmp_path):
    """⛔⛔ THE SYSTEMD LAYOUT. HERMES_HOME is `/home/u-N/.hermes` and HOME is
    `/home/u-N` — one segment apart, and two different files."""
    home = tmp_path / "u-1"
    home.mkdir()
    hermes = home / ".hermes"
    hermes.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv(config.HERMES_HOME_ENV, str(hermes))
    assert config.home_split() == str(hermes)


def test_the_split_reports_what_the_operator_set(monkeypatch, tmp_path):
    """⛔ THE RAW VALUE, not the resolved one — the string somebody can go and look
    at is the one worth printing. A resolved path they never typed sends them
    looking for a line that does not exist in their config."""
    home = tmp_path / "u-1"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv(config.HERMES_HOME_ENV, "/sandbox/.hermes/")
    assert config.home_split() == "/sandbox/.hermes/"


def test_an_unresolvable_home_is_not_reported_as_a_split(monkeypatch, tmp_path):
    """⛔ AN ALARM NOBODY CAN ACT ON IS WORSE THAN THE SILENCE IT BREAKS. A path
    that cannot be resolved cannot be compared, and guessing "split" would put a
    warning in front of somebody with nothing to do about it."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    def _boom(self, *a, **k):
        raise OSError("nope")

    monkeypatch.setattr(Path, "resolve", _boom)
    monkeypatch.setenv(config.HERMES_HOME_ENV, "/somewhere/else")
    assert config.home_split() is None


# ── the consumers, because a helper nobody calls guards nothing ──────────────

def test_the_doctor_is_silent_when_the_homes_are_unset(monkeypatch, tmp_path):
    """The ordinary host: no HERMES_HOME at all."""
    out = _doctor(monkeypatch, tmp_path, hermes_home=None)
    assert "homes" not in out


def test_the_doctor_is_silent_when_the_homes_are_SET_and_agree(monkeypatch, tmp_path):
    """⛔ THE FLEET AS IT IS TODAY, which is the case that must stay quiet — and
    the one the first version of this file never exercised: it passed
    hermes_home=None, which is the variable being ABSENT, a different branch."""
    home = tmp_path / "sandbox"
    home.mkdir()
    out = _doctor(monkeypatch, tmp_path, hermes_home=home, home=home)
    assert "homes" not in out


def test_the_doctor_names_both_homes_when_they_disagree(monkeypatch, tmp_path):
    home = tmp_path / "u-1"
    home.mkdir()
    out = _doctor(monkeypatch, tmp_path, hermes_home="/sandbox/.hermes", home=home)
    assert "/sandbox/.hermes" in out
    assert str(home) in out
    assert "does not reach support" in out


def test_serve_records_the_split_in_the_file_that_gets_sent(monkeypatch, caplog):
    """⛔⛔ INTO THE LOG, NOT ONTO THE SCREEN, and that is the whole design. A
    split home is exactly the condition under which somebody is later told their
    agent log was "empty", and the person reading that sentence is support,
    holding whichever file the handler wrote. The pinned launchers give the bridge
    no StandardOutPath, no StandardOutput and no console, so every print on this
    path goes to /dev/null on the recommended install."""
    monkeypatch.setattr(cli, "_delegate_lifecycle", lambda *a, **k: None)
    monkeypatch.setattr(cli.logsetup, "configure", lambda **k: None)
    monkeypatch.setattr(cli.autostart, "is_installed", lambda: True)
    monkeypatch.setattr(cli.bridge, "serve", lambda: None)
    monkeypatch.setattr(cli.prefs, "get_verbose", lambda: False)
    monkeypatch.setattr(cli.config, "home_split", lambda: "/sandbox/.hermes")
    with caplog.at_level(logging.WARNING, logger="facade.cli"):
        cli.cmd_serve(SimpleNamespace(verbose=False))
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "/sandbox/.hermes" in text
    assert "will not reach support" in text


def test_serve_says_nothing_when_the_homes_agree(monkeypatch, caplog):
    monkeypatch.setattr(cli, "_delegate_lifecycle", lambda *a, **k: None)
    monkeypatch.setattr(cli.logsetup, "configure", lambda **k: None)
    monkeypatch.setattr(cli.autostart, "is_installed", lambda: True)
    monkeypatch.setattr(cli.bridge, "serve", lambda: None)
    monkeypatch.setattr(cli.prefs, "get_verbose", lambda: False)
    monkeypatch.setattr(cli.config, "home_split", lambda: None)
    with caplog.at_level(logging.WARNING, logger="facade.cli"):
        cli.cmd_serve(SimpleNamespace(verbose=False))
    assert not [r for r in caplog.records if "reach support" in r.getMessage()]


def test_the_warning_lands_after_the_file_handler_is_open(monkeypatch):
    """⛔⛔ ORDER IS THE PROPERTY, not the sentence. Logged before
    `logsetup.configure(to_file=True)` the warning goes to a logger with no file
    handler — it would be emitted, look right in a console, and be absent from the
    one file that gets uploaded. A mutant that keeps the message and moves the
    call up is invisible to every other test here."""
    order: list = []
    monkeypatch.setattr(cli, "_delegate_lifecycle", lambda *a, **k: None)
    monkeypatch.setattr(cli.logsetup, "configure",
                        lambda **k: order.append("configure"))
    monkeypatch.setattr(cli.autostart, "is_installed", lambda: True)
    monkeypatch.setattr(cli.bridge, "serve", lambda: None)
    monkeypatch.setattr(cli.prefs, "get_verbose", lambda: False)
    monkeypatch.setattr(cli.config, "home_split",
                        lambda: order.append("split") or "/sandbox/.hermes")
    cli.cmd_serve(SimpleNamespace(verbose=False))
    assert order == ["configure", "split"], order
