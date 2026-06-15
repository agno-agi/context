"""
Context Policy
==============

Everything @context decides from the caller's verified identity, in one place:

- The **surface**: which system prompt and which tools the caller gets. This is the
  primary owner/guest boundary — `context_tools` hands the owner the full provider
  surface and a guest exactly one tool (`submit_update`), and `context_instructions`
  renders the matching guide. The toolset is chosen here, in code, before the model
  runs, so "a guest can't read the owner's data" is structural, not a prompt rule.
- The **hooks**: defense in depth on top of that surface — `normalize_identity`
  (pre-hook) refuses unidentified prod runs and collapses the owner's aliases;
  `enforce_capture_only` (tool-hook) soft-blocks any non-capture tool from a guest.

Both key off `app.identity.is_owner`. See `docs/SECURITY.md`.
"""

from inspect import isawaitable
from pathlib import Path
from typing import Any, Callable

from agno.exceptions import InputCheckError
from agno.run import RunContext
from agno.skills import LocalSkills, Skills
from agno.utils.log import log_warning

from agents.inbox import CAPTURE_ONLY_TOOLS, GUEST_TOOLS, acknowledge, rundown
from agents.instructions import CONTEXT_INSTRUCTIONS, GUEST_GUIDE, OWNER_GUIDE
from agents.sources import context_providers_summary, gate_act_tools, list_contexts, owner_provider_tools
from app.identity import ANON_USER_ID, CANONICAL_OWNER_ID, is_owner, owner_display_name, resolved_user_id
from app.settings import is_prd
from workflows.reminders import queue_reminders

# ---------------------------------------------------------------------------
# Runtime skills — owner-only playbooks (e.g. the week plan)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# The surface — identity-conditioned instructions + tools
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# The hooks — defense in depth
# ---------------------------------------------------------------------------


def normalize_identity(run_context: RunContext, **kwargs: Any) -> None:
    """Collapse the owner's aliases and refuse unidentified prod runs.

    Run as a pre-hook to ensure that every run has a verified identity.
    """
    user_id = getattr(run_context, "user_id", None)

    # In production (auth on) every run must carry a verified identity. A run
    # arriving as the anon sentinel (or with no user_id at all) means
    # something bypassed the auth layer — refuse it.
    if is_prd() and user_id in (None, "", ANON_USER_ID):
        raise InputCheckError("No verified identity on this run; refusing in production.")

    # The owner's identities (Slack email, JWT sub) all collapse onto the
    # canonical id, so the structured store, knowledge base, and queue key
    # under one identity instead of fragmenting per channel.
    if CANONICAL_OWNER_ID is not None and is_owner(run_context):
        run_context.user_id = CANONICAL_OWNER_ID


async def enforce_capture_only(
    name: str,
    func: Callable,
    arguments: dict,
    run_context: RunContext | None = None,
    **kwargs: Any,
) -> Any:
    """Restrict guests to the capture-only allowlist; the owner may call anything.

    Run as a tool-hook: a guest caller may only invoke tools on the
    capture-only allowlist — every other tool is soft-blocked.
    """
    if not is_owner(run_context) and name not in CAPTURE_ONLY_TOOLS:
        # Soft block: return guidance *without* calling func, so the tool's
        # entrypoint never runs (no data is read or written) but the model can
        # still compose a graceful reply instead of the run halting mid-turn.
        # This gates everything outside the capture allowlist — including
        # agno's auto-added built-ins like get_chat_history — for guests.
        # (The per-user memory tool is deliberately *on* the allowlist; see
        # CAPTURE_ONLY_TOOLS in agents.inbox.)
        return (
            "Not permitted: as a guest you have no read access here. Don't "
            "try other tools — tell the caller you can only pass a message to "
            "the owner, and use submit_update if that's what they want."
        )
    result = func(**arguments)
    if isawaitable(result):
        result = await result
    return result
