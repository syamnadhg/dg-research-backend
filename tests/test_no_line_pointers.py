"""No note in this repository may point at a line NUMBER. Name the thing instead.

⛔⛔ MEASURED BEFORE THIS FILE EXISTED (wave 10.10 cross-check, 2026-09-23).
217 notes here pointed somewhere by number — "see research.py" plus a colon and
a number, "line ~N", "(~N)", a bare colon-number. Of those sampled by hand,
EVERY ONE that pointed into research.py landed on unrelated code: a log-rotation
docstring for "the existence check", a prompt string, a `finally:`. The file
moves by thousands of lines a wave and nothing re-anchors a number, so each
pointer cost the next reader a wrong turn — and one measuring pass reported a
fixed defect as open because a note sent it to the wrong place.

The sweep replaced each with the name it meant (a function, closure, constant,
rule or web function). This file keeps the count at ZERO. It replaces
`test_region_comments_108.py`'s ratchet, which saw one form of the family
(42 of research.py's 141) and allowed 47.

⭐ WHAT IS READ is decided in `tests/_line_pointers.py`: comments, docstrings,
the `//` comments of the page JavaScript inside research.py's strings, and
prose files. Runtime strings are NOT read — a prompt, a log line or a fixture
is behaviour, and changing one to satisfy a guard would be a behaviour change.

⭐ THE EXEMPTIONS ARE A CLOSED LIST, BY FILE AND EXACT TEXT, dated 2026-09-23.
It may only shrink. Never exempt "any line with ⛔" — many of the wrong
pointers this sweep fixed sat on ⛔ lines.
"""
from __future__ import annotations

import functools
import subprocess
from pathlib import Path

import pytest

import _line_pointers as lp

ROOT = Path(__file__).resolve().parent.parent

#: Areas not read at all, with the reason each is out.
EXEMPT_AREAS = (
    ("agent/", "the chat assistant belongs to the owner's Windows session; its notes "
               "are left exactly as they are FOR NOW (wave 10.10) and it gets its own sweep"),
    (".mutants/", "harness anchors copy source text verbatim, and two mutants insert a "
                  "pointer on purpose to prove this guard kills them"),
    ("tests/fixtures/", "captured pages and golden data, not notes"),
)

#: (file, exact text, why). A hit is exempt only if its match lies inside the
#: text AND the text is in the note it came from. Every entry must still match
#: something (`test_every_exemption_is_still_needed`).
EXEMPTIONS = (
    ("requirements.txt", "research.py:8186",
     "a tombstone: it quotes the retired pointer it replaced, to say why names win"),
    ("research.py", "base_collection.py:317",
     "a third-party library's own warning (google-cloud-firestore), quoted as evidence"),
    ("research.py", "watch.py:572",
     "a third-party traceback frame (firestore_v1), quoted as evidence"),
    ("research.py", "documents/chatgpt.md:574",
     "a line of a run's own OUTPUT file, quoted as the evidence of a misclick"),
    ("tests/test_chatgpt_panel_prose_0806.py", "documents/chatgpt.md:574",
     "the same run-output line, quoted in the test that pins the fix"),
    ("docs/jira/DGOPS-7337-create-main-default.md", "lines 220",
     "a section of ANOTHER repository's document, cited as the ticket's source"),
)
#: ⛔ THE LIST MAY ONLY SHRINK. Raising this number is a decision to keep a
#: pointer; name the thing instead.
EXEMPTION_CEILING = 6


def _tracked_files() -> "list[str]":
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True,
                             text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        # ⛔ A FAIL, NOT A SKIP: a guard that skips where it cannot look reads as
        # a pass everywhere it cannot look.
        pytest.fail(f"cannot list the repository's files ({e}) — this guard needs a git checkout")
    return [f for f in out.splitlines()
            if f and not any(f.startswith(area) for area, _ in EXEMPT_AREAS)]


@functools.lru_cache(maxsize=1)
def _all_hits() -> "tuple[lp.Hit, ...]":
    hits = []
    for rel in _tracked_files():
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        hits.extend(lp.find_in_file(rel, text))
    return tuple(hits)


def _exemption_for(hit):
    for entry in EXEMPTIONS:
        path, text, _why = entry
        if hit.path == path and hit.match in text and text in hit.block:
            return entry
    return None


