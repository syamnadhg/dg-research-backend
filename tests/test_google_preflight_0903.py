"""#282 — nothing asked whether the credential worked until minute 40.

⛔⛔ ON 2026-09-03 PHASE 5's OAUTH GRANT HAD BEEN REVOKED. The run did all its
research, wrote three reports, encoded and uploaded a podcast, and only then
discovered it could not create the document.

⛔⛔ AND THE COMMENT THAT EXPLAINS WHY IS STILL IN THE FILE, one block above the
new probe: "P5 (Doc + email) dropped 2026-04-30 — FE-owned via Docs API +
Resend. Neither needs login verification in the BE preflight." That is true of a
browser login WALK and was read for four months as needing no check at all. The
identical sentence had already been written about the Anthropic key, and the
#705 probe sitting right there is what it turned into — so this file had both
the mistake and its own correction, side by side, the whole time.

⛔ PHASE 5 IS THE ONE CREDENTIAL WITH NO REDUNDANCY, BY DESIGN. A document has to
land in ONE Drive, so the identity is pinned and there is nothing to rotate to.
That is what makes it worth blocking a run on. The phase-4 pool is reported and
never blocked on: one live slot still uploads, and stranding a run over a
degraded pool trades a real research result for a warning.
"""
import inspect
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research  # noqa: E402

SRC = (Path(__file__).resolve().parents[1] / "research.py").read_text(encoding="utf-8")
PROBE = inspect.getsource(research._probe_google_credentials)


class TestTheProbeItself:
    def test_it_asks_the_app_because_the_secrets_are_not_readable_here(self):
        """The credentials live in App Hosting Secrets. This process cannot read
        them, so the check is a question, not an inspection."""
        assert "/api/health/google" in PROBE
        assert "Authorization" in PROBE and "Bearer" in PROBE

    def test_it_returns_none_rather_than_raising_on_any_failure(self):
        """⛔⛔ A PREFLIGHT THAT FAILS CLOSED ON ITS OWN NETWORK BLIP IS WORSE
        THAN THE GAP IT CLOSES. Every exit that is not a 200 answer returns None,
        and the caller treats None as "unchecked", never as "dead"."""
        assert PROBE.count("return None") >= 4
        assert "raise" not in re.sub(r"(?m)^\s*#.*$", "", PROBE)

    def test_a_non_200_answer_is_unchecked_not_unhealthy(self):
        assert "if _r.status_code != 200:" in PROBE
        i = PROBE.index("if _r.status_code != 200:")
        assert "return None" in PROBE[i:i + 300]


