"""
Owner Identity & Policy
=======================

The single source for "who is the owner" and the ``is_owner`` verdict the whole
owner/guest security model keys off (see ``docs/SECURITY.md``).

Identity arrives already normalized on ``run_context.user_id``:

- **HTTP/UI** — the JWT ``sub``, when AgentOS auth is on (prod). The run route
  prefers the verified ``sub`` over any caller-supplied ``user_id`` form field,
  so it's non-forgeable.
- **Slack** — the author's email, when the Slack interface runs with
  ``resolve_user_identity=True`` (falls back to the raw ``Uxxxx`` id if the
  profile has no email).
- **Dev** — the form ``user_id`` (forgeable — there's no auth locally, which is
  why prod must run with auth on).

We just compare that normalized id against the configured owner id(s).

``OWNER_ID`` is comma-separated so one person's identities across spaces (Slack
email, JWT sub, raw Slack id) all resolve to the owner. The **first** entry is
*canonical* — the ``user_id`` the inbound queue rows are written under and read
back by.

**Fails closed.** With no ``OWNER_ID`` set, ``OWNER_IDS`` is empty and
``is_owner`` is always ``False`` — every caller gets the capture-only surface.
Production must set ``OWNER_ID`` (and run with auth on) for the owner to have
any privileged access.

**The scheduler is the owner's automation.** AgentOS's scheduler triggers runs
over HTTP authenticated with the OS's *internal service token*; the auth
middleware resolves that token to the verified identity ``"__scheduler__"``
(the run route prefers it over any payload ``user_id``, same as a JWT ``sub``).
``is_owner`` accepts it whenever an owner is configured, so scheduled playbooks
(the daily rundown) run with the owner surface and ``normalize_identity`` keys
their writes under the canonical owner id. Trust root: the token is held only
by the in-process scheduler (or shared via ``INTERNAL_SERVICE_TOKEN``), and
creating schedules itself requires authenticated access — see
``docs/SECURITY.md``.
"""

from os import getenv

from agno.run import RunContext

# Sentinel user_id for unauthenticated callers — the agent-level default in
# agents.context. Agno substitutes it before hooks run, so an unauthenticated
# request arrives as this value, never as None.
ANON_USER_ID = "anon"

# The verified identity AgentOS's auth layer assigns to scheduler-triggered
# runs (internal service token, not a JWT). Treated as the owner when an owner
# is configured — scheduled playbooks are the owner's automation.
SCHEDULER_USER_ID = "__scheduler__"


def _parse_owner_ids(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


_OWNER_ID_RAW = getenv("OWNER_ID", "")
_OWNER_ID_LIST = _parse_owner_ids(_OWNER_ID_RAW)

# All identities that count as the owner, casefolded for the is_owner()
# check — Slack can deliver the same email with different capitalization, and
# locking the real owner out to capture-only is the worse failure. (JWT subs
# differing only by case are not a realistic collision.)
OWNER_IDS: frozenset[str] = frozenset(part.casefold() for part in _OWNER_ID_LIST)
# The canonical owner id — what the inbound queue rows are keyed under, in the
# exact spelling configured. None when no owner is configured (the fail-closed
# state).
CANONICAL_OWNER_ID: str | None = _OWNER_ID_LIST[0] if _OWNER_ID_LIST else None

# The owner's display name — cosmetic only, never an identity. Rendered into
# prompts ("Ash's professional alter-ego"); ``is_owner`` never consults it.
OWNER_NAME: str | None = getenv("OWNER_NAME", "").strip() or None


def owner_display_name(default: str = "the owner") -> str:
    """The owner's name for prompts — ``OWNER_NAME``, else the canonical id, else ``default``."""
    return OWNER_NAME or CANONICAL_OWNER_ID or default


def owner_configured() -> bool:
    """True iff at least one owner identity is configured."""
    return bool(OWNER_IDS)


def is_owner(run_context: RunContext | None) -> bool:
    """True iff this run's verified identity is the owner. Fails closed.

    Derive this fresh per run from ``run_context`` — never trust a value a
    prior tool or hook may have written elsewhere. The scheduler's verified
    identity counts as the owner (its runs are the owner's automation), but
    only once an owner is configured — the fail-closed default stands.
    """
    if not OWNER_IDS or run_context is None:
        return False
    user_id = getattr(run_context, "user_id", None)
    if not isinstance(user_id, str):
        return False
    return user_id == SCHEDULER_USER_ID or user_id.casefold() in OWNER_IDS
