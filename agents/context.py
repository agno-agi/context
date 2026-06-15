"""
Context — Personal Context Agent
================================

One Agno agent that captures, files, and retrieves the owner's working context.
The identity-conditioned surface (which prompt, which tools) and the
defense-in-depth hooks both live in `agents.policy`; this module just assembles
the agent from them.
"""

from agno.agent import Agent
from agno.learn import LearningMachine, LearningMode, UserMemoryConfig, UserProfileConfig

from agents.policy import context_instructions, context_tools, enforce_capture_only, normalize_identity
from app.identity import ANON_USER_ID
from app.settings import default_model, owner_timezone
from db import get_postgres_db

context = Agent(
    id="context",
    name="Context",
    model=default_model(),
    db=get_postgres_db(),
    # Identity-conditioned, resolved per run (see agents.policy).
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
