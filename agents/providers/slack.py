"""
Slack Context Provider
======================

Slack read + write. `query_slack` reads channels/DMs; `update_slack` posts.
"""

from os import getenv

from agno.context.slack import SlackContextProvider

from agents.instructions import SLACK_READ
from app.settings import default_model


def create_slack_provider() -> SlackContextProvider | None:
    """Slack — read + write.

    Note: `search.messages` needs a *user* token (`xoxp-`, scope `search:read`); a bot
    token returns `not_allowed_token_type`. Agno hard-codes `enable_search_messages=True`
    with no user-token slot, so search errors out and the read falls back to
    channel/thread history. Pass a user token here to restore it.
    """
    if not getenv("SLACK_BOT_TOKEN"):
        return None
    return SlackContextProvider(
        model=default_model(),
        read=True,
        write=True,
        read_instructions=SLACK_READ,
        stream_sub_agent_events=False,
    )
