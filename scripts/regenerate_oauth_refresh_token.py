"""One-shot helper to (re-)generate the Google OAuth refresh token used by
the FE for Phase 4 (YouTube upload) and Phase 5 (Google Doc + Drive +
email).

Two paths cover this script:

1. **Per-user OAuth** — every signed-in user can plug in their own Google
   credentials in the Super Research web app at Account → API Keys →
   Google OAuth, so THEIR Docs / YouTube uploads land in their own
   account. Run this script to generate the refresh token, then paste
   the printed token into the Account page along with the matching
   Client ID + Client Secret.

2. **Default fallback** (project owner only) — the shared OAuth identity
   used when a user hasn't set their own. Held in Firebase App Hosting
   Secret Manager as `GOOGLE_OAUTH_REFRESH_TOKEN`. Run this script with
   the project owner's OAuth client, then update the secret via:
       firebase apphosting:secrets:set GOOGLE_OAUTH_REFRESH_TOKEN

The 7-day expiry problem (only personal-Gmail External + Testing-mode
apps): re-run this script weekly to get a fresh token. Workspace
Internal-user-type apps don't expire — no script run needed.

Usage:
    # Interactive — prompts for Client ID + Client Secret:
    python scripts/regenerate_oauth_refresh_token.py

    # Non-interactive — flags or env vars:
    python scripts/regenerate_oauth_refresh_token.py \\
        --client-id "..." --client-secret "..."

    GOOGLE_OAUTH_CLIENT_ID=... GOOGLE_OAUTH_CLIENT_SECRET=... \\
        python scripts/regenerate_oauth_refresh_token.py

Cloud Console prerequisites (one-time setup before first run):
    1. Pick a project in the Google account whose Drive/YouTube you want
       data to land in
    2. Enable APIs: YouTube Data API v3, Google Drive API, Google Docs API
    3. OAuth consent screen: External user type, add the 3 scopes below,
       add yourself as a Test user
    4. Create an OAuth client — type **Desktop app** (no redirect URI
       config needed) OR **Web application** with redirect URI
       `http://localhost:8765/`
    5. Create a YouTube channel on the account (required for video upload)

Why a local script vs the OAuth Playground:
    - Reproducible: ~3 minutes to regen the token whenever it expires
    - Uses YOUR OAuth client directly, no third-party hop
    - Same script for both setup paths above

Dependencies (auto-detected; install once if missing):
    pip install google-auth google-auth-oauthlib
"""

from __future__ import annotations

import argparse
import os
import sys

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/youtube.upload",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client-id",
        default=os.environ.get("GOOGLE_OAUTH_CLIENT_ID"),
        help="OAuth Client ID (defaults to env GOOGLE_OAUTH_CLIENT_ID)",
    )
    parser.add_argument(
        "--client-secret",
        default=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET"),
        help="OAuth Client Secret (defaults to env GOOGLE_OAUTH_CLIENT_SECRET)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Local port for the OAuth callback (default 8765)",
    )
    args = parser.parse_args()

    # Interactive fallback when neither flag nor env var supplies a value.
    # Most users running this script will be following the in-app help modal,
    # which doesn't ask them to set env vars first — prompt instead so the
    # script "just works" on a fresh terminal.
    if not args.client_id:
        try:
            args.client_id = input("Client ID: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            return 1
    if not args.client_secret:
        try:
            args.client_secret = input("Client Secret: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            return 1

    if not args.client_id or not args.client_secret:
        print(
            "ERROR: Client ID and Client Secret are both required.",
            file=sys.stderr,
        )
        return 2

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    except ImportError:
        print(
            "ERROR: google-auth-oauthlib not installed. Run:\n"
            "    pip install google-auth google-auth-oauthlib",
            file=sys.stderr,
        )
        return 2

    client_config = {
        "installed": {
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [f"http://localhost:{args.port}/"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    # access_type=offline + prompt=consent forces Google to issue a fresh
    # refresh token even if the user previously consented. Without
    # prompt=consent, re-consenting an existing grant returns access_token
    # only and the refresh_token field comes back None.
    creds = flow.run_local_server(
        port=args.port,
        access_type="offline",
        prompt="consent",
        open_browser=True,
        success_message="Got the token. You can close this tab.",
    )

    if not creds.refresh_token:
        print(
            "\nERROR: No refresh_token returned. This usually means Google "
            "skipped issuing one because the consent was a no-op. Try again "
            "with --port set to a different value to force a fresh grant.",
            file=sys.stderr,
        )
        return 1

    # ASCII-only output: Windows default console codepage (cp1252) can't
    # encode "->" arrow or em-dash, which crashed the script AFTER the
    # token was already captured. Result was a confusing "exit code 1"
    # even though the OAuth flow succeeded. Stick to ASCII characters
    # the cp1252 codepage handles cleanly.
    print("\n" + "=" * 70)
    print("NEW REFRESH TOKEN -- copy this entire line (no spaces):")
    print("=" * 70)
    print(creds.refresh_token)
    print("=" * 70)
    print("\nNext step -- pick whichever path applies:")
    print()
    print("  A. Per-user OAuth (most users)")
    print("     Open Super Research -> Account -> API Keys -> Google OAuth.")
    print("     Paste Client ID, Client Secret, and the Refresh Token above.")
    print("     Click 'Save (validate + store)'.")
    print()
    print("  B. Default fallback (project owner only)")
    print("     firebase apphosting:secrets:set GOOGLE_OAUTH_REFRESH_TOKEN")
    print("     Paste the token above when prompted. Cloud Run picks up the")
    print("     new version on the next /api/uploadYouTube or /api/createDoc")
    print("     call -- no redeploy needed.")
    print()
    print("Granted scopes:")
    for s in SCOPES:
        print(f"    {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
