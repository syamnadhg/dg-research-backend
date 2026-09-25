"""THE EMPTY STATE — wave 7.9-4, items C1 and C5.

⛔⛔ TEN SENTENCES SAID "THIS ACCOUNT HAS NO RESEARCH COMPUTER" AND THEY ALL SAID
SOMETHING DIFFERENT. Seven in the chat client, one in the proactive watcher, one in
the terminal, one on the wire — and NOT ONE OF THEM WAS PINNED BY ANY TEST, so the
whole surface was free to drift and did. Every one of them offered exactly one way
out: paste a pair code. Somebody with no machine of their own, and no way to get
one, was told to go and get one — while the account had been able to ask to use
somebody else's since 7.9-2.

⭐ WHAT C1 REQUIRES, AND WHAT EVERY TEST BELOW CHECKS FOR: three things, in one
order, on every surface — there is no computer on this account · your own can be
added with a pair code · or you can ask to use somebody else's — and the ones on
offer are LISTED, because "ask for a public one" with nothing named is advice and
not a next step.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from facade import cli
from tests.conftest import code_only

_ROOT = Path(__file__).resolve().parents[1] / "facade"
_SR_PATH = _ROOT / "skill" / "scripts" / "sr.py"
_WATCH_PATH = _ROOT / "skill" / "scripts" / "sr_attention_poll.py"
_SKILL = _ROOT / "skill" / "SKILL.md"
_BRIDGE = _ROOT / "bridge.py"
_CLI = _ROOT / "cli.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load("sr_empty_794", _SR_PATH)
poll = _load("poll_empty_794", _WATCH_PATH)

PUB_A = {"deviceId": "dev-a1", "label": "Studio PC", "osFamily": "macos",
         "online": True, "full": False}
PUB_FULL = {"deviceId": "dev-b2", "label": "Research computer", "osFamily": "linux",
            "online": False, "full": True}

# The three things, as the assertions look for them.
# ⛔⛔ `THING_OWN` WAS "access code" AND THAT WAS VACUOUS. The install block that
# follows the three things ends "It installs Super Research and prints an 8-char
# access code — read it to me.", so every door test passed with the pair-code
# SENTENCE deleted — a mutant proved it, killing nothing across eight tests. The
# phrase now belongs to that sentence alone, on both clients.
THING_NONE = "no research computer on this account yet"
# ⚠ "add your own" UNTIL 2026-09-20, AND THAT PHRASE WAS ITSELF THE MISLEAD.
# An access code connects ANY computer running Super Research, so this option has
# always covered somebody else's private machine whose owner hands you the code —
# "your own" narrowed a door that was never that narrow, and heading the block
# "Two ways in" denied the third route outright (owner). The claim pinned here is
# unchanged: the access-code route is NAMED on every door.
THING_OWN = "add a computer"
THING_ASK = "ask to use somebody else"


def _ns(**kw):
    kw.setdefault("json", False)
    return SimpleNamespace(**kw)


@pytest.fixture()
def chat(monkeypatch, capsys):
    """The chat client with both doors stubbed and every call recorded."""
    gets: dict = {}
    posts: dict = {}
    calls: list = []

    def _get(path, timeout=None):
        calls.append(("GET", path, timeout))
        return gets.get(path, (200, {}))

    def _post(path, body=None, timeout=None):
        calls.append(("POST", path, body))
        return posts.get(path, (200, {}))

    monkeypatch.setattr(sr, "_get", _get)
    monkeypatch.setattr(sr, "_post", _post)
    gets["/devices"] = (200, {"devices": [], "selectedDeviceId": None})
    gets["/devices/public"] = (200, {"devices": [PUB_A, PUB_FULL], "truncated": False})
    return SimpleNamespace(gets=gets, posts=posts, calls=calls,
                           out=lambda: capsys.readouterr().out)


@pytest.fixture()
def term(monkeypatch, capsys):
    calls: list = []
    box: dict = {"get": {}, "post": {}}
    monkeypatch.setattr(cli, "_bridge_up", lambda: True)
    monkeypatch.setattr(cli, "_redirect_if_wsl", lambda _m: None)
    monkeypatch.setattr(cli, "_bridge_get",
                        lambda p, timeout=10.0: (calls.append(("GET", p, timeout)),
                                                 box["get"].get(p))[1])
    monkeypatch.setattr(cli, "_bridge_post",
                        lambda p, body=None, timeout=30.0: (calls.append(("POST", p, body)),
                                                            box["post"].get(p))[1])
    box["get"]["/devices"] = (200, {"devices": [], "selectedDeviceId": None})
    box["get"]["/devices/public"] = (200, {"devices": [PUB_A, PUB_FULL],
                                           "truncated": False})
    return SimpleNamespace(box=box, calls=calls, out=lambda: capsys.readouterr().out)


# ── C1: every chat door renders the SAME three things ────────────────────────

def _door_resolve_name():
    _dev, lines = sr._resolve_device_arg("whatever")
    return lines


def _door_pick_fallback():
    return sr._pick_device_lines({}, "no_selection")


def _door_signed_in():
    return sr._signed_in_lines({"email": "e@x.y", "needsDevice": True,
                                "topic": "Golden Retrievers"})


DOORS = {
    "a name that would not resolve": _door_resolve_name,
    "the picker's own fallback": _door_pick_fallback,
    "the sign-in announce": _door_signed_in,
}


@pytest.mark.parametrize("door", sorted(DOORS))
def test_every_line_returning_door_says_all_three_things(chat, door):
    """⛔⛔ THE SITES DRIFTED BECAUSE EACH OWNED ITS OWN WORDING. Parametrised on
    purpose: a new door that writes its own sentence has to be added here, and a
    door that stops rendering the block fails by name rather than in a heap."""
    blob = "\n".join(DOORS[door]()).lower()
    assert THING_NONE in blob, (door, blob)
    assert THING_OWN in blob, (door, blob)
    assert THING_ASK in blob, (door, blob)


@pytest.mark.parametrize("run", [
    lambda: sr.cmd_devices(_ns()),
    lambda: sr.cmd_status_account(_ns()),
])
def test_every_printing_door_says_all_three_things(chat, run):
    chat.gets["/status"] = (200, {"authed": True, "email": "e@x.y"})
    run()
    blob = chat.out().lower()
    assert THING_NONE in blob and THING_OWN in blob and THING_ASK in blob, blob


def test_the_run_that_could_not_be_routed_says_all_three_things(chat):
    chat.posts["/research"] = (400, {"reason": "no_devices", "error": "no devices yet"})
    assert sr.cmd_research(_ns(topic="Pitbulls", device=None, no_video=False,
                               no_email=False)) != 0
    blob = chat.out().lower()
    assert THING_NONE in blob and THING_OWN in blob and THING_ASK in blob, blob


def test_the_add_sentence_is_its_own_line_and_carries_the_install_link(chat):
    """⛔⛔ THE VACUITY THIS PAIR OF ASSERTIONS EXISTED TO CLOSE IS GONE WITH ITS
    CAUSE. The install block below the three things used to say "8-char access
    code" too, so a substring test for that phrase could never see the second
    thing disappear. There is ONE code sentence on the screen now, and the install
    link lives inside it (owner, 2026-09-24)."""
    sr.cmd_devices(_ns())
    out = chat.out()
    # ⚠ REPINNED 2026-09-20, TWICE, AND 2026-09-24. The head is "Add a computer:" —
    # the routes are NAMED (because the unnamed public half was being folded away
    # by the relay) and deliberately NOT NUMBERED (because an access code connects
    # any computer running Super Research, so "two ways in" was false). It is
    # asserted WHOLE, as a line of its own, so neither the link nor the widened
    # clause can quietly vanish.
    assert ("Add a computer: set one up at https://superresearch.io/install, then "
            "send me the 8-character access code the computer shows (or one a "
            "computer's owner gave you).") in out.splitlines()
    # ⛔ AND THE SECOND CODE SENTENCE IS GONE, NOT JUST MOVED. "It gives you…" read
    # as the web page handing out the code; a relay made that "from the app".
    assert "It gives you" not in out
    # (the relay rule below the marker names the code too — to the model, not the
    # person — so the count is of what the person sees)
    above = out.partition(sr._AGENT_ONLY_MARKER)[0]
    assert above.count("access code") == 1, above


def test_the_public_half_is_a_named_section_on_every_surface(chat, term, monkeypatch):
    """⭐⭐ THE SECTION HAD NO NAME, SO IT HAD NOTHING TO SURVIVE ON (owner,
    2026-09-20). The browse screen has always headed these rows "Public computers
    (N):". The empty state rendered the IDENTICAL rows under "Or ask to use
    somebody else's — these are on offer right now:" and never printed the noun
    at all — so a person meeting the concept for the FIRST time met it as the
    tail of a sentence, on the one screen where it is new information.

    ⛔ AND A RELAY PRESERVES WHAT THE CLIENT STATES AND RESTRUCTURES WHAT IT
    LEAVES IMPLICIT. Sent to a chat, the nameless half was merged into the option
    above it and the list of public computers left the message entirely. No
    amount of "relay verbatim" in SKILL.md fixed that — the word was never in the
    bytes. This pins the word into the bytes, on all three surfaces.
    """
    sr.cmd_devices(_ns())
    assert "public computers" in chat.out().lower()

    sr.cmd_devices_public(_ns())
    assert "public computers" in chat.out().lower()

    cli.cmd_device(argparse.Namespace(device_command=None))
    assert "public computers" in term.out().lower()

    line = poll._signed_in_line({"email": "e@x.y", "needsDevice": True,
                                 "topic": "Golden Retrievers", "pendingTopic": ""})
    assert "public computers" in line.lower(), line


def test_one_noun_for_the_public_list_not_two(chat):
    """⛔ THE TWO SCREENS RENDER ONE LIST AND MUST NOT NAME IT TWO WAYS. They drifted
    once already — the browse head said "Public computers", the empty state said
    nothing — so the noun is a module constant and both read from it. The count is
    the browse screen's alone: it is reporting a scan, while the empty state is
    naming an option."""
    assert sr._PUBLIC_HEAD == "Public computers"
    sr.cmd_devices_public(_ns())
    assert f"{sr._PUBLIC_HEAD} (" in chat.out()
    sr.cmd_devices(_ns())
    empty = chat.out()
    assert sr._PUBLIC_HEAD in empty
    # ⛔ and WITHOUT a count, which would be a claim about a scan this screen did
    # not report on
    assert f"{sr._PUBLIC_HEAD} (" not in empty


def test_the_ways_in_are_NAMED_and_never_COUNTED(chat):
    """⛔⛔ THERE IS NO HONEST NUMBER TO GIVE, so no number is given (owner,
    2026-09-20). A first version of this block headed itself "Two ways in:" and
    numbered the options 1 and 2. Both are false: an access code connects ANY
    computer running Super Research, so the access-code option already covers a
    machine of your own AND somebody else's private machine whose owner hands you
    the code — a third way in that the count silently denied. A wrong number is
    worse than no number, because it tells the reader to stop looking.

    ⭐ AND THE NUMBERS WERE NEVER THE FIX. What the public half lacked was a
    NOUN: it rendered as the tail of a sentence, so a relay folded it into the
    option above it and the list left the message entirely. Names fix that;
    ordinals never did."""
    sr.cmd_devices(_ns())
    out = chat.out()
    assert "Add a computer:" in out
    assert f"{sr._PUBLIC_HEAD} —" in out
    assert "Two ways in" not in out
    assert "1 · " not in out and "2 · " not in out, out


def test_the_access_code_route_does_not_narrow_itself_to_your_own_machine(chat):
    """⛔ THE MISLEAD THE COUNT EXPOSED. "Add your own" describes the common case
    and quietly forbids the real one: a private computer somebody else owns is
    added exactly the same way, with the code its owner hands you. Somebody told
    the only route is "your own", who hasn't got one, reads a dead end."""
    sr.cmd_devices(_ns())
    out = chat.out()
    # ⚠ REPINNED 2026-09-24: the owner's wording for the same widening — the code
    # the computer shows, "or one a computer's owner gave you".
    add = next(ln for ln in out.splitlines() if ln.startswith("Add a computer:"))
    assert "or one a computer's owner gave you" in add
    assert "Add your own" not in out
    assert "your own" not in add.lower()


