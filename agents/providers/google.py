"""
Google Context Providers
========================

Gmail and Calendar provider factories with shared auth config.

When ``GOOGLE_TOKEN_ENCRYPTION_KEY`` is set, OAuth tokens are encrypted
and stored in PostgreSQL instead of file-based token paths. The shared
``AuthConfig`` consolidates scopes across Gmail + Calendar, so a single
OAuth consent covers both services.

Agno's Google toolkits handle all credential resolution automatically:
1. Check shared auth cache (already authenticated by another toolkit)
2. Load from DB (encrypted if key set)
3. Fallback to file (local dev)
4. Interactive OAuth (first-time setup)

The precheck functions below validate tokens BEFORE spinning up a sub-agent,
avoiding wasted work when auth is dead.
"""

import asyncio
import json
from os import getenv
from pathlib import Path
from typing import TYPE_CHECKING

from agno.utils.log import log_debug, log_warning

from agents.instructions import CALENDAR_READ, GMAIL_READ
from app.settings import default_model

if TYPE_CHECKING:
    from agno.context.provider import ContextProvider
    from agno.tools.google.auth import AuthConfig

# Repo root for default token paths
REPO_ROOT = Path(__file__).resolve().parents[2]

# Shared auth config — lazily initialized
_google_auth_config: "AuthConfig | None" = None


def google_configured() -> bool:
    """True when the Gmail/Calendar OAuth client is configured.

    Set ``GOOGLE_CLIENT_ID`` + ``GOOGLE_CLIENT_SECRET`` and mint the consent
    tokens once with ``scripts/google_mint_tokens.py`` — see ``docs/GOOGLE.md``.
    """
    return bool(getenv("GOOGLE_CLIENT_ID") and getenv("GOOGLE_CLIENT_SECRET"))


def get_google_auth() -> "AuthConfig | None":
    """Get shared Google AuthConfig with DB storage and encryption.

    Lazily initialized to avoid import overhead when Google isn't configured.
    Shared across all Google toolkits so OAuth scopes consolidate into one
    consent screen and credentials are cached across providers.

    Token storage priority:
    1. DB with encryption (production) — set GOOGLE_TOKEN_ENCRYPTION_KEY
    2. DB without encryption (not recommended) — set encrypt_tokens=False
    3. File fallback (local dev) — uses token_path from each provider
    """
    global _google_auth_config
    if _google_auth_config is not None:
        return _google_auth_config

    if not google_configured():
        return None

    try:
        from agno.tools.google.auth import AuthConfig

        from db import get_postgres_db

        db = get_postgres_db()
        encryption_key = getenv("GOOGLE_TOKEN_ENCRYPTION_KEY")

        # 5 min timeout for API calls — context's sub-agents can take time
        http_timeout = float(getenv("GOOGLE_API_TIMEOUT", "300"))

        _google_auth_config = AuthConfig(
            db=db,
            token_encryption_key=encryption_key,
            http_timeout=http_timeout,
        )

        # Pre-register all scopes BEFORE any toolkit is instantiated.
        # Toolkits are lazy-loaded (created on first query, not at provider init),
        # so if Gmail runs first, OAuth would only have Gmail scopes unless we
        # pre-register everything here.
        _google_auth_config.register_scopes([
            # Gmail
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.compose",
            # Calendar
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar",
        ])

        if encryption_key:
            log_debug("Google auth: DB storage + encryption enabled")
        else:
            log_debug("Google auth: DB storage enabled (no encryption key)")

        return _google_auth_config
    except ImportError:
        log_warning("Google auth: AuthConfig not available (google-api-python-client not installed)")
        return None


def gmail_token_path() -> str:
    """Where the Gmail OAuth token cache lives (``GMAIL_TOKEN_FILE`` or repo root).

    The single source of truth for this path: the provider reads it, the mint
    script (``scripts/google_mint_tokens.py``) writes it, and the entrypoint's
    base64 materialization restores it on deploys that don't keep files.
    """
    return getenv("GMAIL_TOKEN_FILE") or str(REPO_ROOT / "gmail_token.json")


def calendar_token_path() -> str:
    """Where the Calendar OAuth token cache lives (``CALENDAR_TOKEN_FILE`` or repo root)."""
    return getenv("CALENDAR_TOKEN_FILE") or str(REPO_ROOT / "calendar_token.json")


