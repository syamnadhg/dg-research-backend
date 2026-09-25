"""The skill DESCRIPTION — the one string that reaches the host on every turn.

⛔⛔ THIS FIELD IS NOT A TRIGGER, IT IS PART OF SOMEBODY ELSE'S SYSTEM PROMPT. The
runtime builds every installed skill's name + description into the STABLE tier of
its prompt, so whatever is written here shapes turns that have nothing to do with
Super Research. That is why it is guarded separately from the body.

⭐ WHAT WAS NARROWED (owner, 2026-09-21), AND WHAT DELIBERATELY WAS NOT.
The status clause read "ANY status / progress question … is THIS skill's status
command, never your runtime's own health, repos, or memory" — a blanket capture
that forbade the host from answering about ITSELF, ever. It now takes the bare
forms (which is the measured defect) and releases a question explicitly about the
runtime.

⛔⛔ THE RESEARCH CLAUSE STAYS, WORD FOR WORD. It is not stylistic excess: commit
6db3c02 records the live defect it fixes — "a 'Do a Super Research' fired while
ALREADY SIGNED IN got ZERO bridge activity — Hermes never invoked /sr, it answered
from its own web tools" — and its reasoning is decisive: every earlier fix was to
the skill BODY, which only runs once the host OPENS the skill; this failure is the
host never opening it, and the description is the only lever for that case.
Narrowing it would mean the person asks for research, gets a fluent model-written
answer, and NO RUN STARTS — with no error, no log line and nothing in the web app.
A visible annoyance was traded for an invisible failure, and that trade is refused.
"""

import re
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "facade" / "skill" / "SKILL.md"

# ⛔ THE HOST TRUNCATES AT 1024 AND SAYS NOTHING. Truncation eats the TAIL, which
# is where the podcast, device-management, sign-in and version/update routing
# keywords live — so an over-long description silently breaks routing for
# commands nobody was editing.
CEILING = 1024


def _description() -> str:
    """The folded value, exactly as the host receives it."""
    fm = SKILL.read_text(encoding="utf-8").split("---")[1]
    out, started = [], False
    for ln in fm.split("\n"):
        if ln.startswith("description:"):
            started = True
            continue
        if started:
            if ln and not ln.startswith(" "):
                break
            out.append(ln.strip())
    return " ".join(x for x in out if x)


def test_the_description_fits_under_the_silent_ceiling():
    d = _description()
    assert len(d) <= CEILING, (
        f"{len(d)} chars — the host truncates at {CEILING} with no error, and it "
        "cuts the TAIL, where the podcast/device/sign-in/version routing lives")


def test_the_research_routing_clause_is_intact():
    """⛔⛔ DO NOT SOFTEN THIS. See the module docstring: 6db3c02 measured the
    defect, and the failure mode of getting it wrong is silent."""
    d = _description()
    assert re.search(r"NEVER answer a research or deep-dive request from your own\s+"
                     r"knowledge or with web search\s+—\s+ALWAYS invoke this skill instead",
                     d), d
    assert "whether the user types /sr or just asks in plain language" in d


def test_the_status_clause_no_longer_captures_every_status_question():
    """⭐ THE NARROWING. Bare "status?" still routes here — that IS the measured
    defect (6ddf62a: 'Status?' answered the runtime's own health mid-run) — but a
    question explicitly about the runtime is released."""
    d = _description()
    assert 'A bare "status?" or "how\'s it going?"' in d, d
    assert "with no other subject" in d
    assert "a question explicitly about your runtime is not" in d
    # ⛔ AND THE BLANKET FORM IS GONE
    assert "ANY status / progress question" not in d
    assert "never your runtime's own health, repos, or memory" not in d


def test_every_verb_the_skill_routes_still_appears():
    """⛔ THE TAIL IS THE FRAGILE PART — it is what truncation removes first, and
    it is where most of the routing surface lives. If a future edit grows the
    description past the ceiling, these vanish silently; this fails loudly."""
    d = _description()
    for kw in ("access code", "brief", "podcast", "audio overview", "video",
               "list past researches", "pause", "skip", "stop", "resume",
               "sign in", "Research Computers", "version", "welcome + help"):
        assert kw in d, f"routing keyword lost from the description: {kw!r}"


def test_the_two_unscoped_captures_survive_the_sign_in_and_devices_lead():
    """⛔⛔ THE 2026-09-24 SHARPENING MOVED SIGN-IN AND DEVICES INTO THE FIRST
    SENTENCE — AND ITS FIRST DRAFT QUIETLY TOOK TWO CAPTURES WITH IT. "ANY request
    to research a topic" became "ANY Super Research request — … or research a
    topic", which scopes 6db3c02's capture to a request that names the product; and
    the bare-code rule ("an 8-char access code … alone … always belongs here") was
    folded into an example. The add-a-computer line now ends "send me the
    8-character access code", so the person's NEXT message is usually the code on
    its own — the one message with no other word to route by."""
    d = _description()
    assert d.startswith("USE THIS SKILL for ANY request to research a topic"), d[:120]
    assert re.search(r"8-char access code[^.]*\beven alone\b[^.]*\balways belongs here",
                     d), d
