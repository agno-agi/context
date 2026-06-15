"""
Context's Provider Registry
===========================

Wiring for the context providers available to Context. The structured database (`crm`), the knowledge base (`knowledge`), the workspace, and web are always on; Slack, Gmail, and Calendar are added to the agent when credentials are set.

Each provider exposes at most two tools to the main agent — `query_<id>` and `update_<id>` — so the tool surface stays linear at 2N as sources grow.

`ACT_TOOLS` names the tools that act on the outside world *as the owner* — just `update_calendar` (changing the real calendar). `agents.context` flags it `requires_confirmation` so the run pauses for the owner's explicit approval before it executes. Gmail is deliberately *not* here: `update_gmail` only ever drafts (it never sends), and a draft is private and reversible, so it needs no gate (see `_create_gmail_provider`). Filing into your own store is frictionless; acting outward is gated (see `docs/SECURITY.md`).

Slack messaging (`update_slack`) is deliberately **not** in `ACT_TOOLS`: posting a message — to a teammate, a channel, or another person's `@context` agent — is ordinary, low-stakes communication, so it runs ungated like a chat reply. The approval gate is reserved for the sensitive outward action (mutating the calendar). `update_slack` stays owner-only the same way every read/write tool does — it's added only in the owner branch of `context_tools`, so a guest never holds it.
"""

import asyncio
import json
from os import getenv
from pathlib import Path

from agno.context.database import DatabaseContextProvider
from agno.context.provider import ContextProvider
from agno.context.slack import SlackContextProvider
from agno.context.web.parallel import ParallelBackend
from agno.context.web.parallel_mcp import ParallelMCPBackend
from agno.context.web.provider import WebContextProvider
from agno.context.wiki import FileSystemBackend, GitBackend, WikiContextProvider
from agno.context.workspace import WorkspaceContextProvider
from agno.run import RunContext
from agno.tools import tool
from agno.tools.workspace import DEFAULT_EXCLUDE_PATTERNS
from agno.utils.log import log_info, log_warning

from agents.instructions import CRM_READ, CRM_WRITE, KNOWLEDGE_READ, KNOWLEDGE_WRITE
from app.settings import default_model
from db import SCHEMA, get_readonly_engine, get_sql_engine

# Workspace root for the always-on filesystem context. Hardcoded to the context repo so @context can answer questions about its own codebase out of the box.
REPO_ROOT = Path(__file__).resolve().parents[1]

# Knowledge-base root - where @context stores files. Filesystem-backed by default; set KNOWLEDGE_REPO_URL + KNOWLEDGE_GITHUB_TOKEN to switch to GitBackend at startup for durable storage with an audit trail.
KNOWLEDGE_PATH = REPO_ROOT / "knowledge"

# Tools that take action in the outside world as the owner. `agents.context` flags these `requires_confirmation` per run, so the model can never execute one without the owner's explicit approval.
# `update_gmail` is intentionally absent: it's draft-only (see `_create_gmail_provider`), and a draft is harmless, so it isn't gated. `update_slack` is also absent — sending a Slack message is ordinary messaging (ungated), not a sensitive act. Only the calendar gates.
ACT_TOOLS: frozenset[str] = frozenset({"update_calendar"})


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

context_providers: list[ContextProvider] = []


def create_context_providers() -> list[ContextProvider]:
    """Build the registered context providers from env and cache them.

    Optional builders are wrapped in try/except so one bad config doesn't take the whole registry down.
    """
    configured: list[ContextProvider] = [
        _create_web_provider(),
        _create_workspace_provider(),
        _create_crm_provider(),
        _create_knowledge_provider(),
    ]
    for factory in (_create_slack_provider, _create_gmail_provider, _create_calendar_provider):
        try:
            provider = factory()
        except Exception as exc:
            log_warning(f"{factory.__name__} failed: {exc}")
            continue
        if provider is not None:
            configured.append(provider)

    context_providers[:] = configured
    return list(context_providers)


