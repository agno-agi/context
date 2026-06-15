"""
Schedules
=========

@context's background schedules — the cron registration that decides which jobs
fire and when. This is a cross-cutting concern: the scheduler can drive agents or
workflows, so it lives here rather than inside `workflows/` (a catalog of runnable
things). The `Workflow` objects it points at are defined in `workflows/`.

`register_schedules()` is idempotent (safe on every boot) and called from the
AgentOS lifespan in `app/main.py`.
"""

from os import getenv

from agno.scheduler import ScheduleManager
from agno.utils.log import log_info, log_warning

from db import get_postgres_db


def register_schedules() -> None:
    """Register @context's background schedules (idempotent — safe on every boot).

    The scheduler poller (`scheduler=True`) fires each due job against an HTTP
    endpoint; AgentOS authenticates those triggers with the internal service
    token, so the runs arrive as the `__scheduler__` identity that `is_owner`
    honors — i.e. on the owner surface. A failure here must not take startup
    down, so it degrades to a warning.

    - queue-reminders: hourly, the schedule hits the `queue-reminders` workflow
      (`/workflows/queue-reminders/runs`), whose one step calls `_queue_reminders`
      and sweeps `crm.reminders` for anything now due into the inbound queue
      (see `workflows/reminders.py`). It's a workflow, not an agent run, so the
      sweep fires deterministically — no model deciding whether to call a tool.

    - daily-digest / weekly-digest: registered **only when Slack is configured**
      (delivery is a Slack DM, so there's no point arming them otherwise). Each
      hits its digest workflow, which runs a read-only playbook as the owner and
      DMs the result (see `workflows/digest.py`). Cron is tunable via
      `DAILY_DIGEST_CRON` / `WEEKLY_DIGEST_CRON` (UTC); defaults are a weekday-
      morning rundown and a Sunday-evening week-plan.
    """
    try:
        manager = ScheduleManager(get_postgres_db())
        manager.create(
            name="queue-reminders",
            cron="0 * * * *",  # hourly, on the hour (UTC)
            endpoint="/workflows/queue-reminders/runs",
            payload={"message": "Hourly sweep: queue reminders that have come due."},
            description="Hourly: push due reminders into the owner's inbound queue.",
            if_exists="update",
        )
        log_info("@context: registered schedule 'queue-reminders'")

        # "If the Slack thing is active, the schedule comes on." The digests
        # deliver over Slack DM, so they only make sense with a bot token set.
        if getenv("SLACK_BOT_TOKEN"):
            manager.create(
                name="daily-digest",
                cron=getenv("DAILY_DIGEST_CRON", "0 13 * * *"),  # 13:00 UTC daily
                endpoint="/workflows/daily-digest/runs",
                payload={"message": "Scheduled daily rundown digest."},
                description="Daily: DM the owner their rundown on Slack.",
                if_exists="update",
            )
            manager.create(
                name="weekly-digest",
                cron=getenv("WEEKLY_DIGEST_CRON", "0 22 * * 0"),  # Sun 22:00 UTC
                endpoint="/workflows/weekly-digest/runs",
                payload={"message": "Scheduled weekly plan digest."},
                description="Weekly: DM the owner their week-plan on Slack.",
                if_exists="update",
            )
            log_info("@context: registered schedules 'daily-digest', 'weekly-digest' (Slack active)")
    except Exception as exc:
        log_warning(f"@context: could not register schedules: {exc}")