def test_a_renderer_that_returns_nothing_still_leaves_a_whole_screen(chat, monkeypatch):
    """The --json path sets `_RENDERING_LINES` False and `_public_offer_lines`
    returns []. The access-code route and the walkthrough must both survive it.

    ⚠ THIS PINNED "no numbered hole" — the right worry about a design that is
    gone. With the options numbered, a branch returning nothing left an option 1
    followed by the install block and a reader hunting for the 2. Without
    ordinals the hole cannot exist; what is still worth pinning is that the
    early-out does not eat the rest of the screen."""
    monkeypatch.setattr(sr, "_RENDERING_LINES", False)
    lines = sr._no_device_lines()
    blob = "\n".join(lines)
    assert "Add a computer:" in blob
    # ⚠ REPINNED 2026-09-24: the install link rides INSIDE the add line (owner),
    # so the early-out cannot separate them.
    assert any(ln.startswith("Add a computer:") and "superresearch.io/install" in ln
               for ln in lines), lines


def test_the_install_link_rides_on_the_add_line_before_the_public_section(chat):
    """⛔ ORDER IS NOT DECORATION — and the order this pinned was the one that
    failed. It used to require the install link LAST, after the public list; in the
    Hermes history a relay dropped that trailing link 3 times out of 3 (owner,
    2026-09-24). The link is now inside the "Add a computer:" line, which comes
    before the public section, and nothing trails the public section."""
    sr.cmd_devices(_ns())
    above = chat.out().partition(sr._AGENT_ONLY_MARKER)[0]
    lines = [ln.lower() for ln in above.splitlines()]
    said = next(i for i, ln in enumerate(lines) if THING_NONE in ln)
    own = next(i for i, ln in enumerate(lines) if THING_OWN in ln)
    ask = next(i for i, ln in enumerate(lines) if THING_ASK in ln)
    assert said < own < ask, (said, own, ask)
    assert "superresearch.io/install" in lines[own], lines[own]
    # ⛔ AND IT IS SAID ONCE: no second link below the public list for a relay to
    # treat as the "real" one and keep instead
    assert [i for i, ln in enumerate(lines) if "superresearch.io" in ln] == [own], lines


