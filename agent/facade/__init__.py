"""research-facade — the Super Agent bridge.

A standalone, account-authed client on Super Research's normal Firestore
plane. It lets a chat runtime (Hermes / OpenClaw) drive Super Research as a
*headless session of the user's account*: the user signs in once with Google
(`/login`), and the bridge then enqueues research runs on the account's
existing devices. Runs surface in the web app as normal chats.

Hard boundaries (the "nothing breaks" contract):
  * This package NEVER imports or mutates research-automate or research-app.
  * It uses its OWN secret store namespace ("super-agent"), never the device
    daemon's keystore ("super-research") — so refresh-token rotation here can
    never disturb a paired device.
  * It writes only what a normal account client may write, and every write is
    gated by the existing Firestore rules. The authoritative list is not here —
    it is the allowlist in `tests/test_app_plane_unchanged.py`, which is derived
    from the code and fails when a new writer appears.
  * It never writes MEMBERSHIP. Pairing, unlinking and answering an access
    request all forward to `/api/devices/*` and are authorised there against the
    caller's own session; this package holds no admin credential and can grant
    itself nothing. ⚠ `device-visibility` is the one device verb that does NOT
    forward — it PATCHes the device document directly, because no web route for
    it exists. That write is a single field and the rules check its value.
"""

# ⛔⛔ TWO OF THE BULLETS ABOVE WERE FALSE AND ARE RECORDED HERE RATHER THAN IN
# THE CONTRACT ITSELF, because a contract that is half archaeology is harder to
# read than one that is current — and because the guard that keeps these claims
# true sweeps CODE ONLY. `code_only()` blanks `#` comments and a docstring is a
# string literal, so an explanation quoting the old claim INSIDE the docstring
# satisfies the search and leaves the sweep green over the falsehood. That is
# exactly what happened when this correction was first written; it is the fifth
# time in one wave that prose quoting the searched string defeated a guard.
#
# ⛔⛔ "Research-only: it can never control devices (add/remove/pair/share)" was
# FALSE ON ALL FOUR VERBS. `/device/pair`, `/device/remove` and `/device/decide`
# have existed here since 7.9-1, plus `/device/visibility` and `/device/ask`. It
# stood in the one file whose whole job is to say what this package will not do.
#
# ⛔⛔ AND ITS FIRST REPLACEMENT WAS ALSO FALSE — written in 7.9-5 and caught by
# the same wave's cross-verify. It said EVERY device verb forwards to a web
# route. `device-visibility` does not: it PATCHes `devices/{id}` directly through
# `firestore_rest`, and the bridge handler's own docstring says "THERE IS NO WEB
# ROUTE TO RELAY". I had written that exact fact into the 7.95 groups proposal
# the same day and then wrote its opposite into the contract. Replacing a false
# claim with a different false claim is the failure this file keeps having.
#
# ⛔ THE WRITE ENUMERATION WAS WRONG TWICE FOR THE SAME REASON: first "research
# docs + device-queue start docs", then "…plus visibility and one access-request
# document". Cross-verify counted at least SEVEN more — agent-session PATCH and
# DELETE, device commands, research commands, chat-message PATCH, research-doc
# DELETE, and queue CANCEL and RESUME docs, not only "start". A prose list of
# writers cannot be kept true by hand, so this file no longer keeps one: it
# points at the allowlist test, which is derived and fails when a writer appears.

# Reported by `agent --version` + `agent doctor`. Read from the installed
# package metadata so it never drifts from pyproject's version (when run via
# pipx / a pip install); falls back to the literal when run from a source
# checkout (`python -m facade.cli …`, not installed as a distribution).
try:
    from importlib.metadata import PackageNotFoundError, version as _pkg_version

    try:
        __version__ = _pkg_version("superresearch-agent")
    except PackageNotFoundError:
        __version__ = "0.1.32"
except Exception:
    __version__ = "0.1.32"
