"""A log line that was false, and the sources it cost.

⛔⛔ THE QUEUE-GATE HALF OF THIS FILE IS GONE (wave 10.9, N8). It pinned the
wording and the branch order of `_wait_for_prior_fe_completion` — the wait that
held the next dequeue behind the PREVIOUS run's cloud tail — and that function
has been deleted, because phases 4 and 5 run on Cloud Run and there was never
anything on this machine for the next run to contend with. Its own log lines
were the tell: a 70-minute wait announced and abandoned in the same second, then
a "force-dequeue" apologising for holding somebody up. What replaces those pins
is `tests/test_handoff_is_the_end_109.py`, which executes the start listener and
measures that an idle worker starts a run immediately whatever the previous run
is doing.

The vision-URL half below is untouched and unrelated; it shares this file only
because the two fixes shipped together.

THE VISION URL EXTRACTOR RAN OUT OF TOKENS AND CALLED IT A PARSE ERROR

    [chatgpt] vision-urls call/parse error: Expecting value: line 2 column 10
    [chatgpt] vision-urls call/parse error: Expecting property name enclosed in
              double quotes: line 7 column 1

Both runs, both agents. That is not malformed JSON, it is JSON that stops. The
cause is one narrate.py already found and fixed on 2026-08-05: `thinkingConfig`
was removed because the live endpoint rejects it, so reasoning tokens now come
out of `maxOutputTokens`. narrate.py raised its ceiling 600 → 1400 for a
sentence of prose. This call site returns a list of full URLs and stayed at 800.

Every source in the panel was discarded each time, because the parse failure
returned an empty list. That is the same shape as the 08-06 bug that threw away
56% of the activity panel's sources: one late failure discarding a batch that
was overwhelmingly fine.

WHAT THESE TESTS PIN

  1. The token ceiling is above narrate's, and the response's `finishReason` is
     named when the JSON does not parse.
  2. Whole URLs survive a truncated response; a clipped one never does.
"""
import ast
import inspect
import io
import functools
import re
import textwrap
import tokenize

import pytest

import research


@functools.lru_cache(maxsize=8)
def code_only(src: str) -> str:
    """`src` with comments blanked, offsets preserved. Several assertions here
    are about text that the comments explaining the fix also quote."""
    out = list(src)
    starts, pos = [], 0
    for line in src.splitlines(keepends=True):
        starts.append(pos)
        pos += len(line)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type != tokenize.COMMENT:
                continue
            (srow, scol), (erow, ecol) = tok.start, tok.end
            if srow != erow or srow > len(starts):
                continue
            line_start = starts[srow - 1]
            for i in range(line_start + scol, min(line_start + ecol, len(out))):
                out[i] = " "
    except (tokenize.TokenError, IndentationError):
        return src
    return "".join(out)


@functools.lru_cache(maxsize=1)
def vision_src() -> str:
    """The vision-URL extractor body, comments blanked — from its request
    payload through the filter that every returned URL passes."""
    src = code_only(inspect.getsource(research))
    start = src.index('"responseSchema": _VISION_URL_SCHEMA')
    start = src.rindex("    payload = {", 0, start)
    end = src.index("    return filtered[:_SOURCE_LIST_CAP]") + 60
    return src[start:end]


# --------------------------------------------------------- vision URLs


def test_the_token_ceiling_covers_reasoning_plus_a_list_of_urls():
    """narrate.py needed 1400 for one sentence once thinking stopped being
    disabled. A list of full URLs cannot be smaller than that.

    2026-08-12: the literal became a named constant when the read timeout was
    paired to it (test_vision_url_budget_0812). Resolved through the constant so
    this still reads the value the request actually sends."""
    src = code_only(inspect.getsource(research))
    name = re.search(r'"maxOutputTokens": (\w+),\s*\n\s*"responseMimeType": "application/json",'
                     r'\s*\n\s*"responseSchema": _VISION_URL_SCHEMA', src).group(1)
    ceiling = getattr(research, name)
    assert ceiling > 1400, (
        f"vision-urls asks for a list of URLs on {ceiling} tokens while narrate "
        f"needs 1400 for a sentence — this is the 08-11 truncation"
    )


