"""
Context Provider Registry
=========================

Wiring for the context providers available to @context. The structured database
(`crm`), the knowledge base (`knowledge`), the workspace, and web are always on;
Slack, Gmail, and Calendar are added when their credentials are set.

Each provider exposes at most two tools to the main agent — `query_<id>` and
`update_<id>` — so the tool surface stays linear at 2N as sources grow.

Provider factories live in `agents/providers/`. This module handles:
- Registry lifecycle (create, get, setup, close)
- Tool hardening (time-boxing, prechecks)
- Introspection (status, logging)

`ACT_TOOLS` gates tools that act on the outside world as the owner. Only
`update_calendar` qualifies. Two writes are deliberately excluded: `update_gmail`
only ever drafts (never sends), and `update_slack` is ordinary messaging.
See `docs/SECURITY.md`.
"""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from os import getenv

from agno.context.provider import ContextProvider
from agno.run import RunContext
from agno.tools import tool
from agno.utils.log import log_info, log_warning

from agents.providers.core import (
    create_crm_provider,
    create_knowledge_provider,
    create_web_provider,
    create_workspace_provider,
)
from agents.providers.google import create_calendar_provider, create_gmail_provider, google_token_precheck
from agents.providers.hardening import time_boxed_query_tool
from agents.providers.slack import create_slack_provider
from app.settings import backbone_query_timeout, provider_query_timeout

# Tools that act on the outside world as the owner → approval-gated by gate_act_tools.
ACT_TOOLS: frozenset[str] = frozenset({"update_calendar"})


def gate_act_tools(tools: list) -> list:
    """Flag every act tool in `tools` to pause the run for the owner's approval.

    `approval_type="required"` makes the pause a persisted, blocking approval: agno
    writes a pending row at the pause and won't continue until it's resolved, so every
    outward action leaves an audit trail and unattended runs queue up instead of acting
    unseen. Set per run because providers build fresh tool objects on each get_tools().
    See `docs/SECURITY.md` (L6).
    """
    for t in tools:
        if getattr(t, "name", None) in ACT_TOOLS:
            t.requires_confirmation = True
            t.approval_type = "required"
    return tools


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

context_providers: list[ContextProvider] = []


def create_context_providers() -> list[ContextProvider]:
    """Build the registered context providers from env and cache them.

    Optional builders are wrapped in try/except so one bad config doesn't take
    the whole registry down.
    """
    configured: list[ContextProvider] = [
        create_web_provider(),
        create_workspace_provider(),
        create_crm_provider(),
        create_knowledge_provider(),
    ]
    for factory in (create_slack_provider, create_gmail_provider, create_calendar_provider):
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


def size_io_thread_pool() -> None:
    """Size asyncio's default thread pool for this registry's I/O-bound fan-out.

    Agno runs every sync provider call (Postgres, Slack, Google) on the loop's default
    thread pool. Its default is ~6 workers on a 2-vCPU box — too few for a rundown's
    fan-out, so fast sources queue behind slow ones. Tunable via ``THREAD_POOL_WORKERS``.
    Call once from the AgentOS lifespan, inside the running loop.
    """
    try:
        workers = int(getenv("THREAD_POOL_WORKERS", "") or 0) or 64
    except ValueError:
        workers = 64
    asyncio.get_running_loop().set_default_executor(
        ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ctx-io")
    )
    log_info(f"Default thread pool sized to {workers} workers (I/O-bound provider calls)")


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
# Tool hardening
# ---------------------------------------------------------------------------

# Backbone read sources — the brief's spine. They get a longer per-source budget
# than best-effort sources so they reliably land in the concurrent fan-out.
BACKBONE_SOURCES: frozenset[str] = frozenset({"crm"})


def owner_provider_tools() -> list:
    """Owner provider tools, hardened against slow/dead sources.

    Every read (``query_*``) is time-boxed, and Google reads also skip on a dead token.
    Backbone reads (the CRM) get a longer budget than best-effort ones so the brief's
    spine reliably lands. Writes (``update_*``) pass through untouched — single user
    actions, not part of the fan-out, and bounding one risks a half-finished write.
    """
    best_effort = provider_query_timeout()
    backbone = backbone_query_timeout()
    tools: list = []
    for ctx in get_context_providers():
        for t in ctx.get_tools():
            name = getattr(t, "name", "") or ""
            if not name.startswith("query_"):
                tools.append(t)
                continue
            timeout = backbone if ctx.id in BACKBONE_SOURCES else best_effort
            precheck = google_token_precheck(ctx.id) if ctx.id in ("gmail", "calendar") else None
            tools.append(time_boxed_query_tool(t, timeout, precheck))
    return tools


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

    Called per run from ``agents.policy.caller_information`` (the owner branch),
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
