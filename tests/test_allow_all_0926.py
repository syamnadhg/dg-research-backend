"""Wave 12 — "Allow all" on the research computer's command line.

The owner's ask: a PUBLIC research computer can be set to Allow all, so anyone
who asks to use it joins at once with no approval. On this machine that is
`--allow-all yes|no`, plus one step that makes a computer public AND allow-all:
`--visibility public --allow-all`. The grant itself happens on the web server;
what this file pins is that the machine writes, reads and SAYS the setting the
way every other surface does.

⛔⛔ PUBLIC FIRST, THEN THE FLAG. `allowAll` is a separate boolean on the device
document, invisible to every old reader — which also means old WRITERS never
clear it. An installed wheel's `--visibility private`, the published agent and
today's web toggle all write `visibility` alone, so a private computer can carry
a leftover `allowAll: true`. It is harmless only because every reader requires
public first; a machine that read the flag on its own would call a hidden
computer open, and a machine that re-opened a computer without stating the flag
would bring back an instant door nobody asked for this time.

⛔⛔ A NARROWING WRITE CARRIES ONE KEY. The rules are `hasOnly()` lists that refuse
the WHOLE update over one unlisted key, and they are deployed by hand. A close
that also carried `allowAll` would stop working under a lagging ruleset, and the
owner could not make the computer private from the terminal at all.

⛔ BARE `--allow-all` NEVER OPENS THE DOOR. Typing the flag to check where it
stands shows the state; only straight after an explicit `--visibility public`
does it mean yes.

Every test here RUNS the code — `run_visibility` with its collaborators
replaced, or the real `main()` in a child process with a throwaway HOME — and
none of them could pass against the code before this wave: `run_visibility` had
no `allow_all` parameter, printed "You still approve every person yourself." on
every public computer, and the parser had no `--allow-all` at all.
"""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

ON = "Allow all: on — anyone who asks joins at once"
OFF = "Allow all: off — you approve each person"
PRIVATE_OFF = "Allow all is off (this computer is private)"
# ⛔ RE-PINNED 2026-09-27 (wave 12 repair, cross-verify F6/F24): the canonical
# sentence every surface says word for word — the web's checkbox line, the chat's
# confirm, the agent terminal and this screen. It used to stop at "who else is on
# it", but a joiner reads the whole device document, run titles included.
DISCLOSURE = ("They run research on your AI accounts and can see your email, who "
              "else is on it, and what's running on it.")


# ── run_visibility, driven ───────────────────────────────────────────────────

@pytest.fixture
def wired(monkeypatch, capsys):
    """`run_visibility` with its collaborators replaced, and a record of every
    device PATCH it attempted. The same seam `test_visibility_0904` uses."""
    state = {"patches": [], "meta": {}, "device_id": "dev-1", "patch_ok": True}

    monkeypatch.setattr(research, "load_device_id", lambda: state["device_id"])
    monkeypatch.setattr(research, "_fetch_device_meta_rest", lambda: state["meta"])

    def _patch(device_id, fields, *a, **kw):
        state["patches"].append((device_id, dict(fields)))
        return state["patch_ok"]

    monkeypatch.setattr(research, "_pair_patch_device", _patch)
    # ⛔ The empty-read branch asks the real keystore why the read failed; a
    # healthy answer keeps every assertion about the CODE, not the developer's
    # own pairing state.
    monkeypatch.setattr(research, "credential_state_now",
                        lambda *a, **kw: research.CRED_HEALTHY)
    monkeypatch.setattr(research, "_branded_header", lambda *a, **kw: None)
    # The next-actions block would otherwise look for a newer published version.
    monkeypatch.setattr(research, "_newer_version_notice", lambda *a, **kw: None)
    state["out"] = lambda: capsys.readouterr().out
    return state


SHOW = research._VISIBILITY_SHOW
BARE = research._ALLOW_ALL_SHOW


# ── reading it: public first, then a real True ───────────────────────────────

def test_an_allow_all_computer_says_so_on_its_status_screen(wired):
    """⛔⛔ THE OWNER CHECKS HERE AND WAS TOLD THE OPPOSITE. Before this wave the
    public line always ended "You still approve every person yourself." — on a
    computer that lets every signed-in stranger straight in. It fails against the
    old code, which printed that sentence and no allow-all line."""
    wired["meta"] = {"visibility": "public", "allowAll": True}
    assert research.run_visibility(SHOW) == 0
    out = wired["out"]()
    assert ON in out
    assert "Public" in out
    assert "approve every person" not in out
    assert OFF not in out
    assert wired["patches"] == []


def test_a_public_computer_without_it_says_the_owner_approves(wired):
    """The complement: approval mode names itself in the same place, so the two
    states cannot read alike. The old code had no allow-all line at all."""
    wired["meta"] = {"visibility": "public"}
    assert research.run_visibility(SHOW) == 0
    out = wired["out"]()
    assert OFF in out
    assert ON not in out


def test_a_private_computer_shows_no_allow_all_line(wired):
    """Nothing honours the flag while the computer is hidden, so a line about it
    there would describe a door that does not exist — and "you approve each
    person" is not even true of a private computer, where code holders join
    without asking. ⭐ A GUARD, NOT A REGRESSION PIN: the old code passed this
    too (it had no allow-all line anywhere). It is what kills A29, a status
    screen that grew the line on both branches."""
    wired["meta"] = {"visibility": "private"}
    assert research.run_visibility(SHOW) == 0
    out = wired["out"]()
    assert "Private" in out
    assert "Allow all" not in out


