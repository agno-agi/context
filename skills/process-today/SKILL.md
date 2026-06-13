---
name: process-today
description: Process the day into filed context — sweep today's activity (the inbound queue, CRM meetings and reminders, plus calendar, slack, and gmail when connected), extract what's worth keeping, and file it into the CRM and knowledge base. Use for "process today", "log today", "file today", "end-of-day wrap".
metadata:
  version: "1.0.0"
  author: context
  tags: ["capture", "filing", "daily", "crm", "knowledge", "queue"]
---
# Process Today

Turn today's raw activity into filed context. Unlike the read-only playbooks,
this one **writes** — it ends in `update_crm` / `update_knowledge` calls, not
just a summary. It still never acts on the outside world: no mail, no calendar
changes, nothing leaves.

## Procedure

1. **Anchor on now.** "Today" is the start of the local day → now.
2. **Gather the day's raw material:**
   - `rundown` — inbound updates from others. (It marks what it shows as
     briefed; do *not* acknowledge anything — that's the owner's call.)
   - `query_crm` — today's meetings and the reminders that came due today.
   - When connected: `query_calendar` for today's events; `query_slack` for
     today's threads the owner took part in; `query_gmail` for today's
     meaningful exchanges.
3. **Extract what has lasting value.** From that material, pick out:
   - a new person → contact
   - a thing that happened, a decision made in a thread → note
   - a commitment with a date ("I'll send it Friday") → reminder with `due_at`
   - a follow-up that got scheduled → meeting
   - durable prose (a decision on a spec, how something now works) → the
     knowledge base, in the right spec sub-file
   Skip chit-chat, scheduling back-and-forth, and anything already on file.
4. **File it** with `update_crm` / `update_knowledge`, deduping against what
   exists (an existing contact gets updated, not duplicated). Writes are
   additive — never flip reminder or ack status and never delete anything in
   this playbook.
5. **Report the digest.** One line per item filed (what + where), then a short
   "left unfiled" line for material judged not worth keeping, so the owner can
   overrule.

## Edge cases

- **Safe unattended.** Scheduled runs work end to end: this playbook reads and
  files but never sends, so no approval gate fires.
- **A quiet day is a one-line report** ("Nothing worth filing today.") — not an
  invented summary.
- **When unsure whether something is durable, file a note** — cheap to ignore
  later, expensive to lose.
