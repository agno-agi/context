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
from agents.sources import ACT_TOOLS, context_providers_summary, get_context_providers, list_contexts
from app.identity import ANON_USER_ID, is_owner, owner_display_name
from app.settings import default_model
from db import get_postgres_db

# Runtime skills i.e. reusable playbooks the owner can invoke (e.g. the week plan).
# Owner-gated like the provider tools: the access tools are added only in the
# owner branch of `context_tools`, and the browse snippet only renders in the
# owner branch of `caller_information`. So a guest's tool surface *and* system
# prompt carry zero skill references — the boundary is enforced in code, not a
# prompt rule (see `docs/SECURITY.md`).
_SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"


def _load_skills() -> Skills | None:
    """Build the skills registry, degrading to ``None`` if it can't load.

    A malformed ``SKILL.md`` raises ``SkillValidationError`` at load; we don't
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

    Wired as a callable on ``Agent.dependencies`` so agno resolves it on every run.
    """
    if is_owner(run_context):
        skills = _skills.get_system_prompt_snippet() if _skills is not None else ""
        return OWNER_GUIDE.format(providers=context_providers_summary(), skills=skills)
    return GUEST_GUIDE.format(owner=owner_display_name("(no owner configured)"))


def context_tools(run_context: RunContext | None = None) -> list:
    """Build Context's tool list based on the caller's identity.

    Wired as a callable on ``Agent.tools`` and resolved per run by setting ``cache_callables=False``.

    The owner branch grants the full toolset — provider tools, queue, skills.
    The guest branch is the security boundary: a guest never receives
    a read or act tool. Identity absent or unverifiable is also capture-only (fail closed).
    """
    if is_owner(run_context):
        tools: list = []
        for ctx in get_context_providers():
            tools.extend(ctx.get_tools())
        tools += [list_contexts, rundown, acknowledge]
        if _skills is not None:
            tools += _skills.get_tools()
        # The approval gate on acting as the owner: tools that reach the
        # outside world (send email, change the calendar) pause the run for
        # explicit confirmation before they execute. Set per run — providers
        # build fresh tool objects on every get_tools() call.
        for t in tools:
            if getattr(t, "name", None) in ACT_TOOLS:
                t.requires_confirmation = True
        return tools
    return list(GUEST_TOOLS)


context = Agent(
    id="context",
    name="Context",
    model=default_model(),
    db=get_postgres_db(),
    instructions=CONTEXT_INSTRUCTIONS,
    tools=context_tools,
    # Default user_id when a caller (eval runner, unauthenticated script)
    # invokes Context without identifying the user. A guest id, so it defaults
    # to the capture-only surface. Production surfaces (UI, Slack) override this with a verified identity.
    user_id=ANON_USER_ID,
    # Resolve tools on every run based on caller's identity.
    cache_callables=False,
    # Pre-hook refuses unidentified prod runs and collapses the owner's
    # configured identities onto the canonical id; tool-hook refuses any
    # non-capture tool from a guest caller.
    pre_hooks=[normalize_identity],
    tool_hooks=[enforce_capture_only],
    # `{caller_information}` resolves per run: the owner instructions (providers, loop,
    # routing, queue, skills) for the owner; the capture-only instructions for the guests.
    # `{owner_name}` is the owner's display name (OWNER_NAME, falling back to the
    # canonical id) — cosmetic, never used for identity checks.
    dependencies={"caller_information": caller_information, "owner_name": owner_display_name()},
    # Per-caller learning — the one capability every caller keeps, outside the
    # identity-conditioned toolset (see docs/SECURITY.md L2). Agentic mode adds
    # `update_user_memory` + `update_profile` to every run, each keyed in code
    # to the caller's own verified user_id; recall injects only that caller's
    # data. A guest's memories and profile never touch the owner's context.
    learning=LearningMachine(
        user_profile=UserProfileConfig(mode=LearningMode.AGENTIC),
        user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
    ),
    add_datetime_to_context=True,
    add_history_to_context=True,
    read_chat_history=True,
    num_history_runs=5,
    markdown=True,
)
