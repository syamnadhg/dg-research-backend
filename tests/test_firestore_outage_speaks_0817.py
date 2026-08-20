"""A Firestore outage that is not a blip has to SAY so, in words.

⛔ THE LIVE REPORT. A new owner paired successfully — 5/5, all four platforms,
bond forged — `--serve` came up cleanly, and sixty seconds later DNS for
firestore.googleapis.com stopped resolving on their network. What the product
did about that:

  * the reconnect ladder retried forever, correctly and invisibly;
  * the only trace was `[reconnect] Firestore still unreachable — retrying init
    in 30s`, WARN, identical at attempt 1 and attempt 4,921;
  * `Firestore init: transient network error` said "transient" 5,339 times
    about an outage that was nothing of the kind;
  * the aegis pulse went on printing "◆ standing watch" once a minute; and
  * the web app just said the device was offline.

⭐⭐ Not one sentence anywhere in the corpus named DNS, a VPN, a proxy or a
firewall. Grepped: no "cannot reach", no "check your network". The recovery
machinery was excellent and the reporting was absent, which is exactly the
combination that leaves someone staring at a working install that does nothing.

⭐ THE SHARPEST GUARD IN HERE is `_mark_firestore_down` being idempotent. The
reconnect loop calls it on EVERY down tick; if it re-stamped the clock, the
elapsed time would reset to ~0 every five seconds and the escalation could
never fire at all — a guard that cannot fire, the same shape this repo has now
shipped five times.
"""
import inspect
import re

import pytest

import research


# ── how long, said the same way everywhere ───────────────────────────────────

@pytest.mark.parametrize("secs,text", [
    (0, "0s"), (9, "9s"), (59, "59s"),
    (60, "1m00s"), (72, "1m12s"), (252, "4m12s"), (3599, "59m59s"),
    (3600, "1h00m"), (7500, "2h05m"),
])
def test_duration_text(secs, text):
    assert research._outage_duration_text(secs) == text


@pytest.mark.parametrize("junk", [None, "", "abc", -5, float("nan")])
def test_duration_text_never_raises_and_never_goes_negative(junk):
    got = research._outage_duration_text(junk)
    assert isinstance(got, str) and not got.startswith("-")


# ── the clock ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_clock():
    research._clear_firestore_down()
    yield
    research._clear_firestore_down()


def test_marking_down_starts_the_clock():
    research._mark_firestore_down(now=1000.0)
    assert research._firestore_down_since_ts == 1000.0


def test_marking_down_again_does_not_restart_the_clock():
    """⭐⭐ THE ONE THAT MATTERS. The reconnect loop marks on every down tick.
    If this re-stamped, `down_for` would reset to ~0 every five seconds, the
    escalation threshold would never be crossed, and the whole notice would be
    dead code that looked alive."""
    research._mark_firestore_down(now=1000.0)
    research._mark_firestore_down(now=1005.0)
    research._mark_firestore_down(now=9999.0)
    assert research._firestore_down_since_ts == 1000.0


def test_clearing_stops_the_clock():
    research._mark_firestore_down(now=1000.0)
    research._clear_firestore_down()
    assert research._firestore_down_since_ts is None
    research._mark_firestore_down(now=2000.0)
    assert research._firestore_down_since_ts == 2000.0


def test_the_client_success_path_clears_the_clock():
    src = inspect.getsource(research.init_firebase)
    assert "_clear_firestore_down()" in src
    assert src.index("_firebase_db = client") < src.index("_clear_firestore_down()")


def test_the_heartbeat_drop_starts_the_clock():
    src = inspect.getsource(research.heartbeat_loop) if hasattr(
        research, "heartbeat_loop") else inspect.getsource(research)
    assert "_firebase_db = None" in src
    drop = src[src.index("dropping client; reconnect loop will rebuild"):]
    assert "_mark_firestore_down()" in drop[:600], (
        "the outage clock must start where the client actually goes away"
    )


# ── when it speaks, and when it stays quiet ──────────────────────────────────

def _notice(**kw):
    kw.setdefault("down_for", 600.0)
    kw.setdefault("attempts", 12)
    kw.setdefault("last_spoken_ago", None)
    return research._firestore_outage_notice(**kw)


@pytest.mark.parametrize("secs", [0, 5, 30, 59.9])
def test_a_blip_says_nothing(secs):
    """The ladder is 5→5→10→30s. An ordinary hiccup clears inside that and must
    not produce an alarm — an alarm on every blip is how the next one gets
    ignored."""
    assert _notice(down_for=secs) == []


@pytest.mark.parametrize("secs", [60, 61, 600, 7200])
def test_past_the_threshold_it_speaks(secs):
    assert _notice(down_for=secs)


