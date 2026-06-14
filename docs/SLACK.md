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

## Good to do: give it an app icon

Not required, but recommended: give your @context an icon.

In your Slack app config, go to **Basic Information** → **Display Information** → **App icon & Preview** and click **Add App Icon**. Slack wants a square image at least 512×512 px. A PNG works well.

You can use this prompt as a starting point to generate an icon for your own @context app using ChatGPT.

```text
A painterly, semi-realistic matte painting of an imagined city skyline at sunrise — warm, magical, and cinematic, in the style of a high-end animated-film background (Studio Ghibli / Disney concept art). Full-bleed square that fills the frame edge to edge — no border, no frame.

Sky: a soft dawn of peach, rose, and pale lavender with gently painted clouds; the sun sits low on the horizon, washing warm golden light across the city.

City: a cluster of elegant towers — art-deco crowns and ornate spires in warm cream and tan stone, their windows catching the gold of sunrise; one or two rooftops capped in jewel teal-blue as accents. A calm river winds through the middle, holding a shimmering golden reflection of the sun.

Foreground framing: a graceful tree branch with green leaves arcs across an upper corner; soft pink blossoms cascade down one side; lush green park trees and a few slender cypress line the bottom, tiny warm lamp-lights glowing among them. Gentle depth of field — crisp leaves up front, soft painterly city behind.

Palette: warm gold and amber light, peach-and-rose sky, soft blossom pink, cream stone, deep park green, a single teal-blue accent.

Square 1:1, balanced composition, rich depth, reads beautifully when Slack masks it to a rounded square.

Avoid: any real or recognizable city or landmark; text, letters, logos, watermarks; people in the foreground; harsh HDR; night; clutter.
```

After generating the icon, upload it to Slack (a square PNG, 512×512 or larger). Slack masks icons to a rounded square, so a full-bleed image — no border of its own — works best.

Continue tweaking the prompt to taste: swap sunrise for blue-hour dusk, the blossoms for autumn maples, or the river for a harbor.

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
