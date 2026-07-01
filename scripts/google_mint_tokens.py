#!/usr/bin/env python3
"""
Mint Google OAuth tokens — encrypted, DB-backed.

Opens a browser for OAuth consent, saves the encrypted token to PostgreSQL.
Requires GOOGLE_TOKEN_ENCRYPTION_KEY to be set (tokens are always encrypted).

Usage:
    python scripts/google_mint_tokens.py              # mint if no token exists
    python scripts/google_mint_tokens.py --force      # re-mint (delete + mint)
    python scripts/google_mint_tokens.py --generate-key  # print a new encryption key

Setup:
    1. Create OAuth credentials at https://console.cloud.google.com
       (Enable Gmail + Calendar APIs, create Desktop app credentials)
    2. Add to .env:
       GOOGLE_CLIENT_ID=...
       GOOGLE_CLIENT_SECRET=...
       GOOGLE_TOKEN_ENCRYPTION_KEY=<run with --generate-key>
    3. Run this script to mint the token
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def generate_key() -> str:
    from agno.utils.encryption import generate_encryption_key

    return generate_encryption_key()


def main() -> int:
    parser = argparse.ArgumentParser(description="Mint Google OAuth tokens (encrypted, DB-backed)")
    parser.add_argument("--force", action="store_true", help="Delete existing token and re-mint")
    parser.add_argument("--generate-key", action="store_true", help="Generate an encryption key and exit")
    args = parser.parse_args()

    if args.generate_key:
        key = generate_key()
        print(f"GOOGLE_TOKEN_ENCRYPTION_KEY={key}")
        print("\nAdd this to your .env file.")
        return 0

    from dotenv import load_dotenv

    load_dotenv()

    import os

    from agents.providers.google import get_google_auth, google_configured

    # 1. Check OAuth credentials
    if not google_configured():
        print("ERROR: Set GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET in .env")
        print("       See docs/GOOGLE.md for setup instructions.")
        return 1

    # 2. Check encryption key
    encryption_key = os.getenv("GOOGLE_TOKEN_ENCRYPTION_KEY")
    if not encryption_key:
        print("ERROR: GOOGLE_TOKEN_ENCRYPTION_KEY not set.")
        print("       Generate one with: python scripts/google_mint_tokens.py --generate-key")
        return 1

    # 3. Create auth config
    auth = get_google_auth()
    if not auth:
        print("ERROR: Failed to create AuthConfig")
        return 1

    if not auth.db:
        print("ERROR: Database not configured. Check DB_* env vars.")
        return 1

    print(f"Scopes: {len(auth.scopes)} (Gmail + Calendar)")
    print(f"DB: {auth.db.id}")
    print(f"Encryption: enabled")
    print()

    # 4. Check existing token
    row = auth.db.get_auth_token("google", None, "google")
    if row and not args.force:
        scopes = row.get("granted_scopes", [])
        print(f"Token already exists with {len(scopes)} scopes:")
        for s in scopes:
            print(f"  - {s.split('/')[-1]}")
        print("\nUse --force to delete and re-mint.")
        return 0

    if row and args.force:
        from db.url import db_url
        from sqlalchemy import create_engine, text

        engine = create_engine(db_url)
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM ai.agno_auth_tokens WHERE provider = 'google'"))
        print("Deleted existing token.\n")

    # 5. Trigger OAuth
    from agno.tools.google.gmail import GmailTools

    print("Opening browser for OAuth consent...")
    print("(Grant access to Gmail + Calendar)\n")

    gmail = GmailTools(auth=auth)
    result = gmail.get_latest_emails(count=1)

    if "error" in result.lower():
        print(f"FAILED: {result}")
        return 1

    # 6. Verify token was saved
    row = auth.db.get_auth_token("google", None, "google")
    if not row:
        print("FAILED: Token not saved to DB")
        return 1

    from agno.utils.encryption import is_encrypted

    token_data = row.get("token_data", {})
    if not is_encrypted(token_data):
        print("WARNING: Token saved but NOT encrypted. Check encryption key.")
        return 1

    scopes = row.get("granted_scopes", [])
    print(f"SUCCESS: Encrypted token saved to DB with {len(scopes)} scopes:")
    for s in scopes:
        print(f"  - {s.split('/')[-1]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