def test_a_leftover_tick_on_a_private_computer_reads_OFF():
    """⛔⛔ AN OLD WRITER CLOSED IT AND LEFT THE TICK. Old wheels, the published
    agent and today's web toggle write `visibility` alone, so `private` beside
    `allowAll: true` is a real document. Read without the public gate, it would
    call a hidden computer open. `_allow_all_of` did not exist before this wave."""
    assert research._allow_all_of({"visibility": "private", "allowAll": True}) is False
    assert research._allow_all_of({"allowAll": True}) is False
    assert research._allow_all_of({"visibility": "public", "allowAll": True}) is True


@pytest.mark.parametrize("stored", ["true", "false", "yes", 1, {"on": True}, None])
def test_only_a_real_True_turns_it_on(wired, stored):
    """⛔ THE RULES ONLY CHECK THE TYPE ONCE THEY ARE DEPLOYED, so a document
    written before that can carry the STRING "false" — which is truthy. The
    permissive answer is reachable by exactly one value. Fails against the old
    code, whose public screen had no "Allow all: off" line at all."""
    wired["meta"] = {"visibility": "public", "allowAll": stored}
    assert research.run_visibility(SHOW) == 0
    out = wired["out"]()
    assert OFF in out
    assert ON not in out


def test_the_public_gate_follows_the_NEW_name_and_lets_the_OLD_one_win(wired):
    """⛔⛔ `visibility` IS BEING RENAMED `joinPolicy`. A gate that compared the old
    literal would read every allow-all computer as closed the day the migration
    drops it; and while both are there, the old key wins, exactly as
    `_discovery_of` decides — otherwise the allow-all line and the Public/Private
    line on the same screen would disagree about one computer. Fails against
    the old code, which never printed an "Allow all: on" line."""
    wired["meta"] = {"joinPolicy": "public", "allowAll": True}
    assert research.run_visibility(SHOW) == 0
    assert ON in wired["out"]()

    wired["meta"] = {"visibility": "private", "joinPolicy": "public", "allowAll": True}
    assert research.run_visibility(SHOW) == 0
    out = wired["out"]()
    assert "Private" in out
    assert ON not in out


def test_the_status_screen_names_both_allow_all_commands(wired):
    """The screen someone reads to check is where they learn the switch exists.
    The old next-actions block named only the two --visibility words, so an
    owner looking at a public computer had no way to learn Allow all was there."""
    wired["meta"] = {"visibility": "public"}
    research.run_visibility(SHOW)
    out = wired["out"]()
    assert "--allow-all yes" in out
    assert "--allow-all no" in out


# ── turning it on ────────────────────────────────────────────────────────────

def test_yes_on_a_private_computer_makes_it_public_in_ONE_patch(wired):
    """⛔⛔ THE OWNER: "allow all would by default make it public". Written as
    `allowAll` alone, the computer would stay hidden — nobody could find it to
    ask — while this screen said Allow all is on. One patch carrying both keys
    means there is no moment where it is allow-all but unlisted. The old code
    had no `allow_all` parameter, so this call raised."""
    wired["meta"] = {"visibility": "private"}
    assert research.run_visibility(SHOW, allow_all="yes") == 0
    assert wired["patches"] == [("dev-1", {"visibility": "public", "allowAll": True})]
    out = wired["out"]()
    assert ON in out
    assert "made it public too" in out
    # ⛔ The moment of consent says what a joiner gets.
    assert DISCLOSURE in out
    assert "People you removed stay out." in out


def test_yes_on_a_public_computer_still_carries_visibility(wired):
    """The ON write is one shape everywhere — `{visibility: public, allowAll:
    true}` — the same rule the web and the agent follow. And it does not claim
    to have made public a computer that already was. The old `run_visibility`
    had no `allow_all` parameter, so this call raised."""
    wired["meta"] = {"visibility": "public"}
    assert research.run_visibility(SHOW, allow_all="yes") == 0
    assert wired["patches"] == [("dev-1", {"visibility": "public", "allowAll": True})]
    out = wired["out"]()
    assert ON in out
    assert "made it public too" not in out


def test_the_flag_goes_out_as_a_real_boolean(wired):
    """⛔ `_pair_patch_device` maps a bool to `booleanValue` and anything else to
    a string. The rules admit only a bool, and `hasOnly` refuses the WHOLE
    patch — so a string here would lose the `visibility` change riding with it.
    Before this wave there was no allow-all write to check, and the call raised."""
    wired["meta"] = {"visibility": "private"}
    research.run_visibility(SHOW, allow_all="yes")
    (_id, fields), = wired["patches"]
    assert fields["allowAll"] is True

    wired["patches"].clear()
    wired["meta"] = {"visibility": "public", "allowAll": True}
    research.run_visibility(SHOW, allow_all="no")
    (_id, fields), = wired["patches"]
    assert fields["allowAll"] is False


def test_yes_when_it_is_already_on_writes_nothing(wired):
    """Saying yes to a computer that is already allow-all changes nothing, so it
    writes nothing — no PATCH for a rules deploy to refuse, and the screen says
    so rather than repeating the turn-on disclosure. The old code raised on the
    `allow_all` argument."""
    wired["meta"] = {"visibility": "public", "allowAll": True}
    assert research.run_visibility(SHOW, allow_all="yes") == 0
    assert wired["patches"] == []
    out = wired["out"]()
    assert "Already set" in out
    assert ON in out