def get_context_providers() -> list[ContextProvider]:
    """Return the cached provider list, building on first access."""
    if not context_providers:
        create_context_providers()
    return list(context_providers)


async def _gather_provider_calls(providers: list[ContextProvider], method: str) -> None:
    """Run `method` on every provider concurrently, logging failures."""
    results = await asyncio.gather(*(getattr(p, method)() for p in providers), return_exceptions=True)
    for provider, outcome in zip(providers, results, strict=True):
        if isinstance(outcome, BaseException):
            log_warning(f"context {provider.id!r} {method} raised {type(outcome).__name__}: {outcome}")


async def setup_context_providers() -> list[ContextProvider]:
    """Build the registry (if needed) and run async setup on each provider.

    The provider status block is logged *after* ``asetup`` so it reflects the
    post-setup state (e.g. a GitBackend knowledge base shows as cloned, not
    ``clone path does not exist (run setup)`` from a pre-clone snapshot).
    """
    providers = get_context_providers()
    await _gather_provider_calls(providers, "asetup")
    _log_context_providers(providers)
    return providers


async def close_context_providers() -> None:
    """Release resources held by every cached provider (MCP sessions, etc.)."""
    await _gather_provider_calls(list(context_providers), "aclose")


# ---------------------------------------------------------------------------
# Context Providers
# ---------------------------------------------------------------------------


def _create_web_provider() -> WebContextProvider:
    model = default_model()
    if getenv("PARALLEL_API_KEY"):
        return WebContextProvider(backend=ParallelBackend(), model=model)
    return WebContextProvider(backend=ParallelMCPBackend(), model=model)


def _create_workspace_provider() -> WorkspaceContextProvider:
    # agno's defaults already exclude .env*, .git, caches, etc. Also keep Google
    # credential files out: in local dev compose mounts the repo at /app, so
    # without this the owner's own agent could read the minted OAuth token (or a
    # stray key file) back through query_workspace. (The image is clean —
    # .dockerignore excludes them — this covers the mounted-dev case.)
    return WorkspaceContextProvider(
        root=REPO_ROOT,
        model=default_model(),
        exclude_patterns=[*DEFAULT_EXCLUDE_PATTERNS, "*_token.json", "google-service-account.json"],
    )


def _create_crm_provider() -> DatabaseContextProvider:
    """The CRM — the structured database, read + write over the `crm` schema.

    The tuned instructions know the managed table shape (projects/meetings/reminders/notes/contacts), rendered from the schema spec.
    """
    return DatabaseContextProvider(
        id="crm",
        name="CRM",
        sql_engine=get_sql_engine(),
        readonly_engine=get_readonly_engine(),
        schema=SCHEMA,
        read_instructions=CRM_READ,
        write_instructions=CRM_WRITE,
        model=default_model(),
    )


def _create_knowledge_provider() -> WikiContextProvider:
    """The knowledge base — read + write knowledge, organized folder-per-spec.

    Filesystem-backed by default. Set `KNOWLEDGE_REPO_URL` AND `KNOWLEDGE_GITHUB_TOKEN` — ideally pointing at your specs repo — to switch to `GitBackend` for durable storage with an audit trail. Optional knobs: `KNOWLEDGE_BRANCH` (default `main`), `KNOWLEDGE_LOCAL_PATH`.
    """
    repo_url = getenv("KNOWLEDGE_REPO_URL", "").strip()
    github_token = getenv("KNOWLEDGE_GITHUB_TOKEN", "").strip()

    backend: FileSystemBackend | GitBackend
    if repo_url and github_token:
        backend = GitBackend(
            repo_url=repo_url,
            github_token=github_token,
            branch=getenv("KNOWLEDGE_BRANCH", "main"),
            local_path=getenv("KNOWLEDGE_LOCAL_PATH") or None,
        )
        log_info(f"Knowledge base: GitBackend ({repo_url})")
    else:
        if repo_url or github_token:
            log_warning(
                "Knowledge base: KNOWLEDGE_REPO_URL and KNOWLEDGE_GITHUB_TOKEN must both be set "
                "to enable GitBackend; falling back to FileSystemBackend."
            )
        KNOWLEDGE_PATH.mkdir(parents=True, exist_ok=True)
        backend = FileSystemBackend(path=KNOWLEDGE_PATH)

    return WikiContextProvider(
        id="knowledge",
        name="Knowledge Base",
        backend=backend,
        read_instructions=KNOWLEDGE_READ,
        write_instructions=KNOWLEDGE_WRITE,
        model=default_model(),
    )


