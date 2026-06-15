"""
Context — Personal Context Agent
================================
"""

from pathlib import Path

from agno.agent import Agent
from agno.learn import LearningMachine, LearningMode, UserMemoryConfig, UserProfileConfig
from agno.run import RunContext
from agno.skills import LocalSkills, Skills
from agno.utils.log import log_warning

from agents.inbox import GUEST_TOOLS, acknowledge, rundown
from agents.instructions import CONTEXT_INSTRUCTIONS, GUEST_GUIDE, OWNER_GUIDE
from agents.policy import enforce_capture_only, normalize_identity
from agents.sources import ACT_TOOLS, context_providers_summary, list_contexts, owner_provider_tools
from app.identity import ANON_USER_ID, is_owner, owner_display_name
from app.settings import default_model, owner_timezone
from db import get_postgres_db
from workflows.reminders import queue_reminders

# Runtime skills i.e. reusable playbooks the owner can invoke (e.g. the week plan).
# Owner-gated like the provider tools: the access tools are added only in the
# owner branch of `context_tools`, and the browse snippet only renders in the
# owner branch of `caller_information`. So a guest's tool surface *and* system
# prompt carry zero skill references.
_SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"


def _load_skills() -> Skills | None:
    """Build the skills registry, degrading to `None` if it can't load.

    A malformed `SKILL.md` raises `SkillValidationError` at load; we don't
    want one bad skill to take the agent — and the whole app — down at import.
    """
    if not _SKILLS_DIR.exists():
        return None
    try:
        return Skills(loaders=[LocalSkills(str(_SKILLS_DIR))])
    except Exception as exc:
        log_warning(f"Skills failed to load from {_SKILLS_DIR}: {exc}")
        return None


_skills = _load_skills()


def caller_information(run_context: RunContext | None = None) -> str:
    """Build the caller's instructions based on their identity.

    Rendered per run by `context_instructions` (the owner gets the full guide,
    a guest the capture-only one).
    """
    user_id = getattr(run_context, "user_id", None) or ANON_USER_ID
    if is_owner(run_context):
        skills = _skills.get_system_prompt_snippet() if _skills is not None else ""
        return OWNER_GUIDE.format(
            owner_name=owner_display_name(),
            providers=context_providers_summary(),
            skills=skills,
        )
    return GUEST_GUIDE.format(
        owner_name=owner_display_name("(no owner configured)"),
        user_id=user_id,
    )


def context_instructions(run_context: RunContext | None = None) -> str:
    """Render Context's system prompt for this run."""

    user_id = getattr(run_context, "user_id", None) or ANON_USER_ID
    return CONTEXT_INSTRUCTIONS.format(
        owner_name=owner_display_name(),
        user_id=user_id,
        caller_information=caller_information(run_context),
    )


# A per-run signal (set in run metadata) that this is a read-only run: the
# scheduled digests use it so the playbook can read but can't write.
READ_ONLY_FLAG = "read_only"


def _is_read_only(run_context: RunContext | None) -> bool:
    """Whether this run was flagged read-only (the scheduled digests). Off by default."""
    metadata = getattr(run_context, "metadata", None) or {}
    return bool(metadata.get(READ_ONLY_FLAG))


def _is_write_tool(name: str) -> bool:
    """A tool that mutates state: every source write (`update_*`, which includes
    the calendar act tool) plus the owner-queue writes. Reads (`query_*`,
    `list_contexts`), the rundown brief, and the skills are not writes."""
    return name.startswith("update_") or name in {"acknowledge", "queue_reminders"}


def context_tools(run_context: RunContext | None = None) -> list:
    """Build Context's tool list based on the caller's identity.

    Wired as a callable on `Agent.tools` and resolved per run by setting `cache_callables=False`.

    The owner branch gets access to the full set of tools — provider tools, the inbound queue, and runtime skills.
    The guest branch gets access to the capture-only tool — submit_update.
    """
    if is_owner(run_context):
        # Time-boxed provider reads so one slow source can't stall the run; Google
        # reads also skip on a dead token. See `owner_provider_tools`.
        tools: list = list(owner_provider_tools())
        tools += [list_contexts, rundown, acknowledge, queue_reminders]
        if _skills is not None:
            tools += _skills.get_tools()
        # Strip write tools for read-only runs (the scheduled digests).
        if _is_read_only(run_context):
            tools = [t for t in tools if not _is_write_tool(getattr(t, "name", ""))]
        # The approval gate on acting as the owner: tools that reach the
        # outside world (send email, change the calendar) pause the run for
        # explicit confirmation before they execute. `approval_type="required"`
        # makes that gate a *persisted, blocking* approval — agno writes a row
        # to the approvals table at pause (status="pending") and refuses to
        # continue the run until it's resolved, so every outward action leaves a
        # durable audit trail (tool, args, who approved, when) and unattended
        # (scheduled) sends queue up for the owner instead of acting unseen.
        # Set per run — providers build fresh tool objects on every get_tools().
        for t in tools:
            if getattr(t, "name", None) in ACT_TOOLS:
                t.requires_confirmation = True
                t.approval_type = "required"
        return tools
    return list(GUEST_TOOLS)


context = Agent(
    id="context",
    name="Context",
    model=default_model(),
    db=get_postgres_db(),
    instructions=context_instructions,
    tools=context_tools,
    # Default user_id when a caller (eval runner, unauthenticated script) invokes Context without providing a user_id.
    # Production surfaces (UI, Slack) override this with a verified identity.
    user_id=ANON_USER_ID,
    # Resolve tools on every run based on the caller's verified identity.
    cache_callables=False,
    # Pre-hook refuses unidentified prod runs and collapses the owner's configured identities onto the canonical id.
    pre_hooks=[normalize_identity],
    # Tool-hook refuses any non-capture tool from a guest caller.
    tool_hooks=[enforce_capture_only],
    # @context can learn about the caller. Agentic mode adds `update_user_memory` + `update_profile` tools to the agent.
    # A guest's memories and profile never touch the owner's context.
    learning=LearningMachine(
        user_profile=UserProfileConfig(mode=LearningMode.AGENTIC),
        user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
    ),
    # Anchor "now" to the owner's local day, not the server's UTC. The rundown's
    # "today", overdue/due math, and relative-date resolution all key off this.
    # `OWNER_TIMEZONE` unset → "UTC" (prior behavior); the format carries the
    # weekday + zone label so the model can frame and render times with a zone.
    add_datetime_to_context=True,
    timezone_identifier=owner_timezone(),
    datetime_format="%A %Y-%m-%d %H:%M %Z",
    add_history_to_context=True,
    read_chat_history=True,
    # The MCP path reuses a session_id, so each call replays this many prior runs;
    # 3 keeps continuity without a deep replay every request.
    num_history_runs=3,
    # Cap provider fan-out per question. Soft limit — agno lets the model answer from
    # what it has instead of looping. Backs up the hard MCP timeout (app/mcp.py).
    tool_call_limit=12,
)