def test_visibility_public_then_a_bare_allow_all_is_the_one_step_form(wired):
    """⛔⛔ THE OWNER'S DIRECT FORM: `superresearch --visibility public
    --allow-all`. The fleet runs exactly this once after pairing. Before this
    wave the flag did not exist and `run_visibility` took no `allow_all`."""
    wired["meta"] = {"visibility": "private"}
    assert research.run_visibility("public", allow_all=BARE) == 0
    assert wired["patches"] == [("dev-1", {"visibility": "public", "allowAll": True})]


# ── bare means show ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("meta", [{"visibility": "private"}, {"visibility": "public"}])
def test_a_bare_allow_all_only_SHOWS(wired, meta):
    """⛔⛔ CHECKING MUST NEVER OPEN THE DOOR. If bare meant yes, typing the flag
    to see where it stands would make the computer public and instantly
    joinable by every signed-in stranger. (The old code had no bare form to
    get wrong; this is the pin that kills A7.)"""
    wired["meta"] = dict(meta)
    assert research.run_visibility(SHOW, allow_all=BARE) == 0
    assert wired["patches"] == []
    assert "Already set" not in wired["out"]()


def test_private_then_a_bare_allow_all_never_opens_it(wired):
    """Bare counts as yes only after PUBLIC. After private it is a status
    question, and the close goes out alone — read as yes, it would either open
    the computer the person asked to hide or, with the refusal in `main`, fail
    a close that agreed with itself. The old code raised on `allow_all`."""
    wired["meta"] = {"visibility": "public"}
    assert research.run_visibility("private", allow_all=BARE) == 0
    assert wired["patches"] == [("dev-1", {"visibility": "private"})]


# ── turning it off ───────────────────────────────────────────────────────────

def test_no_writes_only_the_flag_and_the_computer_stays_public(wired):
    """Allow all off is approval again, not hiding: people can still find it and
    ask. And it says the part an owner would otherwise assume — everyone who
    joined while it was on is still a member. The old code had no way to turn
    it off at all (the call raised)."""
    wired["meta"] = {"visibility": "public", "allowAll": True}
    assert research.run_visibility(SHOW, allow_all="no") == 0
    assert wired["patches"] == [("dev-1", {"allowAll": False})]
    out = wired["out"]()
    assert "Public" in out
    assert OFF in out
    assert "keeps access" in out


def test_no_when_it_is_already_off_writes_nothing(wired):
    """`no` on a public computer that is already approval-only changes nothing,
    so it writes nothing — writing `allowAll: false` onto every computer anyone
    ever checked would make a no-op depend on a rules deploy. The old code
    raised on `allow_all`."""
    wired["meta"] = {"visibility": "public"}
    assert research.run_visibility(SHOW, allow_all="no") == 0
    assert wired["patches"] == []
    assert "Already set" in wired["out"]()


def test_no_on_a_private_computer_clears_a_leftover_quietly(wired):
    """⛔ THE ONLY WAY THE OLD TICK COULD COME BACK FROM THIS MACHINE IS REMOVED.
    The clear changes nothing while private, so it is done without ceremony and
    the answer is the plain truth: off, because the computer is private. It
    never touches `visibility` — `no` does not open anything. The old code
    raised on `allow_all`."""
    wired["meta"] = {"visibility": "private", "allowAll": True}
    assert research.run_visibility(SHOW, allow_all="no") == 0
    assert wired["patches"] == [("dev-1", {"allowAll": False})]
    out = wired["out"]()
    assert PRIVATE_OFF in out
    assert "Public" not in out


def test_no_on_a_clean_private_computer_writes_nothing(wired):
    """With no tick to clear there is nothing to write, and the answer is still
    the reason it is off rather than a bare "Already set" that leaves the owner
    wondering whether Allow all is secretly on. The old code raised on
    `allow_all`."""
    wired["meta"] = {"visibility": "private"}
    assert research.run_visibility(SHOW, allow_all="no") == 0
    assert wired["patches"] == []
    assert PRIVATE_OFF in wired["out"]()


# ── closing and re-opening ───────────────────────────────────────────────────

def test_going_private_writes_the_close_ALONE_then_clears_the_tick(wired):
    """⛔⛔ A NARROWING WRITE MUST NEVER DEPEND ON A NEW KEY. The close lands on a
    `hasOnly()` rule deployed by hand; if it carried `allowAll` too, a lagging
    ruleset would refuse the whole close and the owner could not hide the
    computer from the terminal. So: `visibility` alone first, then the tick in a
    second patch. The old code sent only the first."""
    wired["meta"] = {"visibility": "public", "allowAll": True}
    assert research.run_visibility("private") == 0
    assert wired["patches"] == [
        ("dev-1", {"visibility": "private"}),
        ("dev-1", {"allowAll": False}),
    ]
    out = wired["out"]()
    assert "Private" in out
    assert "keeps access" in out


def test_a_close_that_could_not_be_confirmed_sends_nothing_after_it(wired):
    """The tick is cleared only once the close has landed. A second write after
    an unconfirmed first one would be a change the screen never reports.
    ⭐ A GUARD, NOT A REGRESSION PIN: the old code sent one patch and passed
    this too. It is what kills A15, the clear moved above the close."""
    wired["meta"] = {"visibility": "public", "allowAll": True}
    wired["patch_ok"] = False
    assert research.run_visibility("private") == 1
    assert wired["patches"] == [("dev-1", {"visibility": "private"})]
    assert "Could not confirm" in wired["out"]()


