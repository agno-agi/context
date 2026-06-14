# Connecting @context to Slack

Slack is where @context comes alive. It's the recommended interface for you, your team, and their agents to talk to @context.

- Teammates — and their agents — can @-mention it to leave you updates;
- You can DM it for private conversations.
- It can DM you for notifications and reminders.

## Prerequisites

- @context running locally or in production (see [README#run-in-production](../README.md#run-in-production))
- A Slack workspace where you can install @context
- [ngrok](https://ngrok.com/download) installed and running if you are running @context locally [not needed for production]

## Step 1: Get the URL to reach @context

For Slack to reach @context, it needs a public URL to send events to.

**Production**: use your AgentOS domain (e.g. the Railway domain).

**Local**: expose the AgentOS API to the public internet using `ngrok`. [Install `ngrok`](https://ngrok.com/download) and run the following command to get a public URL. Copy the `https://` URL.

```bash
ngrok http 8000
```

## Step 2: Create the Slack app

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. **Create New App** → **From an app manifest** → pick your workspace
3. Choose **JSON** and replace the following values in the manifest below:
    - `display_information.name` with the name of your @context app, Eg: `Bob's Context`
    - `display_information.description` with the description of your @context app, Eg: `Bob's work proxy.`
    - `bot_user.display_name` with the name of your @context app, Eg: `Bob's Context`
    - `assistant_view.assistant_description` with the description of your @context app, Eg: `Bob's work proxy.`
    - `event_subscriptions.request_url` with `https://<your-url>/slack/events` (from Step 1)
    - `interactivity.request_url` with `https://<your-url>/slack/interactions` (from Step 1)
4. Paste the manifest.
5. **Next** → **Create**

```json
{
    "display_information": {
        "name": "Context",
        "description": "A professional alter-ego.",
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
        },
        "assistant_view": {
            "assistant_description": "Capture, file, and retrieve your working context.",
            "suggested_prompts": []
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
                "assistant_thread_started",
                "message.im"
            ]
        },
        "interactivity": {
            "is_enabled": true,
            "request_url": "https://your-url/slack/interactions"
        },
        "org_deploy_enabled": false,
        "socket_mode_enabled": false,
        "is_hosted": false,
        "token_rotation_enabled": false
    }
}
```

## Step 3: Install to the workspace

1. Go to **Install App** in the sidebar.
2. Click **Install to Workspace** and then **Allow**.
3. Copy the **Bot User OAuth Token** (`xoxb-***`). This is the token you will use to set the `SLACK_BOT_TOKEN` environment variable.

## Step 4: Set environment variables

Set `SLACK_BOT_TOKEN` using the token you copied in Step 3. Then go to **Basic Information** and copy the **Signing Secret**. This is the `SLACK_SIGNING_SECRET`.

```bash
# .env (or .env.production)
SLACK_BOT_TOKEN=xoxb-***
SLACK_SIGNING_SECRET=***        # Basic Information → App Credentials

# Make sure OWNER_ID includes your Slack email — that's how Slack-you
# resolves to owner-you.
OWNER_ID=owner@example.com
```

## Step 5: Restart the application

**Local**:

```bash
docker compose up -d --build
```

**Production**:

```bash
./scripts/railway/env-sync.sh
```

## Step 6: Verify the setup

DM the bot — no @-mention needed in a DM:

```
how are you?
```

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
    suggested_prompts=[...],  # starter chips in the assistant pane
)
```

A few things to note:

- **Identity can't be forged by message text.** Slack requests are HMAC-verified against the signing secret (with a 5-minute timestamp window to block replays), and the author comes from the event envelope. `resolve_user_identity=True` maps that author to their email via `users:read.email`, and `is_owner` compares it to `OWNER_ID`.
- **Email resolution fails closed.** If the email can't be resolved — scope is missing, or the profile has none — the interface falls back to the raw Slack user ID, which won't match `OWNER_ID`. So a misconfigured owner silently drops to the *guest* surface; it never accidentally promotes a guest.
- **When it replies.** With the default `reply_to_mentions_only=True`, @context answers every message in a DM but only @-mentions in a channel — so in a channel a teammate @-mentions it each turn, while a DM thread flows without re-mentioning.
- **One session per thread.** The session id is `context:<thread_ts>`, so each thread carries its own history; a new top-level message starts a fresh one.
