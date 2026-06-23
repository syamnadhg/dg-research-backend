"""Phoenix self-healing SELECTOR engine — PX-0 foundation (shadow-only).

This is the selector / UI-churn half of `PhoenixRecipe.md`. The model-churn half
(the recipe's PX-1 "generalise verOf into a policy resolver") already shipped via
the model-freshness work in ``models.py`` (``P2_MODEL_POLICY`` etc.); this module
owns the *selector* side — keeping each tier's knowledge of the page current and
turning a recovery into a durable, persisted fix.

NAME COLLISION (read this first): ``research.py`` already has an unrelated
"Phoenix" — the daemon restart / resume / checkpoint subsystem. They share a name
and nothing else. To kill the grep trap, EVERYTHING here is namespaced
``selfheal`` and gated by ``DG_SELFHEAL_ENABLED`` (default OFF), mirroring how the
model-freshness work used ``model_refresh`` / ``DG_MODEL_REFRESH_ENABLED``.

PX-0 SCOPE — foundation only, ZERO behaviour change:
  * Intent / outcome contracts for the 6 P2 setup intents (#708/#709 surfaces):
    ``{chatgpt,gemini,claude}.{enable_deep_research,select_model}``.
  * ``probe_region`` — one reusable, JSON-serialisable accessibility scanner that
    generalises the 3 existing diagnostic DOM dumps.
  * ``selectors.json`` schema + atomic, cross-process-locked loader/writer
    (the runtime overlay; LOADED here, written by the heal loop in PX-2).
  * The ``decide_toggle`` pre-act guard (the #709 firewall, extracted).
  * The kill-switch + a shadow log (``logs/selfheal_shadow.jsonl``).

NOTHING in this module is wired into the pipeline by PX-0 — ``research.py`` does
not import it yet (that is C2, flag-gated and shadow-only). With the flag OFF
every entry point here is a no-op, so importing/shipping this file changes no run.

The intent manifest is compiled in as ``_INTENTS`` (the canonical baseline, so a
Nuitka build with no shipped data file still works) and mirrored by an editable
``selfheal_intents.json`` next to this module which the loader prefers when
present. A test pins the two so they can never drift.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ── Vocabulary (the contract's closed sets) ──────────────────────────────────
PLATFORMS = ("chatgpt", "gemini", "claude")
INTENT_TYPES = ("toggle", "select")
# Tier ordering per PhoenixRecipe §4 (DOM → Vision → CUA, plus the registry
# fast-path and the heuristic heal). The literal order is the resolve sequence.
KNOWN_TIERS = ("registry", "builtin", "heal", "vision", "cua")

_PROBE_CAP = 40  # max elements returned per probe (bounds the page→py payload)


# ── Kill-switch ──────────────────────────────────────────────────────────────
def _flag_on(name: str, default: str = "0") -> bool:
    """Codebase DG_* boolean idiom (mirrors models._flag_on / vision.py)."""
    return (os.environ.get(name, default) or "").strip().lower() not in (
        "0",
        "false",
        "no",
        "",
    )


def is_enabled() -> bool:
    """Master kill-switch — ``DG_SELFHEAL_ENABLED`` (default OFF).

    Read LIVE (never cached at import) so flipping the switch takes effect without
    a restart, and so tests can toggle it via monkeypatch. Every shadow/heal entry
    point gates on this; OFF ⇒ the whole subsystem is inert.
    """
    return _flag_on("DG_SELFHEAL_ENABLED")


def act_enabled() -> bool:
    """Activation sub-switch — ``DG_SELFHEAL_ACT`` (default OFF), AND-ed with the
    master switch. The engine ACTS (clicks + persists a heal) only when BOTH are
    on; with just ``DG_SELFHEAL_ENABLED`` it runs shadow-only (observe + log what
    it WOULD heal). This is the recipe's shadow-first rollout: prove match quality
    in the shadow log, then flip ``DG_SELFHEAL_ACT`` after a clean window.
    """
    return is_enabled() and _flag_on("DG_SELFHEAL_ACT")


def capture_enabled() -> bool:
    """Corpus-capture sub-switch — ``DG_SELFHEAL_CAPTURE`` (default OFF), AND-ed
    with the master switch. When on, the shadow layer ALSO records the FULL probe
    snapshot of each intent's region to ``logs/selfheal_capture.jsonl`` so a real
    golden corpus + drift fixtures can be built from live DOM (replacing the
    synthetic seeds). Pure data capture — acts on nothing.
    """
    return is_enabled() and _flag_on("DG_SELFHEAL_CAPTURE")


# ── Paths (resolved live so env overrides + test isolation just work) ─────────
def _state_dir() -> Path:
    """Persistent state dir — ``~/.super-research`` (matches model_refresh.json
    and the keystore). ``DG_SELFHEAL_STATE_DIR`` overrides (test isolation)."""
    return Path(
        os.environ.get("DG_SELFHEAL_STATE_DIR") or (Path.home() / ".super-research")
    )


def _selectors_path() -> Path:
    """The runtime selector overlay. ``DG_SELFHEAL_SELECTORS`` overrides."""
    return Path(os.environ.get("DG_SELFHEAL_SELECTORS") or (_state_dir() / "selectors.json"))


def _lock_path() -> Path:
    return _state_dir() / ".selfheal.lock"


def _audit_log_path() -> Path:
    return _state_dir() / "selfheal-audit.log"


def _intents_path() -> Path:
    """External manifest, preferred when present. ``DG_SELFHEAL_INTENTS``
    overrides; default is the JSON beside this module (source-checkout) — absent
    in a wheel build, where the embedded ``_INTENTS`` baseline is used instead."""
    return Path(
        os.environ.get("DG_SELFHEAL_INTENTS")
        or (Path(__file__).resolve().parent / "selfheal_intents.json")
    )


def _shadow_log_path() -> str:
    """Per-run shadow-eval JSONL log. Honours ``DG_SELFHEAL_SHADOW_LOG`` or falls
    back to ``logs/selfheal_shadow.jsonl`` in the cwd — mirrors vision.py's
    sibling shadow log exactly (cwd-relative, str)."""
    return os.environ.get("DG_SELFHEAL_SHADOW_LOG") or os.path.join(
        "logs", "selfheal_shadow.jsonl"
    )


def _capture_log_path() -> str:
    """Full-snapshot corpus-capture JSONL (separate from the lean shadow log so
    the bulky raw DOM doesn't bloat per-send telemetry). ``DG_SELFHEAL_CAPTURE_LOG``
    overrides; default ``logs/selfheal_capture.jsonl`` in the cwd."""
    return os.environ.get("DG_SELFHEAL_CAPTURE_LOG") or os.path.join(
        "logs", "selfheal_capture.jsonl"
    )


# ── 1. Intent / outcome contracts ────────────────────────────────────────────
# The manifest. Schema (PhoenixRecipe §4.0):
#   { "<platform>.<intent_id>": {
#       platform, intent_id, type ('toggle'|'select'), irreversible (bool),
#       region (REGIONS key | spec dict), outcome_predicate (str id),
#       signal_hints (durable-signal ranking — role+name first, NEVER class),
#       tier_sequence ([KNOWN_TIERS]) } }
#
# ``outcome_predicate`` is a stable IDENTIFIER for the existing read-only check
# (the JS / py predicate already in research.py); PX-0 only declares it. The heal
# loop (PX-2) maps the id to the live predicate. Predicates reuse, never
# duplicate: _GEMINI_DR_STATE_JS, the Claude verOf>=floor trigger read, and the
# ChatGPT composer-pill check (#13 of the recipe).
_INTENTS: dict[str, dict[str, Any]] = {
    "chatgpt.enable_deep_research": {
        "platform": "chatgpt",
        "intent_id": "enable_deep_research",
        "type": "toggle",
        "irreversible": False,
        "region": "form",
        "outcome_predicate": "cgpt_state:active",
        "signal_hints": {
            "accessible_name": "deep research",
            "role": ["button", "menuitem", "menuitemradio"],
        },
        "tier_sequence": list(KNOWN_TIERS),
    },
    "gemini.enable_deep_research": {
        "platform": "gemini",
        "intent_id": "enable_deep_research",
        "type": "toggle",
        "irreversible": False,
        "region": "composer",
        # Authoritative signal is the composer PLACEHOLDER ("What do you want to
        # research?"), not the pill class (#709) — `pressed` is secondary.
        "outcome_predicate": "gemini_dr_state:placeholderResearch||pressed",
        "signal_hints": {
            "accessible_name": "deep research",
            "role": ["button"],
            "placeholder": "what do you want to research",
        },
        "tier_sequence": list(KNOWN_TIERS),
    },
    "claude.enable_deep_research": {
        "platform": "claude",
        "intent_id": "enable_deep_research",
        "type": "toggle",
        "irreversible": False,
        "region": "composer",
        "outcome_predicate": "claude_research_tool:on",
        "signal_hints": {"accessible_name": "research", "role": ["button"]},
        "tier_sequence": list(KNOWN_TIERS),
    },
    "chatgpt.select_model": {
        "platform": "chatgpt",
        "intent_id": "select_model",
        "type": "select",
        "irreversible": False,
        "region": "composer",
        # DETECT-ONLY: ChatGPT exposes NO P2 model/effort lever today. The
        # predicate is "a model selector is ABSENT"; if one ever appears that is a
        # capability change → escalate, not a churn to silently heal. (The model
        # PICK side is owned by model_refresh; this contract only watches the DOM.)
        "outcome_predicate": "chatgpt_model_selector:absent",
        "signal_hints": {"accessible_name": "model", "role": ["button"], "detect_only": True},
        "tier_sequence": list(KNOWN_TIERS),
    },
    "gemini.select_model": {
        "platform": "gemini",
        "intent_id": "select_model",
        "type": "select",
        "irreversible": False,
        "region": "composer",
        "outcome_predicate": "gemini_flash_selected:trigger",
        "signal_hints": {"accessible_name": "model", "role": ["button"], "value_contains": "flash"},
        "tier_sequence": list(KNOWN_TIERS),
    },
    "claude.select_model": {
        "platform": "claude",
        "intent_id": "select_model",
        "type": "select",
        "irreversible": False,
        "region": "composer",
        "outcome_predicate": "claude_trigger_verOf:>=floor",
        "signal_hints": {"accessible_name": "model", "role": ["button"], "value_matches": "opus"},
        "tier_sequence": list(KNOWN_TIERS),
    },
}


def _validate_intents(data: Any) -> dict[str, dict[str, Any]]:
    """Structural validation of an intent manifest. Raises ``ValueError`` on any
    violation — callers (``load_intents``) catch and fall back to the baseline."""
    if not isinstance(data, dict) or not data:
        raise ValueError("intents manifest must be a non-empty object")
    for key, it in data.items():
        if not isinstance(it, dict):
            raise ValueError(f"{key}: intent must be an object")
        plat = it.get("platform")
        iid = it.get("intent_id")
        if plat not in PLATFORMS:
            raise ValueError(f"{key}: platform must be one of {PLATFORMS}")
        if not isinstance(iid, str) or not iid:
            raise ValueError(f"{key}: intent_id (str) required")
        if key != f"{plat}.{iid}":
            raise ValueError(f"{key}: key must equal '<platform>.<intent_id>'")
        if it.get("type") not in INTENT_TYPES:
            raise ValueError(f"{key}: type must be one of {INTENT_TYPES}")
        if not isinstance(it.get("outcome_predicate"), str) or not it["outcome_predicate"]:
            raise ValueError(f"{key}: outcome_predicate (non-empty str) required")
        if not isinstance(it.get("signal_hints"), dict):
            raise ValueError(f"{key}: signal_hints (object) required")
        seq = it.get("tier_sequence")
        if not isinstance(seq, list) or not seq or any(t not in KNOWN_TIERS for t in seq):
            raise ValueError(f"{key}: tier_sequence must be a non-empty list drawn from {KNOWN_TIERS}")
        if not isinstance(it.get("irreversible"), bool):
            raise ValueError(f"{key}: irreversible (bool) required")
        region = it.get("region")
        # isinstance FIRST — `region in REGIONS` on a dict would raise TypeError
        # (unhashable) and discard an otherwise-valid spec-dict manifest.
        if not (isinstance(region, dict) or (isinstance(region, str) and region in REGIONS)):
            raise ValueError(f"{key}: region must be a REGIONS key or a spec dict")
    return data


def load_intents() -> dict[str, dict[str, Any]]:
    """Return the P2 selector-heal intent contracts (deep-copied).

    Prefers the external manifest (``selfheal_intents.json`` / ``DG_SELFHEAL_INTENTS``)
    and falls back to the compiled-in ``_INTENTS`` baseline when that file is
    missing, corrupt, or invalid (so a Nuitka build with no shipped data file — or
    a fat-fingered edit — still works). Never raises.
    """
    path = _intents_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return copy.deepcopy(_validate_intents(data))
    except FileNotFoundError:
        return copy.deepcopy(_INTENTS)
    except Exception as exc:  # corrupt JSON or schema violation
        logger.warning(
            "selfheal intents manifest invalid (%s) — using embedded baseline", exc
        )
        return copy.deepcopy(_INTENTS)


# ── 2. DOM probe ──────────────────────────────────────────────────────────────
# Named scan regions. Each maps to {scopeSel, scopeClimb, candSel}. These
# generalise where the 3 seed dumps looked: the composer (Claude #708 Step-3A /
# Gemini placeholder), an open menu (ChatGPT #709 Step-2), the composer form
# (ChatGPT pill). `scopeClimb` walks up from the anchor (the composer dump climbed
# 5 parents to include the toolbar row).
REGIONS: dict[str, dict[str, Any]] = {
    "composer": {
        "scopeSel": 'div[contenteditable="true"], .ProseMirror, [role="textbox"], rich-textarea',
        "scopeClimb": 5,
        "candSel": 'button, [role="button"]',
    },
    "menu": {
        "scopeSel": "",
        "scopeClimb": 0,
        "candSel": '[role="menuitem"], [role="menuitemradio"], [role="option"], button, a, li',
    },
    "form": {
        "scopeSel": "form",
        "scopeClimb": 0,
        "candSel": 'button, [role="button"], span, div',
    },
    "document": {
        "scopeSel": "",
        "scopeClimb": 0,
        "candSel": 'button, [role="button"], a, [role="menuitem"], [role="menuitemradio"], [role="option"]',
    },
}

# One reusable, JSON-serialisable accessibility scanner. Promotes the 3 seed
# dumps into a single shape: {role, accessible_name, text, attrs, bounds, visible}.
# Visibility follows the hardened in-tree rule — getClientRects().length OR
# offsetParent (a fixed-position trigger has offsetParent === null but real
# client rects, which is why the Claude #744 read used getClientRects). READ-ONLY:
# this never clicks, focuses, or mutates anything.
PROBE_REGION_JS = """(params) => {
    const cap = params.cap || 40;
    const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
    let root = document.body;
    if (params.scopeSel) {
        const anchor = document.querySelector(params.scopeSel);
        if (anchor) {
            let scope = anchor;
            const climb = params.scopeClimb || 0;
            for (let i = 0; i < climb && scope && scope.parentElement; i++) scope = scope.parentElement;
            root = scope || document.body;
        }
    }
    const candSel = params.candSel || 'button, [role="button"]';
    const out = [];
    const seen = new Set();
    for (const el of root.querySelectorAll(candSel)) {
        if (seen.has(el)) continue;
        seen.add(el);
        const visible = el.getClientRects().length > 0 || !!el.offsetParent;
        if (!visible && !params.includeHidden) continue;
        const r = el.getBoundingClientRect();
        const cls = (el.className && el.className.toString) ? el.className.toString() : '';
        out.push({
            role: el.getAttribute('role') || el.tagName.toLowerCase(),
            accessible_name: norm(el.getAttribute('aria-label')).slice(0, 80),
            text: norm(el.textContent).slice(0, 80),
            attrs: {
                testid: el.getAttribute('data-testid') || '',
                haspopup: el.getAttribute('aria-haspopup') || '',
                pressed: el.getAttribute('aria-pressed') || '',
                checked: el.getAttribute('aria-checked') || '',
                selected: el.getAttribute('aria-selected') || '',
                state: (el.dataset && el.dataset.state) || '',
                placeholder: el.getAttribute('data-placeholder') || el.getAttribute('placeholder') || '',
                cls: cls.toLowerCase().slice(0, 120)
            },
            bounds: {
                x: Math.round(r.x), y: Math.round(r.y),
                w: Math.round(r.width), h: Math.round(r.height)
            },
            visible: visible
        });
        if (out.length >= cap) break;
    }
    return out;
}"""


async def probe_region(page: Any, region: Any) -> list[dict[str, Any]]:
    """Scan ``region`` of ``page`` and return a list of accessibility records
    ``[{role, accessible_name, text, attrs, bounds, visible}, ...]`` (capped).

    ``region`` is a :data:`REGIONS` key or an explicit spec dict
    ``{scopeSel, scopeClimb, candSel, cap}``. Read-only — never mutates the page.
    A bad ``region`` argument raises (a programming error worth surfacing); a live
    page/eval failure returns ``[]`` (runtime resilience — never breaks a run).
    """
    if isinstance(region, str):
        spec = REGIONS.get(region)
        if spec is None:
            raise KeyError(f"unknown probe region: {region!r}")
    elif isinstance(region, dict):
        spec = region
    else:
        raise TypeError("region must be a REGIONS key or a spec dict")
    params = {
        "scopeSel": spec.get("scopeSel", ""),
        "scopeClimb": int(spec.get("scopeClimb", 0)),
        "candSel": spec.get("candSel", 'button, [role="button"]'),
        "cap": int(spec.get("cap", _PROBE_CAP)),
        "includeHidden": bool(spec.get("includeHidden", False)),
    }
    try:
        result = await page.evaluate(PROBE_REGION_JS, params)
    except Exception as exc:
        logger.debug("probe_region(%r) failed: %s", region, exc)
        return []
    return result if isinstance(result, list) else []


# ── 3. Selector registry (selectors.json) — schema + atomic, locked overlay ───
def _valid_selector_entry(key: Any, entry: Any) -> bool:
    """A registry entry is keyed ``platform|intent_id|ui_fingerprint`` and carries
    a non-empty ``strategy_rank`` of ``{by, value}`` strategies (§4.2)."""
    if not isinstance(key, str) or key.count("|") != 2:
        return False
    if not isinstance(entry, dict):
        return False
    rank = entry.get("strategy_rank")
    if not isinstance(rank, list) or not rank:
        return False
    return all(isinstance(s, dict) and "by" in s and "value" in s for s in rank)


def load_selectors() -> dict[str, Any]:
    """Read the runtime selector overlay. Returns ``{}`` when absent / corrupt /
    not-an-object, and DROPS individual malformed entries — a poisoned entry can
    never crash the loader or be acted on. Never raises.
    """
    try:
        raw = _selectors_path().read_text(encoding="utf-8")
    except Exception:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        logger.debug("selectors.json corrupt — ignoring")
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if _valid_selector_entry(k, v)}


@contextlib.contextmanager
def _selfheal_lock(timeout: float = 15.0):
    """Serialise ``selectors.json`` read-modify-write across the N ``--serve``
    worker processes.

    COPIES the proven ``auth/keystore.cross_process_refresh_lock()`` shape
    (``msvcrt.locking`` on Windows / ``fcntl.flock`` on POSIX, degrade-to-unlocked,
    EXACTLY one ``yield``) but against its OWN lock file — reusing the refresh-token
    lock would falsely serialise selector heals against credential rotations.
    Best-effort: on any lock failure we proceed UNLOCKED (the atomic
    temp+``os.replace`` write still prevents a torn read; the lock only prevents a
    lost concurrent update).
    """
    import time as _time

    # All acquisition errors are handled HERE, before the single yield — a body
    # exception thrown back into a double-yielding generator would be masked.
    fh = None
    locked = False
    try:
        _state_dir().mkdir(parents=True, exist_ok=True)
        fh = open(_lock_path(), "a+")
    except Exception:
        fh = None  # can't even create the lock file → degrade to unlocked
    if fh is not None:
        try:
            start = _time.monotonic()
            if sys.platform == "win32":
                import msvcrt

                while True:
                    try:
                        fh.seek(0)
                        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                        locked = True
                        break
                    except OSError:
                        if _time.monotonic() - start > timeout:
                            break
                        _time.sleep(0.1)
            else:
                import fcntl

                while True:
                    try:
                        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        locked = True
                        break
                    except OSError:
                        if _time.monotonic() - start > timeout:
                            break
                        _time.sleep(0.1)
        except Exception:
            locked = False  # lock primitive unusable → degrade to unlocked

    # The ONE yield. The body runs here; its exceptions propagate normally.
    try:
        yield locked
    finally:
        if fh is not None:
            try:
                if locked:
                    if sys.platform == "win32":
                        import msvcrt

                        try:
                            fh.seek(0)
                            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                        except OSError:
                            pass
                    else:
                        import fcntl

                        try:
                            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                        except OSError:
                            pass
            finally:
                try:
                    fh.close()
                except OSError:
                    pass


def _write_selfheal_audit(event: str, detail: Any) -> None:
    """Durable, append-only, fsync'd record of every DESTRUCTIVE registry op
    (selector eviction), written BEFORE the op so a bad eviction is never
    unattributable. Mirrors ``auth/keystore._write_wipe_audit``. Best-effort:
    never raises, never blocks the op it audits.
    """
    try:
        _state_dir().mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,  # evict | ...
            "detail": detail,
            "pid": os.getpid(),
            "worker_id": os.environ.get("DG_WORKER_ID", os.environ.get("SR_WORKER_ID", "?")),
            "stack": [ln.strip() for ln in traceback.format_stack()[-6:-1]],
        }
        with open(_audit_log_path(), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
            fh.flush()
            try:
                os.fsync(fh.fileno())  # survive an immediate os._exit
            except OSError:
                pass
    except Exception:
        pass  # an audit failure must never stop (or crash) the real op


def _atomic_write_json(path: Path, data: Any) -> bool:
    """Atomically persist ``data`` as JSON: temp file + ``os.replace`` so a reader
    always sees a whole file (never a torn write). Returns success; never raises.
    Mirrors ``models._write_model_refresh_overlay``.
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        # Best-effort cleanup so a failed write (e.g. non-serialisable payload,
        # or a replace PermissionError) never leaves an orphaned .tmp behind —
        # mirrors auth/keystore._file_save. The replace is atomic, so the live
        # file is never half-written; only the temp could leak without this.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


def persist_selectors(mutator: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    """Read-modify-write the selector overlay under the cross-process lock.

    ``mutator(current_copy) -> new`` transforms a deep copy of the current overlay;
    the result is written atomically (temp + ``os.replace``). An audit breadcrumb
    is written BEFORE any eviction (keys present before but absent after). Returns
    the persisted overlay, or the unchanged current overlay on any failure. Never
    raises.

    NOTE: PX-0 does not invoke this — it is the foundation the heal loop (PX-2)
    writes through. It is built and tested now so the write path is proven before
    anything depends on it.
    """
    with _selfheal_lock():
        cur = load_selectors()
        try:
            new = mutator(copy.deepcopy(cur))
        except Exception as exc:
            logger.debug("selectors mutator raised: %s — overlay unchanged", exc)
            return cur
        if not isinstance(new, dict):
            return cur
        removed = sorted(set(cur) - set(new))
        if removed:
            # Records eviction INTENT before the write, so a dropped heal is never
            # unattributable. If the write below fails this leaves an orphaned
            # 'evict' record — forensics must cross-check actual selectors.json.
            _write_selfheal_audit("evict", {"keys": removed})
        if _atomic_write_json(_selectors_path(), new):
            return new
        return cur


# ── 4. Pre-act toggle guard (the #709 firewall, extracted) ────────────────────
def decide_toggle(
    target_active: Optional[bool], opposite_confirmed: Optional[bool]
) -> str:
    """The #709 firewall, generalised: decide whether a toggle/radio intent should
    act, judged on the UNMODIFIED page from its outcome-predicate reading.

    Args:
        target_active: is the intent's target state already active?
        opposite_confirmed: is the control CONFIRMED in the opposite (actionable)
            state? (e.g. Gemini composer placeholder explicitly reads "Ask Gemini").

    Returns:
        ``"skip"``      target already active   → return OK, DO NOT click.
        ``"act"``       confirmed-opposite      → safe to click once.
        ``"ambiguous"`` neither confirmed       → NEVER click (capture / escalate).

    A toggle may ONLY ever move a CONFIRMED-opposite control; an ambiguous read
    must never trigger a blind click — that was the bug where the CUA fallback
    clicked an already-active Gemini DR pill and toggled Deep Research back OFF.
    """
    if target_active:
        return "skip"
    if opposite_confirmed:
        return "act"
    return "ambiguous"


# ── 4.5 Tier-1.5 heal resolver (PX-2) — pure matching, ranks durable signals ──
def _norm(s: Optional[str]) -> str:
    """Whitespace-collapse + lowercase for case-insensitive signal matching."""
    return " ".join((s or "").split()).strip().lower()


def ui_fingerprint(snap: list[dict[str, Any]]) -> str:
    """Stable short hash of a region's DURABLE anchors (sorted
    ``role|accessible_name|text`` triples of the visible elements).

    Order-independent and blind to volatile bounds / CSS class, so it survives a
    restyle but changes when the surface's durable structure changes — which is
    exactly when the registry entry should be re-validated / re-healed. Keys the
    ``selectors.json`` overlay (``platform|intent_id|ui_fingerprint``).
    """
    anchors = sorted(
        f"{_norm(el.get('role'))}|{_norm(el.get('accessible_name'))}|{_norm(el.get('text'))}"
        for el in (snap or [])
        if el.get("visible", True)
    )
    return hashlib.sha1("\n".join(anchors).encode("utf-8")).hexdigest()[:12]


# Max achievable raw score = name-exact (1.0) + role (0.4) + one value token (0.6).
# value_contains and value_matches are the SAME "value token" slot (mutually
# exclusive in scoring, see below), so 2.0 is the true ceiling — used to normalise
# confidence into [0, 1].
_MATCH_SCORE_MAX = 2.0


def semantic_match(
    snap: list[dict[str, Any]], signal_hints: dict[str, Any]
) -> Optional[dict[str, Any]]:
    """Find the element in a ``probe_region`` snapshot that best matches an
    intent's ``signal_hints``, ranking by FORGERY/ROTATION resistance (§3.2):
    accessible name + role > visible text > semantic value tokens. CSS class is
    NEVER scored (the #709 failure). Returns ``{element, confidence, reason}`` or
    ``None`` if nothing scores.

    Recognised hints (all optional): ``accessible_name`` (matched against the
    element's aria-label first, then visible text), ``role`` (list of acceptable
    roles), ``value_contains`` / ``value_matches`` (semantic tokens like ``flash``
    / ``opus`` for model triggers). NB: ``placeholder`` in a manifest is an
    OUTCOME-predicate detail (it describes the composer, not the control to act
    on), so it is intentionally NOT used to LOCATE the element.
    """
    name = _norm(signal_hints.get("accessible_name"))
    roles = [r.lower() for r in (signal_hints.get("role") or [])]
    vc = _norm(signal_hints.get("value_contains"))
    vm = _norm(signal_hints.get("value_matches"))
    best = None
    for el in snap or []:
        if not el.get("visible", True):
            continue
        an = _norm(el.get("accessible_name"))
        tx = _norm(el.get("text"))
        role = _norm(el.get("role"))
        score = 0.0
        reasons = []
        if name:
            if an and an == name:
                score += 1.0
                reasons.append("aria==name")
            elif an and name in an:
                score += 0.7
                reasons.append("aria~name")
            elif tx and tx == name:
                score += 0.6
                reasons.append("text==name")
            elif tx and name in tx:
                score += 0.4
                reasons.append("text~name")
        if roles and role in roles:
            score += 0.4
            reasons.append("role")
        # value_contains / value_matches are two spellings of the SAME "value
        # token" signal (e.g. flash / opus) — score at most ONE so a future intent
        # carrying both can't double-count past the _MATCH_SCORE_MAX ceiling.
        if vc and (vc in an or vc in tx):
            score += 0.6
            reasons.append("value_contains")
        elif vm and (vm in an or vm in tx):
            score += 0.6
            reasons.append("value_matches")
        if score <= 0:
            continue
        b = el.get("bounds") or {}
        area = (b.get("w", 0) or 0) * (b.get("h", 0) or 0)
        # Tie-break: higher score, then shorter text (leaf row, not a container),
        # then smaller area (the control, not its wrapper).
        key = (score, -len(tx), -area)
        if best is None or key > best[0]:
            best = (key, el, score, reasons)
    if best is None:
        return None
    _, el, score, reasons = best
    return {
        "element": el,
        "confidence": round(min(1.0, score / _MATCH_SCORE_MAX), 3),
        "reason": ",".join(reasons),
    }


def selector_inference(element: dict[str, Any]) -> list[dict[str, str]]:
    """Map a matched element to a RANKED list of re-resolvable selector strategies,
    most-durable first, per §3.2 (accessible name + role > visible text > semantic
    attr > data-testid > **never CSS class**). The first entry is the preferred
    ``known_good`` strategy; the rest are fallbacks for the validity gate.
    """
    role = _norm(element.get("role")) or "*"
    attrs = element.get("attrs") or {}
    an = _norm(element.get("accessible_name"))
    tx = _norm(element.get("text"))
    haspopup = _norm(attrs.get("haspopup"))
    placeholder = _norm(attrs.get("placeholder"))
    testid = (attrs.get("testid") or "").strip()
    strategies: list[dict[str, str]] = []
    if an:
        strategies.append({"by": "role+name", "value": f"{role}|{an}"})
    if tx:
        strategies.append({"by": "role+text", "value": f"{role}|{tx}"})
    if haspopup:
        strategies.append({"by": "role+haspopup", "value": f"{role}|{haspopup}"})
    if placeholder:
        strategies.append({"by": "role+placeholder", "value": f"{role}|{placeholder}"})
    if testid:
        strategies.append({"by": "testid", "value": testid})
    if not strategies:
        strategies.append({"by": "role", "value": role})
    return strategies  # CSS class is NEVER emitted (forgery/rotation-prone)


def shadow_heal_decision(
    snap: list[dict[str, Any]], intent: dict[str, Any]
) -> dict[str, Any]:
    """PURE: what the Tier-1.5 heal WOULD resolve for ``intent`` given a probe
    ``snap`` — the matched element, its confidence, the selector it would persist,
    and the surface fingerprint. Acts on NOTHING (no click, no persist). The
    shadow layer logs this so we can validate match quality before activating.
    """
    out: dict[str, Any] = {
        "ui_fingerprint": ui_fingerprint(snap),
        "match_found": False,
    }
    m = semantic_match(snap, intent.get("signal_hints") or {})
    if m:
        el = m["element"]
        strategies = selector_inference(el)
        out.update(
            match_found=True,
            match_confidence=m["confidence"],
            match_reason=m["reason"],
            match_role=el.get("role"),
            match_name=el.get("accessible_name") or el.get("text"),
            inferred_selector=strategies[0] if strategies else None,
            strategy_rank=strategies,
        )
    return out


# ── 4.6 Tier-1.5 heal ACTIVATION (PX-2 C5) — resolve → guard → act → verify → persist
# Re-resolves a persisted/inferred strategy to a live element and (optionally)
# clicks it. READ-ONLY unless doClick. Anti-ambiguity: if a strategy resolves to
# more than one visible element it REFUSES to click (a wrong click can't be undone
# safely — escalate instead). Mirrors the probe's visibility rule.
_RESOLVE_CLICK_JS = """(params) => {
    const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
    let root = document.body;
    if (params.scopeSel) {
        const a = document.querySelector(params.scopeSel);
        if (a) {
            let s = a;
            for (let i = 0; i < (params.scopeClimb || 0) && s && s.parentElement; i++) s = s.parentElement;
            root = s || document.body;
        }
    }
    const by = params.by, value = params.value || '';
    const sep = value.indexOf('|');
    const vRole = sep >= 0 ? value.slice(0, sep) : '';
    const vRest = sep >= 0 ? value.slice(sep + 1) : value;
    const vis = el => el.getClientRects().length > 0 || !!el.offsetParent;
    const roleOf = el => (el.getAttribute('role') || el.tagName).toLowerCase();
    const cands = [...root.querySelectorAll(
        'button, [role="button"], [role="menuitem"], [role="menuitemradio"], [role="option"], a, li, [role="switch"], [role="checkbox"]'
    )].filter(vis);
    const match = el => {
        const role = roleOf(el);
        if (by === 'testid') return (el.getAttribute('data-testid') || '') === value;
        if (vRole && role !== vRole) return false;
        if (by === 'role+name') return norm(el.getAttribute('aria-label')) === vRest;
        if (by === 'role+text') return norm(el.textContent) === vRest;
        if (by === 'role+haspopup') return norm(el.getAttribute('aria-haspopup')) === vRest;
        if (by === 'role+placeholder') return norm(el.getAttribute('data-placeholder') || el.getAttribute('placeholder')) === vRest;
        if (by === 'role') return role === vRest;
        return false;
    };
    const hits = cands.filter(match);
    if (!hits.length) return { matched: 0, clicked: false };
    if (hits.length > 1) return { matched: hits.length, clicked: false, ambiguous: true };
    const el = hits[0];
    let clicked = false;
    if (params.doClick) { try { el.click(); clicked = true; } catch (e) {} }
    return { matched: 1, clicked, role: roleOf(el), text: (el.textContent || '').trim().slice(0, 40) };
}"""

# Registry health thresholds (§7): evict a selector after this many CONSECUTIVE
# failed heals (a poisoned/stale strategy must not linger).
_SELECTOR_EVICT_FAILS = 3


async def resolve_and_click(page: Any, region: Any, strategy: dict[str, str], *, do_click: bool) -> dict[str, Any]:
    """Re-resolve ``strategy`` within ``region`` and (if ``do_click``) click the
    sole matching visible element. ``do_click=False`` is the read-only validity
    probe (does this persisted selector still resolve?). Never raises — returns
    ``{}`` on any failure. Refuses to click an ambiguous (>1) match.
    """
    spec = REGIONS.get(region) if isinstance(region, str) else (region or {})
    params = {
        "scopeSel": (spec or {}).get("scopeSel", ""),
        "scopeClimb": int((spec or {}).get("scopeClimb", 0)),
        "by": strategy.get("by"),
        "value": strategy.get("value", ""),
        "doClick": bool(do_click),
    }
    try:
        res = await page.evaluate(_RESOLVE_CLICK_JS, params)
    except Exception as exc:
        logger.debug("resolve_and_click(%s) failed: %s", strategy, exc)
        return {}
    return res if isinstance(res, dict) else {}


def _registry_key(intent_key: str, fingerprint: str) -> str:
    """``platform.intent_id`` + fingerprint → the ``platform|intent_id|fp`` overlay
    key (the schema _valid_selector_entry enforces: exactly two pipes)."""
    return f"{intent_key.replace('.', '|', 1)}|{fingerprint}"


def record_heal(intent_key: str, fingerprint: str, strategy_rank: list[dict[str, str]], *, success: bool) -> dict[str, Any]:
    """Upsert the selector overlay entry under the cross-process lock and update
    its health. On success: bump success_count, reset the consecutive-fail run,
    refresh the working strategy. On failure: bump fail_count + consecutive_fails,
    and EVICT once ``_SELECTOR_EVICT_FAILS`` consecutive fails are reached (the
    eviction is audited by persist_selectors). Returns the persisted overlay.
    """
    key = _registry_key(intent_key, fingerprint)

    def _mut(cur: dict[str, Any]) -> dict[str, Any]:
        e = cur.get(key) or {
            "strategy_rank": strategy_rank,
            "success_count": 0,
            "fail_count": 0,
            "consecutive_fails": 0,
        }
        if success:
            e["success_count"] = e.get("success_count", 0) + 1
            e["consecutive_fails"] = 0
            e["strategy_rank"] = strategy_rank  # the verified-working strategy
        else:
            e["fail_count"] = e.get("fail_count", 0) + 1
            e["consecutive_fails"] = e.get("consecutive_fails", 0) + 1
        tot = e["success_count"] + e["fail_count"]
        e["confidence"] = round(e["success_count"] / tot, 3) if tot else 0.0
        e["last_used"] = datetime.now(timezone.utc).isoformat()
        if e.get("consecutive_fails", 0) >= _SELECTOR_EVICT_FAILS:
            cur.pop(key, None)  # poisoned → evict (audited)
        else:
            cur[key] = e
        return cur

    return persist_selectors(_mut)


async def heal_once(
    page: Any,
    intent: dict[str, Any],
    *,
    check_active: Callable[[], Any],
    confirmed_off: bool,
    do_act: bool,
) -> dict[str, Any]:
    """One bounded Tier-1.5 heal attempt for ``intent`` (PhoenixRecipe §5). Never
    raises — returns a result dict.

    Sequence: probe → fingerprint → Tier-0 registry hit (validity-gated: the
    persisted strategy must still RESOLVE, else evict + fall through) → else
    Tier-1.5 ``semantic_match`` → MANDATORY pre-act toggle guard (``decide_toggle``
    on the live predicate; an ambiguous read NEVER clicks — the #709 firewall) →
    act (only if ``do_act``) → VERIFY-BEFORE-TRUST (re-eval the real predicate) →
    persist the working strategy on pass / record a fail otherwise.

    Args:
        check_active: async/sync callable -> bool, the REAL outcome predicate.
        confirmed_off: the platform's POSITIVE off-signal (not mere "predicate
            false") — gates the click so a false-negative predicate can't toggle a
            live control OFF.
        do_act: actually click + persist (False = full dry-run for the shadow log).
    """
    key = f"{intent.get('platform')}.{intent.get('intent_id')}"
    region = intent.get("region") or "document"
    result: dict[str, Any] = {"intent": key, "tier": None, "acted": False, "healed": False, "reason": ""}
    try:
        snap = await probe_region(page, region)
        fp = ui_fingerprint(snap)
        result["fingerprint"] = fp
        strategy_rank: Optional[list[dict[str, str]]] = None
        tier = None
        # Tier 0 — persisted selector for this fingerprint, validity-gated.
        entry = load_selectors().get(_registry_key(key, fp))
        if entry and entry.get("strategy_rank"):
            probe = await resolve_and_click(page, region, entry["strategy_rank"][0], do_click=False)
            if probe.get("matched"):
                strategy_rank = entry["strategy_rank"]
                tier = "registry"
            elif do_act:
                record_heal(key, fp, entry["strategy_rank"], success=False)  # stale → demote/evict
        # Tier 1.5 — heuristic match.
        if strategy_rank is None:
            m = semantic_match(snap, intent.get("signal_hints") or {})
            if not m:
                result["reason"] = "no_candidate"
                return result
            strategy_rank = selector_inference(m["element"])
            tier = "heal"
        result["tier"] = tier
        result["strategy"] = strategy_rank[0]
        # MANDATORY pre-act toggle guard (#709) — only act from a confirmed-opposite
        # state; never click on an ambiguous read.
        if intent.get("type") == "toggle":
            already = check_active()
            if hasattr(already, "__await__"):
                already = await already
            decision = decide_toggle(bool(already), bool(confirmed_off))
            if decision == "skip":
                result["healed"] = True
                result["reason"] = "already_active"
                return result
            if decision == "ambiguous":
                result["reason"] = "ambiguous_no_act"
                return result
        if not do_act:
            result["reason"] = "shadow_no_act"
            return result
        # ACT.
        click = await resolve_and_click(page, region, strategy_rank[0], do_click=True)
        result["acted"] = bool(click.get("clicked"))
        if not click.get("clicked"):
            result["reason"] = "ambiguous_match" if click.get("ambiguous") else "click_failed"
            record_heal(key, fp, strategy_rank, success=False)
            return result
        # VERIFY-BEFORE-TRUST — re-eval the real predicate; persist only on pass.
        ok = check_active()
        if hasattr(ok, "__await__"):
            ok = await ok
        result["healed"] = bool(ok)
        result["reason"] = "verified" if ok else "act_did_not_satisfy_predicate"
        record_heal(key, fp, strategy_rank, success=bool(ok))
        return result
    except Exception as exc:
        logger.debug("heal_once(%s) failed: %s", key, exc)
        result["reason"] = f"error:{exc}"
        return result


# ── 5. Shadow log ─────────────────────────────────────────────────────────────
def shadow_log(rec: dict[str, Any]) -> None:
    """Append one shadow-eval record to ``logs/selfheal_shadow.jsonl``.

    Schema (PhoenixRecipe §10): ``{ts, platform, intent, tier, outcome_pass,
    selector_or_box, confidence, resolved_by}`` — the caller supplies the fields,
    ``ts`` is stamped here. NO-OP unless ``DG_SELFHEAL_ENABLED``. Lockless and
    crash-safe (one JSON object per line). Never raises — telemetry must never
    break a run.
    """
    if not is_enabled():
        return
    try:
        path = _shadow_log_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        out = {"ts": datetime.now(timezone.utc).isoformat()}
        out.update(rec or {})
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(out, default=str) + "\n")
    except Exception as exc:
        logger.debug("selfheal shadow log append failed: %s", exc)


def capture_snapshot(
    platform: Optional[str],
    intent_id: str,
    snap: list[dict[str, Any]],
    *,
    outcome_pass: Any,
    fingerprint: Optional[str] = None,
) -> None:
    """Append a FULL probe snapshot to ``logs/selfheal_capture.jsonl`` for corpus
    building. NO-OP unless ``DG_SELFHEAL_CAPTURE`` (+ master). One JSON object per
    line; bounded by probe_region's element cap. Never raises — pure data capture.
    """
    if not capture_enabled():
        return
    try:
        path = _capture_log_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "platform": platform,
            "intent": intent_id,
            "ui_fingerprint": fingerprint or ui_fingerprint(snap),
            "outcome_pass": bool(outcome_pass),
            "snapshot": snap,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    except Exception as exc:
        logger.debug("selfheal capture failed: %s", exc)
