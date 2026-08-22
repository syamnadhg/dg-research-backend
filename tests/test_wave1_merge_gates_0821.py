"""Wave 1 (2026-08-21) — the merge-gating batch, backend half.

Three of the four things below are COMMENTS, and that is the point rather than an
apology. Every one of them told a reader something the code does not do, and in
this codebase a confident wrong comment has cost more than a missing one: the
reviewer's questions were answered from them, and one of our own replies to the
review repeated a claim the source contradicts.

⛔⛔ THE CLAIM THAT WAS FALSE TWICE. `pick_highest_model`'s docstring said the
flag is opt-in "so this stays a true mirror of every JS ranker that CALLS it: the
Claude ranker ports the rule and PASSES it". No JS can call a Python function —
a ranker is a string handed to `page.evaluate` — and no production Python calls
that function at all. A second comment in research.py presented
`pick_highest_model(..., drop_upsell=True)` as a live counterpart to the browser
code; that call form exists only in tests.

⭐ SO THE PINS BELOW ARE FALSIFIABLE, not decorative. Each one fails the day the
thing it describes changes — the day somebody ports the upsell rule to the Gemini
ranker, or wires a production caller — which is the only kind of comment test
worth having. A test that merely greps for today's wording would pass forever and
protect nothing.
"""
import ast
import inspect
import re

import research
import models


# ══ 1. the model-helper claims ═════════════════════════════════════════
def _without_historical_notes(doc: str) -> str:
    """Drop the parenthetical "this used to say X, and X was wrong" notes.

    ⛔⛔ A TRAP THIS REPO HAS ALREADY FALLEN INTO. The correction QUOTES the false
    claim in order to explain it, so a plain `"calls it" not in doc` fails
    against the fixed docstring and passes against… nothing useful. The sibling
    harness for the supervisor PATH work hit the identical problem and solved it
    the same way. Only the ASSERTIVE prose is checked; the history is exempt."""
    return re.sub(r"\(20\d\d-\d\d-\d\d:.*?\)", "", doc, flags=re.S)


def test_the_docstring_does_not_claim_a_caller_it_does_not_have():
    doc = _without_historical_notes(models.pick_highest_model.__doc__ or "")
    assert "calls it" not in doc, (
        "the docstring is claiming a JS caller again — a `page.evaluate` string "
        "cannot call into Python")
    assert "passes it" not in doc
    # And the stripper must actually have something to strip, or this test
    # silently becomes a check against the raw docstring.
    assert "calls it" in (models.pick_highest_model.__doc__ or ""), (
        "the historical note is gone, so this test no longer proves the "
        "stripper works — re-point it at whatever records the old wording")
    assert "NO PRODUCTION CALLER" in doc, (
        "the docstring no longer states the one fact a reader most needs: "
        "selection happens in the browser and this is the spec, not a code path")
    assert "PORTED" in doc or "ported" in doc


def test_nothing_in_production_calls_the_model_helper():
    """⛔ THE PIN THAT MAKES THE DOCSTRING FALSIFIABLE. If a production caller
    ever appears, "NO PRODUCTION CALLER" becomes the new false comment — so this
    fails and forces the wording to move with the code."""
    offenders = []
    for mod in ("research", "models", "vision", "narrate", "prompts"):
        try:
            src = inspect.getsource(__import__(mod))
        except Exception:
            continue
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name == "pick_highest_model":
                offenders.append(f"{mod}:{node.lineno}")
    assert not offenders, (
        "`pick_highest_model` now has a caller in module code — the docstring "
        f"says it has none: {offenders}")


def test_only_the_claude_ranker_ports_the_upsell_rule():
    """⭐ THE FALSIFIABLE HALF. The flag is opt-in *because* the two rankers
    disagree. The day the Gemini ranker ports the rule, that reasoning is stale
    and the default should be revisited — so this fails then, deliberately."""
    claude_js = _js_constant(research.setup_claude_dr, "_pick_opus_js")
    gemini_js = research._GEMINI_FLASH_RANK_JS
    assert "isUpsell" in claude_js, (
        "the Claude picker no longer carries the upsell port the docstring "
        "credits it with")
    assert "isUpsell" not in gemini_js, (
        "the Gemini ranker now has an upsell rule — `drop_upsell`'s opt-in "
        "reasoning and the docstring that explains it both need revisiting")


def test_the_claude_port_is_handed_this_modules_word_list():
    """"Read the SAME list" is the one surviving claim of the old paragraph, so
    it gets a pin of its own rather than being taken on trust."""
    src = inspect.getsource(research.setup_claude_dr)
    assert "list(UPSELL_VERBS)" in src
    assert "UPSELL_WINDOW" in src
    assert re.search(r"UPSELL_VERBS\s*=", inspect.getsource(models))