def create_gmail_provider() -> "ContextProvider | None":
    """Gmail — read + draft. ``update_gmail`` only ever creates a draft; it
    never sends, so it is *not* an act tool and needs no approval gate (a draft
    is private and reversible — you review and send from Gmail).

    Imported lazily: the google client libraries are optional, and the
    registry's try/except treats a missing import as "provider not available"
    instead of taking the app down.
    """
    if not google_configured():
        return None
    from agno.context.gmail import GmailContextProvider
    from agno.tools.google.gmail import GmailTools

    class _DraftOnlyGmail(GmailContextProvider):
        """Lock the Gmail write surface to drafts — it can never send.

        Agno's Gmail write sub-agent already drafts by default; we override the
        toolkit hook to drop every outward-send tool, making drafts-only a hard
        guarantee rather than a prompt convention.

        To let @context send for you instead: use ``GmailContextProvider``
        directly (drop this subclass) and add ``update_gmail`` to ``ACT_TOOLS``
        so every send pauses for your approval, like the calendar. The
        implications + steps are in ``docs/GOOGLE.md``.
        """

        def _build_write_toolkit(self) -> GmailTools:
            toolkit = super()._build_write_toolkit()
            for name in ("send_email", "send_email_reply", "send_draft"):
                toolkit.functions.pop(name, None)
                toolkit.async_functions.pop(name, None)
            return toolkit

    auth = get_google_auth()
    return _DraftOnlyGmail(
        auth=auth,
        model=default_model(),
        write=True,
        token_path=gmail_token_path(),
        read_instructions=GMAIL_READ,
    )


def create_calendar_provider() -> "ContextProvider | None":
    """Google Calendar — read + write. ``update_calendar`` is approval-gated.

    Uses shared ``AuthConfig`` with Gmail for consolidated OAuth scopes
    and encrypted DB token storage.
    """
    if not google_configured():
        return None
    from agno.context.calendar import GoogleCalendarContextProvider

    auth = get_google_auth()
    return GoogleCalendarContextProvider(
        auth=auth,
        model=default_model(),
        write=True,
        token_path=calendar_token_path(),
        read_instructions=CALENDAR_READ,
    )


# ---------------------------------------------------------------------------
# Token validation helpers (for precheck in tool hardening)
# ---------------------------------------------------------------------------


def google_token_usable_from_file(token_path: str) -> bool:
    """True iff a file-based Google OAuth token is valid or can be refreshed."""
    p = Path(token_path)
    if not p.exists():
        return False
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(str(p))
    except Exception:
        return False
    if creds.valid:
        return True
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            return False
        try:
            p.write_text(creds.to_json())
        except Exception:
            pass
        return bool(creds.valid)
    return False


def google_token_usable_from_db() -> bool:
    """True iff a DB-stored Google OAuth token is valid or can be refreshed."""
    auth = get_google_auth()
    if auth is None:
        return False

    # Check in-memory cache first — populated by actual queries via _resolve_creds()
    if auth.creds and auth.creds.valid:
        return True

    if auth.db is None:
        return False
    try:
        from agno.utils.encryption import decrypt_dict, is_encrypted
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        row = auth.db.get_auth_token("google", None, "google")
        if not row:
            return False
        token_data = row.get("token_data")
        if not token_data:
            return False
        if is_encrypted(token_data):
            token_data = decrypt_dict(token_data, key=auth.token_encryption_key)
        creds = Credentials.from_authorized_user_info(token_data, row.get("granted_scopes") or [])
    except Exception:
        return False
    if creds.valid:
        # Cache valid creds so subsequent prechecks return immediately
        auth.creds = creds
        return True
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            if creds.valid:
                # Cache refreshed creds — matches what _resolve_creds() does
                auth.creds = creds
                return True
        except Exception:
            return False
    return False


def google_token_precheck(provider_id: str):
    """Build a precheck for time-boxed query tools that skips Google reads on a dead token.

    Returns an async callable that yields ``None`` when the token is usable, or a one-line
    "skipped" chunk to short-circuit before the sub-agent spins up. The token check runs
    off the loop and is itself bounded, so a hung refresh can't stall the run either.

    Checks DB-stored tokens first (when AuthConfig is configured), falling back to file.
    """
    token_path = gmail_token_path() if provider_id == "gmail" else calendar_token_path()

    async def _precheck():
        try:
            # 1. Check DB-stored token first (preferred when AuthConfig is configured)
            auth = get_google_auth()
            if auth is not None and auth.db is not None:
                usable = await asyncio.wait_for(asyncio.to_thread(google_token_usable_from_db), timeout=8)
                if usable:
                    return None
            # 2. Fall back to file-based token
            usable = await asyncio.wait_for(asyncio.to_thread(google_token_usable_from_file, token_path), timeout=8)
        except Exception:
            usable = False
        if usable:
            return None
        return json.dumps({"error": f"{provider_id} is unavailable right now (auth needs refresh) — skipped"})

    return _precheck
