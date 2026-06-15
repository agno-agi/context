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
"""

import logging
from collections.abc import Awaitable, Callable
from os import getenv
from urllib.parse import urlparse

from agno.os.config import AuthorizationConfig
from agno.utils.log import log_warning
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from agents.context import context
from app.identity import CANONICAL_OWNER_ID, OWNER_IDS
from app.settings import is_prd

# The MCP endpoint path. The sub-app is mounted at the app root, so this is also
# the public path (https://<host>/mcp).
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


def _resolve_caller_id(request: Request | None) -> str | None:
    """The verified caller identity for this MCP request.

    Production: the JWT middleware on this sub-app has put the verified token
    ``sub`` on ``request.state.user_id`` — read it. Dev (no JWT): fall back to
    the canonical owner id, the same keyless-local-as-owner shortcut compose
    uses. DEV-ONLY — prod always carries a verified identity.
    """
    state_id = getattr(getattr(request, "state", None), "user_id", None)
    if isinstance(state_id, str) and state_id:
        return state_id
    if not is_prd():
        return CANONICAL_OWNER_ID  # dev shortcut — there is no auth locally
    return None


def _caller_is_owner(user_id: str | None) -> bool:
    """True iff this id is a configured owner identity. Fails closed.

    Stricter than ``app.identity.is_owner``: it does *not* honour the
    ``__scheduler__`` sentinel — the scheduler never calls this endpoint, and
    keeping the human read/act surface to real owner identities is one fewer
    thing to reason about.
    """
    if not user_id:
        return False
    return user_id.casefold() in OWNER_IDS


def _mcp_transport_security() -> TransportSecuritySettings:
    """DNS-rebinding protection for the MCP endpoint.

    An always-on local MCP server is exactly what this guard is for: it stops a
    malicious web page from driving the endpoint via a rebound DNS name (with no
    JWT in dev, that would otherwise reach the owner surface). We mirror the SDK's
    localhost defaults — so the desktop case works with zero config — and add the
    deploy/tunnel host from ``AGENTOS_URL`` so it also works behind a reverse
    proxy (Railway) or an ngrok tunnel (point ``AGENTOS_URL`` at that domain).
    """
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    deploy_host = urlparse(getenv("AGENTOS_URL", "")).hostname
    if deploy_host and deploy_host not in ("127.0.0.1", "localhost", "::1"):
        hosts += [deploy_host, f"{deploy_host}:*"]
        origins += [
            f"https://{deploy_host}",
            f"https://{deploy_host}:*",
            f"http://{deploy_host}",
            f"http://{deploy_host}:*",
        ]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


class OwnerOnlyMiddleware(BaseHTTPMiddleware):
    """Fail-closed owner gate — the structural reason this can't become a guest path.

    Runs after the JWT middleware (in prod) has resolved the verified identity
    onto ``request.state``. Resolves the caller; if it is not the owner it
    returns 401 *before* the MCP machinery and the model ever run. On success it
    stashes the resolved owner id on ``request.state`` for the tool to read.
    """

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        caller = _resolve_caller_id(request)
        if not _caller_is_owner(caller):
            return JSONResponse(
                {"error": "unauthorized", "detail": "The @context MCP server is owner-only."},
                status_code=401,
            )
        request.state.context_owner_id = caller
        return await call_next(request)


async def _run_as_owner(ctx: Context, message: str, session_id: str | None) -> str:
    """Run the real context agent as the owner and return its reply.

    The body of `ask_context` — the caller gets the owner's full read/write/act
    surface; the agent decides what to do with the message.
    """
    request: Request | None = getattr(getattr(ctx, "request_context", None), "request", None)
    caller = _resolve_caller_id(request)
    # Defense in depth — the middleware already 401s non-owners. If we ever
    # reached here without an owner, refuse rather than run as anyone.
    if not _caller_is_owner(caller):
        raise ValueError("The @context MCP server is owner-only.")
    # Key under the canonical id — matches normalize_identity and keeps sessions /
    # storage from fragmenting across the owner's identities.
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


def build_context_mcp_app(
    *, authorization: bool = False, authorization_config: AuthorizationConfig | None = None
) -> Starlette:
    """Build the owner-only MCP sub-app: one tool, owner-gated, fail-closed.

    ``authorization`` / ``authorization_config`` are the *same* values AgentOS
    is constructed with (passed in from [`app/main.py`](main.py)), so the JWT
    layer here is identical to the REST API's — same keys, same algorithm.
    """
    # FastMCP.__init__ calls logging.basicConfig() with a default RichHandler,
    # which hijacks the *root* logger and reformats every library's logs (httpx,
    # mcp) with timestamp + file:line columns. Undo that global side effect by
    # dropping the handler(s) it adds to root — leaving any pre-existing root
    # handlers untouched — so the rest of the app keeps its own logging.
    _root_handlers_before = logging.root.handlers[:]
    # stateless_http=True: each request is self-contained — no in-memory session
    # map to invalidate, so a redeploy/restart (or a second replica) never 404s a
    # client holding a session id from before. `ask_context` is request/response
    # and the agent thread rides the `session_id` arg into Postgres, not the MCP
    # transport, so there's nothing to lose by dropping transport sessions. Left
    # json_response at its SSE default so a slow agent run keeps the connection
    # warm (no proxy idle-timeout) instead of blocking on one JSON response.
    server = FastMCP(
        name="context",
        stateless_http=True,
        transport_security=_mcp_transport_security(),
    )
    for handler in logging.root.handlers[:]:
        if handler not in _root_handlers_before:
            logging.root.removeHandler(handler)

    @server.tool(name="ask_context", description=ASK_CONTEXT_DESCRIPTION)
    async def ask_context(message: str, ctx: Context, session_id: str | None = None) -> str:
        return await _run_as_owner(ctx, message, session_id)

    mcp_app = server.streamable_http_app()

    # Owner gate added first (innermost); JWT added last (outermost) so it
    # populates request.state.user_id before the gate reads it. Starlette runs
    # the last-added middleware first.
    mcp_app.add_middleware(OwnerOnlyMiddleware)
    if authorization and authorization_config is not None:
        from agno.os.middleware.jwt import JWTMiddleware

        # Mirror agno/os/mcp.py: keys come from the config (or, when None, the
        # JWT_VERIFICATION_KEY env var the validator reads on its own).
        mcp_app.add_middleware(
            JWTMiddleware,
            verification_keys=authorization_config.verification_keys,
            jwks_file=authorization_config.jwks_file,
            algorithm=authorization_config.algorithm or "RS256",
            authorization=authorization,
            verify_audience=authorization_config.verify_audience or False,
            user_isolation=authorization_config.user_isolation,
        )
    elif is_prd():
        # No JWT layer in prd means the dev shortcut is the only thing standing
        # in for auth — which would reject every call (no verified identity).
        log_warning(
            "Context MCP server mounted in prd without JWT authorization — the owner gate will "
            "reject every call. Configure authorization (RUNTIME_ENV=prd implies it)."
        )
    return mcp_app
