"""
AgentOS Entrypoint
==================
"""

from contextlib import asynccontextmanager
from os import getenv
from pathlib import Path

from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.scheduler import ScheduleManager
from agno.utils.log import log_info, log_warning
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

from agents.context import context
from agents.reminders import queue_reminders_step
from agents.sources import close_context_providers, setup_context_providers
from app.identity import owner_configured
from app.settings import is_prd, runtime_env
from db import create_tables, get_postgres_db

# One database handle, shared by AgentOS persistence and the scheduler.
db = get_postgres_db()

# The reminder sweep as a one-step workflow. The hourly `queue-reminders`
# schedule triggers it at /workflows/queue-reminders/runs, so the sweep fires
# deterministically — no model deciding whether to call a tool. The step
# re-checks is_owner (see agents/reminders.py).
queue_reminders_workflow = Workflow(
    id="queue-reminders",
    name="Queue Reminders",
    description="Push due reminders into the owner's inbound queue.",
    db=db,
    # Agno injects run_context into the step by name at runtime, but Step.executor's
    # type only declares the single-arg (StepInput) form — hence the narrow ignore.
    steps=[Step(name="queue-reminders", executor=queue_reminders_step)],  # type: ignore[arg-type]
)


def register_schedules() -> None:
    """Register @context's background schedules (idempotent — safe on every boot).

    The scheduler poller (`scheduler=True`) fires each due job against an HTTP
    endpoint; AgentOS authenticates those triggers with the internal service
    token, so the runs arrive as the `__scheduler__` identity that `is_owner`
    honors — i.e. on the owner surface. A failure here must not take startup
    down, so it degrades to a warning.

    - queue-reminders: hourly, the schedule hits the `queue-reminders` workflow
      (`/workflows/queue-reminders/runs`), whose one step calls `_queue_reminders`
      and sweeps `context.reminders` for anything now due into the inbound queue
      (see `agents/reminders.py`). It's a workflow, not an agent run, so the
      sweep fires deterministically — no model deciding whether to call a tool.
    """
    try:
        ScheduleManager(db).create(
            name="queue-reminders",
            cron="0 * * * *",  # hourly, on the hour (UTC)
            endpoint="/workflows/queue-reminders/runs",
            payload={"message": "Hourly sweep: queue reminders that have come due."},
            description="Hourly: push due reminders into the owner's inbound queue.",
            if_exists="update",
        )
        log_info("@context: registered schedule 'queue-reminders'")
    except Exception as exc:
        log_warning(f"@context: could not register schedules: {exc}")


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
agent_os = AgentOS(
    tracing=True,
    scheduler=True,
    lifespan=lifespan,
    db=db,
    agents=[context],
    workflows=[queue_reminders_workflow],
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