def test_the_lead_is_rendered_and_it_leads(chat):
    """⛔ THE CALLERS THAT ARRIVE WITH AN OBJECT IN HAND. Without the lead the
    sign-in announce stops naming the topic that has nowhere to run, and reads as an
    unprompted lecture about hardware."""
    lines = sr._no_device_lines(lead="“Golden Retrievers” has nowhere to run yet.")
    assert lines[0] == "“Golden Retrievers” has nowhere to run yet."
    assert THING_NONE in lines[1].lower()
    said = "\n".join(sr._signed_in_lines({"email": "e@x.y", "needsDevice": True,
                                           "topic": "Golden Retrievers"}))
    assert "“Golden Retrievers” has nowhere to run yet." in said, said


def test_the_skill_file_still_tells_the_model_an_empty_account_is_not_a_dead_end():
    """⛔ NOTHING RENDERS THIS PARAGRAPH, so only a source guard can see it go — and
    without it the model is free to relay the shortest of the ten old sentences."""
    # ⚠ WHITESPACE-FOLDED SINCE 2026-09-24. The phrases were pinned with the
    # file's own line breaks inside them, so rewrapping the paragraph — which this
    # change had to, to put the install link in it — failed the guard without the
    # claim changing. The claim is the words.
    skill = " ".join(_SKILL.read_text(encoding="utf-8").split())
    assert "**An account with NO computer is not a dead end.**" in skill
    assert "names BOTH routes" in skill
    assert "also LIST the public computers on offer" in skill
    assert "never present setting up a machine as the only route." in skill
    # ⛔⛔ AND IT NO LONGER CLAIMS EVERY SCREEN LISTS THEM. Four surfaces name both
    # routes without a list — the one-line sign-in confirmation deliberately so,
    # because rendering one would cost it a second call.
    assert "Every screen that reports it says the same three things" not in skill
    # ⭐ AND THE ROUTE IT NAMES FIRST CARRIES THE PAGE AND THE CODE'S TRUE ORIGIN
    # (owner, 2026-09-24) — the paragraph used to call it "add your own with an
    # access code", with no link, which is the shape the relay reproduced.
    para = skill[skill.index("**An account with NO computer is not a dead end.**"):]
    para = para[:para.index("A **Research Computer** is")]
    assert "https://superresearch.io/install" in para
    assert "never say it comes from the app" in para
    assert "add your own with an access code" not in para


