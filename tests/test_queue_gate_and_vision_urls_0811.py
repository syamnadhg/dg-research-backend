"""Two log lines that were false, and the sources one of them cost.

THE QUEUE GATE ANNOUNCED A 70-MINUTE WAIT AND ENDED IT IN THE SAME SECOND

    15:57:38 [queue-gate] waiting for prior run … FE-P5 completion (fallback in 4200s)
    15:57:38 [queue-gate] FE never reported completed in 4200s — force-dequeueing

Both lines are wrong, and they are wrong for the same reason. The deadline is
anchored to when the PRIOR run finished (`last_be_done_at`), not to when the
gate opened. On a device that has been idle longer than the window — the normal
case, since the owner starts the next run hours later — the deadline is already
in the past, so the first line's "4200s" was really a negative number and the
second line's "in 4200s" was really "two and a half hours ago".

The second line also asserted the one thing the gate had not checked. The
deadline test was the FIRST statement in the poll loop, so it returned before
the loop had read the prior research doc even once. The prior run was sitting
right there at `status="completed"`; had the read happened first, the gate
would have logged `prior run terminal (status=completed) — dequeueing`, which
is both accurate and the branch that already existed.

So: the read moved above the deadline test, and both messages now quote elapsed
time they actually measured. Behaviour is unchanged — the gate still releases —
except that it now usually releases for the accurate reason.

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

  1. The gate reads before it gives up, and every message quotes a measured
     number rather than the constant.
  2. ⭐ The gate still releases on every terminal signal it released on before —
     this fix must not make a worker wait where it used to proceed.
  3. The token ceiling is above narrate's, and the response's `finishReason` is
     named when the JSON does not parse.
  4. Whole URLs survive a truncated response; a clipped one never does.
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
def gate_src() -> str:
    """The queue-gate wait function, comments blanked.

    It is a closure inside the serve body, so it is reached through the module
    source rather than `inspect.getsource` on the function object."""
    src = code_only(inspect.getsource(research))
    start = src.index('log(f"[queue-gate] waiting for prior run')
    # Walk back to the enclosing def so the whole body is in view.
    head = src.rindex("    async def ", 0, start)
    end = src.index("    async def _rescan_queue_for_unclaimed", start)
    return src[head:end]


@functools.lru_cache(maxsize=1)
def vision_src() -> str:
    """The vision-URL extractor body, comments blanked — from its request
    payload through the filter that every returned URL passes."""
    src = code_only(inspect.getsource(research))
    start = src.index('"responseSchema": _VISION_URL_SCHEMA')
    start = src.rindex("    payload = {", 0, start)
    end = src.index("    return filtered[:_SOURCE_LIST_CAP]") + 60
    return src[start:end]


# ------------------------------------------------------------- queue gate


def test_the_gate_reads_the_prior_doc_before_it_gives_up():
    """⭐ THE BUG. With the deadline test first, an expired deadline returned
    before a single read — so the gate reported that the FE had never written
    `completed` for a run whose doc said exactly that."""
    src = gate_src()
    read = src.index("snap = await asyncio.to_thread(_doc_ref.get)")
    giveup = src.index("force-dequeueing")
    assert read < giveup, (
        "the deadline test is back above the status read; an already-expired "
        "deadline will again return without ever looking at the prior run"
    )


def test_the_gate_no_longer_claims_a_wait_it_did_not_perform():
    """The exact false sentence, gone. Comment-blanked, because the paragraph
    above the fix quotes it while explaining it."""
    src = gate_src()
    assert "FE never reported completed in" not in src


def test_the_entry_line_quotes_measured_time_not_the_constant():
    """`fallback in {BE_PHASES_TIMEOUT_SEC}s` was true only on the first run
    after a reboot."""
    src = gate_src()
    assert "_gate_left_ms = deadline - int(time.time() * 1000)" in src
    assert "fallback in {int(_gate_left_ms / 1000)}s" in src
    assert "fallback in {BE_PHASES_TIMEOUT_SEC}s" not in src


def test_an_already_expired_window_says_so_instead_of_pretending_to_wait():
    src = gate_src()
    assert "if _gate_left_ms > 0:" in src
    assert "not waiting" in src


def test_the_giveup_line_reports_elapsed_time_it_measured():
    """And says only what it observed: no terminal status SEEN. It cannot claim
    the FE never wrote one — on a failed read it never looked."""
    src = gate_src()
    assert "{int((now_ms - _pdone) / 1000)}s past its backend finish" in src
    # The phrase is split across two adjacent literals in the source, so join
    # them the way Python will before looking for it.
    joined = re.sub(r'"\s*\n\s*f?"', "", src)
    assert "with no terminal status seen" in joined


def test_the_deadline_test_still_exists_and_still_releases():
    """Moving it must not delete it — without a deadline the gate could wait
    forever on a prior run whose doc never changes."""
    src = gate_src()
    assert "if now_ms >= deadline:" in src
    body = src[src.index("if now_ms >= deadline:"):]
    assert '_QUEUE_STATE.pop("gate_pending_job", None)' in body[:900]
    assert "return" in body[:900]


def test_the_deadline_test_is_reachable_after_a_failed_read():
    """The read is wrapped; if an exception skipped past the deadline test the
    gate would spin every 2s forever. The test must sit after the except."""
    src = gate_src()
    except_at = src.index('log(f"[queue-gate] Firestore read failed: {e}", "WARN")')
    deadline_at = src.index("if now_ms >= deadline:")
    sleep_at = src.index("await asyncio.sleep(2)")
    assert except_at < deadline_at < sleep_at


@pytest.mark.parametrize("release", [
    'if _controls.is_stop():',
    'log(f"[queue-gate] prior run {_prid[:8]}… doc missing — dequeueing")',
    'log(f"[queue-gate] prior run terminal (status={status}) — dequeueing")',
    'if fe_p5_state == "failed":',
    'FE-P5 ghosted, force-dequeueing',
    'log("[queue-gate] read denied (synth user) — releasing gate (Track D)", "DEBUG")',
])
def test_every_prior_release_path_survives(release):
    """⛔ A worker that used to proceed must still proceed. Each of these was a
    separately root-caused way the gate could otherwise hang for 70 minutes."""
    assert release in gate_src()


def test_the_resume_and_errored_short_circuits_are_untouched():
    """Both run before the wait and both prevent a circular deadlock.

    ⭐ Asserted on the CONDITIONS, not on the messages they log. The message
    version of this passed against `if False:` — the log line sits inside the
    disabled branch and goes on matching. That is the same trap that cost two
    rounds on the Phase 1 completion guard."""
    src = gate_src()
    assert 'if _current_job and (_current_job.get("research_id") or "") == _prid:' in src
    assert "if _pdone <= 0:" in src
    # and the branches still say what they do
    assert "matches last_completed_rid — resume path, skipping wait" in src
    assert "prior run errored — skipping FE-completion wait" in src


def test_no_branch_in_the_wait_loop_skips_the_deadline_test():
    """The deadline test is the last statement before the sleep, so anything
    that `continue`s past it makes the gate un-expirable. Read off the syntax
    tree: a textual search cannot tell a loop-level `continue` from one inside
    a nested for-loop elsewhere in the function."""
    fn = textwrap.dedent(gate_src())
    tree = ast.parse(fn)
    loops = [n for n in ast.walk(tree)
             if isinstance(n, ast.While) and isinstance(n.test, ast.Constant)
             and n.test.value is True]
    assert len(loops) == 1, "expected exactly one `while True:` poll loop"
    # `continue` statements belonging to THIS loop — not to any loop nested in it.
    def owned_continues(node):
        found = []
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.While, ast.For, ast.AsyncFor,
                                  ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if isinstance(child, ast.Continue):
                found.append(child)
            found.extend(owned_continues(child))
        return found
    assert owned_continues(loops[0]) == [], (
        "a `continue` in the poll loop can jump past the deadline test — on a "
        "prior doc that keeps failing to read, the gate would never expire"
    )


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
