---
name: daily-rundown
description: The owner's morning brief — inbound updates awaiting acknowledgment (via the rundown tool) plus today's meetings and due-or-overdue reminders from the CRM and the real calendar when connected, stitched into one short digest. Use for "daily rundown", "what's on today", "morning brief", "catch me up".
metadata:
  version: "1.0.0"
  author: context
  tags: ["planning", "daily", "rundown", "crm", "queue"]
---
# Daily Rundown

A focused **today** brief that pulls from two places and stitches them into one
short digest. Read-only assembly — it never files anything.

## Procedure

1. **Anchor on now.** Use the current datetime in your context; "today" is now →
   end of the local day.
2. **Inbound queue — call `rundown`.** It surfaces updates others marked done
   that the owner hasn't acknowledged. (It marks what it shows as briefed — that
   is the point of a morning brief; un-acknowledged items still resurface
   tomorrow.) If it returns nothing, drop the section.
3. **Calendar + due work — call `query_crm`** (one retrieval, ask for both):
   - **Meetings** whose `starts_at` is today.
   - **Reminders** that are `pending` and due today, plus anything **overdue**
     (`due_at < now`, still pending).
4. **If the `calendar` source is connected, pull today's real calendar too** —
   `query_calendar` for today's events — and merge with the CRM meetings
   (dedupe by title + start time; the calendar wins on times).
5. Order each list by its time column, ascending.

## Format

Lead in this order, dropping any empty section:

1. **Awaiting you** — the `rundown` items, one line each (who / what).
2. **Overdue** — past-due pending reminders, with how late.
3. **Today** — meetings (with start time) and reminders due today, time-ordered.

Close with a one-line tally, e.g. `2 awaiting · 1 overdue · 4 today`.

## Edge cases

- **Quiet day:** if all three are empty, say so in one line ("Nothing waiting on
  you and nothing on the calendar today.") — don't pad it.
- Cite the sources you used (the queue via `rundown`, meetings/reminders via
  `crm`, events via `calendar` when connected). Report empties honestly; never
  invent items.