def test_it_does_not_repeat_itself_every_retry():
    """⛔ The old line printed 4,921 times. A message printed 4,921 times is
    wallpaper, not a message."""
    assert _notice(last_spoken_ago=30.0) == []
    assert _notice(last_spoken_ago=299.0) == []


def test_it_does_repeat_on_the_slow_cadence():
    assert _notice(last_spoken_ago=300.0)
    assert _notice(last_spoken_ago=3600.0)


def test_the_two_gates_are_independent():
    """Recently spoken but still short: quiet for BOTH reasons, and neither
    may rescue the other."""
    assert _notice(down_for=10, last_spoken_ago=9999) == []
    assert _notice(down_for=9999, last_spoken_ago=1) == []


@pytest.mark.parametrize("junk", [None, "", "later"])
def test_a_junk_last_spoken_does_not_turn_into_a_flood(junk):
    if junk is None:
        assert _notice(last_spoken_ago=junk)  # never spoken → speak
    else:
        assert _notice(last_spoken_ago=junk) == []


def test_the_thresholds_are_named_and_overridable():
    assert research.FIRESTORE_OUTAGE_SPEAKS_AFTER_S == 60.0
    assert research.FIRESTORE_OUTAGE_REPEAT_S == 300.0
    assert _notice(down_for=10, speaks_after_s=5)


def test_the_alarm_threshold_clears_the_whole_backoff_ladder():
    """⛔ If it fired inside the ladder, every ordinary blip would raise it."""
    src = inspect.getsource(research._firebase_reconnect_loop)
    ladder = re.search(r"BACKOFF = \(([^)]*)\)", src).group(1)
    steps = [float(x) for x in ladder.split(",") if x.strip()]
    assert research.FIRESTORE_OUTAGE_SPEAKS_AFTER_S > sum(steps), (
        f"an outage must survive the full ladder ({sum(steps)}s) before it is "
        f"called persistent"
    )


# ── what it actually says ────────────────────────────────────────────────────

def test_it_names_the_host():
    assert all("firestore.googleapis.com" in l for l in _notice()[:1])
    assert "firestore.googleapis.com" in " ".join(_notice())


def test_it_names_how_long_and_how_many_attempts():
    lines = _notice(down_for=252.0, attempts=9)
    assert "4m12s" in lines[0]
    assert "9 attempts" in lines[0]


def test_one_attempt_is_singular():
    assert "(1 attempt)" in _notice(down_for=99, attempts=1)[0]
    assert "(2 attempts)" in _notice(down_for=99, attempts=2)[0]


def test_it_says_what_the_reader_loses():
    blob = " ".join(_notice()).lower()
    assert "offline" in blob
    assert "will not arrive" in blob


def test_it_rules_out_the_thing_the_reader_will_try_first():
    """Without this, the first move is always to re-pair — which cannot help,
    costs the pairing, and was the new owner's actual next step."""
    assert "nothing to re-pair" in " ".join(_notice()).lower()


def test_it_names_the_three_real_causes_and_one_command():
    blob = " ".join(_notice()).lower()
    for cause in ("vpn", "proxy", "firewall", "dns"):
        assert cause in blob, f"{cause} not named"
    assert "nslookup firestore.googleapis.com" in " ".join(_notice())


def test_it_says_no_restart_is_needed():
    blob = " ".join(_notice()).lower()
    assert "reconnects by itself" in blob or "reconnects on its own" in blob


def test_it_returns_separate_lines_not_one_paragraph():
    """`log()` is a single print per call, so a multi-line string would leave
    every line after the first with no timestamp and no level."""
    lines = _notice()
    assert len(lines) >= 3
    assert not any("\n" in l for l in lines)


def test_every_line_is_greppable_as_one_topic():
    assert all(l.startswith("[firestore] ") for l in _notice())


# ── the aegis pulse stops lying ──────────────────────────────────────────────

def test_the_pulse_still_stands_watch_when_it_is_true():
    line = research._aegis_pulse_line(1, 0)
    assert "standing watch" in line
    assert "◆" in line


def test_the_pulse_alternates_colour_not_glyph():
    a = research._aegis_pulse_line(1, 0)
    b = research._aegis_pulse_line(1, 1)
    assert a.count("◆") == b.count("◆") == 1
    assert "◇" not in a and "◇" not in b


def test_the_pulse_reports_a_broken_watch():
    line = research._aegis_pulse_line(1, 0, down_for=252.0)
    assert "standing watch" not in line, "this is the whole defect"
    assert "watch broken" in line
    assert "4m12s" in line
    assert "✗" in line


