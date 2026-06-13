---
name: prep-for
description: Brief the owner before a meeting or conversation with a person, company, or project — sweep what we already know (crm + knowledge, plus slack, calendar, and gmail when connected), anchor to any upcoming meeting with them, and for people or orgs we don't know, widen to a web search for public background. Use for "prep me for my meeting with X", "brief me on X before the call", "what do we know about X".
metadata:
  version: "1.1.0"
  author: context
  tags: ["prep", "meeting", "briefing", "crm", "knowledge", "slack", "web"]
---
# Prep For

Pull together a tight pre-meeting brief on a **subject** — a person, company, or
project the owner is about to engage. Read-only: gather and synthesize, never
file.

## Procedure

1. **Identify the subject.** Pin down who/what from the request ("my 3pm with
   Sarah Lee from Acme" → person *Sarah Lee*, org *Acme*). If it's genuinely
   ambiguous and a wrong guess would waste the brief, ask one clarifying
   question instead of guessing.
2. **Sweep what we already know — internal first.** Run an entity sweep:
   - `query_crm` — contacts, notes, projects, and any reminders/meetings tagged
     to the subject (name, company, tags, meeting attendees). This is our
     relationship + history.
   - `query_knowledge` — wiki prose about the subject (runbooks, summaries,
     "what I know about X").
   - `query_slack` (when connected) — recent threads mentioning the subject;
     the latest exchanges are often the freshest context in the brief.
3. **Anchor to the meeting.** Surface the specific upcoming meeting/reminder with
   the subject if there is one — the brief should serve *that* interaction. When
   the `calendar` source is connected, check `query_calendar` for the real
   event (time, attendees); when `gmail` is connected and there's an email
   thread with the subject, pull the latest exchange with `query_gmail` — the
   most recent thing they said is often the most useful line in the brief.
4. **Widen to the web only for people/orgs we don't know.** If the internal
   sweep turns up little or nothing on an **external** person or company (no
   contact on file, just a name), call `query_web` for public background — role,
   current company, recent news. Skip the web when we already have a solid
   internal picture, and for internal/private topics. Don't pad a brief with
   generic results, and keep the web query to public identity terms (name +
   company), not the owner's private notes about them.

## Format

A short brief — only the sections that have content:

- **Who** — one line on the subject (role, company), tagged `(on file)` or
  `(from web)` so the owner knows the source.
- **Our history** — relationship, past touchpoints, what's open with them (from
  `crm` / `knowledge` / `slack`).
- **This meeting** — the anchoring meeting and the open items to raise.
- **Background** — public context, *only* when pulled from the web; mark it
  external / unverified.

## Edge cases

- **Total blank** (nothing internal, nothing useful on the web): say so plainly
  and ask what context to add — don't fabricate a profile.
- Attribute every line to its source (`crm`, `knowledge`, `slack`, or `web`).
  Keep on-file facts and web background visibly separate; never blend an
  unverified web claim into our known record.
