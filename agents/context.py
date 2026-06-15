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
from agents.sources import context_providers_summary, gate_act_tools, list_contexts, owner_provider_tools
from app.identity import ANON_USER_ID, is_owner, owner_display_name, resolved_user_id
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
    if is_owner(run_context):
        skills = _skills.get_system_prompt_snippet() if _skills is not None else ""
        return OWNER_GUIDE.format(
            owner_name=owner_display_name(),
            providers=context_providers_summary(),
            skills=skills,
        )
    return GUEST_GUIDE.format(
        owner_name=owner_display_name("(no owner configured)"),
        user_id=resolved_user_id(run_context),
    )


def context_instructions(run_context: RunContext | None = None) -> str:
    """Render Context's system prompt for this run."""
    return CONTEXT_INSTRUCTIONS.format(
        owner_name=owner_display_name(),
        user_id=resolved_user_id(run_context),
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
    """Build Context's tool list for this run, keyed on the caller's identity.

    Wired as a callable on `Agent.tools` and resolved per run (`cache_callables=False`).
    The owner gets the full surface — provider tools, the inbound queue, runtime skills.
    A guest gets exactly one tool: submit_update.
    """
    if not is_owner(run_context):
        return list(GUEST_TOOLS)

    # Provider reads are time-boxed so one slow source can't stall the run, and Google
    # reads skip on a dead token (see owner_provider_tools); the queue and skills layer on.
    tools: list = list(owner_provider_tools())
    tools += [list_contexts, rundown, acknowledge, queue_reminders]
    if _skills is not None:
        tools += _skills.get_tools()
    # Scheduled digests run read-only: strip every write tool.
    if _is_read_only(run_context):
        tools = [t for t in tools if not _is_write_tool(getattr(t, "name", ""))]
    # Pause for owner approval before any act tool (calendar) reaches the outside world.
    return gate_act_tools(tools)


context = Agent(
    id="context",
    name="Context",
    model=default_model(),
    db=get_postgres_db(),
    instructions=context_instructions,
    tools=context_tools,
    # Unauthenticated callers (eval runner, scripts) default to this; UI/Slack override it.
    user_id=ANON_USER_ID,
    # Resolve instructions + tools per run from the caller's verified identity.
    cache_callables=False,
    # Pre-hook refuses unidentified prod runs and collapses the owner's aliases onto the canonical id.
    pre_hooks=[normalize_identity],
    # Tool-hook refuses any non-capture tool from a guest caller.
    tool_hooks=[enforce_capture_only],
    # Learn about the caller; agentic mode adds update_user_memory + update_profile,
    # each keyed to the caller's own id, so a guest's memory never touches the owner's data.
    learning=LearningMachine(
        user_profile=UserProfileConfig(mode=LearningMode.AGENTIC),
        user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
    ),
    # Anchor "now" to the owner's local day (OWNER_TIMEZONE, else UTC); the rundown's
    # "today" and due/overdue math key off this. The format carries the weekday + zone.
    add_datetime_to_context=True,
    timezone_identifier=owner_timezone(),
    datetime_format="%A %Y-%m-%d %H:%M %Z",
    add_history_to_context=True,
    read_chat_history=True,
    # The MCP path reuses a session_id; replay 3 prior runs for continuity without a deep replay.
    num_history_runs=3,
    # Soft cap on provider fan-out per question; backs up the hard MCP timeout (app/mcp.py).
    tool_call_limit=12,
)
