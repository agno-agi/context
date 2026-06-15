"""
AgentOS Entrypoint
==================
"""

from contextlib import asynccontextmanager
from os import getenv
from pathlib import Path

from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.utils.log import log_info, log_warning

from agents.context import context
from agents.sources import close_context_providers, setup_context_providers
from app.identity import owner_configured
from app.mcp import MCP_PATH, build_context_mcp_app
from app.schedules import register_schedules
from app.settings import is_prd, runtime_env
from db import create_tables, get_postgres_db
from workflows import WORKFLOWS

# One database handle for AgentOS persistence. (The scheduler and each workflow
# open their own handle to the same Postgres — see app/schedules.py and workflows/.)
db = get_postgres_db()


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
scheduler_base_url = getenv("AGENTOS_URL", "http://127.0.0.1:8000")

# Missing OWNER_ID check: without an OWNER_ID, @context is capture-only.
if is_prd() and not owner_configured():
    log_warning(
        "OWNER_ID is not set — no caller will be treated as the owner. "
        "Context is capture-only for everyone until OWNER_ID is set."
    )

# ---------------------------------------------------------------------------
# Interfaces
# - @context becomes available on Slack when both env vars are set
# ---------------------------------------------------------------------------
SLACK_BOT_TOKEN = getenv("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = getenv("SLACK_SIGNING_SECRET", "")

interfaces: list = []
if SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET:
    from agno.os.interfaces.slack import Slack

    interfaces.append(
        Slack(
            agent=context,
            streaming=True,
            token=SLACK_BOT_TOKEN,
            signing_secret=SLACK_SIGNING_SECRET,
            resolve_user_identity=True,
            # Starter chips in the assistant pane (the owner's primary surface).
            # Rendered on `assistant_thread_started`, so the manifest must
            # subscribe that event and enable `assistant_view`. Mirrors the
            # quick prompts in app/config.yaml.
            suggested_prompts=[
                {"title": "Daily rundown", "message": "Give me a rundown of what's waiting on me"},
                {"title": "My week", "message": "What does my week look like?"},
                {
                    "title": "Leave an update",
                    "message": "Met Kyle from Agno, wants a partnership — follow up next week",
                },
            ],
        )
    )


# ---------------------------------------------------------------------------
# Lifespan — app-level startup / teardown.
#
# Startup: create database tables and initialize context providers.
# Shutdown: release provider resources.
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app):  # type: ignore[no-untyped-def]
    log_info("@context: startup")
    create_tables()
    register_schedules()
    await setup_context_providers()
    try:
        yield
    finally:
        await close_context_providers()
        log_info("@context: shutdown")


# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
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
    # Enable JWT based authorization in production.
    authorization=is_prd(),
    authorization_config=authorization_config,
    scheduler_base_url=scheduler_base_url,  # The base URL of the scheduler.
    internal_service_token=getenv("INTERNAL_SERVICE_TOKEN") or None,  # The internal service token used by the AgentOS.
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Owner-only MCP server
#
# @context comes with a one-tool MCP server (`ask_context`) which allows the
# owner to read, file, and act from MCP clients like Claude and ChatGPT.
# ---------------------------------------------------------------------------
mcp_app = build_context_mcp_app(authorization=is_prd(), authorization_config=authorization_config)

# The FastMCP StreamableHTTP session manager must be started, or requests to /mcp will 500.
_base_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _lifespan_with_mcp(app):  # type: ignore[no-untyped-def]
    async with _base_lifespan(app):
        async with mcp_app.router.lifespan_context(mcp_app):
            yield


app.router.lifespan_context = _lifespan_with_mcp

# Mounted at root so the public path is exactly MCP_PATH (/mcp).
app.mount("/", mcp_app)
log_info(f"@context: owner-only MCP server mounted at {MCP_PATH}")


if __name__ == "__main__":
    agent_os.serve(app="app.main:app", reload=runtime_env() == "dev")
