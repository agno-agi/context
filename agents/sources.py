"""
Context's Provider Registry
===========================

Wiring for the context providers available to Context. The structured database (`crm`), the knowledge base (`knowledge`), the workspace, and web are always on; Slack, Gmail, and Calendar are added when their credentials are set.

Each provider exposes at most two tools to the main agent — `query_<id>` and `update_<id>` — so the tool surface stays linear at 2N as sources grow.

`ACT_TOOLS` is the canonical list of tools that act on the outside world *as the owner* and so are approval-gated (the run pauses for the owner's explicit OK before they execute). Only `update_calendar` qualifies. Two writes are deliberately excluded: `update_gmail` only ever drafts (never sends — private and reversible), and `update_slack` is ordinary messaging. Filing into your own store is frictionless; only the sensitive outward action is gated. See `docs/SECURITY.md`.
"""

import asyncio
import contextlib
import inspect
import json
from concurrent.futures import ThreadPoolExecutor
from os import getenv
from pathlib import Path

from agno.context.database import DatabaseContextProvider
from agno.context.mode import ContextMode
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

from agents.instructions import (
    CALENDAR_READ,
    CRM_READ,
    CRM_WRITE,
    GMAIL_READ,
    KNOWLEDGE_READ,
    KNOWLEDGE_WRITE,
    SLACK_READ,
)
from app.settings import backbone_query_timeout, default_model, provider_query_timeout
from db import SCHEMA, get_readonly_engine, get_sql_engine

# Workspace root for the always-on filesystem context. Hardcoded to the context repo so @context can answer questions about its own codebase out of the box.
REPO_ROOT = Path(__file__).resolve().parents[1]

# Knowledge-base root - where @context stores files. Filesystem-backed by default; set KNOWLEDGE_REPO_URL + KNOWLEDGE_GITHUB_TOKEN to switch to GitBackend at startup for durable storage with an audit trail.
KNOWLEDGE_PATH = REPO_ROOT / "knowledge"

# Tools that act on the outside world as the owner → approval-gated by gate_act_tools.
# Only the calendar; gmail is draft-only, slack is ordinary messaging (see module docstring).
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
# Context Providers
# ---------------------------------------------------------------------------


def _create_web_provider() -> WebContextProvider:
    model = default_model()
    if getenv("PARALLEL_API_KEY"):
        return WebContextProvider(backend=ParallelBackend(), model=model)
    return WebContextProvider(backend=ParallelMCPBackend(), model=model)


def _create_workspace_provider() -> WorkspaceContextProvider:
    # mode=tools exposes the read tools (list_files / search_content / read_file)
    # straight to the main context agent instead of behind a nested sub-agent, so a
    # codebase question is answered in the agent's own turn (one pass, bounded by its
    # tool_call_limit) rather than paying a full sub-agent round-trip per file read.
    # The usage guidance lives in OWNER_GUIDE (the agent never sees provider
    # instructions); no per-source time-box is needed (see BACKBONE_SOURCES).
    #
    # agno's defaults already exclude .env*, .git, caches, etc. Also keep Google
    # credential files out: in local dev compose mounts the repo at /app, so
    # without this the owner's own agent could read the minted OAuth token (or a
    # stray key file) back through read_file. (The image is clean — .dockerignore
    # excludes them — this covers the mounted-dev case.)
    return WorkspaceContextProvider(
        root=REPO_ROOT,
        model=default_model(),
        mode=ContextMode.tools,
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
    """Slack — read + write. `query_slack` reads channels/DMs; `update_slack` posts.

    Note: `search.messages` needs a *user* token (`xoxp-`, scope `search:read`); a bot
    token returns `not_allowed_token_type`. Agno hard-codes `enable_search_messages=True`
    with no user-token slot, so search errors out and the read falls back to
    channel/thread history. Pass a user token here to restore it.
    """
    if not getenv("SLACK_BOT_TOKEN"):
        return None
    return SlackContextProvider(model=default_model(), read=True, write=True, read_instructions=SLACK_READ)


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
        read_instructions=GMAIL_READ,
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
        read_instructions=CALENDAR_READ,
    )


# ---------------------------------------------------------------------------
# Owner tool hardening
# ---------------------------------------------------------------------------
#
# A rundown fans `use_context` out to several provider sub-agents back to back, and
# agno puts no timeout around each one. We time-box every read here so a slow source
# degrades to a one-line "skipped" and the rest of the brief still lands.
#
# Google reads get an extra guard: on a dead OAuth token we skip before spinning the
# sub-agent, which also avoids agno's interactive browser-auth fallback (wrong on a
# headless server). The token check uses only the public google.oauth2 API.


