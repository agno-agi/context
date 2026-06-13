"""
Context's Provider Registry
===========================

Wiring for the context providers available to Context. The structured store
(``crm``), the knowledge base (``knowledge``), the workspace, and web are
always on; Slack, Gmail, and Calendar are added to the agent when their env
vars are set.

Each provider exposes at most two tools to the main agent — ``query_<id>``
and ``update_<id>`` — so the tool surface stays linear at 2N as sources grow.

``ACT_TOOLS`` names the tools that act on the outside world *as the owner*
(sending email, changing the calendar). ``agents.context`` flags them
``requires_confirmation`` so the run pauses for the owner's explicit approval
before they execute — filing into your own store is frictionless; acting
outward is gated (see ``docs/SECURITY.md``).
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
from agno.utils.log import log_info, log_warning

from agents.instructions import CRM_READ, CRM_WRITE, KNOWLEDGE_READ, KNOWLEDGE_WRITE
from app.settings import default_model
from db import SCHEMA, get_readonly_engine, get_sql_engine

# Workspace root for the always-on filesystem context. Hardcoded to the
# context repo so Context can answer questions about its own codebase out of
# the box. Forks/private deployments can re-point this to their own repo.
REPO_ROOT = Path(__file__).resolve().parents[1]

# Knowledge-base root — the prose Context files into. Filesystem-backed by
# default; set WIKI_REPO_URL + WIKI_GITHUB_TOKEN to switch to GitBackend at
# startup (durable storage with an audit trail).
WIKI_KNOWLEDGE_PATH = REPO_ROOT / "wiki" / "knowledge"

# Tools that act on the outside world as the owner. agents.context flags these
# requires_confirmation per run, so the model can never execute one without the
# owner approving the paused run first.
ACT_TOOLS: frozenset[str] = frozenset({"update_gmail", "update_calendar"})


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

context_providers: list[ContextProvider] = []


def create_context_providers() -> list[ContextProvider]:
    """Build the registered context providers from env and cache them.

    Optional builders are wrapped in try/except so one bad config doesn't take
    the whole registry down. (Agent-side tool registration drops duplicate
    tool names with a warning, so a copy-pasted provider id can't produce two
    ``query_<id>`` tools.)
    """
    configured: list[ContextProvider] = [
        _create_web_provider(),
        _create_workspace_provider(),
        _create_crm_provider(),
        _create_knowledge_wiki(),
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
    _log_context_providers(configured)
    return list(context_providers)


def get_context_providers() -> list[ContextProvider]:
    """Return the cached provider list, building on first access."""
    if not context_providers:
        create_context_providers()
    return list(context_providers)


async def _gather_provider_calls(providers: list[ContextProvider], method: str) -> None:
    """Run ``method`` on every provider concurrently, logging failures."""
    results = await asyncio.gather(*(getattr(p, method)() for p in providers), return_exceptions=True)
    for provider, outcome in zip(providers, results, strict=True):
        if isinstance(outcome, BaseException):
            log_warning(f"context {provider.id!r} {method} raised {type(outcome).__name__}: {outcome}")


async def setup_context_providers() -> list[ContextProvider]:
    """Build the registry (if needed) and run async setup on each provider."""
    providers = get_context_providers()
    await _gather_provider_calls(providers, "asetup")
    return providers


async def close_context_providers() -> None:
    """Release resources held by every cached provider (MCP sessions, etc.)."""
    await _gather_provider_calls(list(context_providers), "aclose")


# ---------------------------------------------------------------------------
# Provider factories
# ---------------------------------------------------------------------------


def _create_web_provider() -> WebContextProvider:
    model = default_model()
    if getenv("PARALLEL_API_KEY"):
        return WebContextProvider(backend=ParallelBackend(), model=model)
    return WebContextProvider(backend=ParallelMCPBackend(), model=model)


def _create_workspace_provider() -> WorkspaceContextProvider:
    return WorkspaceContextProvider(root=REPO_ROOT, model=default_model())


def _create_crm_provider() -> DatabaseContextProvider:
    """The CRM — the structured store, read + write over the ``context`` schema.

    Two engines so the read path never sees the write engine. Tuned
    instructions know the managed table shape (projects/meetings/reminders/
    notes/contacts), rendered from the schema spec.
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


