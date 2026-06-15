"""
Context MCP server
======================

@context comes with a one-tool MCP server (`ask_context`) which lets the owner
read, file, and act through @context from MCP clients — Claude Code, Codex, and
the Claude / ChatGPT desktop apps.

The CLI clients register it with one command (`claude mcp add` / `codex mcp add`)
against http://localhost:8000/mcp; the desktop apps reach the same endpoint
through a small mcp-remote stdio bridge. Cloud clients (ChatGPT web, Claude web)
need a public HTTPS URL — a deploy or an ngrok tunnel (see docs/MCP.md).

The @context mcp server exposes one tool:

- `ask_context(message, session_id?)`

One tool, not several: `ask_context` runs the real context agent as the owner,
which reads, files, and acts on its own — so the client has one obvious door for
anything about the owner's work, rather than a read-vs-write routing decision.

AgentOS owns the JWT layer, the owner gate (`authorize`), DNS-rebinding
protection (`allowed_hosts`), and `user_id` injection — there is no custom
middleware in this module. See `context_mcp_config()` below.
"""

from os import getenv
from urllib.parse import urlparse

from agno.os.config import MCPServerConfig
from agno.tools import tool

from agents.context import context
from app.identity import CANONICAL_OWNER_ID, OWNER_IDS
from app.settings import is_prd

# The MCP endpoint path. AgentOS mounts the MCP server at this path.
MCP_PATH = "/mcp"

ASK_CONTEXT_DESCRIPTION = (
    "The owner's work brain and first stop for anything about their work life. "
    "Always try this before Gmail, Calendar, Drive, Slack, Linear, or a past-chat "
    "search when the question is about the owner's projects, people, companies, "
    "schedule, inbox, decisions, or priorities. It sits on top of those sources "
    "and returns one synthesized, cross-source answer instead of raw results.\n\n"
    'Three modes. (1) Look up: "what\'s on my plate," "where are we with X," '
    '"what do we know about this person or company," "what\'s on my calendar," '
    '"anything urgent in my inbox." (2) Remember: save or update notes, decisions, '
    "contacts, reminders, status, and preferences. Call this whenever the owner "
    "states something worth keeping, even in passing. (3) Act: draft an email reply, "
    "propose a calendar change, or send a Slack message. Email and calendar come "
    "back as a draft or proposal for the owner's approval and never go out on their "
    "own; a Slack message is ordinary communication and goes out directly.\n\n"
    "Pass a natural-language request. Pass session_id to continue an existing "
    "thread. Owner-only. Do not use for general knowledge or anyone else's data."
)


def _resolve_caller_id(user_id: str | None) -> str | None:
    """The verified caller identity for this MCP request.

    Production: AgentOS injects the JWT subject as ``user_id`` (the verified
    token ``sub``). Dev (no JWT): fall back to the canonical owner id, the same
    keyless-local-as-owner shortcut compose uses. DEV-ONLY — prod always carries
    a verified identity.
    """
    if isinstance(user_id, str) and user_id:
        return user_id
    if not is_prd():
        return CANONICAL_OWNER_ID  # dev shortcut — there is no auth locally
    return None


def _caller_is_owner(user_id: str | None) -> bool:
    """True iff this id is a configured owner identity. Fails closed.

    Stricter than ``app.identity.is_owner``: it does *not* honour the
    ``__scheduler__`` sentinel — the scheduler never calls this endpoint, and
    keeping the human read/act surface to real owner identities is one fewer
    thing to reason about.

    Resolves dev shortcuts via :func:`_resolve_caller_id` so the local
    keyless-as-owner path still works in dev.
    """
    resolved = _resolve_caller_id(user_id)
    if not resolved:
        return False
    return resolved.casefold() in OWNER_IDS


@tool(name="ask_context", description=ASK_CONTEXT_DESCRIPTION)
async def ask_context(message: str, user_id: str | None = None, session_id: str | None = None) -> str:
    """Run the real context agent as the owner and return its reply.

    `user_id` is injected by AgentOS from the JWT subject and is hidden from the
    client-facing tool schema, so callers can never supply or spoof it. The
    `authorize` gate in :func:`context_mcp_config` has already 401'd non-owners;
    this body keeps a defense-in-depth check before running.
    """
    if not _caller_is_owner(user_id):
        raise ValueError("The @context MCP server is owner-only.")
    # Key under the canonical id — matches normalize_identity and keeps sessions
    # / storage from fragmenting across the owner's identities.
    result = await context.arun(input=message, user_id=CANONICAL_OWNER_ID, session_id=session_id)
    answer = result.content or ""
    if getattr(result, "is_paused", False):
        # A gated act tool (calendar) is waiting on the owner. There's no approval
        # affordance over MCP, so point them at the chat UI.
        answer += (
            "\n\n[An action is waiting on your approval before it can run — approve it in the "
            "AgentOS chat UI, then ask me to continue.]"
        )
    return answer


def _allowed_hosts() -> list[str]:
    """Deploy/tunnel host for DNS-rebinding protection.

    AgentOS bakes in the localhost defaults (127.0.0.1, localhost, [::1]) so the
    desktop case works with zero config. We only need to add the deploy host
    from ``AGENTOS_URL`` so the server also works behind a reverse proxy
    (Railway) or an ngrok tunnel (point ``AGENTOS_URL`` at that domain).
    """
    deploy_host = urlparse(getenv("AGENTOS_URL", "")).hostname
    if deploy_host and deploy_host not in ("127.0.0.1", "localhost", "::1"):
        return [deploy_host]
    return []


def context_mcp_config() -> MCPServerConfig:
    """Configuration for the @context MCP server — passed to ``AgentOS(mcp_config=...)``.

    Owner-only, single-tool surface:
      - ``tools=[ask_context]`` — the one tool the server exposes.
      - ``enable_builtin_tools=False`` — none of AgentOS's 19 built-ins (no
        session/memory CRUD over MCP; the owner uses chat UI for that).
      - ``authorize=_caller_is_owner`` — 401s non-owners after JWT, before the
        model runs. Replaces the old ``OwnerOnlyMiddleware``.
      - ``allowed_hosts=...`` — built-in DNS-rebinding protection. Localhost is
        baked into AgentOS; we add the deploy/tunnel host. Replaces the old
        ``_mcp_transport_security()`` helper.
    """
    return MCPServerConfig(
        tools=[ask_context],
        enable_builtin_tools=False,
        authorize=_caller_is_owner,
        allowed_hosts=_allowed_hosts(),
    )
