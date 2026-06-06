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
  * It writes only what a normal account client may write (research docs +
    device-queue start docs), all gated by the existing Firestore rules.
  * Research-only: it can never control devices (add/remove/pair/share).
"""

__version__ = "0.0.1"
