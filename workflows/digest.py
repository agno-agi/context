"""
Scheduled Digests
=================

The owner's read-only playbooks (the daily **rundown**, the weekly **week-plan**)
delivered on a schedule to their Slack DM — so the brief reaches the owner the
moment it's due instead of waiting to be asked.

Each digest is a one-step workflow (the objects at the bottom of this module),
registered with AgentOS and run by its schedule (see `app/schedules.py`):
"""

from agno.run import RunContext
from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.workflow import Workflow

from agents.inbox import queue_owner_note
from app.identity import CANONICAL_OWNER_ID, is_owner
from db import get_postgres_db
from workflows.notify import dm_owner

# The playbook prompts. "Return the brief as text, post nothing" keeps the model
# from reaching for update_slack itself — dm_owner does the delivery.
_DAILY_PROMPT = (
    "Run the daily-rundown playbook for me now. Return the brief as text only — "
    "do not post it to Slack or anywhere else; just give me the rundown."
)
_WEEKLY_PROMPT = (
    "Run the week-plan playbook for me now. Return the plan as text only — do not "
    "post it to Slack or anywhere else; just give me the week ahead."
)


async def _run_playbook(prompt: str) -> str:
    """Invoke the context agent on `prompt` as the owner, read-only, return its text.

    Async because the context agent's provider tools are async (e.g. `query_web`,
    the time-boxed query_* wrappers): agno's sync `agent.run()` refuses async tools,
    so the playbook must go through `arun`. The scheduler triggers the digest
    workflow via `workflow.arun()` (see app/schedules.py and the OS workflows
    router), which runs async step executors — so this awaits cleanly.
    """
    # Imported lazily: agents.context imports across the package, so deferring the
    # import keeps this module cheap to load and avoids any import-order surprise.
    from agents.context import context
    from agents.policy import READ_ONLY_FLAG

    # READ_ONLY_FLAG strips every write tool for this run (see context_tools), so the
    # playbook can read but can't post the brief itself or touch the calendar.
    result = await context.arun(input=prompt, user_id=CANONICAL_OWNER_ID, metadata={READ_ONLY_FLAG: True})
    content = getattr(result, "content", None)
    return str(content).strip() if content else ""


async def _run_digest(prompt: str, label: str, run_context: RunContext) -> StepOutput:
    """Shared core: gate, run the playbook as owner, deliver the result, report."""
    if not is_owner(run_context):
        return StepOutput(content=f"The {label} digest is only available to the owner.")
    if CANONICAL_OWNER_ID is None:
        return StepOutput(content=f"No owner configured, so there's no one to send the {label} digest to.")

    brief = await _run_playbook(prompt)
    if not brief:
        return StepOutput(content=f"The {label} digest produced no content; nothing sent.")

    # Try the Slack DM first; if it doesn't go out (Slack down or unconfigured),
    # fall back to the inbound queue so the brief surfaces on the next rundown
    # rather than being silently lost. The queue is the durable channel; the DM
    # is the nudge on top of it.
    if dm_owner(brief):
        status = "DM'd to the owner"
    elif queue_owner_note(f"{label.capitalize()} digest", brief, source="digest"):
        status = "filed to your inbound queue (Slack DM unavailable)"
    else:
        status = "generated (no delivery channel available, not sent)"
    return StepOutput(content=f"{label.capitalize()} digest {status}.")


async def daily_digest_step(step_input: StepInput, run_context: RunContext) -> StepOutput:
    """The daily rundown, delivered to the owner's Slack DM. Run by the schedule."""
    return await _run_digest(_DAILY_PROMPT, "daily", run_context)


async def weekly_digest_step(step_input: StepInput, run_context: RunContext) -> StepOutput:
    """The weekly plan, delivered to the owner's Slack DM. Run by the schedule."""
    return await _run_digest(_WEEKLY_PROMPT, "weekly", run_context)


# The scheduled digests: the owner's read-only playbooks (daily rundown, weekly
# week-plan) run on a schedule and DM'd to Slack. Each is a one-step workflow that
# runs the playbook as the owner and self-DMs the result (see the steps above).
# Registered only when Slack is configured (see register_schedules in app/schedules.py).
daily_digest_workflow = Workflow(
    id="daily-digest",
    name="Daily Digest",
    description="Run the daily rundown and DM it to the owner on Slack.",
    db=get_postgres_db(),
    steps=[Step(name="daily-digest", executor=daily_digest_step)],  # type: ignore[arg-type]
)

weekly_digest_workflow = Workflow(
    id="weekly-digest",
    name="Weekly Digest",
    description="Run the week-plan and DM it to the owner on Slack.",
    db=get_postgres_db(),
    steps=[Step(name="weekly-digest", executor=weekly_digest_step)],  # type: ignore[arg-type]
)