def test_the_install_gate_names_a_string_a_surface_actually_prints():
    """⛔⛔ SKILL.md GATED `install` ON "no devices yet" AND THIS WAVE DELETED THAT
    STRING FROM EVERY SURFACE THAT COULD PRINT IT — the bridge sentence was
    rewritten, and the chat client throws the bridge's English away and renders its
    own. The documented gate for the one command that turns the local PC into a
    Research Computer could no longer be recognised.

    ⚠ AND THE GATE IS NOW THE OTHER WAY ROUND (owner, 2026-09-24). That screen is
    where a brand-new person meets the install page, so `install` is NOT offered
    for it; the note names the printed string to say so, and `install` is kept for
    an explicit "install it on THIS machine" only. The string it names must still
    be one a surface prints — that half of the guard is unchanged."""
    skill = _SKILL.read_text(encoding="utf-8")
    i = skill.index("- **install**")
    said = skill[i:i + 700]
    assert "no research computer on this account" in said and "yet" in said
    assert '"no devices yet" (reason' not in said
    folded = " ".join(said.split())
    assert "explicitly asks to install it on THIS machine" in folded, folded
    assert "NOT for a screen that says" in folded, folded
    # ⛔ and it never hands anybody the pairing command in place of the page
    assert "--pair" not in said
    # ⛔ AND THE STRING IT NAMES IS THE ONE THE WIRE ACTUALLY SENDS.
    src = code_only(_BRIDGE.read_text(encoding="utf-8"))
    j = src.index('"reason": "no_devices"')
    assert "no research computer on this account yet" in src[j:j + 600]


def test_the_post_sign_in_one_liner_names_both_ways_out(chat):
    """⛔ ONE LINE, AND STILL BOTH ROUTES. This is a confirmation, not the empty
    state — it must not fire a second look to render a list — but it was the first
    thing a brand-new account read and it named only the route that needs
    hardware."""
    raw = sr._connected_msg("e@x.y")
    said = raw.lower()
    assert "access code" in said and "public computer" in said, said
    assert "\n" not in said, said
    # ⚠ REPINNED 2026-09-24: NOT ITS OWN WORDING ANY MORE. It said "paste the
    # access code from your Research Computer", which assumed the reader had one
    # and gave them no way to get one; it now carries the shared add line, link
    # and all (owner), and still ends on the public-computer offer.
    assert sr._ADD_A_COMPUTER in raw, raw
    assert raw.rstrip().endswith("public computer you could use."), raw


# ── C1's third thing is a LIST, and it is the browse screen's own rows ───────

def test_the_empty_state_lists_the_public_ones_with_everything_a_row_carries(chat):
    sr.cmd_devices(_ns())
    out = chat.out()
    assert "Studio PC" in out
    assert "online" in out and "offline" in out
    # ⛔⛔ `full` IS A REFUSAL IN ADVANCE. A row offered without it invites an ask
    # the route answers `share_cap_reached` with certainty, spending one of five
    # an hour on a guaranteed no.
    assert "can’t take anyone else" in out
    # ⛔⛔ AND NO ID, BECAUSE THESE TWO ROWS DO NOT READ THE SAME. The id used to
    # print on every row and it was the widest thing on the screen — a 32-char hex
    # string beside a one-word name, which reads as something the person has to
    # deal with (owner, 2026-09-19). It is now shown only where it is the ONLY
    # thing that separates two rows; see the collision test below.
    # ⚠ The comment that stood here claimed both rows were the default unnamed
    # label. They are not — the fixture is "Studio PC" and "Research computer" —
    # so the assertion it justified was passing for a reason that was not true.
    assert "(id dev-a1)" not in out
    assert "(id dev-b2)" not in out


def test_the_id_comes_back_the_moment_two_rows_read_the_same(chat):
    """⭐ THE CASE THE ID EXISTS FOR. Every unnamed machine renders as the identical
    string "Research computer", and the list reorders online-first over a
    thirty-second window — so with two of them neither the name nor the position
    identifies one, and the ask takes the id. Dropping it everywhere would have
    made exactly this situation unanswerable."""
    chat.gets["/devices/public"] = (200, {"devices": [
        {"deviceId": "dup-1", "label": "Research computer", "online": True, "full": False},
        {"deviceId": "dup-2", "label": "Research computer", "online": False, "full": False},
        {"deviceId": "solo", "label": "Studio PC", "online": True, "full": False},
    ]})
    sr.cmd_devices(_ns())
    out = chat.out()
    assert "(id dup-1)" in out and "(id dup-2)" in out
    # ⛔ AND ONLY ON THE ONES THAT COLLIDE. A row with a name of its own keeps the
    # clean line — otherwise one duplicate pair would drag the id back onto
    # everything, which is the state this replaced.
    assert "(id solo)" not in out