def _timeout_error(label: str, timeout: float) -> str:
    return json.dumps({"error": f"{label} timed out after {int(timeout)}s — skipped"})


async def _drain_into(queue: asyncio.Queue, sentinel: object, make_call) -> None:
    """Producer task: run a provider tool and push each chunk onto ``queue``.

    A provider ``query_*`` entrypoint returns a coroutine; awaiting it yields either an
    async generator of streamed events or a finished value. Running this in its own
    task means a timeout cancels only the task — never the consumer or the calling
    agent's tool flow — so a slow source can't corrupt the outer stream.
    """
    try:
        res = make_call()
        if inspect.iscoroutine(res):
            res = await res
        if inspect.isasyncgen(res):
            async for chunk in res:
                await queue.put(chunk)
        else:
            await queue.put(res)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await queue.put(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
    finally:
        await queue.put(sentinel)


async def _bounded_tool_call(make_call, timeout: float, label: str):
    """Yield a provider tool's chunks under a total wall-clock ``timeout``.

    The tool runs as an isolated producer task feeding a queue. On timeout we emit one
    error chunk (the providers' own ``{"error": ...}`` shape) and cancel the producer.
    The remaining budget also caps inter-chunk stalls, not just the total.
    """
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()
    task = asyncio.create_task(_drain_into(queue, sentinel, make_call))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                yield _timeout_error(label, timeout)
                return
            try:
                item = await asyncio.wait_for(queue.get(), timeout=remaining)
            except (asyncio.TimeoutError, TimeoutError):
                yield _timeout_error(label, timeout)
                return
            if item is sentinel:
                return
            yield item
    finally:
        if not task.done():
            task.cancel()
        with contextlib.suppress(BaseException):
            await task


def _time_boxed_query_tool(original, timeout: float, precheck=None):
    """Wrap a provider ``query_*`` tool so its sub-agent run is time-boxed.

    Same name + description; the explicit ``question`` / ``run_context`` signature keeps
    agno's schema inference and run_context injection unchanged. The optional ``precheck``
    (an async callable) runs first: if it returns a chunk, we yield that and skip the
    sub-agent — the Google guard uses it to short-circuit on a dead token.
    """
    raw = original.entrypoint
    label = original.name

    @tool(name=original.name, description=original.description)
    async def _query(question: str, run_context: RunContext | None = None):
        if precheck is not None:
            skip = await precheck()
            if skip is not None:
                yield skip
                return
        async for chunk in _bounded_tool_call(lambda: raw(question=question, run_context=run_context), timeout, label):
            yield chunk

    return _query


def _google_token_usable(token_path: str) -> bool:
    """True iff a Google OAuth token is valid or can be refreshed without a browser.

    Refreshes and persists an expired-but-refreshable token in place, so the provider's
    sub-agent then loads a valid one. Never triggers interactive auth — a dead token
    just returns False.
    """
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


def _google_token_precheck(provider_id: str):
    """Build a precheck for `_time_boxed_query_tool` that skips Google reads on a dead token.

    Returns an async callable that yields ``None`` when the token is usable, or a one-line
    "skipped" chunk to short-circuit before the sub-agent spins up. The token check runs
    off the loop and is itself bounded, so a hung refresh can't stall the run either.
    """
    token_path = gmail_token_path() if provider_id == "gmail" else calendar_token_path()

    async def _precheck():
        try:
            usable = await asyncio.wait_for(asyncio.to_thread(_google_token_usable, token_path), timeout=8)
        except Exception:
            usable = False
        if usable:
            return None
        return json.dumps({"error": f"{provider_id} is unavailable right now (auth needs refresh) — skipped"})

    return _precheck


# Backbone read sources — the brief's spine. They get a longer per-source budget
# than best-effort sources (see backbone_query_timeout) so they reliably land in the
# concurrent fan-out, where best-effort sources still skip fast. Just the CRM today;
# the inbound queue (`rundown`) isn't a query_* sub-agent, so it isn't time-boxed.
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
            precheck = _google_token_precheck(ctx.id) if ctx.id in ("gmail", "calendar") else None
            tools.append(_time_boxed_query_tool(t, timeout, precheck))
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
