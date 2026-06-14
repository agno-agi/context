"""
Owner Notifications
===================

A single outbound channel for proactively nudging the **owner** on Slack — the
reminder sweep and the scheduled digests both reach the owner through here.

This is a self-notification path: it DMs the owner their own follow-ups and
briefs. That is why it is ungated and deterministic (no model, no approval) — you
are messaging yourself, not acting on the outside world. It is distinct from the
`update_slack` *tool*, which the agent uses to message other people and channels.

No-op (returns False) unless Slack DMs are actually available: `SLACK_BOT_TOKEN`
(the bot token that sends) and an owner email (an `OWNER_ID` entry that looks like
one, used to resolve the IM via `users.lookupByEmail`). `SLACK_SIGNING_SECRET`
only verifies *inbound* Slack requests, so it plays no part here — sending needs
just the token, with the `users:read.email`, `im:write`, `chat:write` scopes.
"""

from os import getenv

from agno.utils.log import log_warning

from app.identity import owner_email


def slack_dm_target() -> tuple[str, str] | None:
    """The (bot token, owner email) an owner DM needs — or `None` when unavailable."""
    token = getenv("SLACK_BOT_TOKEN")
    email = owner_email()
    if token and email:
        return token, email
    return None


def dm_owner(text: str) -> bool:
    """Best-effort: DM the owner `text` on Slack. Returns whether it was sent.

    Every failure is logged and swallowed — callers treat the DM as a nudge layered
    on top of a durable source of truth (the inbound queue), never as the delivery
    guarantee itself. No-op when Slack DMs aren't configured (see module docstring).
    """
    target = slack_dm_target()
    if target is None:
        return False
    token, email = target
    try:
        from slack_sdk import WebClient

        client = WebClient(token=token)
        user_id = client.users_lookupByEmail(email=email)["user"]["id"]
        channel = client.conversations_open(users=[user_id])["channel"]["id"]
        client.chat_postMessage(channel=channel, text=text)
        return True
    except Exception as exc:
        log_warning(f"dm_owner: could not DM the owner on Slack: {exc}")
        return False
