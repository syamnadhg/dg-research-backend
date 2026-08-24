"""Cross-verification of waves 3-6, 2026-08-24 — the backend half.

⛔ THESE FOUR WAVES WERE NEVER REVIEWED. They were mutation-tested and green,
and every defect below passed that. Wave 1's review found four; wave 7's found
thirteen; this one found fifteen across both repos. The pattern that keeps
recurring is not a wrong algorithm — it is a confident comment above code that
does something slightly different, and a test written from the comment.
"""
import re

import research


class TestTrailingPunctuationOnASourceUrl:
    """⛔ `rstrip('.,;:)')` truncated a legitimately parenthesised path.

    Every candidate ran through it, including the panel's own already-clean
    urls. `…/wiki/Mercury_(planet)` became `…/wiki/Mercury_(planet`, the lookup
    still matched (it is a prefix of the report text) so a finding was still
    emitted — carrying a url that 404s. Worse than dropping it, because it
    looks right.
    """

    def test_a_balanced_closing_bracket_survives(self):
        u = "https://en.wikipedia.org/wiki/Mercury_(planet)"
        assert research._find_trim_trailing_punct(u) == u

    def test_sentence_punctuation_still_goes(self):
        f = research._find_trim_trailing_punct
        assert f("https://example.com/a.") == "https://example.com/a"
        assert f("https://example.com/a,") == "https://example.com/a"
        assert f("https://example.com/a;") == "https://example.com/a"
        assert f("https://example.com/a:") == "https://example.com/a"

    def test_an_UNbalanced_closing_bracket_still_goes(self):
        # "(see https://example.com/a)" — the bracket belongs to the sentence.
        f = research._find_trim_trailing_punct
        assert f("https://example.com/a)") == "https://example.com/a"
        assert f("https://example.com/a),") == "https://example.com/a"
        assert f("https://example.com/x));") == "https://example.com/x"

    def test_an_inner_bracket_pair_is_untouched(self):
        u = "https://example.com/a(b)c"
        assert research._find_trim_trailing_punct(u) == u

    def test_it_survives_an_empty_or_missing_value(self):
        assert research._find_trim_trailing_punct("") == ""
        assert research._find_trim_trailing_punct(None) == ""

    def test_the_caller_uses_it_rather_than_rstripping_itself(self):
        # ⭐ A correct helper beside a consumer that ignores it is this repo's
        # most repeated defect, and the consumer here cannot be executed
        # without a whole report.
        text = open(research.__file__, encoding="utf-8").read()
        assert 'u = _find_trim_trailing_punct((u or "").strip())' in text
        # ⛔ CODE ONLY, and that is its own small lesson: the helper's
        # docstring QUOTES the old expression to record what changed, so an
        # unscoped search matches the EXPLANATION and the test goes red for a
        # reason it is not about. Only an assignment counts as a use.
        offenders = [
            ln.strip() for ln in text.splitlines()
            if "rstrip(" in ln and ".,;:)" in ln and "=" in ln.split("#")[0]
        ]
        assert offenders == [], offenders


class TestTheReportCaptureDoesNotTruncateFirst:
    """⛔⛔ THE TRIMMER COULD NOT REACH THE REPORT-EXTRACTED HALF.

    `_FIND_BARE_URL_RE` excluded `)` from the match, so a parenthesised path was
    truncated at CAPTURE time — before any trimming ran, and no later trimming
    can undo it. So the fix for the rstrip defect covered the panel-supplied
    urls and left the report ones exactly as broken. Found by the completeness
    critic, after the first fix was already committed.

    The layering is now capture-greedily, trim-by-balance.
    """

    def test_a_parenthesised_path_survives_the_capture(self):
        found = research._FIND_BARE_URL_RE.findall(
            "See https://en.wikipedia.org/wiki/Mercury_(planet) for more.")
        assert found == ["https://en.wikipedia.org/wiki/Mercury_(planet)"]

    def test_and_the_trimmer_keeps_it_whole(self):
        found = [research._find_trim_trailing_punct(u)
                 for u in research._FIND_BARE_URL_RE.findall(
                     "See https://en.wikipedia.org/wiki/Mercury_(planet) for more.")]
        assert found == ["https://en.wikipedia.org/wiki/Mercury_(planet)"]

    def test_a_sentence_bracket_is_still_dropped(self):
        # The reason `)` was excluded in the first place — handled one layer
        # down now, by balance rather than by exclusion.
        found = [research._find_trim_trailing_punct(u)
                 for u in research._FIND_BARE_URL_RE.findall(
                     "(see https://example.com/a) and more")]
        assert found == ["https://example.com/a"]

    def test_the_other_delimiters_are_untouched(self):
        # Guard against the guard: widening the class must not have emptied it.
        for probe, want in [
            ('<a href="https://example.com/c">x', ["https://example.com/c"]),
            ("[https://example.com/d]", ["https://example.com/d"]),
            ("https://example.com/e https://example.com/f",
             ["https://example.com/e", "https://example.com/f"]),
        ]:
            got = [research._find_trim_trailing_punct(u)
                   for u in research._FIND_BARE_URL_RE.findall(probe)]
            assert got == want, (probe, got)


class TestTheDoctorHandsOverOnEveryPath:
    """⛔ The hand-over line claimed to close every doctor run, and one early
    return skipped it — the unsupported-platform branch, whose reader is the
    one who can be told least else."""

    def test_the_unsupported_branch_prints_the_hand_over(self):
        src = _source_of(research.run_doctor)
        branch = src[src.index('if plat == "Unsupported"'):]
        branch = branch[: branch.index("_ok(f\"Platform:")]
        assert "_doctor_share_logs_line()" in branch, (
            "the unsupported-platform branch returns without the hand-over"
        )

    def test_and_it_is_the_only_early_return(self):
        # ⭐ Guard against the guard: a SECOND early return added later would
        # reintroduce the same gap somewhere this test does not look.
        # ⛔⛔ THIS GUARD COULD NOT FIRE, and cross-verification caught it. The
        # regex was `^\s{4}return\b` — a return indented exactly four spaces,
        # i.e. an UNCONDITIONAL one at the top of the body. Every real early
        # return sits inside an `if` at eight, INCLUDING the one this test was
        # written about: measured against the live file it counted zero, so
        # `<= 1` passed vacuously and a second early return would have too.
        # Parsed rather than pattern-matched now, so indentation cannot hide one.
        import ast, textwrap
        tree = ast.parse(textwrap.dedent(_source_of(research.run_doctor)))
        fn = tree.body[0]
        returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
        assert len(returns) == 1, (
            f"run_doctor has {len(returns)} returns; every one needs the "
            f"hand-over before it, and only the unsupported-platform branch is "
            f"covered by the test above"
        )


def _source_of(fn):
    import inspect
    return inspect.getsource(fn)
