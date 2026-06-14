# Connecting Gmail and Google Calendar

Connect your Google account and @context can see what's actually on your
calendar and in your inbox while it preps you — and it can write the follow-up
email and put events on your calendar. Two providers switch on once credentials
are set:

| Provider | Read | Write |
|---|---|---|
| `gmail` | `query_gmail` — inbox search, threads, unread | `update_gmail` — writes a **draft** (never sends) |
| `calendar` | `query_calendar` — events, availability | `update_calendar` — create / move / delete events |

**The one thing to know about writes:**

- **Email only ever drafts.** `update_gmail` writes the email into your Gmail
  **Drafts** — fully formed, for you to skim, edit, and send. @context can't
  send; you do, from Gmail. So you keep the pen (fix the wording, drop the em
  dashes) and nothing leaves without you.
- **Calendar asks first.** `update_calendar` changes the real calendar, so each
  change pauses for your okay — it lands in your **approvals queue** (the
  approvals page in the AgentOS UI) and only runs once you confirm.

(If you'd rather @context send email for you, see
[Letting @context send](#letting-context-send-email) at the end.)

## Setup (a few minutes, one time)

This uses your own Google account — personal `@gmail.com` or Workspace, either
works.

### 1. Create the Google app

This is a one-time thing in the [Google Cloud Console](https://console.cloud.google.com).
"The app" here is just an entry you register with Google that says "this program
may ask for access to my account" — it's yours, it lives in your Google project,
and it's what the credentials below come from.

1. Create (or pick) a project.
2. Enable the **Gmail API** and the **Google Calendar API**.
3. Configure the **OAuth consent screen** and add these five scopes — exactly
   the ones @context uses, nothing more:
   ```
   https://www.googleapis.com/auth/gmail.readonly
   https://www.googleapis.com/auth/gmail.modify
   https://www.googleapis.com/auth/gmail.compose
   https://www.googleapis.com/auth/calendar.readonly
   https://www.googleapis.com/auth/calendar
   ```
4. Create credentials → **OAuth client ID** → application type **Desktop app**.

### 2. Make the connection last (do this — it's the fix for weekly re-logins)

Out of the box, Google puts a new app in **"Testing,"** and in that mode the
login it issues **expires after 7 days** — so @context would lose access every
week. Flip one setting so it sticks:

- **If your account is Google Workspace** (e.g. a company domain): set the
  consent screen's **User type** to **Internal**. Internal apps don't expire and
  need no review. Done.
- **If it's a personal `@gmail.com`:** set the consent screen's **Publishing
  status** to **In production**. The login stops expiring. Because the Gmail
  scopes are sensitive, you'll click past an "unverified app" notice the first
  time you connect — that's expected for your own app and fine; Google's formal
  verification only matters if you hand the app to lots of other people.

### 3. Add the credentials to `.env`

```bash
GOOGLE_CLIENT_ID=***.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=***
GOOGLE_PROJECT_ID=your-project-id
```

### 4. Connect your account — once

The consent screen opens a browser, so this runs on your machine, not in the
container. From the repo root, with the venv active (`./scripts/venv_setup.sh`
if you don't have one):

```bash
python scripts/google_mint_tokens.py
```

It reads `.env`, opens your browser twice (Gmail, then Calendar — approve both),
and writes `gmail_token.json` / `calendar_token.json` at the repo root. Those
files are gitignored and never leave your machine; the dev container picks them
up through the existing `.:/app` mount. (Override where they're written with
`GMAIL_TOKEN_FILE` / `CALENDAR_TOKEN_FILE`.)

### 5. Restart

```bash
docker compose up -d
```

## Deploying (Railway)

The token never goes into the image — it's gitignored and `.dockerignore`'d, so
it can't be baked in. Instead you hand it to the deploy as an env var, and the
[entrypoint](../scripts/entrypoint.sh) writes it back to a file at startup.
Base64 the two token files and sync them:

```bash
echo "GMAIL_TOKEN_JSON_B64=$(base64 < gmail_token.json)" >> .env.production
echo "CALENDAR_TOKEN_JSON_B64=$(base64 < calendar_token.json)" >> .env.production
./scripts/railway/env-sync.sh
```

That's it — on boot each instance decodes the var back to a token file. As long
as you did step 2, the login doesn't expire, so this is set-and-forget; re-run
the mint + sync only if you ever revoke access. @context ships on a single
replica; if you scale up, the same token rides every replica fine — details in
[`docs/SCALING.md`](SCALING.md).

## Verify

Ask, as the owner:

```
What's on my calendar today?
Any unread email from Acme this week?
```

Both should answer from `query_calendar` / `query_gmail` and cite what they
found. Then try a write:

```
Draft a follow-up to Sarah at Acme thanking her for today's call.
```

A draft appears in your Gmail for you to send. Ask it to put something on your
calendar and you'll get an approval request in the AgentOS UI first — confirm
and it's booked, decline and nothing happens.

## Letting @context send email

Off by default on purpose — drafting keeps you in control and means nothing goes
out unread. If you do want @context to send directly:

1. In [`agents/sources.py`](../agents/sources.py), in `_create_gmail_provider`,
   stop stripping the send tools (the `_DraftOnlyGmail` subclass) — or use
   `GmailContextProvider` directly.
2. Add `update_gmail` to `ACT_TOOLS` in the same file, so every send **pauses
   for your approval** the same way calendar changes do — never ship sending
   ungated.

Then it'll draft unless you say "send," and a send waits for your okay in the
approvals queue.

## Troubleshooting

- **Neither provider showed up after restart.** A provider only builds when its
  credentials are set; a misconfig is logged and skipped (the app still starts).
  Check the startup logs for a `_create_gmail_provider failed` /
  `_create_calendar_provider failed` warning, and confirm `.env` has
  `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET`.
- **Access stopped working after about a week.** The app is still in "Testing" —
  do step 2 (Internal for Workspace, or Publish for personal), then re-run
  `python scripts/google_mint_tokens.py` (and on Railway, re-sync the base64).
- **`access_blocked` / "app isn't verified" during connect.** On a personal
  account, add your address as a **test user** on the consent screen, or finish
  publishing it (step 2). Clicking past the unverified notice is expected for
  your own app.
- **A token got revoked.** Re-run the mint script (and re-sync the base64 on
  Railway).

## Scope it down

@context acts with whatever the token allows. Keep the consent to exactly the
five scopes above, for the one account it should touch — nothing else. The
residual-risk notes live in [`docs/SECURITY.md`](SECURITY.md).