def test_a_close_with_no_tick_sends_exactly_one_patch(wired):
    """The second write goes out only for a real `True`; a stored `False` has
    nothing to clear, and a needless second PATCH is one more write a lagging
    ruleset can refuse. ⭐ A GUARD, NOT A REGRESSION PIN: the old code passed
    this too. It is what kills A14, a clear sent on every close."""
    wired["meta"] = {"visibility": "public", "allowAll": False}
    assert research.run_visibility("private") == 0
    assert wired["patches"] == [("dev-1", {"visibility": "private"})]


def test_private_on_an_already_private_computer_still_clears_a_tick(wired):
    """`--visibility private` means Allow all is off afterwards, whatever an old
    writer left behind — quietly, since nothing visible changes. The old code
    saw private == private, said "Already set" and wrote nothing, so the tick
    stayed for the next plain "make it public" to bring back."""
    wired["meta"] = {"visibility": "private", "allowAll": True}
    assert research.run_visibility("private") == 0
    assert wired["patches"] == [("dev-1", {"allowAll": False})]
    assert "Already set" in wired["out"]()


def test_re_opening_a_computer_undoes_an_old_tick_in_the_same_patch(wired):
    """⛔⛔ THE TICK NOBODY ASKED FOR THIS TIME. An old writer closed the computer
    and left `allowAll: true`; a plain `--visibility public` from the old code
    wrote `visibility` alone and the computer came back instantly joinable. Now
    the opener states the flag, in the same patch."""
    wired["meta"] = {"visibility": "private", "allowAll": True}
    assert research.run_visibility("public") == 0
    assert wired["patches"] == [("dev-1", {"visibility": "public", "allowAll": False})]
    out = wired["out"]()
    assert OFF in out
    assert ON not in out


def test_re_opening_a_clean_computer_writes_exactly_what_it_did_before(wired):
    """⛔⛔ THE FIELD IS STATED ONLY WHEN THERE IS A TICK TO UNDO. Every machine
    reaches the rules through `hasOnly()`, deployed by hand; an opener that put
    `allowAll` on every computer would make plain `--visibility public` — which
    never needed the new key — fail whole wherever the rules lag the wheel.
    ⭐ A GUARD, NOT A REGRESSION PIN: the old code wrote exactly this and passed
    too. It is what kills A28, the leftover check widened to every opener."""
    wired["meta"] = {"visibility": "private"}
    assert research.run_visibility("public") == 0
    assert wired["patches"] == [("dev-1", {"visibility": "public"})]
    wired["patches"].clear()
    wired["meta"] = {"visibility": "private", "allowAll": False}
    assert research.run_visibility("public", allow_all="no") == 0
    assert wired["patches"] == [("dev-1", {"visibility": "public"})]


def test_public_on_an_allow_all_computer_leaves_it_alone(wired):
    """A flag-less `--visibility public` on a computer that already is public
    asked for no change; turning Allow all off as a side effect would silently
    shut a door the owner opened on purpose. Fails against the old code, which
    wrote nothing but told the owner "You still approve every person
    yourself." about a computer anyone could join."""
    wired["meta"] = {"visibility": "public", "allowAll": True}
    assert research.run_visibility("public") == 0
    assert wired["patches"] == []
    out = wired["out"]()
    assert ON in out
    assert "Already set" in out


def test_private_outranks_yes_so_a_lost_refusal_still_fails_CLOSED(wired):
    """`main` refuses `--visibility private --allow-all yes` out loud. If that
    refusal were ever lost, this is the difference between closing the door and
    opening it to every signed-in stranger. The old code raised on
    `allow_all`; this is the pin that kills A16."""
    wired["meta"] = {"visibility": "public", "allowAll": True}
    assert research.run_visibility("private", allow_all="yes") == 0
    assert wired["patches"][0] == ("dev-1", {"visibility": "private"})
    assert all(f.get("allowAll") is not True for _i, f in wired["patches"])


def test_a_refused_allow_all_write_claims_nothing(wired):
    """`_pair_patch_device` cannot tell a refusal from a timeout that landed, so
    the failure copy asserts no state — the same honesty `--visibility` has.
    Until the rules admit the key, this is exactly what `--allow-all yes` hits.
    The old code raised on `allow_all`."""
    wired["meta"] = {"visibility": "private"}
    wired["patch_ok"] = False
    assert research.run_visibility(SHOW, allow_all="yes") == 1
    out = wired["out"]()
    assert "Could not confirm" in out
    assert ON not in out
    assert "Public" not in out
    assert len(wired["patches"]) == 1


# ── the empty read ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("value, allow_all", [(SHOW, "yes"), (SHOW, "no"), ("public", BARE)])
def test_an_allow_all_write_on_an_unreadable_computer_changes_nothing_and_says_so(
        wired, value, allow_all):
    """⛔⛔ `--allow-all yes` ARRIVES WITH `value` STILL THE SHOW SENTINEL, so the
    old verdict test (`value != SHOW`) answered the request that opens the door
    as if it were a status question — never saying it was not applied. Exit 1,
    no patch, and neither state claimed."""
    wired["meta"] = {}
    assert research.run_visibility(value, allow_all=allow_all) == 1
    assert wired["patches"] == []
    out = wired["out"]()
    assert "Nothing was changed" in out
    assert "Public" not in out
    assert "Private" not in out


def test_a_bare_allow_all_on_an_unreadable_computer_is_still_a_question(wired):
    """The over-correction: bare is a status question, and nobody who changed
    nothing is owed "nothing was changed". It kills a verdict that fires on the
    raw bare sentinel instead of the resolved value; the old code raised on
    `allow_all`."""
    wired["meta"] = {}
    assert research.run_visibility(SHOW, allow_all=BARE) == 1
    out = wired["out"]()
    assert "Nothing was changed" not in out
    assert "Could not read" in out


