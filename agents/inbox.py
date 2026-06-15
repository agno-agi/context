"""
The Inbound Queue
===========================

Let your teammates (and their agents) leave you non-urgent updates.

Three tools for managing your inbound queue:
- `submit_update` — the only tool a guest user can use. Append-only write to the owner's queue. `from_person` is taken from the verified identity so a caller can't spoof who an update is from. No readback — you can drop a note in the owner's inbox, you can't read it.
- `rundown` — owner-only. Everything awaiting the owner: every update they haven't acknowledged, grouped blocked → done → in progress. Shows them and advances `new → briefed`, stamping `briefed_at`.
- `acknowledge` — owner-only. Moves updates to `acknowledged` (stamping `acknowledged_at`) so they drop off the rundown. Only the owner moves the ack axis — and that falls out of the toolset for free (a guest never holds these tools).

The owner-only tools also check `is_owner` and raise `StopAgentRun` — redundant behind the toolset gate + the tool_hook in `agents.policy`, but a cheap defense none the less.
"""

from collections.abc import Sequence
from typing import Any

from agno.exceptions import StopAgentRun
from agno.run import RunContext
from agno.tools import tool
from sqlalchemy import text

from app.identity import CANONICAL_OWNER_ID, is_owner
from db import SCHEMA, get_sql_engine

_UPDATES = f"{SCHEMA}.updates"

WORK_STATUSES = ("done", "in_progress", "blocked")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def require_owner(run_context: RunContext | None, action: str) -> None:
    """Raise unless this run is the owner. The toolset already withholds the
    owner-only tools from guests; this is a cheap defense-in-depth check per call."""
    if not is_owner(run_context):
        raise StopAgentRun(f"{action} is only available to the owner.")


def _insert_update(values: dict[str, object]) -> None:
    """Insert one row into the inbound queue, columns built from `values`' keys.

    Building the column list from the dict lets an omitted optional (e.g. empty
    tags) fall back to its column DEFAULT instead of binding an untyped empty array.
    """
    columns = ", ".join(values)
    params = ", ".join(f":{name}" for name in values)
    stmt = text(f"INSERT INTO {_UPDATES} ({columns}) VALUES ({params})")
    with get_sql_engine().begin() as conn:
        conn.execute(stmt, values)


def _derive_source(run_context: RunContext | None) -> str:
    """Best-effort channel label. The Slack interface stamps the author's
    display name into metadata; HTTP runs don't."""
    metadata = getattr(run_context, "metadata", None) or {}
    return "slack" if metadata.get("user_name") else "api"


def _coerce_ids(update_ids: object) -> list[int]:
    """Accept a list, a single value, ints, or numeric strings from the model."""
    if update_ids is None:
        return []
    candidates = update_ids if isinstance(update_ids, (list, tuple)) else [update_ids]
    out: list[int] = []
    for value in candidates:
        try:
            out.append(int(str(value).strip()))
        except (TypeError, ValueError):
            continue
    return out


# Rundown groups in presentation order: blocked items need the owner, done
# work awaits acknowledgement, in-progress items are FYIs.
_RUNDOWN_GROUPS = (
    ("blocked", "Blocked — waiting on you"),
    ("done", "Done — awaiting your acknowledgement"),
    ("in_progress", "In progress — FYI"),
)


def _format_update(r: Any) -> str:
    when = r.created_at.strftime("%Y-%m-%d") if r.created_at else ""
    who = r.from_person or "unknown"
    head = f"- [{r.id}] {r.title} — from {who}"
    if when:
        head += f" ({when})"
    if r.body:
        head += f": {r.body}"
    return head


def _format_rundown(rows: Sequence[Any]) -> str:
    lines = [f"{len(rows)} item(s) awaiting you:"]
    grouped: dict[str, list[Any]] = {status: [] for status, _ in _RUNDOWN_GROUPS}
    extras: list[Any] = []  # rows with an off-vocabulary work_status (legacy data)
    for r in rows:
        grouped.get(r.work_status, extras).append(r)
    for status, heading in _RUNDOWN_GROUPS:
        if grouped[status]:
            lines.append(f"\n{heading}:")
            lines.extend(_format_update(r) for r in grouped[status])
    if extras:
        lines.append("\nOther:")
        lines.extend(_format_update(r) for r in extras)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool
