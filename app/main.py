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
from app.settings import is_prd, runtime_env
from db import create_tables, get_postgres_db

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
    await setup_context_providers()
    try:
        yield
    finally:
        await close_context_providers()
        log_info("@context: shutdown")


# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    tracing=True,
    scheduler=True,
    lifespan=lifespan,
    db=get_postgres_db(),
    agents=[context],
    interfaces=interfaces,
    config=str(Path(__file__).parent / "config.yaml"),  # Quick prompts for the agents.
    # Enable JWT based authorization in production.
    authorization=is_prd(),
    # User isolation scopes the OS REST endpoints (sessions / memory / runs) to the
    # verified JWT user. Only takes effect when authorization is on (prod).
    authorization_config=AuthorizationConfig(user_isolation=True),
    scheduler_base_url=scheduler_base_url,  # The base URL of the scheduler.
    internal_service_token=getenv("INTERNAL_SERVICE_TOKEN") or None,  # The internal service token used by the AgentOS.
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="app.main:app", reload=runtime_env() == "dev")
