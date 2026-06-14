# The @context Database (CRM)

The CRM is @context's **structured memory** — a Postgres store for the things
that have shape: people, follow-ups, meetings, projects, notes. It's the other
always-on read/write source alongside the [knowledge base](KNOWLEDGE.md), and the
one the agent reaches for most: "save", "add", "remind me", "track", "what's
due", "who is", "log this" all route here.

Two tools reach it:

- **`query_crm`** — read. A read sub-agent turns your question into scoped SQL
  and answers with tables/lists, citing which tables it read.
- **`update_crm`** — write. A write sub-agent maps what you tell it onto the
  right table (or creates one), scopes the row to you, and confirms in a line.

Owner-only, like the rest of the read surface — a guest never sees these tools
(see [`SECURITY.md`](SECURITY.md)).

## The schema

Everything lives in the `crm` Postgres schema. The day-one tables, declared
once in [`db/schema.py`](../db/schema.py):

| Table | What it holds | Key columns |
|---|---|---|
| `projects` | ongoing work you're driving or watching | `name`, `status` (active/paused/done), `notes`, `tags` |
| `meetings` | calls and meetings | `title`, `starts_at`, `attendees`, `notes`, `tags` |
| `reminders` | follow-ups with a due date | `title`, `due_at`, `status` (pending/done/dropped), `notes`, `tags` |
| `notes` | free-form notes | `title`, `body`, `source_url`, `tags` |
| `contacts` | people | `name`, `role`, `emails`, `phone`, `company`, `notes`, `tags` |

Every row also carries `id`, `user_id`, and `created_at`. `tags` is the
connector that ties an entity together across tables — the same tag can sit on a
contact, a note, and a reminder. Beyond these, the write side can **create new
`crm.*` tables on demand** when something genuinely isn't a project/meeting/
reminder/note/contact.

> `db/schema.py` is the single source of truth: editing `TABLES` there updates
> both the `CREATE TABLE` DDL (applied at startup) and the sub-agents'
> table-awareness. Add a table in one place and the agent knows about it.

## Talk to it in plain language

Real prompts run against a populated CRM (responses trimmed):

> **You:** Add Dana Reyes, Head of Platform at Acme, dana@acme.com. And remind me
> to send her the integration spec next Tuesday.
>
> **@context:** Done — added Dana Reyes at Acme and set the reminder for Tuesday,
> June 16.

One sentence, **two writes**: a contact *and* a dated reminder. A compound dump
becomes several scoped writes — the agent lands all of them before it confirms,
and resolves "next Tuesday" to a concrete date.

> **You:** Who do I know at Acme?
>
> **@context:** You have 1 Acme contact on file: **Dana Reyes** — Head of
> Platform, dana@acme.com. *(Reminder pending: send Dana the integration spec by
> 2026-06-16.)*

> **You:** What reminders do I have coming up?
>
> **@context:** You've got 5 pending reminders:
> | Due | Reminder |
> |---|---|
> | Today, 15:00 UTC | Email the board deck |
> | Jun 16 | Renew the TLS cert |
> | Jun 18 | Follow up with Jordan Li from Vexa about pilot |
> | Jun 19 | Follow up with Priya Shah at Northwind |
> | Jun 20 | Follow up with Kyle about partnership |
>
> No overdue reminders. *(Source: `crm.reminders`.)*

### Reads are time-aware and sweep wide

- **Time-aware:** "what's due / coming up / overdue" filters `reminders` by
  `due_at` and `status = 'pending'` (and `meetings` by `starts_at`), ordered by
  time.
- **Entity sweeps go wide:** "what do you know about X" / "who is Y" searches
  *across* tables — contacts, notes, projects, reminders, meetings — and folds
  in the [knowledge base](KNOWLEDGE.md) too. It never answers an "about X"
  question from a single table.

## How filing decisions are made

The write sub-agent follows a few rules ([`CRM_WRITE`](../agents/instructions.py)):

- **Pick the right table.** A dated to-do → `reminders` (`due_at`); a scheduled
  call → `meetings` (`starts_at`, `attendees`); a person → `contacts`; anything
  else free-form → `notes`. Apply `tags` so it's findable later.
- **Dedupe contacts** by primary email — update the existing row rather than
  inserting a duplicate. (Notes/reminders/meetings allow duplicates.)
- **Resolve relative dates** — "next Tuesday", "tomorrow 3pm" become concrete
  `TIMESTAMPTZ` values.
- **Fit existing columns first;** only create a new table for a genuinely new
  *entity type*, never `ALTER` a shipped table for a one-off field.
- **Confirm in one sentence** echoing the key fields and the id — never recites
  the row or the SQL.

## The write boundary

Writes are confined to the `crm` schema by two independent mechanisms in
[`db/session.py`](../db/session.py):

- the **write path** (`get_sql_engine`) sets the `search_path` and runs behind a
  SQLAlchemy **write-guard**, so a write can't escape the `crm` schema;
- the **read path** (`get_readonly_engine`) runs every query in a Postgres
  **read-only transaction**, so `query_crm` physically cannot mutate anything.

And every row is **scoped to your `user_id`** — reads filter on it, writes stamp
it. Combined with the owner-only toolset, that's why a guest's capture can never
read back across the boundary.

## How it works

The CRM is an Agno `DatabaseContextProvider` wired in
[`agents/sources.py`](../agents/sources.py) as `_create_crm_provider()`, pointed
at the two engines above and handed the `crm` schema. Its read and write
sides run as separate sub-agents on tuned instructions — `CRM_READ` /
`CRM_WRITE` in [`agents/instructions.py`](../agents/instructions.py), rendered
table-aware from `db/schema.py`. The main agent only ever sees `query_crm` /
`update_crm`; the SQL lives inside the sub-agents.

## Related

- [`KNOWLEDGE.md`](KNOWLEDGE.md) — the prose store; the other half of an entity sweep.
- [`SECURITY.md`](SECURITY.md) — the owner/guest boundary and `user_id` scoping.
