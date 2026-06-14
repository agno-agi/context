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

**Local development**: expose the AgentOS API to the public internet using `ngrok`. [Install `ngrok`](https://ngrok.com/download) and run the following command to get a public URL. Copy the `https://` URL.

```bash
ngrok http 8000
```

## Step 2: Create the Slack app

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. **Create New App** → **From an app manifest** → pick your workspace
3. Choose **JSON** and paste the manifest below — replace `https://your-url` with the URL from Step 1
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

Three parts of this manifest are load-bearing — keep them even if you trim
scopes:

- **`features.assistant_view`** turns on Slack's "Agents & AI Apps" experience.
  `app/main.py` runs the interface with `streaming=True`, which streams the
  reply token-by-token with task cards through that assistant UI. Without this
  block the bot still works, but callers stare at a spinner until the whole
  answer lands.
- **`settings.interactivity`** points Slack at `/slack/interactions`. That's the
  return path for @context's **act-tool approvals** — when you ask it to send
  mail or write to the calendar, the run pauses and posts Approve / Reject
  buttons, and the click comes back here. Drop this block and the buttons render
  but do nothing (see [`docs/SECURITY.md`](SECURITY.md) → act tools).
- **`bot_events`** are the three @context acts on: `app_mention` (a teammate
  @-mentions it in a channel), `message.im` (you DM it), and
  `assistant_thread_started` (opening the assistant thread, so the suggested
  prompts appear). It deliberately omits `message.channels` / `message.groups`:
  with the default `reply_to_mentions_only=True`, @context only answers
  @-mentions in channels, so those events would just be received and dropped.

`users:read.email` is the linchpin of the security model: it's how the
interface resolves the verified Slack identity to an email, which is what
`OWNER_ID` matches against. The `channels:history` / `groups:history` /
`search:read.*` scopes aren't for the interface — they power the `slack`
**context provider** (`query_slack`), so you can ask @context to read and
search channel history.

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
OWNER_ID=owner@example.com
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
    suggested_prompts=[...],  # starter chips in the assistant pane
)
```

A few things this wiring leans on:

- **Identity can't be forged by message text.** Slack requests are
  HMAC-verified against the signing secret (with a 5-minute timestamp window to
  block replays), and the author comes from the event envelope — not the body.
  `resolve_user_identity=True` maps that author to their email via
  `users:read.email`, and `is_owner` compares it to `OWNER_ID`.
- **Email resolution fails closed.** If the email can't be resolved — scope
  missing, or the profile has none — the interface falls back to the raw Slack
  user ID, which won't match `OWNER_ID`. So a misconfigured owner silently drops
  to the *guest* surface; it never accidentally promotes a guest.
- **When it replies.** With the default `reply_to_mentions_only=True`, @context
  answers every message in a DM but only @-mentions in a channel — so in a
  channel a teammate @-mentions it each turn, while a DM thread flows without
  re-mentioning.
- **One session per thread.** The session id is `context:<thread_ts>`, so each
  thread carries its own history; a new top-level message starts a fresh one.

The same door works for other interfaces — mirror the conditional in
`app/main.py` with Agno's [Discord / Telegram / WhatsApp
interfaces](https://docs.agno.com/agent-os/interfaces/overview).

## Troubleshooting

- **It treats you as a guest (capture-only).** Your Slack profile email doesn't
  match `OWNER_ID`, or `users:read.email` isn't granted. Confirm the email on
  your Slack profile is in `OWNER_ID`, reinstall the app if you just added the
  scope, and restart.
- **No streaming — a spinner, then the whole answer at once.** The "Agents & AI
  Apps" experience isn't on. The manifest's `features.assistant_view` block
  enables it; on an existing app, toggle it under **App Home → Agents & AI
  Apps**.
- **Approve / Reject buttons do nothing.** Interactivity isn't wired. Set
  **Interactivity & Shortcuts → Request URL** to
  `https://your-url/slack/interactions` (the manifest's `settings.interactivity`
  block does this).
- **403 on events.** Wrong `SLACK_SIGNING_SECRET`, or the request timestamp is
  stale (Slack rejects anything older than 5 minutes). On ngrok, restart it to
  clear a stale tunnel.
- **The bot never responds.** Check the **Request URL** resolves to
  `https://your-url/slack/events`, and that `app_mention` + `message.im` are
  subscribed.
