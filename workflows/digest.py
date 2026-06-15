"""
Scheduled Digests
=================

The owner's read-only playbooks (the daily **rundown**, the weekly **week-plan**)
delivered on a schedule to their Slack DM — so the brief reaches the owner the
moment it's due instead of waiting to be asked.

Each digest is a one-step workflow (the objects at the bottom of this module),
registered with AgentOS and run by its schedule (see `app/schedules.py`):
1. Run the playbook as the owner. The scheduled run arrives as `__scheduler__`,
   which `is_owner` honors, and we invoke the agent under the canonical owner id so
   the playbook gets the full owner surface and keys to the right data.
2. DM the result to the owner via `workflows.notify.dm_owner` — the same self-
   notification path the reminder sweep uses. Ungated and deterministic: messaging
   yourself is not an outward act, so no approval gate fires and unattended runs
   complete end to end.

The playbooks are read-only (they pull and format, they never send), so a
scheduled digest never trips an act tool. We tell the agent explicitly to return
the brief as text rather than post it anywhere — delivery is `dm_owner`'s job, not
the model's.
"""

from agno.run import RunContext
from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.workflow import Workflow

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


def _run_playbook(prompt: str) -> str:
    """Invoke the context agent on `prompt` as the owner and return its text."""
    # Imported lazily: agents.context imports across the package, so deferring the
    # import keeps this module cheap to load and avoids any import-order surprise.
    from agents.context import context

    result = context.run(input=prompt, user_id=CANONICAL_OWNER_ID)
    content = getattr(result, "content", None)
    return str(content).strip() if content else ""


def _run_digest(prompt: str, label: str, run_context: RunContext) -> StepOutput:
    """Shared core: gate, run the playbook as owner, DM the result, report."""
    if not is_owner(run_context):
        return StepOutput(content=f"The {label} digest is only available to the owner.")
    if CANONICAL_OWNER_ID is None:
        return StepOutput(content=f"No owner configured, so there's no one to send the {label} digest to.")

    brief = _run_playbook(prompt)
    if not brief:
        return StepOutput(content=f"The {label} digest produced no content; nothing sent.")

    sent = dm_owner(brief)
    status = "DM'd to the owner" if sent else "generated (Slack DM unavailable, not sent)"
    return StepOutput(content=f"{label.capitalize()} digest {status}.")


def daily_digest_step(step_input: StepInput, run_context: RunContext) -> StepOutput:
    """The daily rundown, delivered to the owner's Slack DM. Run by the schedule."""
    return _run_digest(_DAILY_PROMPT, "daily", run_context)


def weekly_digest_step(step_input: StepInput, run_context: RunContext) -> StepOutput:
    """The weekly plan, delivered to the owner's Slack DM. Run by the schedule."""
    return _run_digest(_WEEKLY_PROMPT, "weekly", run_context)


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