def test_the_two_screens_print_the_identical_row_for_the_identical_machine(chat):
    """⛔⛔ EXTRACTING A HELPER DOES NOT TEST IT. `_public_row_line` has two
    consumers and this is the guard that they are the SAME consumer of it — a
    renderer pinned only through the browse list would let the empty state grow a
    second phrasing, which is exactly how the ten deviceless sentences happened."""
    # ⚠ MATCHED BY NAME, NOT BY ID. This used to find the row by its device id,
    # which stopped working the moment the id left the line — and it failed as
    # "browse and empty are both empty", i.e. as the two screens agreeing about
    # nothing. The property under test is unchanged: one renderer, both screens.
    sr.cmd_devices_public(_ns())
    browse = [ln for ln in chat.out().splitlines() if "Studio PC" in ln]
    sr.cmd_devices(_ns())
    empty = [ln for ln in chat.out().splitlines() if "Studio PC" in ln]
    assert browse and empty and browse == empty, (browse, empty)


def test_the_invitation_says_what_the_consent_question_says(chat):
    """⛔⛔ "your name and email address" IS WRONG TWICE. The owner sees the NAME,
    and the email only when no name is set.

    ⭐ THE TWO SURFACES NOW SAY DIFFERENT AMOUNTS, ON PURPOSE (owner, 2026-09-19).
    The LIST invite is a prompt to pick one of several rows, and a full privacy
    disclosure there made a five-line message out of a one-line question. The
    CONFIRM is the consent gate — the last thing shown before anything is sent —
    and it keeps the whole sentence, including the email fallback, because that is
    the moment the claim has to be exactly true.

    ⛔ What must NOT diverge is the CLAIM. Neither may say "name and email
    address", which is wrong in both directions."""
    sr.cmd_devices(_ns())
    out = chat.out()
    # the short invite: says the owner sees a name, and stops there
    assert "They see your name." in out, out
    assert "name and email address" not in out
    # the consent gate: the precise version, unchanged
    confirm = sr._NL_CONFIRMS["device-ask"]
    assert "or your email, if you haven’t set one" in confirm
    assert "name and email address" not in confirm


# ── the look can fail, and the offer must survive it ─────────────────────────

def test_a_failed_look_keeps_the_offer_and_hands_over_the_retry(chat):
    """⛔ THE OPTION IS TRUE WHETHER OR NOT THE LIST COULD BE READ. Dropping the
    paragraph on a transport hiccup would put the screen back to one way out."""
    chat.gets["/devices/public"] = (0, {"error": "bridge unreachable"})
    sr.cmd_devices(_ns())
    blob = chat.out().lower()
    assert THING_NONE in blob and THING_OWN in blob and THING_ASK in blob
    assert "show me public computers" in blob, blob


def test_nobody_offering_still_names_the_option_before_the_bad_news(chat):
    """⛔⛔ "Nobody is offering one" ON ITS OWN ANSWERS A QUESTION THIS READER DID
    NOT ASK and silently drops the third thing, leaving the pair code again."""
    chat.gets["/devices/public"] = (200, {"devices": [], "truncated": False})
    sr.cmd_devices(_ns())
    out = chat.out()
    assert THING_ASK in out.lower(), out
    assert "nobody is offering one publicly right now" in out.lower(), out
    # ⛔ THE SHARED SENTENCE KEEPS ITS OWN LINE. Spliced after an em-dash it
    # printed "— A computer shows up there…" with a capital A mid-sentence.
    assert sr._PUBLIC_NONE_WHY in out.splitlines(), out


@pytest.mark.parametrize("rows,expect", [
    ([], "may not be the whole story"),
    ([PUB_A], "some may be missing"),
])
def test_truncation_is_carried_on_both_branches(chat, rows, expect):
    """⛔⛔ `truncated` IS ABOUT THE SCAN, NOT THE LIST, and the EMPTY branch is
    where it matters most: zero rows over a filled scan means everything found was
    filtered out, over which a flat "nobody is offering" is definitely wrong."""
    chat.gets["/devices/public"] = (200, {"devices": rows, "truncated": True})
    sr.cmd_devices(_ns())
    assert expect in chat.out()


def test_the_browse_screen_survives_a_bad_row_too(chat):
    """⛔⛔ ONLY THE EMPTY STATE WAS GUARDED. The bridge validates that `devices` is
    a LIST and never that a row is a dict, and the browse renderer calls `.get` on
    every row — so one bad row from the app took down the browse command while the
    screen beside it survived."""
    chat.gets["/devices/public"] = (200, {"devices": ["nonsense", PUB_A],
                                          "truncated": False})
    assert sr.cmd_devices_public(_ns()) == 0
    assert "Studio PC" in chat.out()


def test_a_list_of_nothing_but_full_machines_does_not_call_itself_an_offer(chat):
    """⛔⛔ `full` MEANS THE ASK IS A CERTAIN REFUSAL. "these are on offer right
    now" over a list where every row is full invites somebody to spend one of five
    hourly asks on a guaranteed no — the defect 7.9-3 removed from the ask verb,
    reintroduced by the screen that offers it."""
    chat.gets["/devices/public"] = (200, {"devices": [PUB_FULL], "truncated": False})
    sr.cmd_devices(_ns())
    out = chat.out()
    assert "every computer on offer is already shared with as many people" in out
    assert "these are on offer right now" not in out


def test_a_rate_limited_look_says_how_long_rather_than_try_again(chat):
    """⛔ BROWSE IS RATE LIMITED AND THE REPLY CARRIES THE MINUTES. Collapsing that
    into "say show me public computers and I'll look again" spends another look on
    the same refusal."""
    chat.gets["/devices/public"] = (429, {"error": "rate_limited",
                                          "retryAfterMs": 120_000})
    sr.cmd_devices(_ns())
    out = chat.out()
    assert THING_ASK in out.lower(), out
    assert "2 minutes" in out, out
    assert "look again" not in out, out


