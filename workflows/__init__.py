"""
Workflows
=========

@context's runnable Agno `Workflow` objects — the deterministic background jobs the
scheduler fires (see `app/schedules.py`). Each module owns one concern end to end:
its step executor(s) and the `Workflow` object that wraps them.

- `reminders` — the hourly reminder sweep (`queue_reminders_workflow`). Also home to
  the `queue_reminders` owner *tool* the context agent calls in chat, since both
  share one core (`_queue_reminders`).
- `digest` — the daily rundown / weekly week-plan digests (`daily_digest_workflow`,
  `weekly_digest_workflow`), delivered to the owner's Slack DM.
- `notify` — `dm_owner`, the shared self-notification path both of the above use.

`WORKFLOWS` is the registration list handed to `AgentOS(workflows=...)` in
`app/main.py`. Scheduling (which of these fire, and when) is a separate, cross-
cutting concern that lives in `app/schedules.py`, not here.
"""

from agno.workflow import RemoteWorkflow, Workflow, WorkflowFactory

from workflows.digest import daily_digest_workflow, weekly_digest_workflow
from workflows.reminders import queue_reminders_workflow

# The workflows registered with AgentOS. Order is cosmetic. The element type
# matches AgentOS's `workflows=` parameter so the shared list types cleanly — a
# bare list literal here would infer as the invariant `list[Workflow]` and be
# rejected at the call site (it was only accepted inline via bidirectional inference).
WORKFLOWS: list[Workflow | RemoteWorkflow | WorkflowFactory] = [
    queue_reminders_workflow,
    daily_digest_workflow,
    weekly_digest_workflow,
]

__all__ = [
    "WORKFLOWS",
    "queue_reminders_workflow",
    "daily_digest_workflow",
    "weekly_digest_workflow",
]