def _create_slack_provider() -> SlackContextProvider | None:
    """Slack — read + write. `query_slack` reads channels/DMs; `update_slack` posts."""
    if not getenv("SLACK_BOT_TOKEN"):
        return None
    return SlackContextProvider(model=default_model(), read=True, write=True)


def _google_configured() -> bool:
    """True when the Gmail/Calendar OAuth client is configured.

    Set ``GOOGLE_CLIENT_ID`` + ``GOOGLE_CLIENT_SECRET`` and mint the consent
    tokens once with ``scripts/google_mint_tokens.py`` — see ``docs/GOOGLE.md``.
    """
    return bool(getenv("GOOGLE_CLIENT_ID") and getenv("GOOGLE_CLIENT_SECRET"))


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


def _create_gmail_provider() -> ContextProvider | None:
    """Gmail — read + draft. ``update_gmail`` only ever creates a draft; it
    never sends, so it is *not* an act tool and needs no approval gate (a draft
    is private and reversible — you review and send from Gmail).

    Imported lazily: the google client libraries are optional, and the
    registry's try/except treats a missing import as "provider not available"
    instead of taking the app down.
    """
    if not _google_configured():
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
            # Strip the send tools; keep create_draft_email / update_draft.
            for name in ("send_email", "send_email_reply", "send_draft"):
                toolkit.functions.pop(name, None)
                toolkit.async_functions.pop(name, None)
            return toolkit

    return _DraftOnlyGmail(
        model=default_model(),
        write=True,
        token_path=gmail_token_path(),
    )


def _create_calendar_provider() -> ContextProvider | None:
    """Google Calendar — read + write. ``update_calendar`` is approval-gated."""
    if not _google_configured():
        return None
    from agno.context.calendar import GoogleCalendarContextProvider

    return GoogleCalendarContextProvider(
        model=default_model(),
        write=True,
        token_path=calendar_token_path(),
    )


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------


def _log_context_providers(ctxs: list[ContextProvider]) -> None:
    """Log the resolved provider set with each provider's status detail."""
    if not ctxs:
        log_info("Context Providers: (none)")
        return
    width = max(len(c.id) for c in ctxs)
    lines = ["Context Providers:"]
    for c in ctxs:
        try:
            detail = c.status().detail
        except Exception as exc:
            detail = f"<status failed: {type(exc).__name__}>"
        lines.append(f"  {c.id:<{width}}  {detail}")
    log_info("\n".join(lines))


def context_providers_summary() -> str:
    """Markdown summary of registered providers, for prompt interpolation.

    Called per run from ``agents.context.caller_information`` (the owner branch),
    so the prompt never holds a stale snapshot of the registry.
    """
    providers = get_context_providers()
    if not providers:
        return "(no context providers registered)"
    return "\n".join(f"- `{p.id}`: {p.name}" for p in providers)


async def _astatus_row(ctx: ContextProvider) -> dict:
    try:
        s = await ctx.astatus()
        return {"id": ctx.id, "name": ctx.name, "ok": s.ok, "detail": s.detail}
    except Exception as exc:
        return {"id": ctx.id, "name": ctx.name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"}


@tool
async def list_contexts(run_context: RunContext | None = None) -> str:
    """List registered contexts with current status.

    Returns:
        JSON list of ``{id, name, ok, detail}``.
    """
    rows = await asyncio.gather(*(_astatus_row(ctx) for ctx in get_context_providers()))
    return json.dumps(list(rows))