def submit_update(
    run_context: RunContext,
    title: str,
    body: str = "",
    work_status: str = "done",
    tags: list[str] | None = None,
) -> str:
    """Save an update in the owner's inbound queue.

    Use this to pass the owner a message from someone else — "tell them I fixed
    the auth bug", "the report is ready", "I'm blocked on the API key". The
    update lands in their queue marked new; they'll see it on their next
    rundown.

    Args:
        title: A short one-line summary of the update.
        body: Any detail worth keeping (optional).
        work_status: State of the work being reported — "done" (default),
            "in_progress", or "blocked".
        tags: Optional tags to group related updates.
    """
    if CANONICAL_OWNER_ID is None:
        return "No owner is configured, so there's nowhere to file this update."

    # The column has no CHECK constraint; an off-vocabulary value would create
    # a row no rundown ever matches.
    if work_status not in WORK_STATUSES:
        work_status = "done"

    from_person = getattr(run_context, "user_id", None) or "unknown"
    values: dict[str, object] = {
        "title": title,
        "body": body,
        "from_person": from_person,
        "source": _derive_source(run_context),
        "work_status": work_status,
        "ack_status": "new",
        "user_id": CANONICAL_OWNER_ID,
    }
    if tags:
        values["tags"] = tags
    _insert_update(values)

    # No id in the reply: a guest holds no tool that accepts one, and a
    # sequence number leaks queue volume.
    return "Filed your update for the owner."


@tool
def rundown(run_context: RunContext) -> str:
    """Give the owner a rundown of everything awaiting them.

    Returns every update the owner hasn't acknowledged — blocked items first
    (they need the owner), then done work awaiting acknowledgement, then
    in-progress FYIs — and marks the items shown as briefed. Owner-only.
    """
    require_owner(run_context, "The rundown")

    engine = get_sql_engine()
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT id, title, body, from_person, source, work_status, ack_status, created_at
                FROM {_UPDATES}
                WHERE user_id = :owner
                  AND ack_status <> 'acknowledged'
                ORDER BY created_at DESC
                """
            ),
            {"owner": CANONICAL_OWNER_ID},
        ).all()

        new_ids = [r.id for r in rows if r.ack_status == "new"]
        if new_ids:
            conn.execute(
                text(
                    f"UPDATE {_UPDATES} SET ack_status = 'briefed', briefed_at = NOW() "
                    f"WHERE user_id = :owner AND id = ANY(:ids) AND ack_status = 'new'"
                ),
                {"owner": CANONICAL_OWNER_ID, "ids": new_ids},
            )

    if not rows:
        return "Nothing awaiting you — the queue is clear."
    return _format_rundown(rows)


@tool
def acknowledge(run_context: RunContext, update_ids: list[int]) -> str:
    """Acknowledge updates by id so they drop off the rundown.

    Use once the owner has dealt with an item. Owner-only — only the owner moves
    the ack axis.

    Args:
        update_ids: The ids of the updates to acknowledge (from the rundown).
    """
    require_owner(run_context, "Acknowledging updates")

    ids = _coerce_ids(update_ids)
    if not ids:
        return "No update ids given to acknowledge."

    engine = get_sql_engine()
    with engine.begin() as conn:
        result = conn.execute(
            text(
                f"UPDATE {_UPDATES} SET ack_status = 'acknowledged', acknowledged_at = NOW() "
                f"WHERE user_id = :owner AND id = ANY(:ids) AND ack_status <> 'acknowledged'"
            ),
            {"owner": CANONICAL_OWNER_ID, "ids": ids},
        )
        count = result.rowcount

    return f"Acknowledged {count} update(s)."


def queue_owner_note(title: str, body: str = "", *, source: str = "system", work_status: str = "done") -> bool:
    """File a note straight into the owner's inbound queue — no caller, no model.

    The system-side counterpart to `submit_update`: a background job (e.g. a digest
    whose Slack DM didn't go out) lands content where the next rundown will surface
    it, so nothing is silently lost. Returns whether it was filed (False when no
    owner is configured). Owner-internal, so `from_person` is `@context`, not a guest.
    """
    if CANONICAL_OWNER_ID is None:
        return False
    if work_status not in WORK_STATUSES:
        work_status = "done"

    _insert_update(
        {
            "title": title,
            "body": body,
            "from_person": "@context",
            "source": source,
            "work_status": work_status,
            "ack_status": "new",
            "user_id": CANONICAL_OWNER_ID,
        }
    )
    return True


# ---------------------------------------------------------------------------
# The guest surface
# ---------------------------------------------------------------------------

# The exact toolset a guest is handed — the guest branch of
# agents.policy.context_tools returns this list.
GUEST_TOOLS = (submit_update,)

# The allowlist the tool_hook enforces for guest callers: the guest
# toolset (derived, so the two can't drift) plus the per-caller learning
# tools — the agent's LearningMachine adds `update_user_memory` and
# `update_profile` for every caller, each keyed in code to the caller's own
# verified id, so they cross no boundary (see docs/SECURITY.md).
CAPTURE_ONLY_TOOLS: frozenset[str] = frozenset(t.name for t in GUEST_TOOLS) | {
    "update_user_memory",
    "update_profile",
}