def test_json_mode_does_not_pay_for_lines_it_throws_away(chat, monkeypatch):
    """⛔⛔ `--json` PRINTS THE PAYLOAD AND DROPS EVERY RENDERED LINE, so the empty
    state's second look was up to twenty seconds of wall clock spent building a
    string nobody reads — on the STREAMING CRON's own invocation, which runs every
    minute. Measured by cross-verify."""
    monkeypatch.setattr(sr, "_RENDERING_LINES", False)
    sr.cmd_devices(_ns(json=True))
    assert not [c for c in chat.calls if c[1] == "/devices/public"]
    monkeypatch.setattr(sr, "_RENDERING_LINES", True)
    sr.cmd_devices(_ns())
    assert [c for c in chat.calls if c[1] == "/devices/public"]


def test_the_terminal_looks_before_it_prints_anything(monkeypatch, capsys):
    """⛔ IT PRINTED THREE LINES AND THEN BLOCKED FOR UP TO TWENTY SECONDS
    MID-MESSAGE, which reads as a hung command. The chat client returns its whole
    block at once and this one stuttered.

    ⛔⛔ AND THE FIRST VERSION OF THIS GUARD COULD NOT SEE IT. It asserted the CALL
    ORDER — `["/devices", "/devices/public"]` — which moving the fetch below the
    prints does not change, because both calls still happen in the same sequence.
    A mutant proved it survived. What has to be measured is how much has already
    been PRINTED when the look is made, so the stub records it.
    """
    printed_at_look = []

    def _bridge_get(path, timeout=10.0):
        if path == "/devices/public":
            printed_at_look.append(len(capsys.readouterr().out))
            return (200, {"devices": [dict(PUB_A)], "truncated": False})
        return (200, {"devices": [], "selectedDeviceId": None})

    monkeypatch.setattr(cli, "_bridge_up", lambda: True)
    monkeypatch.setattr(cli, "_redirect_if_wsl", lambda _m: None)
    monkeypatch.setattr(cli, "_bridge_get", _bridge_get)
    assert cli.cmd_device(argparse.Namespace(device_command=None)) == 0
    assert printed_at_look == [0], printed_at_look


def test_the_terminal_carries_the_route_for_somebody_with_no_machine_at_all(term):
    """⛔ THE CHAT CLIENT'S BLOCK CARRIES THE ONE-LINE INSTALLER AND THE TERMINAL'S
    DID NOT — it offered a pair code from a computer that may be running nothing,
    which is advice you cannot act on."""
    cli.cmd_device(argparse.Namespace(device_command=None))
    out = term.out()
    # ⚠ REPINNED 2026-09-23: the install route is the install PAGE on every surface
    # (owner) — the one-liners and `superresearch --pair` left this screen.
    assert "superresearch.io/install" in out
    assert "superresearch --pair" not in out and "install.ps1" not in out
    # ⚠ AND 2026-09-24: on the "Add a computer:" line itself, before the public
    # section — the closing install block every exit used to print is gone.
    lines = out.splitlines()
    add = next(i for i, ln in enumerate(lines) if "Add a computer:" in ln)
    pub = next(i for i, ln in enumerate(lines) if "Public computers" in ln)
    assert "superresearch.io/install" in lines[add] and add < pub, lines
    assert "It gives you" not in out


def test_the_device_list_never_hands_a_slash_command_to_a_chat(chat):
    """⛔⛔ THE BRIDGE'S 401 IS A SENTENCE — "not signed in — run /login" — and this
    wave made `devices` the answer to "I don't have a computer", so the very people
    it was written for were handed a TERMINAL command in a chat.

    ⛔ AND THE GUARD FOR THIS EXISTED AND MISSED IT: it drove `_list_refusal_line`,
    which the device list does not use. A mutant survived on that gap. This drives
    the command.
    """
    chat.gets["/devices"] = (401, {"error": "not signed in — run /login"})
    sr.cmd_devices(_ns())
    out = chat.out()
    assert "/login" not in out, out
    assert "tell me to log you in" in out.lower(), out


def test_the_watcher_carries_the_whole_disclosure_not_half_of_it(monkeypatch):
    """⛔⛔ THE ONE SURFACE THE DISCLOSURE WAS NOT UNIFIED ON. It said only "they
    see your name", so somebody who has never set a display name is told a stranger
    will see their name when the product hands over their EMAIL ADDRESS. It runs
    with `no_agent`, so it reaches the reader verbatim with no model turn to
    complete it."""
    line = poll._signed_in_line({"email": "e@x.y", "needsDevice": True,
                                 "topic": "Golden Retrievers", "pendingTopic": ""})
    # ⭐ CAPITALISED SINCE 2026-09-24 — it follows the chat invite's own sentence
    # now (see the next test), so the claim is compared, not the case.
    assert "they see your name" in line.lower()
    assert "or your email, if you have not set one" in line, line


def test_the_watcher_says_what_asking_gets_you_like_the_chat_invite():
    """⛔ "SAME ORDER AND FACTS" (owner, 2026-09-24). The chat invite says what an
    accepted request gets you; the watcher's paragraph had left that sentence out,
    so the one surface nothing relays was the one that did not say it."""
    line = poll._signed_in_line({"email": "e@x.y", "needsDevice": True,
                                 "topic": "Golden Retrievers", "pendingTopic": ""})
    for said in ("Tell me which one to ask for.",
                 "Once the request is accepted you can use that computer."):
        assert said in sr._PUBLIC_ASK_INVITE, said
        assert said in " ".join(line.split()), (said, line)