# ══ 1. the tree ═══════════════════════════════════════════════════════════
def test_no_note_points_at_a_line_number():
    """The ceiling is ZERO, over every form. Each failure line names the file,
    the note's first line, the form and the text; the fix is always to write
    the NAME of what the number meant (and, when the number cannot be resolved
    any more, to say what the note means without it)."""
    bad = [h for h in _all_hits() if _exemption_for(h) is None]
    assert not bad, (
        f"{len(bad)} note(s) point at a line number. Name the function, class, "
        "constant, rule or test instead — a number drifts on the next edit:\n  "
        + "\n  ".join(str(h) for h in bad[:40]))


def test_the_guard_read_the_repository_and_not_nothing():
    """⛔ A GUARD MUST NOT BE ABLE TO PASS BY LOOKING AT NOTHING. If the file
    listing, the scanner or the note finder broke, the test above would pass on
    an empty list; this pins that it read the big file and a lot of notes."""
    files = _tracked_files()
    assert "research.py" in files and len(files) > 300, len(files)
    notes = lp.python_notes((ROOT / "research.py").read_text(encoding="utf-8"))
    assert len(notes) > 5000, f"only {len(notes)} notes found in research.py"


def test_every_exemption_is_still_needed():
    """An entry that matches nothing is a stale licence for the next pointer
    written in its file. Delete it."""
    used = {_exemption_for(h) for h in _all_hits()} - {None}
    stale = [e[:2] for e in EXEMPTIONS if e not in used]
    assert not stale, f"exemptions that match nothing any more — delete them: {stale}"


def test_an_exemption_covers_its_own_file_only():
    """⛔ The text of an exemption is not a licence anywhere else: the same
    quoted pointer written into another file is a new pointer."""
    path, text, _why = EXEMPTIONS[0]
    here = lp.Hit(path, 1, "file:N", text, "quoted: " + text)
    elsewhere = lp.Hit("README.md", 1, "file:N", text, "quoted: " + text)
    assert _exemption_for(here) is not None
    assert _exemption_for(elsewhere) is None


def test_the_exemption_list_only_shrinks():
    assert len(EXEMPTIONS) <= EXEMPTION_CEILING, (
        "an exemption was added. Name the thing instead; a number drifts")
    assert [a for a, _ in EXEMPT_AREAS] == ["agent/", ".mutants/", "tests/fixtures/"]


# ══ 2. accept polarity: every form is caught ══════════════════════════════
# ⛔ Built by concatenation so THIS file carries no pointer of its own.
# ⭐ Each form has at least one example ONLY it can catch (the short numbers,
# the `L` and `#L` anchors, the bare `@`), so dropping any single form from the
# finder turns a case here red — which the wave 10.10 harness proves.
N = "12345"
POINTERS = [
    "see research.py:" + N,
    "firestore.rules:" + "45-49 has the rule",
    "(app)/layout.tsx:" + "733",
    "research.py:~" + N,
    "route.ts#L" + "120",
    "the gate at research.py line " + N,
    "`research.py` ~line " + N,
    "vision.py, line " + "269",
    "setup.py line " + "9",
    "emit_decision (research.py ~" + N + ")",
    "research.py (~" + N + ")",
    "vision.py ~" + "269",
    "see #L" + "120 of the route",
    "rules:" + "324 says so",
    "(usePipeline:" + "3063)",
    "the sweep at line ~" + N,
    "(~line " + N + ")",
    "see lines " + "1916-1918",
    "the dispatcher at :" + N,
    "(:" + "7718)",
    "fixed at ~:" + N,
    "the clear seam (~" + N + ") never fires",
    "the cleanup (~" + "596) here",
    "see ~" + N + " and",
    "see ~" + "596 and",
    "backstop @ " + N + ",",
    "reload @~" + N + ", switch",
    "scrape_progress_gemini ~" + N + "), so",
]


@pytest.mark.parametrize("text", POINTERS)
def test_every_form_is_caught(text):
    assert lp.find_in_text(text), f"a pointer the guard does not see: {text!r}"


