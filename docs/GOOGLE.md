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
| Setup | `python scripts/google_mint_tokens.py` | `./scripts/google_setup.sh` |
| Runs headless after setup | no (re-mint on expiry) | yes |
| Best for | local / single-machine use | deploys (Railway, your VPC) |

Either way you only ever grant the five scopes @context uses (three Gmail, two
Calendar) — and only for the one account it should touch.

## Path 1: OAuth (personal accounts)

### 1. Create the OAuth client

The OAuth client itself can't be scripted (it's a Console-only flow), so this
part is manual — once:

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

### 2. Mint the tokens — once

The consent flow opens a browser, so it runs on your machine, not in the
container. From the repo root, with the venv active (`./scripts/venv_setup.sh`
if you don't have one):

```bash
python scripts/google_mint_tokens.py
```

It loads `.env`, mints Gmail and Calendar tokens with exactly the scopes the
providers use, and writes them to `gmail_token.json` / `calendar_token.json` at
the repo root (gitignored, and visible to the dev container through the existing
`.:/app` mount). Your browser opens twice — approve both. Override the
destinations with `GMAIL_TOKEN_FILE` / `CALENDAR_TOKEN_FILE` if you want them
elsewhere.

### 3. Restart

```bash
docker compose up -d
```

## Path 2: Service account (Workspace, headless)

### 1. Provision the service account

```bash
./scripts/google_setup.sh
```

This creates a GCP project, enables the Gmail + Calendar APIs, creates a service
account, downloads its JSON key to `google-service-account.json` (gitignored),
and — if an org policy blocks key creation — auto-applies a project-scoped
override. It's idempotent: rerun it any time. When it finishes it prints the two
things the next step needs: the service account's **Client ID** and the exact
**scopes**.

(No `gcloud`, or your org locks it down? Do the same by hand in the Console:
enable both APIs, create a service account, download its JSON key. The rest is
identical.)

### 2. Grant domain-wide delegation — the one manual step

A service account can't read *your* mailbox until your Workspace lets it
impersonate you. That grant lives in the **Admin console**, not GCP, so no
script can do it. In [admin.google.com](https://admin.google.com) → Security →
Access and data control → API controls →
[Manage Domain Wide Delegation](https://support.google.com/a/answer/162106) →
**Add new**, paste the **Client ID** the script printed and these scopes:

```
https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/gmail.compose,https://www.googleapis.com/auth/calendar.readonly,https://www.googleapis.com/auth/calendar
```

> Use the service account's **numeric OAuth2 client ID** (the script prints and
> copies it), not its email address. Delegation can take a few minutes to
> propagate.

### 3. Point @context at the key and restart

```bash
GOOGLE_SERVICE_ACCOUNT_FILE=google-service-account.json   # gitignored
GOOGLE_DELEGATED_USER=you@yourdomain.com                  # the mailbox/calendar it acts as
```

```bash
docker compose up -d
```

## Deploying: make the credentials survive a redeploy

On a baked image (Railway) there's no file mount, so credentials shipped as
files vanish on redeploy. Ship them as base64 instead — the
[entrypoint](../scripts/entrypoint.sh) decodes each one back to a file at
startup.

**Service account** (recommended for deploys — the key never rotates):

```bash
GOOGLE_SERVICE_ACCOUNT_JSON_B64=$(base64 < google-service-account.json)
GOOGLE_DELEGATED_USER=you@yourdomain.com
```

**OAuth tokens** (if you must deploy the personal-account path):

```bash
GMAIL_TOKEN_JSON_B64=$(base64 < gmail_token.json)
CALENDAR_TOKEN_JSON_B64=$(base64 < calendar_token.json)
```

Add them to `.env.production` and run `./scripts/railway/env-sync.sh` (or set
them before `up.sh`). The minted token carries a long-lived refresh token, so
the restored copy keeps working across redeploys — re-mint and re-sync only if
the tokens are ever revoked.

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

## Troubleshooting

- **Neither provider showed up after restart.** A provider factory only builds
  when its auth path is configured; a misconfig is logged and skipped (the app
  still starts). Check the startup logs for a `_create_gmail_provider failed` /
  `_create_calendar_provider failed` warning, and confirm `.env` has either
  `GOOGLE_SERVICE_ACCOUNT_FILE` or `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET`.
- **`delegated_user is required for Gmail service account authentication`.** The
  service-account path needs `GOOGLE_DELEGATED_USER` (the mailbox to act as).
- **`unauthorized_client` / 403 on the service-account path.** Delegation isn't
  in effect: you pasted the SA *email* instead of its numeric client ID, the
  scopes don't match the five above, or the grant hasn't propagated yet (wait a
  few minutes). Personal Gmail accounts *can't* do domain-wide delegation at all
  — use the OAuth path.
- **`access_blocked` / "app isn't verified" during OAuth.** Add your address as
  a **test user** on the consent screen (External apps in testing only admit
  listed testers).
- **OAuth stopped working after a while.** While the consent screen is in
  *testing*, Google expires refresh tokens after 7 days — re-run
  `python scripts/google_mint_tokens.py`, or publish the app to make them
  durable. If a token is revoked, re-mint (and on Railway, re-sync the base64).

## Scope it down

The providers act with whatever the credentials allow. Scope the delegation
(or the OAuth consent) to exactly the five scopes above, for the one account
@context should touch — and nothing else. The residual-risk notes live in
[`docs/SECURITY.md`](SECURITY.md).
