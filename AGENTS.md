# @context

This file is the source of truth for any agent (Claude Code, Codex, others) working in this repo. `CLAUDE.md` is a symlink to this file — edit one, both update.

## What this is

`@context` is a self-hosted **context agent** — a professional alter-ego you own. One [Agno](https://docs.agno.com) agent that **captures, files, and retrieves** your working context across many sources, and that other people (and their agents) can leave updates with. **Anyone can write to your context. Only you can read it** — or act through it.

Two ideas define it:

- **The tool surface is the job description, not the union of every API.** Each source is a [ContextProvider](https://ashpreetbedi.com/context-providers): a sub-agent behind at most two tools — `query_<id>` (read) and `update_<id>` (write). The main agent sees `2N` tools for `N` sources, and each source's quirks stay inside its own sub-agent's scope.
- **The asymmetry is the security model.** The toolset is chosen *in code, from a verified identity, before the model runs*: the **owner** gets the full surface; **everyone else** gets exactly one context tool — `submit_update` — which appends to the owner's queue with no readback. A guest never holds a read tool into the owner's data, so "don't leak the owner's data" is structural, not a prompt rule. (One deliberate exception rides outside the toolset: per-user learning — @context remembers details about *whoever* talks to it (memory + profile), scoped to that caller's own identity, never the owner's data. See [`docs/SECURITY.md`](docs/SECURITY.md).)

## Architecture

```
Context  (agents/context.py — one Agno agent, gpt-5.5)
│
├── ContextProviders (agents/sources.py)        each source = query_<id> / update_<id>
│   ├── crm        DatabaseContextProvider        structured store (context schema)  R/W  always on
│   ├── knowledge  WikiContextProvider            knowledge base — specs (FS → Git)  R/W  always on
│   ├── workspace  WorkspaceContextProvider       this repo's files                  R    always on
│   ├── web        WebContextProvider             Parallel (SDK or keyless MCP)      R    always on
│   ├── slack      SlackContextProvider           channel / DM history               R    SLACK_BOT_TOKEN set
│   ├── gmail      GmailContextProvider           inbox; send = act tool (approval)  R/W* GOOGLE_* set
│   └── calendar   GoogleCalendarContextProvider  events; write = act tool (approval) R/W* GOOGLE_* set
│        (*act tools — update_gmail / update_calendar — pause for per-call owner approval)
│
├── Inbound queue (agents/inbox.py)             submit_update / rundown / acknowledge
│
├── Reminder sweep (agents/reminders.py)        fire_due_reminders → inbound queue  (daily schedule, owner-only)
│
├── Skills (skills/ + agents/context.py)        owner-only playbooks  week-plan / daily-rundown / prep-for / process-today
│
└── Owner policy (agents/policy.py + app/identity.py)
    identity-conditioned toolset, pre-hook, tool-hook — all from a verified id
```

Shared:
- PostgreSQL + pgvector for sessions, memory, knowledge, and the `context` schema (the structured store).
- `app.settings.default_model()` returns `OpenAIResponses(id="gpt-5.5")` — bump the model in one place.
- Scheduler enabled by default (`scheduler=True`). Scheduled runs arrive with the verified identity `__scheduler__`, which `is_owner` treats as the owner (the scheduler is the owner's automation — see `docs/SECURITY.md`).
- Slack interface is added automatically when both `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` are set, routed to `context` ([`docs/SLACK.md`](docs/SLACK.md)).
- JWT auth on whenever `RUNTIME_ENV == "prd"`, with `user_isolation=True` (so production deploys are gated by default).

## Key Files

| File | Purpose |
|------|---------|
| [`app/main.py`](app/main.py) | AgentOS entrypoint — lifespan (create tables + setup/close providers), conditional Slack, JWT gate, `OWNER_ID` warning. |
| [`app/identity.py`](app/identity.py) | `OWNER_ID` parsing + `is_owner(run_context)` — the verdict the whole owner/guest model keys off. Fails closed. |
| [`app/settings.py`](app/settings.py) | `default_model()` factory. |
| [`app/config.yaml`](app/config.yaml) | Quick prompts for the `context` agent. |
| [`agents/context.py`](agents/context.py) | The `context` Agent — identity-conditioned `tools=` callable, identity-resolved prompt (`caller_information`), defense-in-depth hooks, owner-gated skills. |
| [`agents/sources.py`](agents/sources.py) | Provider registry — builds/caches providers, async setup/close, `list_contexts`. |
| [`agents/instructions.py`](agents/instructions.py) | `CONTEXT_INSTRUCTIONS` + the `crm` and `knowledge` read/write sub-agent prompts (`crm` rendered table-aware from the schema spec; `knowledge` specs-aware). |
| [`agents/inbox.py`](agents/inbox.py) | The inbound queue — `submit_update` (everyone), `rundown` / `acknowledge` (owner-only). |
| [`agents/reminders.py`](agents/reminders.py) | The reminder sweep — `fire_due_reminders` finds due reminders and files them into the inbound queue; runs on the daily schedule, owner-only. |
| [`agents/policy.py`](agents/policy.py) | Defense-in-depth hooks — `normalize_identity` (pre) + `enforce_capture_only` (tool). |
| [`skills/`](skills/) | Runtime skills — owner-only playbooks, one `SKILL.md` per folder (`week-plan`, `daily-rundown`, `prep-for`, `process-today`). Loaded + owner-gated by `context.py`; the agent uses them via progressive disclosure. |
| [`.agents/skills/`](.agents/skills/) | Dev-time **coding-agent workflows** (`extend-agent`, `improve-agent`, `eval-and-improve`, `review-and-improve`) — slash commands coding agents run *on this repo*, distinct from the runtime skills above. `.claude/skills` is a committed symlink here — see "Working with coding agents". |
| [`db/schema.py`](db/schema.py) | Single source for the structured store — `TABLES` renders the DDL (`create_tables()`, run at startup) *and* the agent's table-awareness. |
| [`db/session.py`](db/session.py) | Two engines (write-guarded + read-only) + `get_postgres_db()` for agno persistence. |
| [`db/url.py`](db/url.py) | Builds the database URL from env. |
| [`evals/cases.py`](evals/cases.py) | Eval cases against `context` (capture/file, retrieval grounded in real files, graceful unknown, the guest boundary). |
| [`evals/__main__.py`](evals/__main__.py) | `python -m evals` runner — wraps Agno's `AgentAsJudgeEval` + `ReliabilityEval`. |
| [`docs/SECURITY.md`](docs/SECURITY.md) | The owner/guest security & authorization design — including act tools and the approval gate. |
| [`docs/SLACK.md`](docs/SLACK.md) | Slack setup — app manifest, identity resolution, both sides of the boundary. |
| [`docs/GOOGLE.md`](docs/GOOGLE.md) | Gmail + Calendar setup — both auth paths, token minting, the act-tool approval flow. |
| [`compose.yaml`](compose.yaml) | Docker Compose for local development. |
| [`railway.json`](railway.json) | Railway deploy config (Docker + 2 replicas + 4Gi/2vCPU). |

## The owner/guest security model

This is the heart of the product — read [`docs/SECURITY.md`](docs/SECURITY.md) before touching identity, tools, or the inbound queue. The one thing to internalize: the toolset is chosen **in code, from a verified identity, before the model runs**. [`context_tools()`](agents/context.py) hands the owner the full provider surface and everyone else exactly one context tool — `submit_update` — so a guest never even *sees* a read tool; the boundary is structural, not a prompt rule. `OWNER_ID` lists the identities that count as you (first is canonical); unset ⇒ capture-only for everyone (fail closed). The hooks in [`agents/policy.py`](agents/policy.py) add defense in depth.

One deliberate exception rides outside the identity-conditioned toolset: the agent's `learning=LearningMachine(...)` (user profile + user memory, agentic mode) hands **every** caller two learning tools — `update_user_memory` and `update_profile` — so @context remembers the people (and agents) who talk to it. Memories and profile fields are keyed to the caller's own verified `user_id` and surface only on that caller's later runs — a teammate's memories never touch the owner's data, so this adds no read path across the boundary.

Act tools get a second gate on top of the toolset: the tools named in `ACT_TOOLS` ([`agents/sources.py`](agents/sources.py) — `update_gmail`, `update_calendar`) are flagged `requires_confirmation` per run in [`context_tools()`](agents/context.py), so the run pauses for the owner's explicit approval before anything outward-facing executes. Add any new act-on-the-world tool to `ACT_TOOLS` — don't ship one ungated. The full enforcement layers, threat model, and trust roots live in [`docs/SECURITY.md`](docs/SECURITY.md).

## Development Setup

### Local with Docker

```bash
cp example.env .env
# Edit .env and set OPENAI_API_KEY

docker compose up -d --build
```

Hot-reload watches `agents/`, `app/`, `db/`, and `skills/`. Edits land in <2s. `compose.yaml` sets `RUNTIME_ENV=dev`, `AGNO_DEBUG=True`, and `WAIT_FOR_DB=True` — so JWT is off and the API blocks on the DB before serving.

The intended path is to set `OWNER_ID` to your email (the one you sign in to os.agno.com with) in `.env`; the AgentOS UI then sends it as your verified identity and you get the owner surface. As a fallback for runs that carry *no* identity — the eval suite, the odd unauthenticated `curl` — compose defaults `OWNER_ID` to `owner@example.com,anon` with a cosmetic `OWNER_NAME=Me`, so the `anon` sentinel that agno assigns an unauthenticated local caller resolves to the owner. That keyless-local-as-owner shortcut is a test convenience, **not** a supported way to run the product. A `.env` `OWNER_ID` overrides the compose default entirely (drop `anon` unless you want keyless callers on the owner surface). Any non-owner `user_id` exercises the guest (capture-only) path.

### Format & Validate

The format / validate / eval scripts run on the host, so they need a venv. Set one up once:

```bash
./scripts/venv_setup.sh
source .venv/bin/activate
```

Then:

```bash
./scripts/format.sh     # ruff format + import sort
./scripts/validate.sh   # ruff check + mypy (runs both, summarizes)
```

CI installs the same pinned `requirements.txt`, adds a `ruff format --check` gate, and runs the same `scripts/validate.sh` — local and CI never drift.

## Conventions

### Adding a source (the common extension)

A "source" is a `ContextProvider`. Wire one in [`agents/sources.py`](agents/sources.py): write a `_create_<id>_provider()` factory and add it to `create_context_providers()`. Always-on providers go in the `configured` list directly; env-gated ones go through the `try/except` loop so one bad config can't take the registry down. Each provider exposes `query_<id>` (and `update_<id>` if writable) to the main agent automatically — no change to `context.py` needed.

Agno ships providers for web, workspace, database, wiki (FileSystem/Git), MCP, gmail, calendar, gdrive, slack, and fs. To wrap something Agno doesn't cover, subclass `agno.context.provider.ContextProvider`.

If a provider needs a model, reuse `default_model()` so the model id stays in one place.

### Adding a skill (runtime playbook, owner-only)

A "skill" is a reusable **playbook** the owner can invoke — a named, versioned procedure layered over the provider tools (`week-plan`, `daily-rundown`, `prep-for`, `process-today`). These are *runtime* skills for the `context` agent's owner; don't confuse them with the **coding-agent workflows** in `.agents/skills/`, which drive *coding* agents against this repo.

Drop a folder in [`skills/`](skills/): `skills/<name>/SKILL.md` with YAML frontmatter (`name` must equal the folder name, plus a trigger-rich `description`) and a markdown body that *is* the instructions. Optional `scripts/` and `references/` subdirs are auto-discovered. Agno's `LocalSkills` loader validates on startup (lowercase-hyphenated name, name == dir); the agent then exposes three access tools — `get_skill_instructions` / `get_skill_reference` / `get_skill_script` — with progressive disclosure, so only each skill's name + description sit in the prompt until the model loads one. **No change to `context.py` is needed — it loads every folder in `skills/`.** In dev, adding or editing a `SKILL.md` hot-reloads.

**Owner-gated by construction.** Skills ride the same identity rails as the rest of the toolset: the access tools are added only in the owner branch of [`context_tools()`](agents/context.py), and the browse snippet only renders in the owner branch of the `caller_information` `dependencies` resolver (which also keeps the provider list and routing playbook out of a guest's prompt). A guest's toolset and system prompt carry zero skill references. A malformed `SKILL.md` degrades to "no skills" with a warning rather than taking the app down. See [`docs/SECURITY.md`](docs/SECURITY.md).

### The structured store

Managed tables are declared once in [`db/schema.py`](db/schema.py) `TABLES`. One edit there updates both the `CREATE TABLE` DDL (applied at startup) and the `crm` sub-agents' table-awareness (spliced into their prompts). Day-1 tables: `projects`, `meetings`, `reminders`, `notes`, `contacts`, `updates`. The write sub-agent can also create ad-hoc `context.*` tables on demand. Writes are confined to the `context` schema by two mechanisms: `search_path` + a SQLAlchemy write-guard (`get_sql_engine`), and a Postgres-level read-only transaction on the read path (`get_readonly_engine`).

### The knowledge base

The `knowledge` provider ([`agents/sources.py`](agents/sources.py), a `WikiContextProvider`) is the prose store — `query_knowledge` / `update_knowledge`. Like the CRM, its sub-agents run on tuned instructions (`KNOWLEDGE_READ` / `KNOWLEDGE_WRITE` in [`agents/instructions.py`](agents/instructions.py)), and those instructions make a **folder of specs** the canonical shape: the root `README.md` is the index, and each spec is a *folder* (often nested, e.g. `agno/features/agent-factories/`) following the `_template/` layout — `README.md` with a status table, `design.md`, `implementation.md`, `decisions.md`, `how-to-review.md`, `prompts.md`, `future-work.md`. Reads resolve a question through the index to the right sub-file (status vs design vs decisions); writes land in the right sub-file (a decision becomes the next ADR in `decisions.md`), keep the status table current, and add new specs to the index. Loose prose pages (runbooks, notes) live alongside the specs.

The intended setup is Git-backed: point `WIKI_REPO_URL` + `WIKI_GITHUB_TOKEN` at your specs repo and the knowledge base becomes a durable source of truth — every `update_knowledge` auto-commits and pushes, so the audit trail is the git history. Without them it falls back to a local folder (`wiki/knowledge/`, gitignored).

### Adding another agent (less common)

This repo is a single-agent product, but you can still register more agents: create `agents/<slug>.py`, import and add it to `agents=[…]` in [`app/main.py`](app/main.py), add quick prompts to [`app/config.yaml`](app/config.yaml), then `docker compose restart context-api` (uvicorn hot-reload is unreliable for newly-registered modules).

## Working with coding agents

Dev-time **coding-agent workflows** live in [`.agents/skills/`](.agents/skills/) — the vendor-neutral home for coding-agent assets, mirroring how `CLAUDE.md` symlinks to `AGENTS.md`. `.claude/skills` is a committed symlink into it, so Claude Code picks the skills up on every clone with no setup step; other harnesses (Codex, Cursor, …) can symlink the same folder. (Windows needs developer mode or `core.symlinks=true` for the symlink to materialize.) Claude-specific config like `.claude/settings.json` stays a real file in `.claude/`.

These workflows cover the agent-development lifecycle against the `context` agent:

- **`/extend-agent`** — you drive. Add a source, refine `CONTEXT_INSTRUCTIONS`, fix a known bug. Uses the `agno-docs` MCP for grounded toolkit research.
- **`/improve-agent`** — Claude drives. Derives probes from the agent's `INSTRUCTIONS`, judges, edits, re-runs. No user input needed.
- **`/eval-and-improve`** — run the eval suite, diagnose failures, fix in scope until green.
- **`/review-and-improve`** — repo-wide drift sweep (docs vs code vs config).

## Evals

The suite lives in [`evals/`](evals/). Each case sends one input to the `context` agent and optionally checks the response with [`AgentAsJudgeEval`](https://docs.agno.com/evals/agent-as-judge) (LLM judge against a rubric) and/or [`ReliabilityEval`](https://docs.agno.com/evals/reliability) (tool-call assertion). The runner pins `OWNER_ID=eval-owner`, so a case's `user_id` decides whether it exercises the owner toolset or the capture-only guest surface. Run with `python -m evals`; results log to Postgres via `eval_db`.

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | yes | — | OpenAI key for models + embeddings. |
| `OWNER_ID` | prd | — | Comma-separated identities that count as the owner (JWT `sub` and/or Slack email); first entry is canonical (the inbound queue is keyed under it). Unset ⇒ capture-only for everyone (fail closed). Compose sets a dev default. |
| `OWNER_NAME` | no | — | The owner's display name, rendered into the agent's prompt ("Ash's professional alter-ego"). Cosmetic only — never matched as an identity. Falls back to the canonical `OWNER_ID` entry. |
| `RUNTIME_ENV` | no | `prd` | `dev` enables hot-reload and disables JWT. Compose sets this to `dev` for local. |
| `JWT_VERIFICATION_KEY` | prd | — | Public key from os.agno.com. Required when `RUNTIME_ENV=prd` and `authorization=True`. |
| `AGENTOS_URL` | no | `http://127.0.0.1:8000` | Scheduler base URL. Set to your Railway domain in production so cron triggers reach AgentOS. |
| `INTERNAL_SERVICE_TOKEN` | no | auto-generated | Scheduler-to-OS auth token. Auto-generated per process; pin it when running multiple replicas behind one URL (railway.json ships two). |
| `PARALLEL_API_KEY` | no | — | Switches the `web` provider from the keyless Parallel MCP endpoint to the authenticated Parallel SDK (higher rate ceiling). |
| `SLACK_BOT_TOKEN` | no | — | Bot token. Activates the `slack` provider on its own; set with the signing secret to enable the Slack interface ([`docs/SLACK.md`](docs/SLACK.md)). |
| `SLACK_SIGNING_SECRET` | no | — | Signing secret. Both must be set for the interface to load. |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | no | — | Service-account JSON key path — activates the `gmail` + `calendar` providers (headless; Gmail needs `GOOGLE_DELEGATED_USER`). See [`docs/GOOGLE.md`](docs/GOOGLE.md). |
| `GOOGLE_DELEGATED_USER` | no | — | The mailbox/calendar the service account acts as (domain-wide delegation). |
| `GOOGLE_SERVICE_ACCOUNT_JSON_B64` | no | — | The key as base64 for platforms without secret-file mounts — the entrypoint materializes it and sets `GOOGLE_SERVICE_ACCOUNT_FILE`. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_PROJECT_ID` | no | — | OAuth client for the `gmail` + `calendar` providers (personal accounts; consent tokens minted locally — [`docs/GOOGLE.md`](docs/GOOGLE.md)). |
| `WIKI_REPO_URL` | no | — | Set with `WIKI_GITHUB_TOKEN` to back the `knowledge` base with a Git repo (durable, audit trail) instead of the local filesystem. Point it at your specs repo — see "The knowledge base". |
| `WIKI_GITHUB_TOKEN` | no | — | GitHub token for the knowledge base's `GitBackend`. Required alongside `WIKI_REPO_URL`. |
| `WIKI_BRANCH` | no | `main` | Branch for the knowledge base's `GitBackend`. |
| `WIKI_LOCAL_PATH` | no | — | Local checkout path for the knowledge base's `GitBackend`. |
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASS` / `DB_DATABASE` | no | matches compose | Postgres connection. |
| `DB_DRIVER` | no | `postgresql+psycopg` | SQLAlchemy driver. |
| `AGNO_DEBUG` | no | `False` | If `True`, Agno emits verbose debug logs. Compose sets this for dev. |
| `WAIT_FOR_DB` | no | `False` | If `True`, the entrypoint blocks on the DB before starting. Compose sets this. |

## Ports

- API: `8000`
- Database: `5432`

## Scheduler

`scheduler=True` is on in [`app/main.py`](app/main.py), and `register_schedules()` registers one schedule on every boot (idempotent):

- **`fire-due-reminders`** — daily at 08:00 UTC, the owner-surface run calls `fire_due_reminders` ([`agents/reminders.py`](agents/reminders.py)), which sweeps `context.reminders` for anything now due and drops it into the inbound queue, where the next rundown surfaces it. `notified_at` is stamped so each reminder fires exactly once.

Hand the scheduler any other agent / workflow + a cron expression to add more. Natural fits for `@context`:

- **A morning digest** — query `context.meetings` (next 7d) + `context.reminders` (due/overdue) and post a "what's coming up" digest to Slack.
- **Maintenance** — purge acknowledged updates older than N days; vacuum tables.
- **Periodic re-evaluation** — run `python -m evals` weekly to catch regressions.

Identity: the scheduler authenticates its run triggers with AgentOS's internal service token, and those runs arrive as the verified `__scheduler__` identity — which [`is_owner`](app/identity.py) honors as the owner (once `OWNER_ID` is set), so scheduled playbooks get the owner surface and key their writes under the canonical id. Act tools still pause for approval, so unattended runs can read and file but never send. Running >1 replica? Pin `INTERNAL_SERVICE_TOKEN`. See [Agno scheduler docs](https://docs.agno.com/agent-os/scheduler) for the cron API.

## Slack

Set `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` and restart. The wiring in [`app/main.py`](app/main.py) routes Slack messages to `context` with `resolve_user_identity=True` — so a teammate who @-mentions it files an update (capture-only), and the owner gets the full surface. [`docs/SLACK.md`](docs/SLACK.md) has the app manifest and full setup. For Discord, Telegram, WhatsApp, and custom UIs, mirror the same conditional with the relevant Agno interface.

## Gmail + Google Calendar

Configure Google credentials (either auth path) and the `gmail` + `calendar` providers are added to the registry — `query_gmail` / `query_calendar` for reads, `update_gmail` / `update_calendar` as approval-gated act tools. Setup, token minting, and the approval flow live in [`docs/GOOGLE.md`](docs/GOOGLE.md); the act-tool design is in [`docs/SECURITY.md`](docs/SECURITY.md) (L6).

## Deploying to Railway

```bash
./scripts/railway/up.sh        # provision Postgres + agent-os service
./scripts/railway/env-sync.sh  # sync .env.production (default) or .env
./scripts/railway/redeploy.sh  # redeploy after code changes
```

`up.sh` forwards everything set in `.env.production` — including `OWNER_ID` and the multi-line `JWT_VERIFICATION_KEY` — so **set `OWNER_ID` to your real identity** (Slack email and/or JWT `sub`) before running. JWT auth is on by default, and os.agno.com needs your Railway domain to mint the key, so `up.sh` creates the domain *before* deploying: if `JWT_VERIFICATION_KEY` isn't set yet, it prints the fresh domain and pauses while you mint the key (Add OS → Live → Token Based Authorization) and paste it into `.env.production` — press Enter and the first deploy comes up serving. `AGENTOS_URL` defaults to the new domain. For later env changes, run `./scripts/railway/env-sync.sh` and Railway auto-redeploys.

The Railway *project* is `agent-platform`; the app *service* is `agent-os`.

## Common Tasks

```bash
# Add a dependency
# 1. Edit pyproject.toml
./scripts/generate_requirements.sh upgrade
docker compose up -d --build

# Build a multi-arch image (maintainer-only)
./scripts/build_image.sh

# Tail Railway logs
railway logs --service agent-os
```

## Documentation Links

- [Context Providers](https://ashpreetbedi.com/context-providers) — the pattern @context is built on.
- [Agno documentation](https://docs.agno.com) — full framework reference.
- [Agno LLM-friendly docs](https://docs.agno.com/llms.txt) — concise overview, good for fetching.
- [AgentOS introduction](https://docs.agno.com/agent-os/introduction).
- [Agno tools / toolkits](https://docs.agno.com/tools/toolkits) — 100+ integrations.
- [Agno model providers](https://docs.agno.com/models) — OpenAI, Anthropic, Google, Ollama, Bedrock, Azure, etc.
- [Agno on GitHub](https://github.com/agno-agi/agno). Drop a star if this is useful.
