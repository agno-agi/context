"""
AgentOS Entrypoint
==================
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from os import getenv
from pathlib import Path

from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.utils.log import log_info, log_warning

from agents.context import context
from agents.sources import close_context_providers, setup_context_providers
from app.identity import owner_configured
from app.mcp import context_mcp_config
from app.schedules import register_schedules
from app.settings import is_prd, owner_timezone, owner_timezone_configured, runtime_env
from db import create_tables, get_postgres_db
from workflows import WORKFLOWS

# One database session for AgentOS persistence. (The scheduler and workflows open their own sessions)
db = get_postgres_db()

# Scheduler base URL — where cron triggers reach AgentOS (set to the deploy domain in prod).
scheduler_base_url = getenv("AGENTOS_URL", "http://127.0.0.1:8000")


def _warn_on_missing_config() -> None:
    """Log startup warnings for unset config that silently changes behavior."""
    # Without an OWNER_ID, @context is capture-only for everyone.
    if is_prd() and not owner_configured():
        log_warning(
            "OWNER_ID is not set — no caller will be treated as the owner. "
            "Context is capture-only for everyone until OWNER_ID is set."
        )
    # Without OWNER_TIMEZONE, "today" and relative dates fall back to UTC.
    if owner_timezone_configured():
        log_info(f"OWNER_TIMEZONE={owner_timezone()}")
    else:
        log_warning(
            "OWNER_TIMEZONE is not set (or invalid) — 'today', due/overdue math, and relative "
            "dates use UTC. Set it to your IANA zone (e.g. America/Los_Angeles)."
        )


def _build_interfaces() -> list:
    """@context's external interfaces — Slack is added when its credentials are set."""
    token = getenv("SLACK_BOT_TOKEN", "")
    signing_secret = getenv("SLACK_SIGNING_SECRET", "")
    if not (token and signing_secret):
        return []

    from agno.os.interfaces.slack import Slack

    return [
        Slack(
            agent=context,
            streaming=True,
            token=token,
            signing_secret=signing_secret,
            resolve_user_identity=True,
            # Starter chips in the assistant pane. Rendered on `assistant_thread_started`,
            # so the manifest must subscribe that event and enable `assistant_view`.
            # Mirrors the quick prompts in app/config.yaml.
            suggested_prompts=[
                {"title": "Daily rundown", "message": "Give me a rundown of what's waiting on me"},
                {"title": "My week", "message": "What does my week look like?"},
                {
                    "title": "Leave an update",
                    "message": "Met Kyle from Agno, wants a partnership — follow up next week",
                },
            ],
        )
    ]


interfaces = _build_interfaces()


def _enlarge_default_executor() -> None:
    """Size asyncio's default thread pool for I/O-bound provider fan-out.

    Agno runs every sync tool call (Postgres, Slack, Google) on the loop's default
    thread pool. Its default is ~6 workers on a 2-vCPU box — too few for a rundown's
    fan-out, so the fast sources queue behind the slow ones. Tunable via
    ``THREAD_POOL_WORKERS``.
    """
    try:
        workers = int(getenv("THREAD_POOL_WORKERS", "") or 0) or 64
    except ValueError:
        workers = 64
    asyncio.get_running_loop().set_default_executor(
        ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ctx-io")
    )
    log_info(f"Default thread pool sized to {workers} workers (I/O-bound provider calls)")


@asynccontextmanager
async def lifespan(app):  # type: ignore[no-untyped-def]
    """App startup: warn on missing config, size the thread pool, create tables,
    register schedules, set up providers. Shutdown: release provider resources."""
    log_info("@context: startup")
    _warn_on_missing_config()
    _enlarge_default_executor()
    create_tables()
    register_schedules()
    await setup_context_providers()
    try:
        yield
    finally:
        await close_context_providers()
        log_info("@context: shutdown")


# User isolation scopes the OS REST endpoints (sessions / memory / runs) to the
# verified JWT user. Only takes effect when authorization is on (prod).
_self_verification_key = getenv("CONTEXT_SELF_VERIFICATION_KEY", "").strip()
authorization_config = AuthorizationConfig(
    user_isolation=True,
    verification_keys=[_self_verification_key] if _self_verification_key else None,
    algorithm="RS256",
)

agent_os = AgentOS(
    tracing=True,
    scheduler=True,
    lifespan=lifespan,
    db=db,
    agents=[context],
    workflows=WORKFLOWS,
    interfaces=interfaces,
    config=str(Path(__file__).parent / "config.yaml"),  # Quick prompts for the agents.
    authorization=is_prd(),  # JWT authorization in production.
    authorization_config=authorization_config,
    scheduler_base_url=scheduler_base_url,
    internal_service_token=getenv("INTERNAL_SERVICE_TOKEN") or None,
    # Owner-only single-tool MCP server at /mcp — see app/mcp.py.
    enable_mcp_server=True,
    mcp_config=context_mcp_config(),
)
app = agent_os.get_app()
log_info("@context: owner-only MCP server mounted at /mcp")


if __name__ == "__main__":
    agent_os.serve(app="app.main:app", reload=runtime_env() == "dev")
