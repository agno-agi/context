"""
Identity Validation
===================

When you make a request to the AgentOS API, you provide the user's identity in the `user_id` form field and as a JWT via the `Authorization: Bearer <token>` header.

AgentOS extracts the user's identity (sub) from the JWT and stores it in `run_context.user_id`. The user_id is then compared against the configured owner id(s) to determine if the caller is the owner. See `docs/SECURITY.md` for more details.

Different systems provide the user_id in different ways:
- **AgentOS API:** When `authorization=True`, AgentOS extracts the `sub` from the JWT and prefers it over the caller-supplied `user_id` form field (non-forgeable).
- **Slack:** The Slack interface maps the author's email to the user_id and sets it as the run's `user_id` when `resolve_user_identity=True`. If the profile has no email, the raw `Uxxxx` id is used.
- **Dev:** The provided `user_id` (forgeable — there's no auth locally, which is why prod must run with auth on).

We compare the provided user_id against the configured owner id(s) in `OWNER_ID`.

`OWNER_ID` is a comma-separated list of identities across surfaces (email, Slack email, raw Slack id) that resolve to the owner. The **first** entry is canonical — the `user_id` the inbound queue rows are written under and read back by.

If no `OWNER_ID` is set, `OWNER_IDS` is empty and `is_owner` is always `False` — every caller gets the capture-only surface.
Production must set `OWNER_ID` (and run with auth on) for the owner to have any privileged access.

The scheduler runs as the owner's automation.

AgentOS's scheduler sends requests over HTTP that are authenticated using the OS's *internal service token*. The auth middleware resolves that token to the verified identity `"__scheduler__"` (the run route prefers it over any payload `user_id`, same as a JWT `sub`). `is_owner` accepts it whenever an owner is configured, so scheduled playbooks (the daily rundown) run with owner level permissions. See `docs/SECURITY.md`.
"""

from os import getenv

from agno.run import RunContext
from agno.utils.log import log_warning

# Default user_id for unauthenticated requests.
# Agno substitutes it before pre_hooks run, so an unauthenticated request (whose underlying user_id is None) arrives as this value.
ANON_USER_ID = "anon"

# The verified identity AgentOS's auth layer assigns to scheduler-triggered
# runs (internal service token, not a JWT). Treated as the owner when an owner
# is configured — scheduled playbooks run as the owner's automation.
SCHEDULER_USER_ID = "__scheduler__"


# Reserved internal identities — never valid owner ids. `anon` is the
# unauthenticated sentinel and `__scheduler__` is minted only by the auth layer
# from the internal service token; letting either into OWNER_ID would hand the
# owner surface to unauthenticated callers (in dev) or be redundant.
_RESERVED_IDS = frozenset({ANON_USER_ID.casefold(), SCHEDULER_USER_ID.casefold()})


def _parse_owner_ids(raw: str) -> list[str]:
    ids: list[str] = []
    dropped: list[str] = []
    for part in raw.split(","):
        candidate = part.strip()
        if not candidate:
            continue
        if candidate.casefold() in _RESERVED_IDS:
            dropped.append(candidate)
            continue
        ids.append(candidate)
    if dropped:
        log_warning(
            f"OWNER_ID: ignoring reserved identity value(s) {dropped} — these are internal sentinels, not owners."
        )
    return ids


_OWNER_ID_RAW = getenv("OWNER_ID", "")
_OWNER_ID_LIST = _parse_owner_ids(_OWNER_ID_RAW)

# All identities that count as the owner, casefolded for the is_owner()
# check — Slack can deliver the same email with different capitalization and can lock the real owner out to capture-only
# (JWT `sub`s differing only by case are not a realistic collision).
OWNER_IDS: frozenset[str] = frozenset(part.casefold() for part in _OWNER_ID_LIST)
# The canonical owner id — what the inbound queue rows are keyed under. None when no owner is configured
CANONICAL_OWNER_ID: str | None = _OWNER_ID_LIST[0] if _OWNER_ID_LIST else None

# The owner's display name — used in the agent prompt. Not used for identity checks.
OWNER_NAME: str | None = getenv("OWNER_NAME", "").strip() or None


def owner_display_name(default: str = "the owner") -> str:
    """The owner's name for prompts — `OWNER_NAME`, else the canonical id, else `default`."""
    return OWNER_NAME or CANONICAL_OWNER_ID or default


def owner_email() -> str | None:
    """The owner's email, if one was configured — the first `OWNER_ID` entry that looks like one.

    `OWNER_ID` can mix surfaces (JWT `sub`, raw Slack id, email); only an email
    is usable to resolve the owner's Slack DM (`users.lookupByEmail`). Returns
    `None` when no configured identity is an email.
    """
    return next((i for i in _OWNER_ID_LIST if "@" in i), None)


def owner_configured() -> bool:
    """True iff at least one owner identity is configured."""
    return bool(OWNER_IDS)


def is_owner(run_context: RunContext | None) -> bool:
    """True iff this run's verified identity is the owner. Fails closed.

    Derive this fresh per run from `run_context` — never trust a value a prior tool or hook may have written elsewhere.
    The scheduler's verified identity counts as the owner.
    """
    if not OWNER_IDS or run_context is None:
        return False
    user_id = getattr(run_context, "user_id", None)
    if not isinstance(user_id, str):
        return False
    return user_id == SCHEDULER_USER_ID or user_id.casefold() in OWNER_IDS
