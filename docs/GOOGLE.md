# Connecting Gmail and Google Calendar

Gmail and Calendar make @context more than a notetaker: it can check what's
actually on your calendar, sweep your inbox while prepping you for a meeting —
and, with your explicit approval, send the follow-up email or put the meeting
on the calendar.

Two providers activate when Google credentials are configured:

| Provider | Read | Write (act) |
|---|---|---|
| `gmail` | `query_gmail` — inbox search, threads, unread | `update_gmail` — draft / send / reply |
| `calendar` | `query_calendar` — events, availability | `update_calendar` — create / move / delete events |

**The write tools act as you**, so they're double-gated: owner-only by
construction, and every call pauses the run for your explicit approval before
it executes — the model can't self-approve. Read the act-tool design in
[`docs/SECURITY.md`](SECURITY.md) (L6).

## Pick an auth path

| | OAuth (browser consent) | Service account + delegation |
|---|---|---|
| Account type | personal Gmail or Workspace | **Google Workspace only** (Gmail needs domain-wide delegation) |
| Setup | mint tokens locally once | admin console, fully headless |
| Best for | local / single-machine use | deploys (Railway, your VPC) |

## Path 1: OAuth (personal accounts)

### 1. Create the OAuth client

1. In the [Google Cloud Console](https://console.cloud.google.com), create (or
   pick) a project and enable the **Gmail API** and the **Google Calendar API**.
2. Configure the **OAuth consent screen** (External is fine; add yourself as a
   test user).
3. Create credentials → **OAuth client ID** → application type **Desktop app**.

Add the client to `.env`:

```bash
GOOGLE_CLIENT_ID=***.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=***
GOOGLE_PROJECT_ID=your-project-id
```

### 2. Mint the tokens locally — once

The consent flow opens a browser, so it has to run on your machine, not in the
container. From the repo root, with the venv active (`./scripts/venv_setup.sh`
if you don't have one) and `.env` populated:

```bash
set -a; source .env; set +a

python - <<'PY'
from agno.tools.google.gmail import GmailTools
from agno.tools.google.calendar import GoogleCalendarTools

# Mint with the union of read + write scopes so the read and write
# sub-agents can share one token file per service.
GmailTools(
    token_path="gmail_token.json",
    scopes=[
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.compose",
    ],
).get_latest_emails(1)

GoogleCalendarTools(
    token_path="calendar_token.json",
    scopes=[
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar",
    ],
).list_events(limit=1)
PY
```

Your browser opens twice (once per service); approve both. The tokens land in
`gmail_token.json` and `calendar_token.json` at the repo root — gitignored,
and visible to the dev container through the existing `.:/app` mount. If
either call prints an auth error instead of data, the token didn't mint —
re-run after checking the client credentials.

### 3. Restart

```bash
docker compose up -d
```

Token caveat for production: the OAuth tokens are files. On a baked image
(Railway) they don't survive a redeploy — use the service account path for
deploys, or re-mint and sync when they expire.

## Path 2: Service account (Workspace, headless)

1. In the Cloud Console, enable the **Gmail API** and **Calendar API**, create
   a **service account**, and download its JSON key.
2. In the Workspace **Admin console** → Security → API controls →
   [domain-wide delegation](https://support.google.com/a/answer/162106), add
   the service account's client ID with the scopes listed in the snippet above
   (the three Gmail scopes + the two Calendar scopes).
3. Configure `.env`:

```bash
GOOGLE_SERVICE_ACCOUNT_FILE=google-service-account.json   # gitignored
GOOGLE_DELEGATED_USER=you@yourdomain.com                  # the mailbox/calendar it acts as
```

For platforms without secret-file mounts (Railway), ship the key as base64
instead — the entrypoint materializes it at startup:

```bash
GOOGLE_SERVICE_ACCOUNT_JSON_B64=$(base64 -i google-service-account.json)
GOOGLE_DELEGATED_USER=you@yourdomain.com
```

Then `./scripts/railway/env-sync.sh` (or set both in `.env.production` before
`up.sh`).

## Verify

Ask, as the owner:

```
What's on my calendar today?
Any unread email from Acme this week?
```

Both should answer from `query_calendar` / `query_gmail` and cite what they
found. Then exercise the approval gate:

```
Draft a follow-up email to Sarah at Acme thanking her for today's call.
```

The run pauses with a confirmation request before `update_gmail` executes —
approve it in the chat UI and the draft lands in your Gmail. Decline and
nothing is sent. That pause is the point: read and file are frictionless;
**acting as you requires your sign-off**.

## Scope it down

The providers act with whatever the credentials allow. Scope the delegation
(or the OAuth consent) to exactly the scopes above, for the one account
@context should touch — and nothing else. The residual-risk notes live in
[`docs/SECURITY.md`](SECURITY.md).