# ── the real parser and dispatch, in a child process ─────────────────────────
#
# ⭐ THE REAL `main()`, NOT A COPY OF ITS RULES. A child process imports this
# checkout's research.py, replaces the three collaborators that would reach the
# network or the keystore, and runs `main()` under a throwaway HOME — so the
# word checks, the refusals and the dispatch all run exactly as a person's
# command would, and what was WRITTEN can still be read back.

_DRIVER = """
import json, sys
import research
meta = json.loads(sys.argv[1])
patches = []
def _patch(device_id, fields, *a, **kw):
    patches.append(dict(fields))
    return True
research.load_device_id = lambda: "dev-1"
research._fetch_device_meta_rest = lambda: meta
research._pair_patch_device = _patch
research.credential_state_now = lambda *a, **kw: research.CRED_HEALTHY
research._newer_version_notice = lambda *a, **kw: None
sys.argv = ["research.py", *sys.argv[2:]]
code = 0
try:
    research.main()
except SystemExit as exc:
    code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
print("@@RESULT@@" + json.dumps({"code": code, "patches": patches}))
"""


def _drive(*args, meta, tmp_home):
    env = dict(os.environ, HOME=str(tmp_home), DG_ALERT_AI_COPY="0")
    env.pop("SUPERRESEARCH_STATE_DIR", None)
    r = subprocess.run(
        [sys.executable, "-c", _DRIVER, json.dumps(meta), *args],
        cwd=str(REPO), env=env, capture_output=True, text=True, encoding="utf-8",
        timeout=300,
    )
    tail = [ln for ln in r.stdout.splitlines() if ln.startswith("@@RESULT@@")]
    if not tail:
        # argparse's own exit happens inside main() too, so a missing line means
        # the child died some other way — say so rather than guess.
        raise AssertionError("the child never reported:\n"
                             + r.stdout[-2000:] + r.stderr[-2000:])
    res = json.loads(tail[-1][len("@@RESULT@@"):])
    return res["code"], res["patches"], r.stdout, r.stderr


def test_allow_all_yes_alone_reaches_the_command_and_writes_both_keys(tmp_path):
    """⛔ THE FLAG ON ITS OWN, THROUGH THE REAL PARSER. Before this wave argparse
    did not know `--allow-all` and exited 2 with "unrecognized arguments"."""
    code, patches, _out, err = _drive("--allow-all", "yes",
                                      meta={"visibility": "private"}, tmp_home=tmp_path)
    assert code == 0, err[-2000:]
    assert patches == [{"visibility": "public", "allowAll": True}]


def test_the_one_step_form_through_the_real_parser(tmp_path):
    """`--visibility public --allow-all`: argparse binds the bare flag to its
    sentinel, `main` hands it over untouched, and the command reads it as yes.
    The old parser exited 2 on the unknown flag, so the fleet's one-step setup
    command did nothing at all."""
    code, patches, _out, err = _drive("--visibility", "public", "--allow-all",
                                      meta={"visibility": "private"}, tmp_home=tmp_path)
    assert code == 0, err[-2000:]
    assert patches == [{"visibility": "public", "allowAll": True}]


def test_a_bare_allow_all_through_the_real_parser_writes_nothing(tmp_path):
    """⛔⛔ CHECKING MUST NEVER OPEN THE DOOR — through the real parser, where the
    bare flag arrives as argparse's `const`, not as a value a unit test chose.
    Exit 0, the private computer shown as private, nothing written. The old
    parser exited 2 on the unknown flag."""
    code, patches, out, err = _drive("--allow-all", meta={"visibility": "private"},
                                     tmp_home=tmp_path)
    assert code == 0, err[-2000:]
    assert patches == []
    assert "Private" in out


def test_show_visibility_plus_allow_all_no_is_the_write(tmp_path):
    """`--visibility` bare beside a word for `--allow-all` asks for that change;
    the bare --visibility only means "leave discovery where it is". Read as a
    status question, the owner who typed `no` would be shown the screen and
    anyone would still join at once. The old parser exited 2."""
    code, patches, _out, err = _drive("--visibility", "--allow-all", "no",
                                      meta={"visibility": "public", "allowAll": True},
                                      tmp_home=tmp_path)
    assert code == 0, err[-2000:]
    assert patches == [{"allowAll": False}]


@pytest.mark.parametrize("word", ["maybe", "Yes", "on", "true"])
def test_any_word_but_yes_or_no_is_refused_by_name(tmp_path, word):
    """⛔⛔ EXACTLY yes OR no. The guess that matters here is the one that opens a
    computer to every signed-in stranger, so `Yes`, `on` and `true` are refused
    by name rather than read generously — and nothing is written. The old
    parser also exited 2, but with argparse's "unrecognized arguments", which
    this refuses to accept as the same answer."""
    code, patches, _out, err = _drive("--allow-all", word,
                                      meta={"visibility": "private"}, tmp_home=tmp_path)
    assert code == 2
    assert patches == []
    assert "--allow-all takes yes or no" in err
    assert repr(word) in err
    assert "unrecognized arguments" not in err