def test_a_truncated_response_is_reported_as_truncated_not_as_a_parse_error():
    src = vision_src()
    assert "vision-urls response was not complete JSON" in src
    assert "finishReason=" in src
    assert "vision-urls call/parse error" not in src


def test_the_finish_reason_is_read_from_the_candidate():
    """Without it the log cannot distinguish a token ceiling from a safety stop
    or a malformed prompt."""
    src = vision_src()
    assert '_finish = _cand.get("finishReason") or ""' in src


def test_only_the_json_decode_is_caught_by_the_salvage_branch():
    """A network error must not be reported as a truncated response."""
    src = vision_src()
    assert "except ValueError as _je:" in src


def test_the_handler_actually_calls_the_salvage():
    """⭐ Every other test here exercises the helper directly, so all of them
    still pass when the call site is replaced with an empty list — the helper
    would be perfect and unreachable. Read the assignment off the syntax tree."""
    tree = ast.parse(textwrap.dedent(vision_src()))
    calls = [
        getattr(n.value.func, "id", None)
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and any(getattr(t, "id", "") == "_salvaged" for t in n.targets)
    ]
    assert calls == ["_salvage_urls_from_truncated_json"], (
        f"_salvaged is built from {calls!r} — the recovery is not wired in"
    )


@pytest.mark.parametrize("text,expected", [
    # a clean array that simply stops
    ('{"urls": ["https://a.example/x", "https://b.example/y", "https://c.exa',
     ["https://a.example/x", "https://b.example/y"]),
    # stops immediately after the opening bracket
    ('{"urls": [', []),
    # stops right after a complete entry's comma
    ('{"urls": ["https://only.example/1",', ["https://only.example/1"]),
    # http as well as https
    ('{"urls": ["http://plain.example/p", "http://cut.example', ["http://plain.example/p"]),
    # nothing at all
    ("", []),
    ("   ", []),
])
def test_whole_urls_are_salvaged_and_clipped_ones_are_not(text, expected):
    """⭐ The clipped LAST entry is the one that must never come through — a
    half-URL in the report is worse than a missing one."""
    assert research._salvage_urls_from_truncated_json(text) == expected


def test_the_salvage_keeps_panel_order():
    text = '{"urls": ["https://one.example/a", "https://two.example/b", "https://three.exam'
    assert research._salvage_urls_from_truncated_json(text) == [
        "https://one.example/a", "https://two.example/b"]


def test_the_salvage_ignores_non_url_strings():
    """The object also carries schema keys and prose; only URLs may come out."""
    text = '{"confidence": 0.8, "note": "some sources", "urls": ["https://real.example/z", "not-a-url'
    assert research._salvage_urls_from_truncated_json(text) == ["https://real.example/z"]


def test_the_salvage_rejects_an_absurdly_long_string():
    """The parsed path caps URLs at 500 chars; the salvage must not be a way
    around that cap."""
    long_url = "https://x.example/" + ("a" * 600)
    assert research._salvage_urls_from_truncated_json(f'{{"urls": ["{long_url}"') == []


def test_salvaged_confidence_clears_the_floor_that_gates_the_result():
    """A truncated object never reaches its trailing `confidence` field, so the
    salvage supplies one. If it fell below the 0.4 gate the recovery would be
    silently thrown away again — which is the bug, not the fix."""
    assert research._VISION_URL_SALVAGE_CONFIDENCE > 0.4


def test_salvaged_confidence_does_not_claim_a_clean_read():
    """0.7+ is what the prompt reserves for URLs the model says it read
    clearly. We never saw its verdict."""
    assert research._VISION_URL_SALVAGE_CONFIDENCE < 0.7


def test_an_empty_salvage_reports_no_confidence_at_all():
    """Otherwise a total failure would present as a 0.5-confidence empty read."""
    src = vision_src()
    assert "_VISION_URL_SALVAGE_CONFIDENCE if _salvaged else 0.0" in src


def test_salvaged_urls_still_go_through_the_platform_filter():
    """They return through the same value the parsed path returns, so the
    scheme / length / chrome-domain filter below applies unchanged."""
    src = vision_src()
    ret = src.index("return _salvaged,")
    filt = src.index("if any(d in u.lower() for d in _VISION_URL_SKIP_DOMAINS):")
    assert ret < filt