def test_a_non_dict_row_cannot_crash_the_empty_state(chat):
    """The bridge validates that `devices` is a list and not that each row is a
    dict, and the browse renderer calls `.get` unguarded. The empty state rides on
    a screen that was asked something else, so a bad row must not take it down."""
    chat.gets["/devices/public"] = (200, {"devices": ["nonsense", PUB_A],
                                          "truncated": False})
    sr.cmd_devices(_ns())
    assert "Studio PC" in chat.out()


def test_the_second_look_is_shorter_than_the_browse_command_s_own(chat):
    """⛔ IT RIDES ON A COMMAND THAT WAS ASKED SOMETHING ELSE, so it must not be
    able to hold that answer open for the whole client budget."""
    sr.cmd_devices(_ns())
    looks = [c for c in chat.calls if c[1] == "/devices/public"]
    assert looks and looks[0][2] == sr._PUBLIC_LOOK_TIMEOUT
    # ⛔ AGAINST THE BROWSE COMMAND'S ACTUAL BUDGET, READ FROM SOURCE. The first
    # version compared with the literal 40, so raising the browse command's own
    # timeout would have left this passing while the claim in its name went false.
    src = code_only(_SR_PATH.read_text(encoding="utf-8"))
    browse = int(re.search(r'_get\("/devices/public", timeout=(\d+)\)', src).group(1))
    assert sr._PUBLIC_LOOK_TIMEOUT < browse, (sr._PUBLIC_LOOK_TIMEOUT, browse)


# ── C1 on the terminal, which had the emptiest empty state of all ────────────

def test_the_terminal_empty_state_says_all_three_things(term):
    assert cli.cmd_device(argparse.Namespace(device_command=None)) == 0
    blob = term.out().lower()
    assert THING_NONE in blob and THING_OWN in blob, blob
    assert THING_ASK in blob, blob
    assert "studio pc" in blob, blob


def test_the_terminal_lists_the_public_ones_in_its_own_row_format(term):
    cli.cmd_device(argparse.Namespace(device_command=None))
    out = term.out()
    assert "id=dev-a1" in out and "id=dev-b2" in out
    assert "(can't take anyone else)" in out
    # ⛔ THIS FILE HAS NO CURLY APOSTROPHES AND THE CHAT CLIENT IS FULL OF THEM. A
    # guard compares the CLAIMS, not the glyphs.
    assert "or your email, if you have not set one" in out
    assert "name and email address" not in out


def test_one_name_for_the_code_on_every_surface(term, chat):
    """⛔⛔ THE VOCABULARY GUARD THE OTHER ASSERTIONS STOPPED PROVIDING. Pinning the
    three things by the phrase "access code" was vacuous (the install block says it
    too), so those assertions moved to "add your own" — and that left NOTHING
    watching what the code is CALLED. The terminal said "8-char code" while the
    chat client, the install walkthrough and SKILL.md all said "8-char access
    code": three vocabularies for one object is how somebody comes to believe
    there are two of them, and this file's own comment two hundred lines down says
    exactly that about `findable`/`public`.
    """
    # ⚠ REPINNED 2026-09-24: "8-character access code" — the owner's wording for
    # the add line on every surface. The NAME under guard is unchanged: "access
    # code", never "8-char code" and never "pair code".
    cli.cmd_device(argparse.Namespace(device_command=None))
    assert "8-character access code" in term.out()
    sr.cmd_devices(_ns())
    # ⛔ THE SENTENCE, NOT THE PHRASE — it is the one line on the screen that names
    # the code, so it is asserted as that line.
    assert "then send me the 8-character access code the computer shows" in chat.out()
    assert "8-character access code" in _SKILL.read_text(encoding="utf-8")
    # ⛔ SCOPED TO THE EMPTY STATE, WHICH IS THIS WAVE'S SUBJECT. The short form
    # "8-char" still appears in SKILL.md, in sentences that name the thing
    # properly ("8-char access code") — what must not drift is the screen that
    # introduces the code to somebody who has never seen one.
    body = code_only(_CLI.read_text(encoding="utf-8"))
    body = body[body.index("def _print_no_devices"):]
    body = body[:body.index("def _public_row")]
    assert "8-character access code" in body
    assert "8-char code" not in body and "pair code" not in body


def test_the_terminal_offer_survives_a_failed_look(term):
    term.box["get"]["/devices/public"] = None
    cli.cmd_device(argparse.Namespace(device_command=None))
    blob = term.out().lower()
    assert THING_NONE in blob and "agent device public" in blob, blob


def test_the_terminal_empty_state_no_longer_ends_at_one_sentence(term):
    """⛔⛔ IT WAS `print("No devices reachable by this account.")` AND `return 0` —
    no pair-code line, no install link, no mention that somebody else's computer
    can be asked for, and nothing anywhere pinned it."""
    assert "No devices reachable by this account." not in code_only(
        _CLI.read_text(encoding="utf-8"))


# ── C1 on the two surfaces that are delivered word for word ──────────────────