def test_a_topic_swallowed_by_the_flag_is_refused_and_pointed_home(tmp_path):
    """⛔ THE SAME ARGPARSE TRAP AS `--visibility`: `nargs="?"` binds the next word
    to the flag, so `--allow-all "my topic"` would eat the topic. It is refused
    with the command that would research it. The old parser's "unrecognized
    arguments" line never quoted the topic, and never named the flag's words."""
    code, patches, _out, err = _drive("--allow-all", "my topic",
                                      meta={"visibility": "private"}, tmp_home=tmp_path)
    assert code == 2
    assert patches == []
    assert "--allow-all takes yes or no" in err
    assert '"my topic"' in err


@pytest.mark.parametrize("topic", ["allow-all", "allowall", "Allow_All", "allow all"])
def test_the_flag_typed_without_its_dashes_is_did_you_mean(tmp_path, topic):
    """⛔ THE OWNER'S SPOKEN FORM. `--visibility public allow-all` parses the last
    word as a TOPIC; the old code announced it as ignored and offered to
    research "allow-all", after making the computer public without the part the
    person actually asked for."""
    code, patches, _out, err = _drive("--visibility", "public", topic,
                                      meta={"visibility": "private"}, tmp_home=tmp_path)
    assert code == 2
    assert patches == []
    assert "did you mean --allow-all?" in err


@pytest.mark.parametrize("word", ["allow-all", "Allow_All", "allowall"])
def test_the_flag_given_as_visibilitys_own_word_is_did_you_mean(tmp_path, word):
    """⛔ THE SAME SPOKEN FORM, BOUND TO THE WRONG FLAG. `--visibility allow-all`
    hands the word to --visibility itself; before this, the refusal offered to
    research "allow-all" as a topic — a wrong way forward for someone who asked
    for a setting. Now it names the flag they meant, and nothing is written."""
    code, patches, _out, err = _drive("--visibility", word,
                                      meta={"visibility": "private"}, tmp_home=tmp_path)
    assert code == 2
    assert patches == []
    assert "did you mean --allow-all?" in err
    assert "--allow-all yes" in err
    assert "To research a topic" not in err


def test_private_plus_yes_is_refused_and_nothing_is_written(tmp_path):
    """⛔⛔ "HIDE IT" AND "LET ANYONE IN" CANNOT BOTH BE DONE, and picking either
    one silently acts on a sentence the person did not finish thinking through.
    Refused out loud, before anything is read or written."""
    code, patches, _out, err = _drive("--visibility", "private", "--allow-all", "yes",
                                      meta={"visibility": "public"}, tmp_home=tmp_path)
    assert code == 2
    assert patches == []
    assert "contradict" in err
    assert "unrecognized arguments" not in err


@pytest.mark.parametrize("extra", [["no"], []])
def test_private_beside_no_or_a_bare_flag_is_not_a_contradiction(tmp_path, extra):
    """The over-correction: only `yes` contradicts `private`. `no` and a bare
    flag agree with it, so they close the computer as asked. The old parser
    exited 2 on the unknown flag and closed nothing."""
    code, patches, _out, err = _drive("--visibility", "private", "--allow-all", *extra,
                                      meta={"visibility": "public"}, tmp_home=tmp_path)
    assert code == 0, err[-2000:]
    assert patches == [{"visibility": "private"}]


# ── the surfaces a user reads ────────────────────────────────────────────────

def test_the_help_screen_has_an_allow_all_row_and_approval_is_conditional(
        monkeypatch, capsys):
    """⛔ `add_help=False`: `run_commands_help` is the ONLY place a flag can be
    found. The old --visibility row ended "You still approve everyone", which
    is false once Allow all is on, and there was no row for the new flag."""
    monkeypatch.setattr(research, "_branded_header", lambda *a, **kw: None)
    research.run_commands_help()
    out = capsys.readouterr().out
    rows = [ln for ln in out.splitlines() if "--allow-all [yes|no]" in ln]
    assert len(rows) == 1, out
    assert "joins at once" in rows[0]
    assert "makes it public" in rows[0]
    vis = [ln for ln in out.splitlines() if "--visibility [public|private]" in ln]
    assert len(vis) == 1
    assert "unless --allow-all is on" in vis[0]
    assert "You still approve everyone" not in out


_HELP_DUMP = """
import argparse, json, sys
import research
def _dump(self, *a, **kw):
    print("@@HELP@@" + json.dumps({x.dest: x.help for x in self._actions
                                   if x.dest in ("visibility", "allow_all")}))
    raise SystemExit(0)
argparse.ArgumentParser.parse_args = _dump
sys.argv = ["research.py"]
research.main()
"""


def test_the_parser_help_strings_say_the_same_thing(tmp_path):
    """Users never see these (`add_help=False`), but they are the parser's own
    account of the flags and they stay true. Read from the REAL parser `main()`
    builds, in a child process."""
    env = dict(os.environ, HOME=str(tmp_path), DG_ALERT_AI_COPY="0")
    env.pop("SUPERRESEARCH_STATE_DIR", None)
    r = subprocess.run([sys.executable, "-c", _HELP_DUMP], cwd=str(REPO), env=env,
                       capture_output=True, text=True, encoding="utf-8", timeout=300)
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("@@HELP@@")]
    assert line, r.stdout[-2000:] + r.stderr[-2000:]
    helps = json.loads(line[-1][len("@@HELP@@"):])
    assert "unless --allow-all is on" in helps["visibility"]
    assert "joins this computer at once" in helps["allow_all"]
    assert "made public too" in helps["allow_all"]
    assert "Bare --allow-all prints the current setting" in helps["allow_all"]


# ── pairing is untouched ─────────────────────────────────────────────────────

class _Stop(Exception):
    pass


