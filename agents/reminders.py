"""
Queue Reminders
===============

Push due reminders into the owner's inbound queue.

@context saves reminders in `context.reminders`, each with a due date — but
nothing watches that clock. This is the watcher: it finds reminders that are now
due and surfaces them.

There are two ways to surface a due reminder:
1. Drop it into the owner's inbound queue, where the rundown picks it up.
2. Ping the owner in Slack.

We always do (1): the rundown reads the queue, so a due reminder lands in the
same place as everything else that needs the owner — one surface to run down each
day, not several. The hourly sweep *also* does (2) when Slack is configured — a
best-effort nudge so a timed reminder reaches the owner the moment it comes due
instead of waiting for the next rundown. The queue stays the source of truth; the
DM is only a ping, so if Slack fails the sweep still succeeds. (The manual tool
skips the DM — when you ask for your due reminders in chat you're already looking
at them.)

Three ways in, one core:
- `queue_reminders` — an owner tool, for "push my due reminders now" in chat.
  Queues only; no DM.
- the `queue-reminders` workflow step — what the hourly schedule runs, so the
  sweep fires on its own without the model deciding to call a tool. This is the
  path that also sends the Slack nudge.
- `_queue_reminders` — the shared core: claim each due reminder, file it into the
  queue, mark it surfaced so it shows once, and (only when asked) DM the owner.

Owner-only on every path. The tool and the workflow step both check `is_owner`
(the scheduler's verified identity counts as the owner), so a guest never
reaches the owner's reminders.
"""

from datetime import datetime, timezone
from os import getenv

from agno.exceptions import StopAgentRun
from agno.run import RunContext
from agno.tools import tool
from agno.utils.log import log_warning
from agno.workflow.step import StepInput, StepOutput
from sqlalchemy import text

from app.identity import CANONICAL_OWNER_ID, is_owner, owner_email
from db import SCHEMA, get_sql_engine

_REMINDERS = f"{SCHEMA}.reminders"
_UPDATES = f"{SCHEMA}.updates"


def _format_due(due_at: datetime) -> str:
    """A due timestamp as `2026-06-13` (date-only) or `2026-06-13 14:00 UTC` (timed)."""
    d = due_at.astimezone(timezone.utc)
    if (d.hour, d.minute) == (0, 0):
        return d.strftime("%Y-%m-%d")
    return d.strftime("%Y-%m-%d %H:%M UTC")


def _slack_dm_target() -> tuple[str, str] | None:
    """The (bot token, owner email) an owner DM needs — or `None` when unavailable.

    Availability is gated on the actual env config: `SLACK_BOT_TOKEN` (the bot
    token that sends the message) and an owner email (an `OWNER_ID` entry that
    looks like one, resolving the IM via `users.lookupByEmail`). Both must be set
    or there is no DM. `SLACK_SIGNING_SECRET` only verifies *inbound* Slack
    requests, so it plays no part in an outbound DM — sending needs just the token,
    with the `users:read.email`, `im:write`, `chat:write` scopes (in the manifest,
    see `docs/SLACK.md`).
    """
    token = getenv("SLACK_BOT_TOKEN")
    email = owner_email()
    if token and email:
        return token, email
    return None


def _ping_owner_on_slack(due: list) -> None:
    """Best-effort: DM the owner a short summary of the reminders just queued.

    The inbound queue is the source of truth — this is only a proactive nudge, so
    every failure is logged and swallowed rather than failing the sweep. No-op
    unless Slack DMs are available (see `_slack_dm_target`).
    """
    target = _slack_dm_target()
    if target is None:
        return
    token, email = target

    try:
        from slack_sdk import WebClient

        client = WebClient(token=token)
        user_id = client.users_lookupByEmail(email=email)["user"]["id"]
        channel = client.conversations_open(users=[user_id])["channel"]["id"]

        lines = "\n".join(f"• {r.title} — due {_format_due(r.due_at)}" for r in due)
        header = f"🔔 *{len(due)} reminder{'' if len(due) == 1 else 's'} due*"
        client.chat_postMessage(channel=channel, text=f"{header}\n{lines}")
    except Exception as exc:
        log_warning(f"queue-reminders: could not DM the owner on Slack: {exc}")


