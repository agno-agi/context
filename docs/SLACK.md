# Connecting @context to Slack

Slack is where @context becomes *addressable*. Teammates — and their agents —
@-mention it to leave you updates; you DM it for the full surface: capture,
retrieval, the rundown. Same bot, two very different callers, and Slack's
verified identity is what decides which one it's talking to (see
[`docs/SECURITY.md`](SECURITY.md)).

## Prerequisites

- @context running locally or deployed (see the [README](../README.md))
- A Slack workspace where you can install apps
- [ngrok](https://ngrok.com) for local development only

## Step 1: Get your URL

Slack needs a public URL that reaches your AgentOS.

**Local development** — expose the API with ngrok and copy the `https://` URL:

```bash
ngrok http 8000
```

**Production** — use your deployed domain (e.g. the Railway domain `up.sh`
printed).

## Step 2: Create the Slack app

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. **Create New App** → **From an app manifest** → pick your workspace
3. Choose **JSON** and paste the manifest below — replace `https://your-url`
   with the URL from Step 1
4. **Create**

```json
{
    "display_information": {
        "name": "Context",
        "description": "A professional alter-ego — anyone can leave updates, only the owner can read them.",
        "background_color": "#000000"
    },
    "features": {
        "app_home": {
            "home_tab_enabled": false,
            "messages_tab_enabled": true,
            "messages_tab_read_only_enabled": false
        },
        "bot_user": {
            "display_name": "Context",
            "always_online": true
        }
    },
    "oauth_config": {
        "scopes": {
            "bot": [
                "app_mentions:read",
                "assistant:write",
                "channels:history",
                "channels:read",
                "chat:write",
                "chat:write.customize",
                "chat:write.public",
                "files:read",
                "files:write",
                "groups:history",
                "groups:read",
                "im:history",
                "im:read",
                "im:write",
                "mpim:read",
                "search:read.public",
                "search:read.files",
                "search:read.users",
                "users:read",
                "users:read.email"
            ]
        }
    },
    "settings": {
        "event_subscriptions": {
            "request_url": "https://your-url/slack/events",
            "bot_events": [
                "app_mention",
                "message.channels",
                "message.groups",
                "message.im"
            ]
        },
        "org_deploy_enabled": false,
        "socket_mode_enabled": false,
        "is_hosted": false,
        "token_rotation_enabled": false
    }
}
```

`users:read.email` matters: it's how the interface resolves the verified Slack
identity to an email, which is what `OWNER_ID` matches against.

## Step 3: Install to the workspace

1. **Install App** in the sidebar → **Install to Workspace** → **Allow**
2. Copy the **Bot User OAuth Token** (`xoxb-***`)

## Step 4: Set environment variables

```bash
# .env (or .env.production + ./scripts/railway/env-sync.sh)
SLACK_BOT_TOKEN="xoxb-***"
SLACK_SIGNING_SECRET="***"        # Basic Information → App Credentials

# Make sure OWNER_ID includes your Slack email — that's how Slack-you
# resolves to owner-you.
OWNER_ID=you@example.com
```

Restart:

```bash
docker compose up -d
```

Setting `SLACK_BOT_TOKEN` also activates the `slack` context provider
(`query_slack` — channel/DM history) on the agent; the interface itself needs
both variables.

## Verify — both sides of the boundary

**As you** (DM the bot, or @-mention it):

```
@Context give me the rundown
```

Full surface: it reads your queue, your CRM, your wiki.

**As a teammate** (any other workspace member):

```
@Context — fixed the auth bug, deploying tomorrow
```

It files the update in your queue and confirms — and that's all it can do. No
readback, no questions answered about you: a guest session holds exactly
one context tool. The update surfaces in your next rundown, attributed to
their verified identity (it never trusts a claimed name).

## How it works

The wiring lives in [`app/main.py`](../app/main.py):

```python
from agno.os.interfaces.slack import Slack

Slack(
    agent=context,
    streaming=True,
    token=SLACK_BOT_TOKEN,
    signing_secret=SLACK_SIGNING_SECRET,
    resolve_user_identity=True,
)
```

Slack requests are HMAC-verified against the signing secret, and the message
author comes from the event envelope — not the message text — so identity
can't be forged by what someone types. `resolve_user_identity=True` maps the
author to their email, and `is_owner` compares that against `OWNER_ID`. Each
thread is its own session, so follow-ups carry context without re-mentioning.

The same door works for other interfaces — mirror the conditional in
`app/main.py` with Agno's [Discord / Telegram / WhatsApp
interfaces](https://docs.agno.com/agent-os/interfaces/overview).
