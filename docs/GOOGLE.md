# Connecting @context to Gmail and Google Calendar

## Setup (a few minutes, one time)

### 1. Create the Google app

This is a one-time thing in the [Google Cloud Console](https://console.cloud.google.com). We create an app that says "this program may ask for access to my account". The app belongs to you and lives in your Google project. All credentials are stored with you.

1. Open https://console.cloud.google.com and, using the account switcher at the top right, select the Google account you want to connect to @context.
2. In the project dropdown in the top bar, pick a project — or click **New Project** to make one.
3. **Turn on the two APIs.** Go to **APIs & Services → Library**. Search **Gmail API**, open it, click **Enable**. Go back to the Library and do the same for **Google Calendar API**. Each takes a few seconds; nothing else to fill in.
4. **Set up the consent screen and add the scopes.** Go to **APIs & Services → OAuth consent screen** (newer projects label this **Google Auth Platform**) and work through the prompts — app name, your email for user support, your email for the developer contact. It also asks for a **User type** (Internal vs. External); [section 2 below](#2-increase-login-lifetime) covers which to pick. When you reach the **Scopes** step (called **Data Access** in the newer UI), click **Add or remove scopes**, paste the five lines below into the **Manually add scopes** box, click **Add to table**, then **Update**:
   ```
   https://www.googleapis.com/auth/gmail.readonly
   https://www.googleapis.com/auth/gmail.modify
   https://www.googleapis.com/auth/gmail.compose
   https://www.googleapis.com/auth/calendar.readonly
   https://www.googleapis.com/auth/calendar
   ```
   You have to paste them — Gmail and Calendar are *sensitive* scopes, so they don't show up in the checklist of suggestions; the manual box is the only way to add them.
5. **Create the credentials.** Go to **APIs & Services → Credentials → Create credentials → OAuth client ID**, choose application type **Desktop app**, and create it. Keep the **client ID** and **client secret** it shows you — they go in `.env` in step 3 below.

### 2. Increase login lifetime

Out of the box, Google puts a new app in **"Testing,"** and in that mode the login it issues **expires after 7 days** — so @context would lose access every week. Flip one setting so it sticks:

- **If your account is Google Workspace** (e.g. a company domain): set the consent screen's **User type** to **Internal**. Internal apps don't expire and need no review. Done.
- **If it's a personal `@gmail.com`:** set the consent screen's **Publishing status** to **In production**. The login stops expiring. Because the Gmail scopes are sensitive, you'll click past an "unverified app" notice the first time you connect — that's expected for your own app and fine; Google's formal verification only matters if you hand the app to lots of other people.

### 3. Add the credentials to `.env`

```bash
# Google OAuth
GOOGLE_CLIENT_ID=***.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=***

# Token encryption (required) — generate with:
#   python scripts/google_mint_tokens.py --generate-key
GOOGLE_TOKEN_ENCRYPTION_KEY=***
```

### 4. Connect your account

The OAuth consent screen opens a browser, so this step runs on your machine (not in the container). From the repo root, with the venv active (`./scripts/venv_setup.sh` if you don't have one):

```bash
python scripts/google_mint_tokens.py
```

It opens a browser to connect Gmail + Calendar. Approve both, and the encrypted token is saved to PostgreSQL.

Pass `--force` to re-connect from scratch or to switch accounts.

### 5. Restart

```bash
docker compose up -d
```

## Deploying

Tokens are encrypted and stored in PostgreSQL, so they persist across deploys automatically. No base64 env vars or file mounts needed.

Just ensure your production database has the token (run the mint script once pointing at your prod DB), and the same `GOOGLE_TOKEN_ENCRYPTION_KEY` is set in production.

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

1. In [`agents/providers/google.py`](../agents/providers/google.py), in `create_gmail_provider`,
   stop stripping the send tools (the `_DraftOnlyGmail` subclass) — or use
   `GmailContextProvider` directly.
2. Add `update_gmail` to `ACT_TOOLS` in [`agents/sources.py`](../agents/sources.py), so every send **pauses
   for your approval** the same way calendar changes do — never ship sending
   ungated.

Then it'll draft unless you say "send," and a send waits for your okay in the
approvals queue.

## Troubleshooting

- **Neither provider showed up after restart.** A provider only builds when its
  credentials are set; a misconfig is logged and skipped (the app still starts).
  Check the startup logs for a `_create_gmail_provider failed` /
  `_create_calendar_provider failed` warning, and confirm `.env` has
  `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_TOKEN_ENCRYPTION_KEY`.
- **Access stopped working after about a week.** The app is still in "Testing" —
  do step 2 (Internal for Workspace, or Publish for personal), then re-run
  `python scripts/google_mint_tokens.py --force`.
- **`access_blocked` / "app isn't verified" during connect.** On a personal
  account, add your address as a **test user** on the consent screen, or finish
  publishing it (step 2). Clicking past the unverified notice is expected for
  your own app.
- **A token got revoked.** Re-run the mint script with `--force`.

## Scope it down

@context acts with whatever the token allows. Keep the consent to exactly the
five scopes above, for the one account it should touch — nothing else. The
residual-risk notes live in [`docs/SECURITY.md`](SECURITY.md).
