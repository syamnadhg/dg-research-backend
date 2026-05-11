"""One-shot helper to regenerate the Google OAuth refresh token used by the
FE for Phase 4 (YouTube upload) and Phase 5 (Doc + email).

Background:
    The FE's `/api/uploadYouTube` and `/api/createDoc` routes authenticate as
    a Workspace user (the project owner) via an OAuth refresh token held in
    Firebase App Hosting Secret Manager as `GOOGLE_OAUTH_REFRESH_TOKEN`.

    Before the 2026-05-10 P4 cutover the token only needed:
        drive + documents
    After the cutover it must also include:
        youtube.upload

    A refresh token cannot be "re-scoped" in place — you have to re-run
    OAuth consent with the new combined scope set, then replace the secret.

Usage:
    1. Make sure GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_CLIENT_SECRET are
       available as env vars OR pass them via --client-id / --client-secret.
    2. Run:
           python scripts/regenerate_oauth_refresh_token.py
    3. A browser tab opens for Google consent — sign in as the project owner
       (sammy.guli@distributedglobal.com) and approve the three scopes.
    4. The script prints the new refresh token. Copy it.
    5. Update the App Hosting secret:
           firebase apphosting:secrets:set GOOGLE_OAUTH_REFRESH_TOKEN
       Paste the token at the prompt. App Hosting picks up the new version
       on the next request to /api/uploadYouTube or /api/createDoc — no
       redeploy needed.

Why a local script vs the OAuth Playground:
    - Uses YOUR OAuth client (same one App Hosting uses), so the refresh
      token is bound to the right project + redirect URIs.
    - Reproducible — re-run any time you need to rotate or add a scope.

Dependencies:
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

    if not args.client_id or not args.client_secret:
        print(
            "ERROR: missing OAuth client credentials. Pass --client-id and "
            "--client-secret, or set GOOGLE_OAUTH_CLIENT_ID + "
            "GOOGLE_OAUTH_CLIENT_SECRET in your env first.",
            file=sys.stderr,
        )
        print(
            "\nTo fetch the existing values from App Hosting Secret Manager:",
            file=sys.stderr,
        )
        print(
            "    firebase apphosting:secrets:access GOOGLE_OAUTH_CLIENT_ID",
            file=sys.stderr,
        )
        print(
            "    firebase apphosting:secrets:access GOOGLE_OAUTH_CLIENT_SECRET",
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

    print("\n" + "=" * 70)
    print("NEW REFRESH TOKEN — copy this entire line (no spaces):")
    print("=" * 70)
    print(creds.refresh_token)
    print("=" * 70)
    print("\nNext step — update App Hosting Secret Manager:")
    print("    firebase apphosting:secrets:set GOOGLE_OAUTH_REFRESH_TOKEN")
    print("Paste the token above when prompted. App Hosting picks up the new")
    print("version on the next /api/uploadYouTube or /api/createDoc call.")
    print()
    print("Granted scopes:")
    for s in SCOPES:
        print(f"    {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
