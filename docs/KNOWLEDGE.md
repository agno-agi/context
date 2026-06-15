# The @context Knowledge Base

The knowledge base is @context's long-term **prose memory** — the place durable,
written-down context lives: design specs, runbooks, decisions, summaries, and
"what I know about X" pages. It's one of the two always-on read/write sources
(the other is the [CRM](CRM.md)).

Two tools reach it:

- **`query_knowledge`** — read. Ask a question; a read sub-agent resolves it
  through the index to the right page(s) and answers, grounded in what's there.
- **`update_knowledge`** — write. Hand it a decision, a note, or a new spec; a
  write sub-agent files it in the right place and keeps the index current.

It's owner-only, like the rest of the read surface — a guest never sees these
tools (see [`SECURITY.md`](SECURITY.md)).

## What it stores: a folder per spec

The canonical shape is a **folder per spec**, not a flat wiki of pages. The root
`README.md` is the index; each spec is a folder (often nested, e.g.
`agno/features/agent-factories/`) following the `_template/` layout:

```
spec-name/
├── README.md          # overview + a status table (Design / Implementation / …)
├── design.md          # the design itself
├── implementation.md  # how it's built
├── decisions.md       # the ADR log — one entry per decision
├── how-to-review.md    # how to review and test it
├── prompts.md          # prompts for a coding agent
└── future-work.md     # what's deferred and why
```

Not every spec needs every file. Loose prose pages — runbooks, meeting notes,
a stub page for a partnership — live alongside the spec folders.

Reads resolve a question through the index to the right *sub-file* (a status
question hits the `README.md` table; a "why did we…" hits `decisions.md`).
Writes land in the right sub-file (a decision becomes the next ADR in
`decisions.md`), keep the status table current, and register new specs in the
index.

## Talk to it in plain language

These are real prompts run against a populated knowledge base (responses
trimmed):

> **You:** What do we know about the Acme partnership? Keep it short.
>
> **@context:** Not much, honestly. The knowledge base has `acme-partnership.md`,
> but it's just a stub — no substance yet. *(It also folds in the CRM and Slack —
> see [the entity sweep](#a-question-becomes-a-sweep) below.)*

> **You:** Summarize the agent-factories spec — the design and where it stands.
>
> **@context:** Agent Factories = accepted design, not implemented yet. The spec
> proposes request-time, identity-aware agent construction for AgentOS…
> *(cites `agno/features/agent-factories/design.md:110-134`, `decisions.md:7-41`,
> and the README status table.)*

> **You:** What's our pgvector standard for new Agno services?
>
> **@context:** pgvector 18 for every new Agno service that needs vector storage —
> baseline `agnohq/pgvector:18`… *(cites `agno/infra/pgvector-standard/`.)*

Writes are just as conversational:

> **You:** Write up a decision: we're standardizing on pgvector 18 for new services.
>
> **@context** files it as the next ADR in the relevant spec's `decisions.md`,
> updates the status table, and confirms in one line.

### A question becomes a sweep

An "about X" question (a person, org, or project) reads **both** the knowledge
base *and* the [CRM](CRM.md): the entity may be filed as a contact/note there and
described in prose here. So "what do we know about Acme" pulls the stub page
*and* the contact and any open reminders, then synthesizes — it doesn't answer
from a single store.

## Storage: filesystem by default, Git for production

Out of the box the knowledge base is **filesystem-backed** — a local `knowledge/`
folder (gitignored), perfect for trying it out locally.

**In production, back it with Git.** On a container platform like Railway the
local folder lives on the container's filesystem, which is ephemeral — it is
*not* the mounted Postgres volume, so it's wiped on every redeploy. The
[CRM](CRM.md) persists (it's in Postgres on a volume); the prose knowledge base
does **not**, unless it's Git-backed. Point it at a repo — ideally your specs
repo — and every `update_knowledge` auto-commits and pushes, so the **git
history *is* the audit trail** and nothing is lost across deploys.

| Variable | Default | Purpose |
|---|---|---|
| `KNOWLEDGE_REPO_URL` | — | Git remote, e.g. `https://github.com/you/your-specs.git`. Set with the token to switch from filesystem to Git. |
| `KNOWLEDGE_GITHUB_TOKEN` | — | GitHub token with push access. Required alongside the URL. |
| `KNOWLEDGE_BRANCH` | `main` | Branch to commit to. |
| `KNOWLEDGE_LOCAL_PATH` | managed temp dir | Local checkout path for the Git backend. |

Set both `KNOWLEDGE_REPO_URL` and `KNOWLEDGE_GITHUB_TOKEN` to enable Git; set
neither and it falls back to the local folder. (Set only one and it warns and
falls back.)

## How it works

The knowledge base is an Agno `WikiContextProvider` wired in
[`agents/sources.py`](../agents/sources.py) as `_create_knowledge_provider()`,
with a `FileSystemBackend` or `GitBackend` chosen at startup from the env above.
Like the CRM, its read and write sides run as separate sub-agents on tuned
instructions — `KNOWLEDGE_READ` / `KNOWLEDGE_WRITE` in
[`agents/instructions.py`](../agents/instructions.py) — which is where the
spec-shaped behavior (index → sub-file routing, ADRs, status tables) comes from.
The main agent only ever sees the two tools; the routing lives inside the
sub-agents.

## Related

- [`CRM.md`](CRM.md) — the structured store; the other half of an entity sweep.
- [`SECURITY.md`](SECURITY.md) — why the read tools are owner-only.
