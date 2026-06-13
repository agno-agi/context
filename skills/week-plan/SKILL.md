---
name: week-plan
description: Produce the owner's week-ahead plan — scheduled meetings and due-or-overdue reminders for the next 7 days, grouped by day, read from the CRM and enriched from the real calendar, Slack, and knowledge-base briefs when connected. Use for "what's my week", "plan the week ahead", "what's coming up".
metadata:
  version: "1.1.0"
  author: context
  tags: ["planning", "weekly", "crm", "slack", "knowledge"]
---
# Week Plan

Assemble a clear plan for the **next 7 days** from the structured `crm`
store, enriched from the connected sources. This is a read-only retrieval
workflow: it pulls, merges, and formats — it never writes anything.

## Procedure

1. **Anchor on now.** Use the current datetime already in your context. The
   window is `now` → `now + 7 days`.
2. **Pull the two time-bearing tables with `query_crm`** (one retrieval —
   ask it for both):
   - **Meetings** whose `starts_at` falls between now and now + 7 days.
   - **Reminders** with `status = 'pending'` and `due_at` ≤ now + 7 days.
     Include anything already **overdue** (`due_at < now`, still pending) — a
     plan that hides what's late isn't useful.
3. **If the `calendar` source is connected, pull the real calendar too** —
   `query_calendar` for events in the same 7-day window — and merge with the
   CRM meetings (dedupe by title + start time; the calendar wins on times).
4. **Enrich from connected sources.** When the `slack` source is connected,
   `query_slack` for recent threads that touch this week's meetings,
   attendees, or active projects — surface commitments and deadlines that
   never made it into the CRM as plan items, flagged `(from slack)`. When a
   meeting or reminder ties to a project with a brief in the knowledge base,
   pull its status from `query_knowledge` so the plan reflects where things
   actually stand. Enrichment is bounded: it adds context to the week's
   items, it doesn't grow the window.
5. **Order** meetings and reminders by their time column, ascending.

## Format

- Lead with an **Overdue** section *only if* past-due pending reminders exist;
  note how late each one is.
- Then one heading **per day** (today through day 7), in date order. Under each
  day list its meetings (with start time) and any reminders due that day.
- Skip days with nothing — don't pad the plan with empty dates.
- Close with a one-line tally, e.g. `3 meetings, 5 reminders, 1 overdue.`

## Edge cases

- **Nothing in the window:** say so in one line ("Nothing scheduled or due in
  the next 7 days.") — don't invent items or reach to other sources.
- **Don't widen past the playbook.** `crm`, `calendar`, `slack`, and
  knowledge-base briefs feed this plan; don't pull from web / workspace unless
  the owner explicitly asks.
- Cite the sources the plan came from (`crm` meetings + reminders, plus
  `calendar` / `slack` / `knowledge` where they contributed), and report empty
  results honestly rather than guessing.
