#!/usr/bin/env python3
"""
Migrate Google OAuth tokens from file to database.

Reads existing token files (gmail_token.json, calendar_token.json),
encrypts them, and stores in PostgreSQL. After migration, the file
tokens can be deleted.

Usage:
    python scripts/migrate_google_tokens_to_db.py [--dry-run]
"""

import argparse
import json
import sys
from pathlib import Path

import os

from dotenv import load_dotenv

load_dotenv()

from agno.utils.encryption import encrypt_dict
from db import get_postgres_db


def get_encryption_key() -> str | None:
    return os.getenv("GOOGLE_TOKEN_ENCRYPTION_KEY")


def migrate_token(token_path: Path, db, encryption_key: str | None, dry_run: bool) -> bool:
    """Migrate a single token file to DB."""
    if not token_path.exists():
        print(f"  {token_path.name}: not found, skipping")
        return False

    try:
        token_data = json.loads(token_path.read_text())
    except Exception as e:
        print(f"  {token_path.name}: failed to read ({e})")
        return False

    # Extract scopes from token
    scopes = token_data.get("scopes", [])
    if not scopes:
        scopes = ["https://www.googleapis.com/auth/gmail.readonly"]

    # Encrypt if key provided
    if encryption_key:
        encrypted_data = encrypt_dict(token_data, key=encryption_key)
        print(f"  {token_path.name}: encrypted ({len(encrypted_data['encrypted'])} chars)")
    else:
        encrypted_data = token_data
        print(f"  {token_path.name}: NOT encrypted (set GOOGLE_TOKEN_ENCRYPTION_KEY)")

    if dry_run:
        print(f"  {token_path.name}: would save to DB (dry run)")
        return True

    # Save to DB
    result = db.upsert_auth_token(
        {
            "provider": "google",
            "user_id": "",
            "service": "google",
            "token_data": encrypted_data,
            "granted_scopes": scopes,
        }
    )

    if result:
        print(f"  {token_path.name}: saved to DB")
        return True
    else:
        print(f"  {token_path.name}: failed to save to DB")
        return False


def main():
    parser = argparse.ArgumentParser(description="Migrate Google tokens to DB")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually save to DB")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    gmail_token = repo_root / "gmail_token.json"
    calendar_token = repo_root / "calendar_token.json"

    encryption_key = get_encryption_key()
    if not encryption_key:
        print("WARNING: GOOGLE_TOKEN_ENCRYPTION_KEY not set, tokens will be stored unencrypted")

    db = get_postgres_db()
    print("Migrating Google OAuth tokens to database...")

    # Gmail and Calendar share the same token in DB (unified Google auth)
    # We'll use the Gmail token as the primary, since it typically has more scopes
    migrated = False
    for token_path in [gmail_token, calendar_token]:
        if migrate_token(token_path, db, encryption_key, args.dry_run):
            migrated = True
            break

    if migrated and not args.dry_run:
        print("\nMigration complete. You can now delete the token files:")
        print(f"  rm {gmail_token}")
        print(f"  rm {calendar_token}")
    elif not migrated:
        print("\nNo tokens migrated.")

    return 0 if migrated else 1


if __name__ == "__main__":
    sys.exit(main())
