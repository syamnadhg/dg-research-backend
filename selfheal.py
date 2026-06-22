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
