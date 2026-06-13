"""
Owner-Policy Hooks (defense in depth)
=====================================

The *primary* boundary is the identity-conditioned toolset in
``agents.context`` — a guest literally never receives the privileged tools,
so "don't read the owner's data" is structural, not a prompt rule. These hooks
are belt-and-suspenders on top of that, each enforced in code from the verified
identity (see ``docs/SECURITY.md``).

- :func:`normalize_identity` (``pre_hook``) — fails closed, then canonicalizes.
  In production every run must carry a verified identity; agno substitutes the
  agent-level default (``"anon"``) before hooks run, so a request that bypassed
  auth arrives as that sentinel — refuse it with ``InputCheckError`` (the one
  exception type a pre_hook may raise — everything else is swallowed). Then the
  owner's configured identities (Slack email, JWT sub) are collapsed onto the
  canonical id, so the structured store, wiki, and queue key under one identity
  instead of fragmenting per channel. Provider sub-agents inherit ``user_id``
  from ``run_context``, so the rewrite reaches them; agno's memory/session
  machinery captures the original id before hooks run, so sessions stay under
  the channel identity the OS routes filter by (see docs/SECURITY.md).

- :func:`enforce_capture_only` (``tool_hook``) — an allowlist gate on *every*
  tool call: a guest caller may only invoke the capture-only tools (the
  guest toolset plus the per-user memory tool). Anything else is
  soft-blocked — the hook returns refusal guidance instead of running the
  tool, so no data is read or written but the model can still reply
  gracefully. This is the per-call backstop behind the toolset gate — if
  ``context_tools`` ever regressed and handed a guest a privileged tool,
  this still blocks the call.

Why a tool_hook *and* a pre_hook: they fail closed for different failures. The
pre_hook can't see which tools a run will call (tools resolve after it), so it
can't gate per-tool; the tool_hook can't abort the whole run cleanly across the
model loop the way an ``InputCheckError`` pre_hook can. Together they cover both.
"""

from inspect import isawaitable
from typing import Any, Callable

from agno.exceptions import InputCheckError
from agno.run import RunContext

from agents.inbox import CAPTURE_ONLY_TOOLS
from app.identity import ANON_USER_ID, CANONICAL_OWNER_ID, is_owner
from app.settings import is_prd


def normalize_identity(run_context: RunContext, **kwargs: Any) -> None:
    """Pre-hook: refuse unidentified prod runs; collapse the owner's aliases."""
    user_id = getattr(run_context, "user_id", None)

    # In production (auth on) every run must carry a verified identity. A run
    # arriving as the anon sentinel (or with no user_id at all) means
    # something bypassed the auth layer — refuse it.
    if is_prd() and user_id in (None, "", ANON_USER_ID):
        raise InputCheckError("No verified identity on this run; refusing in production.")

    # The owner's identities (Slack email, JWT sub) all collapse onto the
    # canonical id, so the structured store, wiki, and queue key under one
    # identity instead of fragmenting per channel.
    if CANONICAL_OWNER_ID is not None and is_owner(run_context):
        run_context.user_id = CANONICAL_OWNER_ID


async def enforce_capture_only(
    name: str,
    func: Callable,
    arguments: dict,
    run_context: RunContext | None = None,
    **kwargs: Any,
) -> Any:
    """Tool-hook: a guest may only call capture-only tools.

    Async so AgentOS's async tool-execution chain routes it through the
    awaiting hook caller: ``func`` (the continuation) is a coroutine there and
    *must* be awaited, or the wrapped tool silently never runs. ``func`` is
    always called to continue the chain unless the caller is denied.
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