def test_pairing_never_asks_about_or_writes_allow_all(monkeypatch, capsys):
    """⛔⛔ AN UNATTENDED PAIR NEVER OPENS AN INSTANT DOOR, and the pairing patch
    keeps exactly its two keys. It lands on a `hasOnly()` rule: had `allowAll`
    joined it, a rules deploy lagging the wheel would refuse the whole patch and
    lose BOTH the On Startup and the discoverability answers, with the person
    told they were saved. Driven for real up to that one write — the pair
    stages run with a yes to every question, and the write is caught.
    ⭐ A GUARD, NOT A REGRESSION PIN: pairing did not change, so the old code
    passed this too. It is what kills P1."""
    asked = []

    async def _yes(question, *a, **kw):
        asked.append(question)
        return True

    written = []

    def _patch(device_id, fields, *a, **kw):
        written.append(dict(fields))
        raise _Stop

    monkeypatch.setattr(research, "_ask_yes_no", _yes)
    monkeypatch.setattr(research, "_pair_patch_device", _patch)
    monkeypatch.setattr(research.tm, "tm_emit", lambda *a, **kw: None)
    with pytest.raises(_Stop):
        asyncio.run(research._continue_pair_stages_2_to_6(
            "profile", linked_uid="u", linked_email="e@example.com",
            initial_paired_uid=None, token="t", device_id_for_progress="dev-1"))
    assert written == [{"supervised": True, "visibility": "public"}]
    screen = capsys.readouterr().out.lower()
    assert "allow all" not in screen and "allow-all" not in screen
    assert not any("allow" in q.lower() or "join" in q.lower() for q in asked), asked


# ── wave 12 repair 4 (cross-verify K1): an old tick is cleared ALONE first ───
# ⛔⛔ THE RULES NOW REFUSE A WRITE THAT MAKES A NON-PUBLIC COMPUTER PUBLIC WHILE A
# STORED `allowAll: true` IS LEFT OUT OF IT. That is what stops an old wheel, the
# published agent or an old web tab — they write `visibility` alone — from
# bringing a leftover tick back as an instant door. But `allowAll` true→true is
# not a change the rules can see either, so this machine's own ON patch would be
# refused on exactly the computer that carries a tick. The machine clears it with
# `{allowAll: false}` alone first, then writes the ON patch — there and only
# there. Every other request makes exactly the writes it made before, key order
# included (the order is the update mask's order on the wire).
#
# Executed against the code before this repair: the three K1 rows wrote the ON
# patch alone (the rules would refuse it); every other row was already this.

_CLEAR = [("allowAll", False)]
_ON = [("visibility", "public"), ("allowAll", True)]
_PUB = [("visibility", "public")]
_PUB_CLEAR = [("visibility", "public"), ("allowAll", False)]
_PRIV = [("visibility", "private")]

# The stored documents, grouped by what the writer reads off them: discovery (by
# `_discovery_of`, either name), and whether `allowAll` is EXACTLY True.
_PRIVATE_CLEAN = [{"visibility": "private"}, {"visibility": "private", "allowAll": False},
                  {"visibility": "private", "allowAll": "true"}]
_PRIVATE_TICKED = [{"visibility": "private", "allowAll": True},
                   {"joinPolicy": "private", "allowAll": True},
                   {"allowAll": True, "name": "No discovery key"},
                   {"visibility": "private", "joinPolicy": "public", "allowAll": True}]
_PUBLIC_CLEAN = [{"visibility": "public"}, {"visibility": "public", "allowAll": False}]
_PUBLIC_ON = [{"visibility": "public", "allowAll": True},
              {"joinPolicy": "public", "allowAll": True}]

# Every request `main` can hand over: (--visibility word, --allow-all word).
_REQUESTS = [("public", None), ("private", None), (SHOW, "yes"), (SHOW, "no"),
             (SHOW, BARE), ("public", BARE), ("private", BARE), ("public", "yes"),
             ("public", "no"), ("private", "no"), ("private", "yes"), (SHOW, None)]

# What each group writes for each request, in order. The K1 cells are marked.
_K1 = [_CLEAR, _ON]
_WRITES = {
    "private-clean": [[_PUB], [], [_ON], [], [], [_ON], [], [_ON], [_PUB], [], [], []],
    "private-ticked": [[_PUB_CLEAR], [_CLEAR], _K1, [_CLEAR], [], _K1, [_CLEAR], _K1,
                       [_PUB_CLEAR], [_CLEAR], [_CLEAR], []],
    "public-clean": [[], [_PRIV], [_ON], [], [], [_ON], [_PRIV], [_ON], [], [_PRIV],
                     [_PRIV], []],
    "public-on": [[], [_PRIV, _CLEAR], [], [_CLEAR], [], [], [_PRIV, _CLEAR], [], [_CLEAR],
                  [_PRIV, _CLEAR], [_PRIV, _CLEAR], []],
}
_GROUPS = {"private-clean": _PRIVATE_CLEAN, "private-ticked": _PRIVATE_TICKED,
           "public-clean": _PUBLIC_CLEAN, "public-on": _PUBLIC_ON}
_MATRIX = [(g, meta, req, want)
           for g, metas in _GROUPS.items() for meta in metas
           for req, want in zip(_REQUESTS, _WRITES[g])]


def _record(monkeypatch, results=None):
    """Replace the writer with a recorder of each patch's keys IN ORDER. `results`
    answers the n-th write (True when it runs out), so a test can fail one."""
    seen = []
    results = list(results or [])

    def _patch(device_id, fields, *a, **kw):
        # Nothing but the fields: no other device, and no delete list.
        assert device_id == "dev-1" and not a and not kw
        seen.append(list(fields.items()))
        return results[len(seen) - 1] if len(seen) <= len(results) else True

    monkeypatch.setattr(research, "_pair_patch_device", _patch)
    return seen


