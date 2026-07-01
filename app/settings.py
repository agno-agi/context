"""
AgentOS Settings
================

Shared runtime objects for the AgentOS.
"""

from os import getenv
from zoneinfo import ZoneInfo

from agno.models.openai import OpenAIResponses
from agno.utils.log import log_info, log_warning


def default_model() -> OpenAIResponses:
    """Fresh model instance per agent — avoids memory leaks."""
    return OpenAIResponses(id="gpt-5.5")


def owner_timezone() -> str:
    """The owner's IANA timezone from ``OWNER_TIMEZONE`` (e.g. ``America/Los_Angeles``).

    Anchors "today", "due today", and relative-date resolution to the owner's
    local day instead of UTC. Unset (or an invalid name) falls back to ``UTC`` —
    the prior behavior, so nothing breaks. ``app/main.py`` warns once at startup
    when it's unset or invalid, so the UTC default is visible, not silent.
    """
    raw = getenv("OWNER_TIMEZONE", "").strip()
    if not raw:
        return "UTC"
    try:
        ZoneInfo(raw)
    except Exception:
        return "UTC"
    return raw


def owner_timezone_configured() -> bool:
    """True iff ``OWNER_TIMEZONE`` is set to a valid IANA zone (not the UTC fallback)."""
    raw = getenv("OWNER_TIMEZONE", "").strip()
    return bool(raw) and owner_timezone() == raw


def runtime_env() -> str:
    """``RUNTIME_ENV`` with the production default."""
    return getenv("RUNTIME_ENV", "prd")


def is_prd() -> bool:
    """True unless explicitly running dev — auth and owner checks rely on this."""
    return runtime_env() == "prd"


def warn_on_missing_config() -> None:
    """Log startup warnings for unset config that silently changes behavior.

    Called once from the AgentOS lifespan (app/main.py).
    """
    from app.identity import owner_configured  # local import to keep settings load lean

    # Without an OWNER_ID, @context is capture-only for everyone.
    if is_prd() and not owner_configured():
        log_warning(
            "OWNER_ID is not set — no caller will be treated as the owner. "
            "Context is capture-only for everyone until OWNER_ID is set."
        )
    # Without OWNER_TIMEZONE, "today" and relative dates fall back to UTC.
    if owner_timezone_configured():
        log_info(f"OWNER_TIMEZONE={owner_timezone()}")
    else:
        log_warning(
            "OWNER_TIMEZONE is not set (or invalid) — 'today', due/overdue math, and relative "
            "dates use UTC. Set it to your IANA zone (e.g. America/Los_Angeles)."
        )


def _float_env(name: str, default: float) -> float:
    """Read a float env var, falling back to ``default`` on unset/garbage."""
    try:
        return float(getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


def use_context_timeout() -> float:
    """Hard ceiling (seconds) for one ``use_context`` run on the MCP path.

    Bounds a cross-source sweep so a slow source returns an "ask something narrower"
    message instead of hanging the client. Keep it under the client's own tool timeout
    (e.g. Claude Code's ``MCP_TOOL_TIMEOUT``) so our message wins, not a dead stream.
    """
    return _float_env("USE_CONTEXT_TIMEOUT", 300.0)


def provider_query_timeout() -> float:
    """Per-source ceiling (seconds) for a single best-effort ``query_<id>`` sub-agent run.

    A slow source degrades to a one-line "skipped" and the rest of the brief still
    lands. Smaller than ``use_context_timeout`` so several can skip within one budget.
    """
    return _float_env("PROVIDER_TIMEOUT", 180.0)


def backbone_query_timeout() -> float:
    """Per-source ceiling (seconds) for a *backbone* read (the CRM — the structured store).

    The rundown fires its sources as one concurrent batch, so wall-clock is the
    slowest source, not the sum. Backbone and best-effort want opposite things from
    that window: best-effort should skip fast (``PROVIDER_TIMEOUT``), but the
    backbone is the brief's spine and must reliably land — a gpt-5.5 sub-agent run
    varies (~10-25s), so a tight 20s ceiling drops it too often. Giving the backbone
    a longer budget catches that slow tail while best-effort still skips fast; the
    batch's wall-clock is the larger of the two. Kept under ``use_context_timeout``
    (minus skill-load + compose headroom) so a rundown still fits the MCP ceiling.
    """
    return _float_env("BACKBONE_TIMEOUT", 35.0)
