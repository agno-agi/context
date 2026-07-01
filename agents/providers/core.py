"""
Core Context Providers
======================

Always-on providers: web, workspace, CRM, knowledge.
These don't require external credentials — they work out of the box.
"""

from os import getenv
from pathlib import Path

from agno.context.database import DatabaseContextProvider
from agno.context.mode import ContextMode
from agno.context.web.parallel import ParallelBackend
from agno.context.web.parallel_mcp import ParallelMCPBackend
from agno.context.web.provider import WebContextProvider
from agno.context.wiki import FileSystemBackend, GitBackend, WikiContextProvider
from agno.context.workspace import WorkspaceContextProvider
from agno.tools.workspace import DEFAULT_EXCLUDE_PATTERNS
from agno.utils.log import log_info, log_warning

from agents.instructions import CRM_READ, CRM_WRITE, KNOWLEDGE_READ, KNOWLEDGE_WRITE
from app.settings import default_model
from db import SCHEMA, get_readonly_engine, get_sql_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_PATH = REPO_ROOT / "knowledge"


def create_web_provider() -> WebContextProvider:
    """Web search and page reading via Parallel or MCP backend."""
    model = default_model()
    if getenv("PARALLEL_API_KEY"):
        return WebContextProvider(backend=ParallelBackend(), model=model)
    return WebContextProvider(backend=ParallelMCPBackend(), model=model)


def create_workspace_provider() -> WorkspaceContextProvider:
    """Filesystem context for the context repo itself.

    mode=tools exposes the read tools (list_files / search_content / read_file)
    straight to the main context agent instead of behind a nested sub-agent, so a
    codebase question is answered in the agent's own turn (one pass, bounded by its
    tool_call_limit) rather than paying a full sub-agent round-trip per file read.

    agno's defaults already exclude .env*, .git, caches, etc. Also keep Google
    credential files out: in local dev compose mounts the repo at /app, so
    without this the owner's own agent could read the minted OAuth token (or a
    stray key file) back through read_file.
    """
    return WorkspaceContextProvider(
        root=REPO_ROOT,
        model=default_model(),
        mode=ContextMode.tools,
        exclude_patterns=[*DEFAULT_EXCLUDE_PATTERNS, "*_token.json", "google-service-account.json"],
    )


def create_crm_provider() -> DatabaseContextProvider:
    """The CRM — the structured database, read + write over the `crm` schema.

    The tuned instructions know the managed table shape
    (projects/meetings/reminders/notes/contacts), rendered from the schema spec.
    """
    return DatabaseContextProvider(
        id="crm",
        name="CRM",
        sql_engine=get_sql_engine(),
        readonly_engine=get_readonly_engine(),
        schema=SCHEMA,
        read_instructions=CRM_READ,
        write_instructions=CRM_WRITE,
        model=default_model(),
    )


def create_knowledge_provider() -> WikiContextProvider:
    """The knowledge base — read + write knowledge, organized folder-per-spec.

    Filesystem-backed by default. Set `KNOWLEDGE_REPO_URL` AND `KNOWLEDGE_GITHUB_TOKEN`
    to switch to `GitBackend` for durable storage with an audit trail.
    """
    repo_url = getenv("KNOWLEDGE_REPO_URL", "").strip()
    github_token = getenv("KNOWLEDGE_GITHUB_TOKEN", "").strip()

    backend: FileSystemBackend | GitBackend
    if repo_url and github_token:
        backend = GitBackend(
            repo_url=repo_url,
            github_token=github_token,
            branch=getenv("KNOWLEDGE_BRANCH", "main"),
            local_path=getenv("KNOWLEDGE_LOCAL_PATH") or None,
        )
        log_info(f"Knowledge base: GitBackend ({repo_url})")
    else:
        if repo_url or github_token:
            log_warning(
                "Knowledge base: KNOWLEDGE_REPO_URL and KNOWLEDGE_GITHUB_TOKEN must both be set "
                "to enable GitBackend; falling back to FileSystemBackend."
            )
        KNOWLEDGE_PATH.mkdir(parents=True, exist_ok=True)
        backend = FileSystemBackend(path=KNOWLEDGE_PATH)

    return WikiContextProvider(
        id="knowledge",
        name="Knowledge Base",
        backend=backend,
        read_instructions=KNOWLEDGE_READ,
        write_instructions=KNOWLEDGE_WRITE,
        model=default_model(),
    )