def test_no_comment_describes_the_reverted_family_first_exemption_as_present():
    """⛔ The picker JS carried the REASONING for an exemption that was tried and
    reverted 2026-08-14, sitting directly above code that has none — and its
    worked example ("Opus 5 — try Opus with extended thinking") is classified the
    OTHER way by the code beneath it."""
    js = _js_constant(research.setup_claude_dr, "_pick_opus_js")
    assert "the first mention of the family is describing a row" not in js, (
        "the orphaned exemption comment is back")
    assert "NO \"FAMILY NAMED FIRST\" EXEMPTION" in js, (
        "the anti-regression note is gone — deleting the comment outright loses "
        "the record of why the exemption must not be re-added")


def _js_constant(fn, name: str) -> str:
    """The value of a `name = \"\"\"…\"\"\"` assignment inside `fn`.

    Read out of the REAL function source, so this cannot drift from the string
    production hands to the browser."""
    src = inspect.getsource(fn)
    tree = ast.parse(inspect.cleandoc("if True:\n" + src) if False else src.lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for t in node.targets:
                if getattr(t, "id", None) == name:
                    return str(node.value.value)
    raise AssertionError(f"{name} is no longer a string constant in {fn.__name__}")


# ══ 2. the systemd unit says what its PATH does ════════════════════════
def test_the_generated_unit_explains_its_own_path_ordering():
    """⭐ IN THE FILE, NOT IN THE SOURCE. The trade-off is explained three times
    in Python comments and a docstring — none of which reach the text
    `systemctl --user cat` prints, which is the only thing an administrator
    reading this machine will ever see."""
    unit = _unit_template()
    body = [ln for ln in unit.splitlines() if ln.startswith("#")]
    assert body, "the generated unit carries no comment at all"
    joined = "\n".join(body)
    assert "PATH" in joined
    assert "shadow" in joined.lower(), (
        "the note no longer names the actual consequence — that a binary in a "
        "user-writable directory wins for every supervised child")


def test_the_unit_note_does_not_promise_the_interpreter_is_shadowable():
    """The one thing that must stay accurate: ExecStart is absolute."""
    unit = _unit_template()
    assert "ExecStart=" in unit
    note = "\n".join(ln for ln in unit.splitlines() if ln.startswith("#"))
    assert "absolute" in note.lower()


def test_the_unit_note_cannot_break_the_f_string_or_the_macos_pin():
    """⛔⛔ TWO CONSTRAINTS THE OBVIOUS WORDING VIOLATES. The note lives inside an
    f-string, so a stray brace either raises at format time — before the `try`
    that would have caught it, on the `--resurrect` path — or silently
    interpolates. And a macOS test asserts the word "Library" is absent from this
    function's RAW source, comments included."""
    src = inspect.getsource(research._arm_supervisor_linux)
    note_lines = [ln for ln in src.splitlines()
                  if ln.lstrip().startswith("#") and "PATH" in ln.upper()]
    assert note_lines, "the unit note is gone from the source"
    for ln in note_lines:
        assert "{" not in ln and "}" not in ln, (
            f"a brace inside the unit f-string: {ln}")
    assert "Library" not in src, (
        "the macOS relocation pin greps this function's raw source for "
        "'Library' — a comment reintroduced it")


def _unit_template() -> str:
    src = inspect.getsource(research._arm_supervisor_linux)
    m = re.search(r'unit_content = f"""(.*?)"""', src, re.S)
    assert m, "the unit template is no longer a single f-string literal"
    return m.group(1)


# ══ 3. the queue rule guards a DIFFERENT field than the one we read ════
def test_the_queue_comment_no_longer_claims_the_rule_validates_uid():
    """⛔⛔ The comment above the start-path identity read asserted that "uid
    validation is enforced server-side by the Firestore queue rule
    (`submittedBy == request.auth.uid`)". The rule pins `submittedBy`; the line
    above it reads `uid`, which the rules leave unconstrained. A reviewer asking
    "is this identity trusted?" was answered wrongly by our own source."""
    src = inspect.getsource(research)
    assert "uid validation is enforced server-side by the Firestore queue" not in src, (
        "the false claim is back")
    idx = src.find("WHAT THE RULE PINS IS NOT WHAT WE JUST READ")
    assert idx > 0, "the correction is gone"
    window = src[idx:idx + 1400]
    assert "unconstrained" in window
    # The half that IS true must survive the correction — membership really is
    # enforced, and saying otherwise would be the same error in the other
    # direction.
    assert "deviceWritingTo" in window
    assert "sharedWith" in window


def test_the_start_path_still_reads_the_field_the_comment_describes():
    """A comment about `uid` is only correct while the code reads `uid`. If the
    read is ever moved to `submittedBy` — which is the real fix, deferred out of
    this wave — this fails and takes the comment with it."""
    src = inspect.getsource(research)
    idx = src.find("WHAT THE RULE PINS IS NOT WHAT WE JUST READ")
    assert idx > 0
    before = src[max(0, idx - 1200):idx]
    assert 'uid = data.get("uid", "")' in before, (
        "the start path no longer reads `uid` — the correction above it now "
        "describes something else")
