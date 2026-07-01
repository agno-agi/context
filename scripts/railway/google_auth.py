#!/usr/bin/env python3
"""
Mint Google OAuth tokens to Railway DB.

Connects to Railway PostgreSQL via TCP proxy, runs OAuth flow, saves encrypted
tokens. Creates TCP proxy if needed via Railway GraphQL API.

Usage:
    python scripts/railway/google_auth.py              # mint if no token exists
    python scripts/railway/google_auth.py --force      # re-mint (delete + mint)

Prerequisites:
    - Railway CLI installed and logged in (`railway login`)
    - Project deployed (`./scripts/railway/up.sh`)
    - .env with GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_TOKEN_ENCRYPTION_KEY
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


def run(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def gql(query: str, token: str) -> dict:
    return requests.post(
        "https://backboard.railway.com/graphql/v2",
        json={"query": query},
        headers={"Authorization": f"Bearer {token}"},
    ).json()


def main() -> int:
    parser = argparse.ArgumentParser(description="Mint Google OAuth tokens to Railway DB")
    parser.add_argument("--force", action="store_true", help="Delete existing token and re-mint")
    args = parser.parse_args()

    from dotenv import load_dotenv

    os.chdir(REPO_ROOT)
    load_dotenv()

    # 1. Check prerequisites
    if not os.getenv("GOOGLE_CLIENT_ID") or not os.getenv("GOOGLE_CLIENT_SECRET"):
        print("ERROR: GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET required in .env")
        return 1

    if not os.getenv("GOOGLE_TOKEN_ENCRYPTION_KEY"):
        print("ERROR: GOOGLE_TOKEN_ENCRYPTION_KEY not set.")
        print("       Generate: python scripts/google_mint_tokens.py --generate-key")
        return 1

    # 2. Railway project
    print("Connecting to Railway...\n")

    project_json = run("railway status --json")
    if not project_json:
        print("ERROR: No Railway project linked. Run: railway link")
        return 1

    project = json.loads(project_json).get("name", "")
    print(f"  Project:  {project}")

    pgvars_json = run("railway variables --service pgvector --json")
    if not pgvars_json:
        print("ERROR: pgvector service not found. Run: ./scripts/railway/up.sh")
        return 1

    pgvars = json.loads(pgvars_json)
    service_id = pgvars.get("RAILWAY_SERVICE_ID", "")
    env_id = pgvars.get("RAILWAY_ENVIRONMENT_ID", "")

    # 3. Railway access token
    config_path = Path.home() / ".railway" / "config.json"
    with open(config_path) as f:
        access_token = json.load(f).get("user", {}).get("accessToken", "")

    if not service_id or not access_token:
        print("ERROR: Missing Railway credentials. Run: railway login")
        return 1

    # 4. TCP proxy (query or create)
    query = f'{{ tcpProxies(serviceId: "{service_id}", environmentId: "{env_id}") {{ domain proxyPort applicationPort }} }}'
    result = gql(query, access_token)

    proxy = None
    for p in result.get("data", {}).get("tcpProxies", []):
        if p.get("applicationPort") == 5432:
            proxy = f"{p['domain']}:{p['proxyPort']}"
            break

    if not proxy:
        mutation = f'mutation {{ tcpProxyCreate(input: {{ serviceId: "{service_id}", environmentId: "{env_id}", applicationPort: 5432 }}) {{ domain proxyPort }} }}'
        data = gql(mutation, access_token).get("data", {}).get("tcpProxyCreate", {})
        if not data.get("domain"):
            print(f"ERROR: Failed to create TCP proxy")
            return 1
        proxy = f"{data['domain']}:{data['proxyPort']}"
        print(f"  TCP:      {proxy} (created)")
    else:
        print(f"  TCP:      {proxy}")

    # 5. Database connection
    db_user = pgvars.get("POSTGRES_USER", "context")
    db_pass = pgvars.get("POSTGRES_PASSWORD", "context")
    db_name = pgvars.get("POSTGRES_DB", "context")
    db_url = f"postgresql+psycopg://{db_user}:{db_pass}@{proxy}/{db_name}"

    from sqlalchemy import create_engine, text

    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("  Database: connected\n")
    except Exception as e:
        print(f"ERROR: Database connection failed: {e}")
        return 1

    # 6. Auth config
    os.environ["DATABASE_PUBLIC_URL"] = db_url

    from agents.providers.google import get_google_auth

    auth = get_google_auth()
    if not auth or not auth.db:
        print("ERROR: Failed to create auth config")
        return 1

    print(f"Scopes: {len(auth.scopes)} (Gmail + Calendar)")
    print(f"DB: {auth.db.id}")
    print("Encryption: enabled\n")

    # 7. Check existing token
    row = auth.db.get_auth_token("google", None, "google")
    if row and not args.force:
        scopes = row.get("granted_scopes", [])
        print(f"Token already exists with {len(scopes)} scopes:")
        for s in scopes:
            print(f"  - {s.split('/')[-1]}")
        print("\nUse --force to delete and re-mint.")
        return 0

    if row and args.force:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM ai.agno_auth_tokens WHERE provider = 'google'"))
        print("Deleted existing token.\n")

    # 8. OAuth flow
    from agno.tools.google.gmail import GmailTools

    print("Opening browser for OAuth consent...")
    print("(Grant access to Gmail + Calendar)\n")

    gmail = GmailTools(auth=auth)
    result = gmail.get_latest_emails(count=1)

    if "error" in result.lower():
        print(f"FAILED: {result}")
        return 1

    # 9. Verify
    row = auth.db.get_auth_token("google", None, "google")
    if not row:
        print("FAILED: Token not saved to DB")
        return 1

    from agno.utils.encryption import is_encrypted

    if not is_encrypted(row.get("token_data", {})):
        print("WARNING: Token saved but NOT encrypted.")
        return 1

    scopes = row.get("granted_scopes", [])
    print(f"SUCCESS: Encrypted token saved to Railway DB with {len(scopes)} scopes:")
    for s in scopes:
        print(f"  - {s.split('/')[-1]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
