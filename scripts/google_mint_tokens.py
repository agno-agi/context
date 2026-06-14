#!/usr/bin/env python3
"""
@context Google token minter — connects your Gmail + Calendar.

The OAuth consent flow opens a browser, so it can't run in the container — you
mint the tokens once on your machine and the dev container picks them up through
the .:/app mount. This script is the one-command version of that: it loads .env,
checks the OAuth client is configured, and mints a token file for Gmail and one
for Calendar with exactly the scopes @context's providers use.

Usage (from the repo root, with the venv active — ./scripts/venv_setup.sh):

    python scripts/google_mint_tokens.py

Prereqs in .env (see docs/GOOGLE.md):
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID

The tokens are written to GMAIL_TOKEN_FILE / CALENDAR_TOKEN_FILE (or the repo
root by default) — gitignored. Your browser opens twice; approve both.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# The scopes the Gmail + Calendar providers use. Minted as the union of read +
# write so the read and write sub-agents can share one token file per service.
# Kept in sync with docs/GOOGLE.md.
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
]
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar",
]


def _load_dotenv() -> None:
    """Populate os.environ from .env at the repo root (without overriding real env).

    A tiny, dependency-free parser — enough for KEY=VALUE lines so you don't
    have to `set -a; source .env` first. Real environment values win.
    """
    from os import environ

    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in environ:
            environ[key] = value


def main() -> int:
    from os import getenv

    _load_dotenv()

    missing = [k for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET") if not getenv(k)]
    if missing:
        print(f"Missing required env: {', '.join(missing)}.")
        print("Set the OAuth client in .env — see docs/GOOGLE.md.")
        return 1

    from agents.sources import calendar_token_path, gmail_token_path

    gmail_token = gmail_token_path()
    calendar_token = calendar_token_path()

    print("Minting Google tokens — your browser will open twice (Gmail, then Calendar).")
    print("Approve both consent screens.\n")

    # Importing here keeps the missing-env message fast and dependency-light.
    from agno.tools.google.calendar import GoogleCalendarTools
    from agno.tools.google.gmail import GmailTools

    # Each call triggers the OAuth flow on first use and writes the token file.
    print("→ Gmail...")
    GmailTools(token_path=gmail_token, scopes=GMAIL_SCOPES).get_latest_emails(1)
    if not Path(gmail_token).exists():
        print(f"Gmail token was not written to {gmail_token} — check the client credentials.")
        return 1
    print(f"  wrote {gmail_token}")

    print("→ Calendar...")
    GoogleCalendarTools(token_path=calendar_token, scopes=CALENDAR_SCOPES).list_events(limit=1)
    if not Path(calendar_token).exists():
        print(f"Calendar token was not written to {calendar_token} — check the client credentials.")
        return 1
    print(f"  wrote {calendar_token}")

    print("\nDone. Restart to pick them up: docker compose up -d")
    print(
        "\nDeploying to Railway? OAuth token files don't survive a redeploy — ship them\n"
        "as base64 (the entrypoint restores them at startup):\n"
        f'  echo "GMAIL_TOKEN_JSON_B64=$(base64 < {gmail_token})" >> .env.production\n'
        f'  echo "CALENDAR_TOKEN_JSON_B64=$(base64 < {calendar_token})" >> .env.production\n'
        "  ./scripts/railway/env-sync.sh\n"
        "Re-run this minter and re-sync if the tokens are ever revoked."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