def _create_knowledge_wiki() -> WikiContextProvider:
    """The knowledge base — read + write prose, organized folder-per-spec.

    Tuned instructions teach the sub-agents the specs convention (root
    README index, ``_template/`` folder layout) so a spec is read as one
    coherent unit and writes land in the right sub-file. Filesystem-backed
    by default. Set ``WIKI_REPO_URL`` AND ``WIKI_GITHUB_TOKEN`` — ideally
    pointing at your specs repo — to switch to ``GitBackend`` for durable
    storage with an audit trail. Optional knobs: ``WIKI_BRANCH`` (default
    ``main``), ``WIKI_LOCAL_PATH``.
    """
    repo_url = getenv("WIKI_REPO_URL", "").strip()
    github_token = getenv("WIKI_GITHUB_TOKEN", "").strip()

    backend: FileSystemBackend | GitBackend
    if repo_url and github_token:
        backend = GitBackend(
            repo_url=repo_url,
            github_token=github_token,
            branch=getenv("WIKI_BRANCH", "main"),
            local_path=getenv("WIKI_LOCAL_PATH") or None,
        )
        log_info(f"Knowledge base: GitBackend ({repo_url})")
    else:
        if repo_url or github_token:
            log_warning(
                "Knowledge base: WIKI_REPO_URL and WIKI_GITHUB_TOKEN must both be set "
                "to enable GitBackend; falling back to FileSystemBackend."
            )
        WIKI_KNOWLEDGE_PATH.mkdir(parents=True, exist_ok=True)
        backend = FileSystemBackend(path=WIKI_KNOWLEDGE_PATH)

    return WikiContextProvider(
        id="knowledge",
        name="Knowledge Base",
        backend=backend,
        read_instructions=KNOWLEDGE_READ,
        write_instructions=KNOWLEDGE_WRITE,
        model=default_model(),
    )


def _create_slack_provider() -> SlackContextProvider | None:
    if not getenv("SLACK_BOT_TOKEN"):
        return None
    return SlackContextProvider(model=default_model())


def _google_configured() -> bool:
    """True when either Google auth path is configured.

    Service account (headless, recommended for deploys):
    ``GOOGLE_SERVICE_ACCOUNT_FILE`` (+ ``GOOGLE_DELEGATED_USER`` for Gmail).
    OAuth (personal accounts): ``GOOGLE_CLIENT_ID`` + ``GOOGLE_CLIENT_SECRET``,
    with the consent token minted locally first — see ``docs/GOOGLE.md``.
    """
    if getenv("GOOGLE_SERVICE_ACCOUNT_FILE"):
        return True
    return bool(getenv("GOOGLE_CLIENT_ID") and getenv("GOOGLE_CLIENT_SECRET"))


def _create_gmail_provider() -> ContextProvider | None:
    """Gmail — read + write. ``update_gmail`` is an act tool (approval-gated).

    Imported lazily: the google client libraries are optional, and the
    registry's try/except treats a missing import as "provider not available"
    instead of taking the app down.
    """
    if not _google_configured():
        return None
    from agno.context.gmail import GmailContextProvider

    return GmailContextProvider(
        model=default_model(),
        write=True,
        token_path=str(REPO_ROOT / "gmail_token.json"),
    )


def _create_calendar_provider() -> ContextProvider | None:
    """Google Calendar — read + write. ``update_calendar`` is approval-gated."""
    if not _google_configured():
        return None
    from agno.context.calendar import GoogleCalendarContextProvider

    return GoogleCalendarContextProvider(
        model=default_model(),
        write=True,
        token_path=str(REPO_ROOT / "calendar_token.json"),
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