# ══ 3. quiet polarity: what only LOOKS like a pointer ═════════════════════
LOOK_ALIKES = [
    "the server on :8000 still answered",
    "lsof -ti :8000 matches both ends",
    "http://localhost:8000/api/health",
    "0.0.0.0:8000 LISTENING",
    "Expecting value: line 1 column 1 (char 0)",
    "Expecting property name enclosed in double quotes: line 7 column 1",
    'File "/x/firestore_v1/watch.py", line 572, in push',
    "Observable in BE log line 37642 at 09:08:58",
    "backend.log 49728 shows it",
    "line 01999 padded out",
    "412 lines  33.9% of BYTES",
    "a ~400-character WARNING on every retry",
    "~250 of them across 50 files",
    "~1160 lines of the self-heal registry",
    "writes ~600 KB containing all three",
    "requests raises here at ~300 s",
    "at ~10 frames/sec",
    "~2000-char chunks",
    "~5-6K chars",
    "text[:200] to meta.json",
    "`[:140]` ran before the gate",
    "send at ~07:02, conversation 6a72ce1e",
    "≈267px at 1280, gate demanded ≥280",
    "0600 whatever the umask, 0755 → 0700",
    "version 0.1.33 on 2026-09-23 at 18:13:28",
    "RFC 2606 reserves .invalid",
    "#723 read fast-path, #955 Phase 5",
    "every line after the 500th",
    "`--help` puts SUPER RESEARCH on line 4",
    "exit code 143 for SIGTERM",
]


@pytest.mark.parametrize("text", LOOK_ALIKES)
def test_a_look_alike_is_not_a_pointer(text):
    assert lp.find_in_text(text) == [], f"flagged a look-alike: {lp.find_in_text(text)}"


# ══ 4. where the notes are ════════════════════════════════════════════════
def _src(*lines):
    return "\n".join(lines) + "\n"


def test_a_pointer_is_found_in_every_place_a_note_lives():
    js = "/" + "/"
    ptr = "research.py:" + N
    src = _src(
        f"# a comment naming {ptr}",
        "def f():",
        f'    """a docstring naming {ptr}"""',
        f'    PAGE_JS = """() => {{ {js} a page-JS note naming {ptr}',
        '        return 1; }"""',
        "    # a pointer split over a line break (~line",
        f"    # {N}) is still one pointer",
        "    return PAGE_JS",
    )
    lines = {line for line, _block in lp.python_notes(src)
             if lp.find_in_text(_block)}
    assert lines == {1, 3, 4, 6}, lines


def test_runtime_text_is_not_a_note():
    """⛔ A prompt, a log line or an assertion message is behaviour. The guard
    must not demand an edit there — that would be a behaviour change to satisfy
    a comment rule."""
    src = _src(
        "def f():",
        "    x = 1",
        f'    log("see research.py:{N}")',
        f'    return "the prompt names research.py:{N}"',
    )
    assert [b for _l, b in lp.python_notes(src) if lp.find_in_text(b)] == []


def test_a_prose_paragraph_is_read_across_its_line_breaks():
    text = "Alerts go through `emit_decision` (research.py\n~" + N + ") today.\n\nNext.\n"
    assert lp.find_in_file("README.md", text)
    assert lp.find_in_file("README.md", "Alerts go through `emit_decision`.\n") == []


def test_a_json_file_is_data_not_notes():
    assert lp.find_in_file("bundle-contract.json", '{"note": "research.py:' + N + '"}') == []


# ══ 5. the security note that outlived the code ═══════════════════════════
def test_no_note_says_the_local_server_binds_every_interface():
    """⛔ It has bound 127.0.0.1 behind `ServeTokenMiddleware` since 2026-09-05,
    and two notes said the opposite for a month after one copy was fixed. A
    note describing a security posture the code no longer has is how a later
    edit talks itself into restoring it. Past-tense history is fine; the
    present-tense claim is not."""
    src = (ROOT / "research.py").read_text(encoding="utf-8")
    bad = [(line, block[:120]) for line, block in lp.python_notes(src)
           if lp.BIND_EVERYWHERE.search(block)]
    assert not bad, f"a note says the local server binds every interface: {bad}"


def test_the_phrase_is_caught_across_a_line_break():
    src = _src("# on a local server that binds every", "# interface with no auth", "x = 1")
    assert any(lp.BIND_EVERYWHERE.search(b) for _l, b in lp.python_notes(src))
    assert not lp.BIND_EVERYWHERE.search("it listened on every interface when this was written")
