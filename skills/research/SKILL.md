---
name: research
description: Research a topic and file the result — sweep what we already know (knowledge base, crm, and slack when connected), go to the web for current and external background, then write a clear sourced brief and FILE it into the knowledge base with update_knowledge. Labels what came from the web versus our own notes. Use for "research X and save it", "look into X and write it up", "find out what's known about X and file it", "write up a brief on X".
metadata:
  version: "1.0.0"
  author: context
  tags: ["research", "knowledge", "web", "crm", "slack", "filing"]
---
# Research

> _**Runtime skill** — a playbook the deployed @context agent runs for its owner, invoked in natural language. Not a coding-agent workflow; those live in [`.agents/skills/`](../../.agents/skills/)._

Turn a topic into a durable, sourced brief filed in the knowledge base. Like
`process-today`, this one **writes** — it ends in an `update_knowledge` call, not
just a summary. It still never acts on the outside world: it reads and files, and
nothing leaves.

## Procedure

1. **Pin the topic and the question.** Settle what the owner actually wants to
   know ("research how teams handle multi-tenant RBAC" → the question is *how do
   teams do this, and where does it leave us*). If the topic is genuinely
   ambiguous and a wrong guess wastes the work, ask one clarifying question.
2. **Sweep what we already know first — internal before web.** Always do this,
   even for a topic that looks purely external: it's how you avoid duplicating a
   page that already exists and how you learn where the brief should land. A
   quick sweep that comes back empty is fine; skipping it is not.
   - `query_knowledge` — route through the index to any spec or page already on
     the topic. If one exists, the brief extends it; it doesn't shadow it.
   - `query_crm` — contacts, notes, projects, meetings tagged to the topic (our
     relationship and history with it).
   - `query_slack` (when connected) — recent threads where the team discussed it;
     often the freshest internal context.
3. **Go to the web for current and external background.** `query_web` for what
   we can't know from our own notes: public facts, recent developments, how
   others approach it. Keep queries to the public subject, not the owner's
   private notes. Skip the web only when the topic is purely internal and the
   internal sweep already answers it.
4. **Read the codebase when the topic is framework-related.** If the question
   touches how @context is built or how Agno does something (a toolkit, a
   provider, the scheduler, AgentOS), read the repo's files (`list_files`,
   `read_file`) to see how it uses it, and `query_web` for anything the code
   doesn't answer.
5. **Synthesize a clear, sourced brief.** Lead with the answer. Attribute every
   claim to where it came from, and keep web background visibly separate from our
   own record: tag lines `(from web)`, `(on file)`, or `(auto-summarized,
   unverified)` for anything you distilled but haven't confirmed. Never blend an
   unverified web claim into our known facts.
6. **File it with `update_knowledge`.** Filing is frictionless (no approval
   gate), so land it directly:
   - Topic already covered → file into that spec's right sub-file (a decision →
     `decisions.md`, design detail → `design.md`, status → the `README.md`) and
     keep the status table current.
   - New topic that's a real spec → a new folder-per-spec following `_template/`,
     plus a row in the root `README.md` index.
   - A standalone write-up that isn't a spec → a loose prose page ("what we know
     about X").
   The write sub-agent carries the provenance labels through, so keep them in the
   prose you hand it.
7. **Make the brief findable — don't orphan your own research.** Filing isn't
   done until the new page or spec has a row in the root `README.md` index. A new
   spec earns its row through the write tool's own rules; for a new *loose page*,
   make a second `update_knowledge` call that adds a one-line index row pointing
   at the path you just wrote. Skipping this lands the brief as exactly the kind
   of orphan the `knowledge-review` sweep exists to flag.
8. **Report what you filed and where.** One line per file touched (what + path),
   then one line on what you leaned on — *"web: 4 sources; on file: the
   pgvector-standard spec"* — so the owner can see the brief's footing at a
   glance. Mirror `process-today`'s digest.

## Format

The filed brief, only the sections with content:

- **Answer** — the tight take on the question, up top.
- **What we already knew** — from `knowledge` / `crm` / `slack`, tagged `(on file)`.
- **What the web adds** — public background, tagged `(from web)` and dated where
  it matters; marked external / unverified.
- **Where this leaves us** — the so-what for the owner: implications, open
  questions, a next step if there's an obvious one.
- **Sources** — the web results cited and the internal pages drawn on.

## Edge cases

- **Read and file only.** No mail, no calendar, no Slack send. This skill never
  reaches outward, so a scheduled run completes with no approval gate.
- **Nothing on the web** (or nothing useful): say so plainly and file what the
  internal sweep gave you, rather than padding the brief with generic results.
- **Thin topic, nothing anywhere:** don't fabricate a brief. File a short stub
  page that frames the question and says what's missing, and tell the owner.
- **Already well covered:** extend the existing spec or page in place and say
  what you added; don't create a parallel duplicate.
- **Label every fact.** A reader six months out has to know whether a line is our
  own record, an unverified summary, or a web claim. Keep the labels light (tag
  the claim or the section, not every sentence), but never drop them.
