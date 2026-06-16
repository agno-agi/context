# Connecting @context to Slack

Slack is where @context comes alive. It's the recommended interface for you, your team, and their agents to talk to @context.

- Teammates — and their agents — can @-mention it to leave you updates;
- You can DM it for private conversations.
- It can DM you for notifications, reminders, and scheduled digests (your daily rundown, your weekly plan).
- It can message on your behalf — post to a channel, DM a teammate, or @-mention another person's @context — through the `update_slack` tool.

The setup below also turns on two things beyond the chat interface: the `update_slack` send tool and the scheduled digests. Both are covered in [What turns on with Slack](#what-turns-on-with-slack).

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

## Moving from local to production

If you first set @context up against a local ngrok URL, your Slack app is still pointed at your local AgentOS — events stop reaching it the moment ngrok closes. To switch the app to your deployed instance, repoint the two request URLs at your AgentOS (Railway) domain:

1. Make sure @context is already deployed and serving in production (see [README#run-in-production](../README.md#run-in-production)).
2. Confirm `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, and your `OWNER_ID` (with your Slack email) are in `.env.production`, then run `./scripts/railway/env-sync.sh` so the deployed instance has them.
3. Go to [api.slack.com/apps](https://api.slack.com/apps) → your app.
4. **Event Subscriptions** → set **Request URL** to `https://<your-railway-domain>/slack/events` and wait for the green **Verified**.
5. **Interactivity & Shortcuts** → set **Request URL** to `https://<your-railway-domain>/slack/interactions`.
6. **Save Changes** on both pages.

The bot token and signing secret don't change — only the URLs. A Slack app has one set of request URLs, so it points at either local or production at a time; to run both side by side, create a second Slack app for local and production with its own token and secret.

## Good to do: give it an app icon

Not required, but recommended: give your @context an icon.

In your Slack app config, go to **Basic Information** → **Display Information** → **App icon & Preview** and click **Add App Icon**. Slack wants a square image at least 512×512 px. A PNG works well.

You can use this prompt as a starting point to generate an icon for your own @context app using ChatGPT.

```text
A glowing, glassy diamond emblem floating at the center of a deep near-black navy background — minimal, modern, and luminous, like a premium app icon. Full-bleed square that fills the frame edge to edge — no border, no frame.

Shape: a single rounded-corner square rotated 45° so it reads as a diamond, centered with generous dark space around it. Smooth, soft-rounded corners; a clean translucent-glass surface with a subtle bevel and a bright highlight running along the upper-left edge.

Light: the diamond glows from within with a smooth gradient — cool cyan and electric blue at the top-left flowing into violet-purple at the bottom-right. A soft bloom of blue-purple light radiates outward into the dark; gentle inner reflections suggest polished glass.

Background: deep midnight navy, almost black, perfectly even — no texture, no other objects — so the glowing diamond is the only focus.

Palette: cyan, electric blue, and violet-purple on near-black navy.

Square 1:1, centered composition, lots of negative space, reads beautifully when Slack masks it to a rounded square.

Avoid: text, letters, logos, watermarks; people; busy or textured backgrounds; harsh HDR; multiple shapes; hard outlines or a visible frame.
```

After generating the icon, upload it to Slack (a square PNG, 512×512 or larger). Slack masks icons to a rounded square, so a full-bleed image — no border of its own — works best.

Continue tweaking the prompt to taste: shift the gradient toward teal-green or magenta, soften or intensify the outer glow, or round the corners more for a softer, pill-like diamond.

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

## What turns on with Slack

Setting `SLACK_BOT_TOKEN` (plus `SLACK_SIGNING_SECRET` for the inbound interface) lights up three things, all from the same bot token:

1. **The chat interface** — @context answers in Slack (DMs and @-mentions), and teammates and their agents reach it there. Identity is resolved per request (see [How it works](#how-it-works)).
2. **`update_slack` — the send tool (owner-only, ungated).** The owner can ask @context to post to a channel, reply in a thread, DM a teammate, or @-mention another person's @context. Sending a Slack message is ordinary communication, so it runs without an approval pause — as does `update_gmail`, which only ever drafts (never sends). The one tool that pauses for approval is `update_calendar` (see [`docs/SECURITY.md`](SECURITY.md) L6). It rides the provider surface, so a *guest* never holds it. The scopes it needs (`chat:write`, `chat:write.public`, `im:write`, `users:read`) are already in the manifest above — no extra setup.
3. **Scheduled digests — delivered to your DM.** With Slack active, two schedules auto-arm: a daily **rundown** and a weekly **week-plan**, each run as the owner and DM'd to you. They're read-only briefs (no act tool fires), and they DM *you* — self-notification, ungated. Tune the timing with `DAILY_DIGEST_CRON` / `WEEKLY_DIGEST_CRON` (UTC cron; defaults are a weekday-morning rundown and a Sunday-evening plan). The reminder sweep already DMs you the same way the moment a reminder comes due.

### The context network

Because `update_slack` can @-mention another person's @context, and that context receives the mention through *its own* Slack interface, your team's @context agents talk to each other with no extra infrastructure. When your @context @-mentions `@dana-context`, Dana's deployment sees *your* verified Slack identity as a **guest**, so the message lands in Dana's queue (capture-only) and can't read Dana's data back. The asymmetry holds across the whole network: anyone — including another agent — can write to a context, but only its owner can read it. See [`docs/NETWORK.md`](NETWORK.md).