def _queue_reminders(notify_slack: bool = False) -> str:
    """Claim every due reminder, file each into the owner's inbound queue, return a summary.

    Owner-scoped — writes under `CANONICAL_OWNER_ID`. Callers gate on `is_owner` first.
    With `notify_slack=True` (the scheduled sweep), also best-effort DMs the owner;
    the manual tool leaves it False so an in-chat call doesn't echo a DM.
    """
    if CANONICAL_OWNER_ID is None:
        return "No owner is configured, so there are no reminders to queue."

    engine = get_sql_engine()
    with engine.begin() as conn:
        # Claim and stamp in one statement. The row lock on UPDATE serializes
        # concurrent sweeps, so each due reminder is claimed exactly once: a
        # second sweep blocks, re-reads notified_at as set, and the row drops
        # out of its RETURNING set. No select-then-update race, no double-filing.
        claimed = conn.execute(
            text(
                f"""
                UPDATE {_REMINDERS}
                SET notified_at = NOW()
                WHERE user_id = :owner
                  AND status = 'pending'
                  AND due_at IS NOT NULL
                  AND due_at <= NOW()
                  AND notified_at IS NULL
                RETURNING id, title, notes, due_at
                """
            ),
            {"owner": CANONICAL_OWNER_ID},
        ).all()

        if not claimed:
            return "No reminders have come due."

        # RETURNING has no defined order; surface oldest-due first.
        due = sorted(claimed, key=lambda r: r.due_at)
        for r in due:
            body = (r.notes or "").strip()
            body = f"{body}\n\nReminder due {_format_due(r.due_at)}.".strip()
            # work_status='blocked' lands it under "waiting on you" on the
            # rundown; source='reminder' / from_person='@context' mark it as the
            # owner's own follow-up surfacing, not a teammate's update.
            conn.execute(
                text(
                    f"""
                    INSERT INTO {_UPDATES}
                        (user_id, title, body, from_person, source, work_status, ack_status)
                    VALUES
                        (:owner, :title, :body, '@context', 'reminder', 'blocked', 'new')
                    """
                ),
                {"owner": CANONICAL_OWNER_ID, "title": r.title, "body": body},
            )

    # Queue is committed and is the source of truth. On the scheduled sweep,
    # layer a best-effort Slack nudge on top (no-op when Slack isn't configured);
    # the manual tool skips it — the caller is already looking at the result.
    if notify_slack:
        _ping_owner_on_slack(due)

    titles = ", ".join(r.title for r in due)
    return f"Queued {len(due)} due reminder(s) to your inbox: {titles}."


@tool
def queue_reminders(run_context: RunContext) -> str:
    """Push reminders that have come due into the owner's inbound queue.

    Finds every pending reminder whose due date has passed and hasn't been
    surfaced yet, files each into the owner's queue (where the rundown shows it,
    grouped as needing the owner), and marks it surfaced so it never queues
    twice. Owner-only. The hourly `queue-reminders` schedule runs this for you,
    so you rarely call it by hand — and never to answer a conversational "what's
    due", which is a plain `query_crm` read, not a sweep that writes to the
    queue. Returns a one-line summary of what came due.
    """
    if not is_owner(run_context):
        raise StopAgentRun("Queueing reminders is only available to the owner.")
    return _queue_reminders()


def queue_reminders_step(step_input: StepInput, run_context: RunContext) -> StepOutput:
    """The reminder sweep as a workflow step — what the hourly schedule runs.

    Deterministic: the step always runs the sweep, so nothing depends on a model
    choosing to call a tool. It re-checks `is_owner` because the
    `/workflows/queue-reminders/runs` endpoint is reachable by any authenticated
    caller — the schedule arrives as the verified `__scheduler__` identity (owner),
    but the gate keeps the owner's reminders off a guest's run.

    Runs with `notify_slack=True`, so this is the path that sends the best-effort
    Slack nudge (the manual `queue_reminders` tool doesn't).
    """
    if not is_owner(run_context):
        return StepOutput(content="Queueing reminders is only available to the owner.")
    return StepOutput(content=_queue_reminders(notify_slack=True))