def test_the_broken_pulse_says_what_it_costs_the_user():
    line = research._aegis_pulse_line(2, 3, down_for=600.0)
    assert "offline" in line
    assert "will not arrive" in line
    assert "worker 2" in line


def test_zero_seconds_down_is_still_down():
    """⛔ `down_for=0.0` is a real state — the client just went. A falsy check
    here would put the pulse straight back to claiming a watch."""
    line = research._aegis_pulse_line(1, 0, down_for=0.0)
    assert "watch broken" in line


# ── the loops are wired to all of it ─────────────────────────────────────────

def _loop_src():
    return inspect.getsource(research._firebase_reconnect_loop)


def test_the_retry_line_distinguishes_a_blip_from_a_dead_network():
    """⛔ It used to read identically at attempt 1 and attempt 4,921."""
    src = _loop_src()
    assert "Firestore still unreachable — retrying init in" not in src
    assert "Firestore unreachable for" in src
    assert "_outage_duration_text(_down_for)" in src
    assert "(attempt {attempts})" in src


def test_the_attempt_counter_is_not_the_backoff_index():
    """`idx` stops climbing once the backoff caps, so it cannot count attempts.
    That is why the old line could never say how long this had gone on."""
    src = _loop_src()
    assert "attempts += 1" in src
    assert "attempts = 0" in src
    assert "idx = 0" in src


def test_the_notice_is_logged_at_error():
    src = _loop_src()
    block = src[src.index("_firestore_outage_notice("):]
    assert 'log(_line, "ERROR")' in block[:400], (
        "a machine that cannot run anything is not a WARN"
    )


def test_the_notice_records_that_it_spoke_only_when_it_did():
    src = _loop_src()
    assert "if _notice:" in src and "spoke_at = time.time()" in src


def test_the_clock_is_snapshotted_before_the_rebuild():
    """⛔ A SUCCESSFUL init_firebase clears the clock, so reading it afterwards
    reports every recovery as 0s. My first draft did exactly that."""
    src = _loop_src()
    assert "_down_started = _firestore_down_since_ts" in src
    assert src.index("_down_started = _firestore_down_since_ts") < src.index(
        "ok = await asyncio.to_thread(init_firebase)")


def test_recovery_is_announced_only_if_the_alarm_was_raised():
    src = _loop_src()
    ok_branch = src[src.index("ok = await asyncio.to_thread(init_firebase)"):]
    assert "if spoke_at is not None:" in ok_branch[:300], (
        "a blip that never raised an alarm must not announce a resolution"
    )
    assert "Reachable again after" in ok_branch


def test_the_reconnect_loop_starts_the_clock_for_workers_with_no_heartbeat():
    """Workers 2+ never run the heartbeat, and a boot-time failure has no drop
    to observe. Without this the clock would never start for either."""
    src = _loop_src()
    assert "_mark_firestore_down()" in src


def test_the_pulse_loop_passes_the_real_state():
    """⛔ SLICED TO THE NEXT CONSTRUCT, NOT A BYTE WINDOW. This used to take the
    first 1,200 bytes, and on 2026-08-19 the loop grew the comments explaining
    its emission cadence — which pushed `down_for=` past the window and turned
    this into a failure about slice arithmetic rather than about the pulse. A
    fixed window silently stops covering the thing it names."""
    src = inspect.getsource(research)
    start = src.index("async def _aegis_pulse_loop():")
    body = src[start:src.index("asyncio.create_task(_aegis_pulse_loop())", start)]
    assert "_firebase_db is None" in body
    assert "down_for=" in body
    assert '"WARN" if _cut_off else "INFO"' in body, (
        "a broken watch logged at INFO is invisible in a level filter"
    )


def test_init_no_longer_asserts_transience_it_has_not_earned():
    """The classification stays; the sentence stops claiming to know."""
    src = inspect.getsource(research.init_firebase)
    assert "transient network error" not in src
    assert "could not reach Google" in src
    # ⛔ MUTATION FOUND THIS. `init_firebase` sets `= "transient"` TWICE — once
    # for a failed import, once for the network path — so a bare `in src` check
    # passed with the network one deleted. Pin it to the branch it belongs to.
    net = src[src.index("could not reach Google"):]
    net = net[:net.index("return False") + len("return False")]
    assert '_firebase_down_reason = "transient"' in net, (
        "the revoked-vs-transient classification routes ALL recovery; rewording "
        "the sentence must not take the classification with it"
    )
    assert src.count('_firebase_down_reason = "transient"') == 2, (
        "one for the import path, one for the network path — a third would be a "
        "new caller nobody has judged"
    )