class TestWhereItRuns:
    def _phase0(self) -> str:
        i = SRC.index("# ── #282: Google credential preflight")
        j = SRC.index("# Honor the user's preference", i)
        return SRC[i:j]

    def test_it_runs_above_the_skip_verification_blanking(self):
        """⛔⛔ LIKE THE CUA PROBE, AND FOR THE SAME REASON. A dead credential is
        infrastructure, not a login nicety: "Skip login verification" must not
        also skip this. The ordering IS the guarantee — `preflight_platforms` is
        emptied below, so anything gated on it silently stops running."""
        assert SRC.index("# ── #282: Google credential preflight") < \
            SRC.index('_skip_verify_pref = bool(pipeline_config.get("skipInitVerify"')

    def test_the_block_never_consults_the_skip_preference_itself(self):
        """⛔⛔ SOURCE ORDER PROVES WHERE THE CODE SITS, NOT WHAT IT ASKS. A mutant
        that moved the probe below the blanking was caught by the ordering test;
        one that leaves it where it is and simply reads `skipInitVerify` inside
        the block would not have been, and it is the easier edit of the two — the
        preference is right there and defaults ON. "Skip login verification" must
        not also skip a dead-credential check."""
        # ⛔ LIVE CODE ONLY. The comment inside the block explains that this check
        # is deliberately NOT subject to the preference, so it names it — and a
        # guard that forbids the name forbids the explanation. Same rule the
        # absence guards elsewhere in this repo settled on.
        code = re.sub(r"(?m)^\s*#.*$", "", self._phase0())
        assert "skipInitVerify" not in code
        assert "_skip_verify" not in code

    def test_it_only_runs_when_a_google_phase_will(self):
        """A links-only run that skips 4 and 5 has no Google credential to check,
        and a card about one would be an invented problem."""
        block = self._phase0()
        assert "_need_p5 = 5 not in skip_phases" in block
        assert "_need_p4 = 4 not in skip_phases" in block
        assert "if _need_p5 or _need_p4:" in block

    def test_it_blocks_only_on_the_document_identity(self):
        """⛔⛔ THE ASYMMETRY IS THE DESIGN. Phase 5's identity is pinned, so a
        refusal there is fatal and nothing can rotate around it. Phase 4's pool
        is reported and never blocked on."""
        block = self._phase0()
        assert 'if _need_p5 and _gcred.get("driveBlocked"):' in block
        assert "fail_phase(" in block
        # The pool branch logs and does not pause.
        i = block.index("if _need_p4 and _pool_t and _pool_n < _pool_t:")
        j = block.index('if _need_p5 and _gcred.get("driveBlocked"):')
        assert "fail_phase" not in block[i:j]
        assert "request_pause" not in block[i:j]

    def test_it_names_the_dead_pool_accounts_and_why(self):
        """⭐ "1 of 3 healthy" is what would have caught the syamnadhg entry in
        July. Rotation hides a dead slot so well that it was rejected on every
        pick for eight weeks with nothing but a WARN line to show for it, and a
        line that does not say WHICH account or WHY is a line nobody acts on."""
        block = self._phase0()
        assert "upload pool DEGRADED" in block
        assert "a.get('label')" in block and "a.get('error')" in block
        assert "a.get('detail')" in block

    def test_it_logs_the_healthy_case_too(self):
        """⚠ A pool that silently degrades is the failure this closes. Logging
        only on failure leaves "3 of 3" and "never ran" identical in the record."""
        block = self._phase0()
        i = block.index('log(f"Phase 0: Google credentials —')
        j = block.index("if _need_p4", i)
        assert "if " not in block[block.rindex("\n", 0, i):i], \
            "the healthy line must not sit behind a condition"
        assert "upload pool {_pool_n}/{_pool_t} healthy" in block[i:j]


class TestTheCard:
    def test_the_intent_is_registered_in_the_catalog(self):
        """⛔ A card whose intent is not in the catalog has no recoverability
        class, so the notifier's `recoverability == "blocker"` gate cannot see
        it — and the run waits overnight without telling anyone. The first draft
        of this fix invented the name and did not register it."""
        assert "oauth_expired" in research.ALERT_INTENTS
        assert research.ALERT_INTENTS["oauth_expired"]["class"] == "blocker"

    def test_it_is_retry_only(self):
        """The sign-in is reconnected out of band, so nothing on the card can fix
        it and nothing auto-heals.

        ⛔ AND NO `skip_phase`, NOT BECAUSE RUNNING WITHOUT THE DOCUMENT IS
        UNTHINKABLE. The action is scoped to the card's OWN phase, and this card
        is phase 0 — a skip token here would offer to skip the preflight, not the
        Doc. A control that looks like the thing you want and does something else
        is worse than no control."""
        assert research.ALERT_INTENTS["oauth_expired"]["actions"] == ["retry_phase"]

    def test_the_copy_carries_googles_own_sentence(self):
        """The card is where a person reads why. `invalid_grant` alone cannot tell
        a revoked grant from a token minted against the wrong client, and those
        are different repairs."""
        block = SRC[SRC.index("# ── #282: Google credential preflight"):
                    SRC.index("# Honor the user's preference")]
        assert '_why = _drv.get("detail") or _drv.get("error") or "rejected"' in block
        assert "{_why}" in block

    def test_the_copy_says_why_it_is_stopping_before_the_work(self):
        """The whole argument for a preflight is in this sentence — otherwise it
        reads as an arbitrary refusal to start."""
        block = SRC[SRC.index("# ── #282: Google credential preflight"):
                    SRC.index("# Honor the user's preference")]
        assert "starting now would do all the research and then fail" in block
