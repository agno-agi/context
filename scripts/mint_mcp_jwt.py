#!/usr/bin/env python3
"""
@context — self-issue the production MCP bearer token.

Your deployed @context verifies JWTs against a public key. By default that key is
the os.agno.com control-plane key, and os.agno.com mints the tokens its UI uses —
which you can't easily copy into an MCP client config. This script makes @context
*also* trust a key you own, so you can mint your own durable admin token locally,
with no os.agno.com round-trip. Both issuers work at once (multi-issuer
verification — see https://docs.agno.com/agent-os/security/authorization/self-hosted),
so the AgentOS UI keeps working.

What it does:

  1. Generates an RS256 keypair (once) — private key in `secrets/` (gitignored,
     chmod 600), used only here to sign. The server never sees the private key.
  2. Derives the *public* key → `CONTEXT_SELF_VERIFICATION_KEY`. The app adds it
     to its verification list (app/main.py) so your tokens verify.
  3. Signs an admin JWT (`sub` = your owner id, `scopes` = ["agent_os:admin"],
     long expiry) → `CONTEXT_MCP_JWT`, the token scripts/connect.py threads into
     your MCP clients.

Usage (run in the venv — `source .venv/bin/activate`):

    python scripts/mint_mcp_jwt.py            # print the two values + next steps
    python scripts/mint_mcp_jwt.py --write    # upsert them into .env.production (backed up)
    python scripts/mint_mcp_jwt.py --rotate-key   # regenerate the keypair (invalidates old tokens)
    python scripts/mint_mcp_jwt.py --ttl-days 90  # shorter-lived token (default 365)
    python scripts/mint_mcp_jwt.py --sub you@example.com   # override owner id (else read from .env.production)

After `--write`: run `./scripts/railway/env-sync.sh` (pushes the public key so the
deploy trusts it — the token itself is kept local), then
`python scripts/connect.py --production`. Or do it all with
`./scripts/setup_context.sh` (add `--no-redeploy` to skip the redeploy).
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = REPO_ROOT / ".env.production"
DEFAULT_PRIVATE_KEY = REPO_ROOT / "secrets" / "context_jwt_private.pem"

ALGORITHM = "RS256"
PUBLIC_KEY_ENV = "CONTEXT_SELF_VERIFICATION_KEY"  # public key the app verifies against (server-side)
TOKEN_ENV = "CONTEXT_MCP_JWT"  # the signed bearer token connect.py reads (client-side, local only)
DEFAULT_SCOPES = ["agent_os:admin"]  # admin scope → covers the MCP route under RBAC
DEFAULT_TTL_DAYS = 365


# ---------------------------------------------------------------------------
# Reading the owner id
# ---------------------------------------------------------------------------
def read_owner_id(env_file: Path) -> str | None:
    """First (canonical) entry of OWNER_ID in the env file — the token's `sub`.

    A single-line scan is enough: OWNER_ID is single-line, and PEM blocks never
    contain a line starting with `OWNER_ID=`.
    """
    if not env_file.exists():
        return None
    match = re.search(r"(?m)^OWNER_ID=(.*)$", env_file.read_text())
    if not match:
        return None
    raw = match.group(1).strip().strip('"').strip("'")
    first = raw.split(",")[0].strip()
    return first or None


# ---------------------------------------------------------------------------
# Keypair
# ---------------------------------------------------------------------------
def load_or_create_private_key(path: Path, *, rotate: bool) -> tuple[rsa.RSAPrivateKey, bool]:
    """Load the signing key, or generate a new one. Returns (key, created)."""
    if path.exists() and not rotate:
        loaded = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(loaded, rsa.RSAPrivateKey):
            sys.exit(f"  ✗ {path} is not an RSA private key. Use --rotate-key to regenerate.")
        return loaded, False

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_private_pem(key).encode())
    path.chmod(0o600)
    return key, True


def _private_pem(key: rsa.RSAPrivateKey) -> str:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def public_pem(key: rsa.RSAPrivateKey) -> str:
    return (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
        .strip()
    )


def sign_token(key: rsa.RSAPrivateKey, *, sub: str, scopes: list[str], ttl_days: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "scopes": scopes,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=ttl_days)).timestamp()),
    }
    return jwt.encode(payload, _private_pem(key), algorithm=ALGORITHM)


# ---------------------------------------------------------------------------
# Writing values into .env.production (PEM-aware upsert)
# ---------------------------------------------------------------------------
def upsert_env_var(text: str, key: str, value: str) -> str:
    """Set `key=value` in dotenv `text`, replacing an existing entry in place.

    Handles multi-line PEM values the way scripts/railway/env-sync.sh reads them:
    a `KEY=-----BEGIN ...` line whose value continues until the `-----END-----`
    line. Appends the var if absent.
    """
    lines = text.splitlines()
    block = f"{key}={value}".split("\n")

    start = next((i for i, line in enumerate(lines) if line.startswith(f"{key}=")), None)
    if start is None:
        if lines and lines[-1].strip() != "":
            lines.append("")
        lines.extend(block)
        return "\n".join(lines) + "\n"

    end = start
    first_val = lines[start].split("=", 1)[1]
    if "-----BEGIN" in first_val and "-----END" not in first_val:
        while end + 1 < len(lines) and "-----END" not in lines[end]:
            end += 1
    lines[start : end + 1] = block
    return "\n".join(lines) + "\n"


def _backup(path: Path) -> Path:
    backup = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    backup.write_text(path.read_text())
    return backup


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Self-issue the production MCP bearer token for @context.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--env-file", type=Path, default=DEFAULT_ENV_FILE, help="env file to read/write (default: .env.production)"
    )
    parser.add_argument(
        "--private-key",
        type=Path,
        default=DEFAULT_PRIVATE_KEY,
        help="signing key path (default: secrets/context_jwt_private.pem)",
    )
    parser.add_argument("--sub", default=None, help="token subject (default: first OWNER_ID in the env file)")
    parser.add_argument(
        "--scopes", nargs="+", default=DEFAULT_SCOPES, help=f"token scopes (default: {' '.join(DEFAULT_SCOPES)})"
    )
    parser.add_argument(
        "--ttl-days", type=int, default=DEFAULT_TTL_DAYS, help=f"token lifetime in days (default: {DEFAULT_TTL_DAYS})"
    )
    parser.add_argument(
        "--rotate-key",
        action="store_true",
        help="regenerate the signing keypair (invalidates tokens minted with the old key)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"upsert {PUBLIC_KEY_ENV} and {TOKEN_ENV} into the env file (timestamped backup)",
    )
    args = parser.parse_args()

    sub = args.sub or read_owner_id(args.env_file)
    if not sub:
        print(f"  ✗ No subject. Set OWNER_ID in {args.env_file} or pass --sub <id>.", file=sys.stderr)
        return 1

    key, created = load_or_create_private_key(args.private_key, rotate=args.rotate_key)
    pub = public_pem(key)
    token = sign_token(key, sub=sub, scopes=args.scopes, ttl_days=args.ttl_days)

    keystate = "generated new" if created else "reused existing"
    print(
        f"@context: minted MCP token (sub={sub}, scopes={args.scopes}, ttl={args.ttl_days}d) — {keystate} signing key at {args.private_key}\n"
    )

    if not args.write:
        print(f"Add these to {args.env_file} (then run env-sync + connect):\n")
        print(f"{PUBLIC_KEY_ENV}={pub}\n")
        print(f"{TOKEN_ENV}={token}\n")
        print("  Next: ./scripts/railway/env-sync.sh   (pushes the public key — the token stays local)")
        print("        python scripts/connect.py --production")
        return 0

    if not args.env_file.exists():
        print(f"  ✗ {args.env_file} not found — create it first (cp .env .env.production).", file=sys.stderr)
        return 1

    backup = _backup(args.env_file)
    text = args.env_file.read_text()
    text = upsert_env_var(text, PUBLIC_KEY_ENV, pub)
    text = upsert_env_var(text, TOKEN_ENV, token)
    args.env_file.write_text(text)

    print(f"  ✓ wrote {PUBLIC_KEY_ENV} (public key) and {TOKEN_ENV} (bearer token) to {args.env_file}")
    print(f"    backup: {backup}\n")
    print("  Next: ./scripts/railway/env-sync.sh   (pushes the public key so the deploy trusts it)")
    print("        python scripts/connect.py --production   (threads the token into your MCP clients)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