def test_the_watcher_names_both_ways_out(monkeypatch):
    """⛔ THE WATCHER RUNS WITH `no_agent`, so its text reaches the person verbatim
    with no model turn to launder it. It named only the pair code."""
    line = poll._signed_in_line({"email": "e@x.y", "needsDevice": True,
                                 "topic": "Golden Retrievers", "pendingTopic": ""})
    low = line.lower()
    assert "no research computer on your account yet" in low
    # ⚠ REPINNED 2026-09-23: the install route is the install PAGE on every surface
    # (owner) — the one-liners and `superresearch --pair` left this screen.
    assert "superresearch.io/install" in line
    assert "superresearch --pair" not in line
    assert "public computers" in low, line
    # ⚠ AND 2026-09-24: the page is inside the "Add a computer:" line, before the
    # public paragraph, and the "Don't have your own…" / "It gives you…" tail is
    # gone — the same order as the chat screen (owner).
    rows = line.splitlines()
    add = next(i for i, ln in enumerate(rows) if ln.startswith("Add a computer:"))
    pub = next(i for i, ln in enumerate(rows) if ln.startswith("Public computers"))
    assert "https://superresearch.io/install" in rows[add] and add < pub, rows
    assert "It gives you" not in line and "Don't have your own" not in line


def test_the_bridge_sentence_names_both_ways_out():
    """⛔⛔ ITS COMMENT SAID "Relayed verbatim into chat" AND THAT HAS NEVER BEEN
    TRUE — chat reads the `reason` and throws this English away. The surface that
    prints it word for word is the TERMINAL, which reads no reason codes at all."""
    src = code_only(_BRIDGE.read_text(encoding="utf-8"))
    i = src.index('"reason": "no_devices"')
    said = src[i:i + 600]
    assert "device add <code>" in said
    assert "device public" in said, said
    # ⛔ THE COMMANDS ARE RUNNABLE AS PRINTED. This sentence is read on the TERMINAL,
    # where `device add <code>` is not a command — `agent` is the program.
    assert "agent device add <code>" in said
    assert "agent device public" in said, said


# ── the source guard: no site may hand-write this block again ────────────────

def test_chat_never_relays_the_wire_sentence_it_is_sent(chat):
    """⛔⛔ THE CLAIM THE BRIDGE'S COMMENT USED TO MAKE, TESTED AS BEHAVIOUR. The
    first version of this guard asserted the words "Relayed verbatim into chat"
    were absent from `code_only(bridge.py)` — and `code_only` blanks comments, which
    is the only place that phrase ever appeared, so it could not fail. What is
    actually worth pinning is the fact: chat reads the `reason` and renders its own
    screen, so a change to the wire sentence reaches the terminal and nobody else.
    """
    chat.posts["/research"] = (400, {"reason": "no_devices",
                                     "error": "WIRE-SENTINEL-DO-NOT-RELAY"})
    sr.cmd_research(_ns(topic="Pitbulls", device=None, no_video=False, no_email=False))
    out = chat.out()
    assert "WIRE-SENTINEL-DO-NOT-RELAY" not in out, out
    assert THING_NONE in out.lower(), out


def test_no_deviceless_sentence_is_hand_written_anywhere_in_the_chat_client():
    """⛔⛔ THE FAILURE MODE THIS WAVE EXISTS TO END. Ten wordings of one fact, each
    added by somebody who could not see the other nine."""
    src = code_only(_SR_PATH.read_text(encoding="utf-8"))
    for gone in ("No devices connected yet",
                 "No device connected yet",
                 "Paste the access code from your Research Computer first"):
        assert gone not in src, gone


def test_every_deviceless_door_calls_the_one_renderer():
    """⛔ A COUNT, SO A DOOR CANNOT QUIETLY STOP USING IT.

    Seven occurrences in all: the `def` plus SIX call sites. The seventh door — the
    post-sign-in one-liner — deliberately does NOT call it, because rendering the
    block would cost that line a second network call; it renders the shared add
    line plus the public-computer offer in one line instead, and
    `test_the_post_sign_in_one_liner_names_both_ways_out` pins that. The first
    version of this docstring said "seven callers", which miscounted its own
    subject by one.
    """
    src = code_only(_SR_PATH.read_text(encoding="utf-8"))
    assert src.count("_no_device_lines(") == 7, src.count("_no_device_lines(")
    assert src.count("def _no_device_lines(") == 1


# ── C5 / the routing rule that did not exist ─────────────────────────────────

@pytest.mark.parametrize("said", [
    "I don't have a computer of my own",
    "I have no computer, what can I do",
    "I don't have any computers",
    "I dont have a machine",
    "I haven't got a mac",
    "I have no research computer",
    "I do not own a pc",
])
def test_having_no_computer_is_a_sentence_the_client_answers(said):
    """⛔⛔ MEASURED AT HEAD BEFORE THIS WAVE: every one of these reached the
    catch-all, INCLUDING the phrasing SKILL.md gives as its own worked example. The
    one sentence a person with nothing says was the one nothing answered."""
    argv, lines = sr._nl_resolve(said)
    assert argv == ["devices"], (said, argv, lines)


def test_it_answers_from_the_account_and_not_from_the_public_list():
    """⛔ `devices`, NOT `devices-public`. The public list cannot contain the
    asker's own machine, so sending these there tells somebody who DOES have a
    computer to go and ask a stranger for one."""
    row = [ln for ln in _SKILL.read_text(encoding="utf-8").splitlines()
           if "I don't have a computer of my own" in ln]
    assert len(row) == 1, row
    assert "`sr.py devices`" in row[0] and "devices-public" in row[0]
    assert "**not**" in row[0].lower()


@pytest.mark.parametrize("said", [
    "I don't have a computer — are there any public ones?",
    "I have no computer, show me somebody else's",
])
def test_a_sentence_that_names_the_alternative_still_reaches_the_browse_rule(said):
    """⛔ BELOW 2d ON PURPOSE. The half of these sentences that names an
    alternative belongs to the browse rule, and it sits above this one."""
    argv, _lines = sr._nl_resolve(said)
    assert argv == ["devices-public"], (said, argv)