@pytest.mark.parametrize("group, meta, req, want", _MATRIX,
                         ids=[f"{g}-{i}-{r[0]}-{r[1]}" for i, (g, _m, r, _w)
                              in enumerate(_MATRIX)])
def test_every_request_writes_exactly_this_sequence(wired, monkeypatch, group, meta,
                                                    req, want):
    wired["meta"] = dict(meta)
    seen = _record(monkeypatch)
    assert research.run_visibility(req[0], allow_all=req[1]) == 0
    assert seen == want


@pytest.mark.parametrize("meta", _PRIVATE_TICKED)
@pytest.mark.parametrize("req", [(SHOW, "yes"), ("public", BARE), ("public", "yes")])
def test_allow_all_on_over_an_old_tick_clears_it_alone_first(wired, monkeypatch, meta,
                                                             req):
    """⛔⛔ THE FINDING'S OWN CASE, from every spelling of ON: a private computer
    whose old tick the rules will not let a publish ride over. The screen is the
    ordinary ON screen — the clear is an implementation detail, not news."""
    wired["meta"] = dict(meta)
    seen = _record(monkeypatch)
    assert research.run_visibility(req[0], allow_all=req[1]) == 0
    assert seen == [_CLEAR, _ON]
    out = wired["out"]()
    assert ON in out
    assert "made it public too" in out
    assert "Could not" not in out


def test_a_failed_clear_sends_nothing_after_it_and_claims_nothing(wired, monkeypatch):
    """The first write failing is today's failure: the same "could not confirm"
    words, no state claimed — and the ON patch never goes out behind it."""
    wired["meta"] = {"visibility": "private", "allowAll": True}
    seen = _record(monkeypatch, results=[False])
    assert research.run_visibility(SHOW, allow_all="yes") == 1
    assert seen == [_CLEAR]
    out = wired["out"]()
    assert "Could not confirm that change." in out
    assert "Could not turn Allow all on" not in out
    assert ON not in out and "Public" not in out


def test_an_unconfirmed_on_after_the_clear_claims_neither_on_nor_off(wired, monkeypatch):
    """⛔ THE CLEAR LANDED AND THE ON PATCH DID NOT COME BACK CONFIRMED. "Could not
    confirm that change" would hide that something DID change; "Allow all is on"
    would be one lie and "Could not turn Allow all on" the other — the writer
    answers False for a refusal and for a lost reply alike, so it cannot know
    which (wave 12 repair 5, final verify rules-1: repair 4 pinned the failure
    claim here). It says it could not confirm, that it may or may not have been
    saved, and that a tick which opened nothing was cleared before it."""
    wired["meta"] = {"visibility": "private", "allowAll": True}
    seen = _record(monkeypatch, results=[True, False])
    assert research.run_visibility(SHOW, allow_all="yes") == 1
    assert seen == [_CLEAR, _ON]
    out = wired["out"]()
    assert "Could not confirm Allow all went on — it may or may not have been saved." in out
    assert "Before it, an old Allow all tick was cleared, which did nothing" in out
    assert "while this computer was private" in out
    assert "Could not turn Allow all on" not in out
    assert "Could not confirm that change." not in out
    assert ON not in out and "Public" not in out
    assert "--visibility" in out


def test_an_on_patch_that_landed_with_its_reply_lost_is_never_called_a_failure(
        wired, monkeypatch):
    """⛔⛔ WAVE 12 REPAIR 5 (final verify rules-1), THE FINDING'S OWN RUN. The clear
    lands, the ON patch commits on the server, and its reply is lost — a 10-second
    timeout or a 5xx, which `_pair_patch_device` answers False exactly as it does
    a refusal. The computer is now public with Allow all on, so anyone who asks
    joins at once. Repair 4 printed "Could not turn Allow all on" over it. The
    screen may not claim either state, and the one step it points to finds the
    truth. Executed against repair 4: the failure line printed."""
    server = {"visibility": "private", "allowAll": True}
    wired["meta"] = dict(server)
    seen = []

    def _patch(device_id, fields, *a, **kw):
        assert device_id == "dev-1" and not a and not kw
        seen.append(dict(fields))
        server.update(fields)
        # Every patch commits; only the ON patch's reply never arrives.
        return fields.get("allowAll") is not True

    monkeypatch.setattr(research, "_pair_patch_device", _patch)
    assert research.run_visibility(SHOW, allow_all="yes") == 1
    assert seen == [{"allowAll": False}, {"visibility": "public", "allowAll": True}]
    assert research._allow_all_of(server) is True
    out = wired["out"]()
    assert "Could not turn Allow all on" not in out
    assert "did not go on" not in out
    assert "Could not confirm Allow all went on — it may or may not have been saved." in out
    # The step it names reads the computer as it really is.
    wired["meta"] = dict(server)
    assert research.run_visibility(SHOW) == 0
    assert ON in wired["out"]()


def test_the_clear_first_goes_through_the_real_parser(tmp_path):
    """The same sequence from `superresearch --allow-all yes`, parsed for real."""
    code, patches, _out, err = _drive("--allow-all", "yes",
                                      meta={"visibility": "private", "allowAll": True},
                                      tmp_home=tmp_path)
    assert code == 0, err[-2000:]
    assert patches == [{"allowAll": False}, {"visibility": "public", "allowAll": True}]
