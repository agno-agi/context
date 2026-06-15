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
│   ├── crm        DatabaseContextProvider        structured store (crm schema)  R/W  always on
│   ├── knowledge  WikiContextProvider            knowledge base — specs (FS → Git)  R/W  always on
│   ├── workspace  WorkspaceContextProvider       this repo's files                  R    always on
│   ├── web        WebContextProvider             Parallel (SDK or keyless MCP)      R    always on
│   ├── slack      SlackContextProvider           channel / DM history; send = update_slack (ungated)  R/W  SLACK_BOT_TOKEN set
│   ├── gmail      GmailContextProvider           inbox; update_gmail drafts only     R/W  GOOGLE_* set
│   └── calendar   GoogleCalendarContextProvider  events; write = act tool (approval) R/W* GOOGLE_* set
│        (*act tool — update_calendar — pauses for per-call owner approval. update_gmail only drafts (never sends), update_slack is ordinary messaging — both ungated.)
│
├── Inbound queue (agents/inbox.py)             submit_update / rundown / acknowledge
│
├── Workflows (workflows/ → WORKFLOWS)          runnable Agno Workflow objects (registered with AgentOS), owner-only
│   ├── reminders (workflows/reminders.py)      hourly sweep: queue_reminders → inbound queue  (+ the queue_reminders owner tool)
│   ├── digest    (workflows/digest.py)         daily rundown / weekly week-plan → owner Slack DM (auto-armed when SLACK_BOT_TOKEN set)
│   └── notify    (workflows/notify.py)         dm_owner() — self-notification path shared by the sweep + digests
│
├── Schedules (app/schedules.py)                register_schedules() — cron that fires the workflows (hourly sweep; Slack-gated digests)
│
├── Skills (skills/ + agents/policy.py)         owner-only playbooks  week-plan / daily-rundown / prep-for / process-today / research / knowledge-review
│
├── MCP server (app/mcp.py)                     owner-only `use_context` at /mcp (on by default) — read/act/file via Claude/ChatGPT desktop + CLI
│
└── Owner policy (agents/policy.py + app/identity.py)
    the identity-conditioned surface (instructions + toolset) + pre-hook + tool-hook — all from a verified id
```

Shared:
- PostgreSQL + pgvector for sessions, memory, knowledge, and the `crm` schema (the structured store).
- `app.settings.default_model()` returns `OpenAIResponses(id="gpt-5.5")` — bump the model in one place.
- Scheduler enabled by default (`scheduler=True`). Scheduled runs arrive with the verified identity `__scheduler__`, which `is_owner` treats as the owner (the scheduler is the owner's automation — see `docs/SECURITY.md`).
- Slack interface is added automatically when both `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` are set, routed to `context` ([`docs/SLACK.md`](docs/SLACK.md)).
- JWT auth on whenever `RUNTIME_ENV == "prd"`, with `user_isolation=True` (so production deploys are gated by default).
- Owner-only MCP server (`use_context` at `/mcp`), mounted by default — the owner's read/act/file surface for the Claude/ChatGPT desktop apps and CLI clients (localhost; one `claude mcp add` / `codex mcp add` for the CLIs, a stdio bridge for the desktop apps), fail-closed (not a guest path). See [`docs/MCP.md`](docs/MCP.md).

## Key Files

| File | Purpose |
|------|---------|
| [`app/main.py`](app/main.py) | AgentOS entrypoint — assembles the `AgentOS` (agents, workflows, interfaces, MCP) and the lifespan (startup checks, thread-pool sizing, create tables, register schedules, setup/close providers). Pure assembly; the steps live in their domain modules. |
| [`app/identity.py`](app/identity.py) | `OWNER_ID` parsing + `is_owner(run_context)` — the verdict the whole owner/guest model keys off. Fails closed. |
| [`app/mcp.py`](app/mcp.py) | `context_mcp_config()` — the `MCPServerConfig` handed to `AgentOS(enable_mcp_server=True, mcp_config=…)`. One tool (`use_context`) running the `context` agent as the owner; fail-closed owner gate (`authorize=_caller_is_owner` — JWT then owner check → 401) + DNS-rebinding protection (`allowed_hosts`), so it's never a guest path ([`docs/MCP.md`](docs/MCP.md)). |
| [`app/settings.py`](app/settings.py) | Config accessors — `default_model()` factory, `owner_timezone()`, the MCP/provider timeout knobs, and `warn_on_missing_config()` (the startup config warnings). |
| [`app/config.yaml`](app/config.yaml) | Quick prompts for the `context` agent. |
| [`app/schedules.py`](app/schedules.py) | `register_schedules()` — the cron registration (idempotent; called from the lifespan): hourly `queue-reminders`, plus the Slack-gated `daily-digest` / `weekly-digest`. Cross-cutting (the scheduler can fire agents *or* workflows), so it lives here, not in `workflows/`. |
| [`agents/context.py`](agents/context.py) | The `context` Agent definition — assembled from the identity-conditioned surface + hooks in [`agents/policy.py`](agents/policy.py), the model, persistence, learning, and history config. |
| [`agents/sources.py`](agents/sources.py) | Provider registry — builds/caches providers, async setup/close, `list_contexts`, the act-tool gate (`gate_act_tools`), and the I/O thread-pool sizing (`size_io_thread_pool`). |
| [`agents/instructions.py`](agents/instructions.py) | `CONTEXT_INSTRUCTIONS` + the `crm` and `knowledge` read/write sub-agent prompts (`crm` rendered table-aware from the schema spec; `knowledge` specs-aware). |
| [`agents/inbox.py`](agents/inbox.py) | The inbound queue — `submit_update` (everyone), `rundown` / `acknowledge` (owner-only). |
| [`agents/policy.py`](agents/policy.py) | Everything decided from the verified identity: the surface (`context_instructions` / `context_tools` — owner gets the full toolset, a guest only `submit_update`), owner-gated skills loading, and the defense-in-depth hooks (`normalize_identity` pre, `enforce_capture_only` tool). |
| [`workflows/__init__.py`](workflows/__init__.py) | Exports `WORKFLOWS` — the list handed to `AgentOS(workflows=...)` in `app/main.py`. |
| [`workflows/reminders.py`](workflows/reminders.py) | The reminder sweep — `_queue_reminders` claims due reminders and files them into the inbound queue. Exposed three ways: the `queue_reminders` owner tool (manual, wired onto the agent), the `queue_reminders_step`, and the `queue_reminders_workflow` (run hourly by the schedule, deterministically). Owner-only on every path. |
| [`workflows/digest.py`](workflows/digest.py) | The scheduled digests — `daily_digest_step` / `weekly_digest_step` (+ the `daily_digest_workflow` / `weekly_digest_workflow` objects) run a read-only playbook (rundown / week-plan) as the owner and DM the result. Auto-arm when `SLACK_BOT_TOKEN` is set. |
| [`workflows/notify.py`](workflows/notify.py) | `dm_owner()` — the shared, ungated self-notification path (DM the owner on Slack). Used by the reminder sweep and the digests. No-op unless a bot token + owner email are configured. |
| [`skills/`](skills/) | Runtime skills — owner-only playbooks, one `SKILL.md` per folder (`week-plan`, `daily-rundown`, `prep-for`, `process-today`, `research`, `knowledge-review`). Loaded + owner-gated by [`agents/policy.py`](agents/policy.py); the agent uses them via progressive disclosure. |
| [`.agents/skills/`](.agents/skills/) | Dev-time **coding-agent workflows** (`extend-agent`, `improve-agent`, `eval-and-improve`, `review-and-improve`) — slash commands coding agents run *on this repo*, distinct from the runtime skills above. `.claude/skills` is a committed symlink here — see "Working with coding agents". |
| [`db/schema.py`](db/schema.py) | Single source for the structured store — `TABLES` renders the DDL (`create_tables()`, run at startup) *and* the agent's table-awareness. |
| [`db/session.py`](db/session.py) | Two engines (write-guarded + read-only) + `get_postgres_db()` for agno persistence. |
| [`db/url.py`](db/url.py) | Builds the database URL from env. |
| [`evals/cases.py`](evals/cases.py) | Eval cases against `context` — the owner/guest asymmetry proven by deterministic structural gates (`boundary_is_structural`, `mcp_server_is_owner_only`) plus an adversarial guest arc and owner-competence cases (judge / reliability / capture-only checks). |
| [`evals/__main__.py`](evals/__main__.py) | `python -m evals` runner — runs each case (or the deterministic gate), wiring Agno's `AgentAsJudgeEval` + `ReliabilityEval` with a trace-level capture-only check; one event loop, judge/reliability results to `eval_db`. |
| [`docs/SECURITY.md`](docs/SECURITY.md) | The owner/guest security & authorization design — including act tools and the approval gate. |
| [`docs/SLACK.md`](docs/SLACK.md) | Slack setup — app manifest, identity resolution, both sides of the boundary. |
| [`docs/GOOGLE.md`](docs/GOOGLE.md) | Gmail + Calendar setup — connect your Gmail, draft-only email, the keep-the-token-alive step. |
| [`docs/KNOWLEDGE.md`](docs/KNOWLEDGE.md) | The `knowledge` base — the folder-per-spec prose store, the read/write split, filesystem vs Git backing (`KNOWLEDGE_*`). |
| [`docs/CRM.md`](docs/CRM.md) | The `crm` structured store — the `crm` schema tables, filing rules, and the write-guard/read-only boundary. |
| [`compose.yaml`](compose.yaml) | Docker Compose for local development. |
| [`railway.json`](railway.json) | Railway deploy config (Docker + 2 replicas + 4Gi/2vCPU each, for zero-downtime deploys + fault tolerance; scale in [`docs/SCALING.md`](docs/SCALING.md)). |

## The owner/guest security model

This is the heart of the product — read [`docs/SECURITY.md`](docs/SECURITY.md) before touching identity, tools, or the inbound queue. The one thing to internalize: the toolset is chosen **in code, from a verified identity, before the model runs**. [`context_tools()`](agents/policy.py) hands the owner the full provider surface and everyone else exactly one context tool — `submit_update` — so a guest never even *sees* a read tool; the boundary is structural, not a prompt rule. `OWNER_ID` lists the identities that count as you (first is canonical); unset ⇒ capture-only for everyone (fail closed). The hooks in [`agents/policy.py`](agents/policy.py) add defense in depth.

One deliberate exception rides outside the identity-conditioned toolset: the agent's `learning=LearningMachine(...)` (user profile + user memory, agentic mode) hands **every** caller two learning tools — `update_user_memory` and `update_profile` — so @context remembers the people (and agents) who talk to it. Memories and profile fields are keyed to the caller's own verified `user_id` and surface only on that caller's later runs — a teammate's memories never touch the owner's data, so this adds no read path across the boundary.

Act tools get a second gate on top of the toolset: the tools named in `ACT_TOOLS` ([`agents/sources.py`](agents/sources.py) — just `update_calendar`) are flagged `requires_confirmation` per run by `gate_act_tools` (called from [`context_tools()`](agents/policy.py)), so the run pauses for the owner's explicit approval before the calendar changes. Two writes are deliberately ungated: `update_gmail` only ever drafts (it never sends — the send tools are stripped from its write toolkit, and a draft is private and reversible), and `update_slack` is ordinary communication, not a sensitive act (still owner-only, since it rides the provider surface). This ungated messaging is what powers the context network (agents messaging each other) — see [`docs/NETWORK.md`](docs/NETWORK.md). When you add a *sensitive* act-on-the-world tool, add it to `ACT_TOOLS` — don't ship one ungated. The full enforcement layers, threat model, and trust roots live in [`docs/SECURITY.md`](docs/SECURITY.md).

## Development Setup

### Local with Docker

```bash
cp example.env .env
# Edit .env and set OPENAI_API_KEY

docker compose up -d --build
```

Hot-reload watches `agents/`, `app/`, `db/`, `skills/`, and `workflows/`. Edits land in <2s. `compose.yaml` sets `RUNTIME_ENV=dev`, `AGNO_DEBUG=True`, and `WAIT_FOR_DB=True` — so JWT is off and the API blocks on the DB before serving.

The intended path is to set `OWNER_ID` to your email (the one you sign in to os.agno.com with) in `.env`; the AgentOS UI then sends it as your verified identity and you get the owner surface. If you don't set one, compose falls back to a placeholder `OWNER_ID` of `owner@example.com` (with a cosmetic `OWNER_NAME=Me`) so the dev UI path works out of the box; a `.env` `OWNER_ID` overrides it entirely. Any other `user_id` — including the `anon` sentinel agno assigns an unauthenticated local caller — exercises the guest (capture-only) path.

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

A "skill" is a reusable **playbook** the owner can invoke — a named, versioned procedure layered over the provider tools (`week-plan`, `daily-rundown`, `prep-for`, `process-today`, `research`, `knowledge-review`). These are *runtime* skills for the `context` agent's owner; don't confuse them with the **coding-agent workflows** in `.agents/skills/`, which drive *coding* agents against this repo.

Drop a folder in [`skills/`](skills/): `skills/<name>/SKILL.md` with YAML frontmatter (`name` must equal the folder name, plus a trigger-rich `description`) and a markdown body that *is* the instructions. Optional `scripts/` and `references/` subdirs are auto-discovered. Agno's `LocalSkills` loader validates on startup (lowercase-hyphenated name, name == dir); the agent then exposes three access tools — `get_skill_instructions` / `get_skill_reference` / `get_skill_script` — with progressive disclosure, so only each skill's name + description sit in the prompt until the model loads one. **No code change is needed — [`agents/policy.py`](agents/policy.py) loads every folder in `skills/`.** In dev, adding or editing a `SKILL.md` hot-reloads.

**Owner-gated by construction.** Skills ride the same identity rails as the rest of the toolset: the access tools are added only in the owner branch of [`context_tools()`](agents/policy.py), and the browse snippet only renders in the owner branch of `caller_information` (which also keeps the provider list and routing playbook out of a guest's prompt). A guest's toolset and system prompt carry zero skill references. A malformed `SKILL.md` degrades to "no skills" with a warning rather than taking the app down. See [`docs/SECURITY.md`](docs/SECURITY.md).

### The structured store

Managed tables are declared once in [`db/schema.py`](db/schema.py) `TABLES`. One edit there updates both the `CREATE TABLE` DDL (applied at startup) and the `crm` sub-agents' table-awareness (spliced into their prompts). Day-1 tables: `projects`, `meetings`, `reminders`, `notes`, `contacts`, `updates`. The write sub-agent can also create ad-hoc `crm.*` tables on demand. Writes are confined to the `crm` schema by two mechanisms: `search_path` + a SQLAlchemy write-guard (`get_sql_engine`), and a Postgres-level read-only transaction on the read path (`get_readonly_engine`).

### The knowledge base

The `knowledge` provider ([`agents/sources.py`](agents/sources.py), a `WikiContextProvider`) is the prose store — `query_knowledge` / `update_knowledge`. Like the CRM, its sub-agents run on tuned instructions (`KNOWLEDGE_READ` / `KNOWLEDGE_WRITE` in [`agents/instructions.py`](agents/instructions.py)), and those instructions make a **folder of specs** the canonical shape: the root `README.md` is the index, and each spec is a *folder* (often nested, e.g. `agno/features/agent-factories/`) following the `_template/` layout — `README.md` with a status table, `design.md`, `implementation.md`, `decisions.md`, `how-to-review.md`, `prompts.md`, `future-work.md`. Reads resolve a question through the index to the right sub-file (status vs design vs decisions); writes land in the right sub-file (a decision becomes the next ADR in `decisions.md`), keep the status table current, and add new specs to the index. Loose prose pages (runbooks, notes) live alongside the specs.

The intended setup is Git-backed: point `KNOWLEDGE_REPO_URL` + `KNOWLEDGE_GITHUB_TOKEN` at your specs repo and the knowledge base becomes a durable source of truth — every `update_knowledge` auto-commits and pushes, so the audit trail is the git history. Without them it falls back to a local folder (`knowledge/`, gitignored).

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

The suite lives in [`evals/`](evals/) and is built around the product's headline — *anyone can write, only you can read* — proving it two ways. A deterministic **structural gate** (`boundary_is_structural`) asserts, with no model in the loop, that a guest's resolved toolset is exactly `submit_update` while the owner's includes the read/act tools — "structural, not a prompt rule" made testable. The behavioural cases then run the agent as the owner (capture, grounded retrieval, graceful unknown) and as a guest (an adversarial arc: read the CRM, read the owner's schedule, a prompt-injection impersonation, and the one thing a guest *can* do — leave an update), each with up to three checks: [`ReliabilityEval`](https://docs.agno.com/evals/reliability) (which tools fired), a **capture-only** trace check (a guest run fired no read/act tool), and [`AgentAsJudgeEval`](https://docs.agno.com/evals/agent-as-judge) (an LLM rubric, kept decisive so it corroborates rather than flakes). The deterministic checks are the spine; the judge corroborates. The runner pins `OWNER_ID=eval-owner`, so a case's `user_id` decides whether it exercises the owner toolset or the capture-only guest surface, and runs the whole suite in one event loop (closing provider clients at the end). Run with `python -m evals`; the judge and reliability results log to Postgres via `eval_db` (visible at os.agno.com → Evaluation).

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | yes | — | OpenAI key for models + embeddings. |
| `OWNER_ID` | prd | — | Comma-separated identities that count as the owner (JWT `sub` and/or Slack email); first entry is canonical (the inbound queue is keyed under it). Unset ⇒ capture-only for everyone (fail closed). Compose sets a dev default. |
| `OWNER_NAME` | no | — | The owner's display name, rendered into the agent's prompt ("Ash's professional alter-ego"). Cosmetic only — never matched as an identity. Falls back to the canonical `OWNER_ID` entry. |
| `OWNER_TIMEZONE` | no | `UTC` | The owner's IANA timezone (e.g. `America/Los_Angeles`). Anchors "today", due/overdue math, and relative-date resolution (the rundown, the CRM date sub-agents, the digests) to the owner's local day instead of the server's UTC. Wired as the agent's `timezone_identifier`. Unset or invalid ⇒ UTC (prior behavior), warned once at startup. Override per request in natural language ("rundown in GMT"). |
| `RUNTIME_ENV` | no | `prd` | `dev` enables hot-reload and disables JWT. Compose sets this to `dev` for local. |
| `JWT_VERIFICATION_KEY` | prd | — | Public key from os.agno.com. Required when `RUNTIME_ENV=prd` and `authorization=True`. AgentOS appends it to the JWT verification list automatically. |
| `CONTEXT_SELF_VERIFICATION_KEY` | no | — | A second JWT public key the app *also* trusts (passed to `AuthorizationConfig.verification_keys` in [`app/main.py`](app/main.py); RS256, multi-issuer) — your own, so a token you self-issue with `scripts/mint_mcp_jwt.py` verifies while the os.agno.com UI keeps working. Server-side; pushed by `env-sync.sh`. |
| `CONTEXT_MCP_JWT` | no | — | The self-issued bearer token `scripts/connect.py --production` threads into MCP clients (minted by `scripts/mint_mcp_jwt.py`). **Client-side only** — lives in `.env.production`, `env-sync.sh` skips it so the signing-grade token never reaches the server. |
| `AGENTOS_URL` | no | `http://127.0.0.1:8000` | Scheduler base URL. Set to your Railway domain in production so cron triggers reach AgentOS — and so the MCP server's Host allowlist accepts that domain (deploy/tunnel; see [`docs/MCP.md`](docs/MCP.md)). |
| `INTERNAL_SERVICE_TOKEN` | no | auto-generated | Scheduler-to-OS auth token. Auto-generated per process — but the deploy ships 2 replicas, which must share one (else triggers signed by one are rejected by the other), so `scripts/railway/up.sh` pins one automatically (override in `.env.production`). See [`docs/SCALING.md`](docs/SCALING.md). |
| `USE_CONTEXT_TIMEOUT` | no | `55` | Hard ceiling (seconds) for one `use_context` MCP run ([`app/mcp.py`](app/mcp.py)). A cross-source sweep that runs long returns an "ask something narrower" reply instead of hanging the client; keep it under the client's own tool timeout (e.g. Claude Code's `MCP_TOOL_TIMEOUT`). |
| `PROVIDER_TIMEOUT` | no | `20` | Per-source ceiling (seconds) for a single **best-effort** `query_<id>` sub-agent run ([`agents/sources.py`](agents/sources.py)). A slow source degrades to a one-line "skipped" and the rest of the brief still lands; smaller than `USE_CONTEXT_TIMEOUT` so several can skip within one budget. |
| `BACKBONE_TIMEOUT` | no | `35` | Per-source ceiling (seconds) for a **backbone** read — the CRM, the brief's spine ([`agents/sources.py`](agents/sources.py), `BACKBONE_SOURCES`). Longer than `PROVIDER_TIMEOUT` so the backbone reliably lands in the concurrent fan-out while best-effort sources still skip fast; kept under `USE_CONTEXT_TIMEOUT` (minus skill-load + compose headroom) so a rundown still fits the MCP ceiling. |
| `THREAD_POOL_WORKERS` | no | `64` | Size of asyncio's default executor — the thread pool agno runs sync provider I/O (Postgres, Slack, Google) on ([`app/main.py`](app/main.py)). The stock ~6 is too few for a rundown's fan-out, so fast sources queue behind slow ones. |
| `PARALLEL_API_KEY` | no | — | Switches the `web` provider from the keyless Parallel MCP endpoint to the authenticated Parallel SDK (higher rate ceiling; recommended for production). Get a key at [platform.parallel.ai](https://platform.parallel.ai/settings?tab=api-keys). |
| `SLACK_BOT_TOKEN` | no | — | Bot token. Activates the `slack` provider on its own (`query_slack` + the ungated `update_slack` send tool) and auto-arms the scheduled digests; set with the signing secret to enable the Slack interface ([`docs/SLACK.md`](docs/SLACK.md)). |
| `SLACK_SIGNING_SECRET` | no | — | Signing secret. Both must be set for the interface to load. |
| `DAILY_DIGEST_CRON` | no | `0 13 * * *` | UTC cron for the Slack-delivered daily rundown digest (only armed when `SLACK_BOT_TOKEN` is set). |
| `WEEKLY_DIGEST_CRON` | no | `0 22 * * 0` | UTC cron for the Slack-delivered weekly week-plan digest (only armed when `SLACK_BOT_TOKEN` is set). |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_PROJECT_ID` | no | — | Connects the `gmail` + `calendar` providers — mint the consent tokens with `python scripts/google_mint_tokens.py` ([`docs/GOOGLE.md`](docs/GOOGLE.md)). |
| `GMAIL_TOKEN_FILE` / `CALENDAR_TOKEN_FILE` | no | `<repo>/gmail_token.json`, `<repo>/calendar_token.json` | Where the OAuth token caches live (read by the providers, written by the mint script). |
| `GMAIL_TOKEN_JSON_B64` / `CALENDAR_TOKEN_JSON_B64` | no | — | The minted OAuth tokens as base64, for platforms without secret-file mounts — the entrypoint restores them to the token-file paths at startup (so OAuth survives a redeploy). |
| `KNOWLEDGE_REPO_URL` | no | — | Set with `KNOWLEDGE_GITHUB_TOKEN` to back the `knowledge` base with a Git repo (durable, audit trail) instead of the local filesystem. Point it at your specs repo — see "The knowledge base". |
| `KNOWLEDGE_GITHUB_TOKEN` | no | — | GitHub token for the knowledge base's `GitBackend`. Required alongside `KNOWLEDGE_REPO_URL`. |
| `KNOWLEDGE_BRANCH` | no | `main` | Branch for the knowledge base's `GitBackend`. |
| `KNOWLEDGE_LOCAL_PATH` | no | — | Local checkout path for the knowledge base's `GitBackend`. |
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASS` / `DB_DATABASE` | no | matches compose | Postgres connection. |
| `DB_DRIVER` | no | `postgresql+psycopg` | SQLAlchemy driver. |
| `AGNO_DEBUG` | no | `False` | If `True`, Agno emits verbose debug logs. Compose sets this for dev. |
| `WAIT_FOR_DB` | no | `False` | If `True`, the entrypoint blocks on the DB before starting. Compose sets this. |

## Ports

- API: `8000`
- Database: `5432`

## Scheduler

`scheduler=True` is on in [`app/main.py`](app/main.py), and `register_schedules()` ([`app/schedules.py`](app/schedules.py)) registers schedules on every boot (idempotent), called from the lifespan. The reminder sweep always; the digests only when Slack is configured:

- **`queue-reminders`** — hourly (on the hour, UTC), the schedule hits the `queue-reminders` workflow (`/workflows/queue-reminders/runs`), whose one step runs `_queue_reminders` ([`workflows/reminders.py`](workflows/reminders.py)) on the owner surface. It sweeps `crm.reminders` for anything now due and drops it into the inbound queue, where the next rundown surfaces it. `notified_at` is stamped (via an atomic claim) so each reminder fires exactly once. It's a workflow, not an agent run, so the sweep fires deterministically — nothing depends on a model choosing to call a tool.
- **`daily-digest` / `weekly-digest`** — registered **only when `SLACK_BOT_TOKEN` is set** (delivery is a Slack DM, so there's no point otherwise). Each hits its digest workflow ([`workflows/digest.py`](workflows/digest.py)), which runs a read-only playbook as the owner (daily rundown, weekly week-plan) and DMs the result via `dm_owner` ([`workflows/notify.py`](workflows/notify.py)). Read-only, so no act tool fires; the DM is self-notification, so it's ungated and completes unattended. Timing is tunable via `DAILY_DIGEST_CRON` / `WEEKLY_DIGEST_CRON` (UTC; defaults `0 13 * * *` and `0 22 * * 0`).

To add a workflow, drop a module in [`workflows/`](workflows/) (the `Workflow` object + its step executor) and include it in `WORKFLOWS`; then register a cron for it in [`app/schedules.py`](app/schedules.py). You can also point a schedule at any agent. Natural fits for `@context`:

- **Maintenance** — purge acknowledged updates older than N days; vacuum tables.
- **Periodic re-evaluation** — run `python -m evals` weekly to catch regressions.

Identity: the scheduler authenticates its run triggers with AgentOS's internal service token, and those runs arrive as the verified `__scheduler__` identity — which [`is_owner`](app/identity.py) honors as the owner (once `OWNER_ID` is set), so scheduled playbooks get the owner surface and key their writes under the canonical id. The gated act tool (calendar) still pauses for approval, so unattended runs can read, draft, file, and message on Slack but never change the calendar. The deploy runs 2 replicas, so the scheduler token is shared (`up.sh` pins `INTERNAL_SERVICE_TOKEN`) and each due job is claimed via a row-level lease on `agno_schedules` — so the sweep and digests fire once, not once per replica ([`docs/SCALING.md`](docs/SCALING.md)). See [Agno scheduler docs](https://docs.agno.com/agent-os/scheduler) for the cron API.

## Slack

Set `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` and restart. The wiring in [`app/main.py`](app/main.py) routes Slack messages to `context` with `resolve_user_identity=True` — so a teammate who @-mentions it files an update (capture-only), and the owner gets the full surface. [`docs/SLACK.md`](docs/SLACK.md) has the app manifest and full setup. For Discord, Telegram, WhatsApp, and custom UIs, mirror the same conditional with the relevant Agno interface.

The bot token alone (no signing secret) still activates the `slack` provider, which now exposes both `query_slack` and `update_slack` (the ungated send tool). Sending is what enables the **context network**: the owner's context can @-mention a teammate's `@context`, which receives it through *its own* Slack interface as a guest and files it in that owner's queue — the owner/guest asymmetry holding across the network. See [`docs/NETWORK.md`](docs/NETWORK.md). With a bot token set, the daily/weekly **digests** also auto-arm (see Scheduler).

## Gmail + Google Calendar

Set `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` and mint the consent tokens once with `python scripts/google_mint_tokens.py`, and the `gmail` + `calendar` providers join the registry — `query_gmail` / `query_calendar` for reads, `update_gmail` / `update_calendar` for writes. **`update_gmail` only ever drafts** (it never sends — you send from Gmail), so it isn't gated; **`update_calendar`** is approval-gated, so calendar changes land in your approvals queue.

Token caches live at `gmail_token.json` / `calendar_token.json` (override with `GMAIL_TOKEN_FILE` / `CALENDAR_TOKEN_FILE`; resolved in one place by `gmail_token_path()` / `calendar_token_path()` in [`agents/sources.py`](agents/sources.py)). On Railway, ship the tokens as base64 (`GMAIL_TOKEN_JSON_B64` / `CALENDAR_TOKEN_JSON_B64`) and the [entrypoint](scripts/entrypoint.sh) restores them at startup. Full setup (including how to stop the tokens expiring), the draft-only design, and troubleshooting live in [`docs/GOOGLE.md`](docs/GOOGLE.md); the act-tool design is in [`docs/SECURITY.md`](docs/SECURITY.md) (L6).

## MCP (owner-only read/act/file server)

The MCP server is mounted at `/mcp` by [`app/main.py`](app/main.py), on by default. It exposes one tool, `use_context(message, session_id?)`, running the *real* `context` agent ([`app/mcp.py`](app/mcp.py)) as the **owner**. The point is the lowest-friction way in: [`scripts/connect.py`](scripts/connect.py) registers it with every local MCP client in one command — the **CLI clients (Claude Code, Codex)** via `claude mcp add` / `codex mcp add` (→ `http://localhost:8000/mcp`, no token in dev), the **desktop apps (Claude, ChatGPT)** via a small `mcp-remote` stdio bridge merged into `claude_desktop_config.json` — and the client then learns about @context and uses it without the owner prompting. Cloud clients (ChatGPT web, Claude web) can't reach localhost — deploy (connector URL `https://<your-domain>/mcp` + `Authorization: Bearer <JWT>`) or tunnel with ngrok, the same paths as Slack.

**Production (`scripts/connect.py --production`).** Against a deployed instance the endpoint is `https://<AGENTOS_URL host>/mcp` and JWT auth is on, so a bearer token is required. The token is **self-issued, not copied from os.agno.com**: [`scripts/mint_mcp_jwt.py`](scripts/mint_mcp_jwt.py) generates an RS256 keypair (private key in `secrets/`, gitignored), and the app trusts that key's public half via `CONTEXT_SELF_VERIFICATION_KEY` *in addition to* the os.agno.com control-plane key (multi-issuer `verification_keys` in [`app/main.py`](app/main.py)), so the AgentOS UI keeps working. `connect.py --production` reads `AGENTOS_URL` + the minted `CONTEXT_MCP_JWT` from `.env.production` and threads `Authorization: Bearer …` into each client (Codex via `--bearer-token-env-var CONTEXT_JWT`, so it stays out of Codex's config). [`scripts/setup_production_mcp.sh`](scripts/setup_production_mcp.sh) chains mint → `env-sync` → connect. The server only ever holds public keys; the signing key and the token never leave the owner's machine. Full walkthrough in [`docs/MCP.md`](docs/MCP.md#self-issued-production-token).

It's owner-only — **not** a guest path; teammates keep their Slack write path. Owner-only and fail-closed (see [`docs/SECURITY.md`](docs/SECURITY.md) L7): in prod the same JWT middleware AgentOS uses validates the token, then the `authorize` gate (`MCPServerConfig.authorize=_caller_is_owner`) 401s anyone not in `OWNER_ID` — it never falls back to the guest surface; an always-on local server is a DNS-rebinding target, so host validation is on (`allowed_hosts`, anchored on localhost + the `AGENTOS_URL` host, a non-allowed Host → 400). We use AgentOS's native MCP server (`enable_mcp_server=True`, `mcp_config=context_mcp_config()`), which injects the verified `user_id` into `use_context` (hidden from clients) so identity is threaded through. The per-client setup steps (Claude Code, Codex, the desktop bridge, cloud) are in [`docs/MCP.md`](docs/MCP.md).

## Deploying to Railway

```bash
./scripts/railway/up.sh        # provision Postgres + agent-os service
./scripts/railway/env-sync.sh  # sync .env.production (default) or .env
./scripts/railway/redeploy.sh  # redeploy after code changes
```

`up.sh` forwards everything set in `.env.production` — including `OWNER_ID` and the multi-line `JWT_VERIFICATION_KEY` — so **set `OWNER_ID` to your real identity** (Slack email and/or JWT `sub`) before running. JWT auth is on by default, and os.agno.com needs your Railway domain to mint the key, so `up.sh` creates the domain *before* deploying: if `JWT_VERIFICATION_KEY` isn't set yet, it prints the fresh domain and pauses while you mint the key (Connect AgentOS → Live → Token Based Authorization) and paste it into `.env.production` — press Enter and the first deploy comes up serving. `AGENTOS_URL` defaults to the new domain. For later env changes, run `./scripts/railway/env-sync.sh` and Railway auto-redeploys.

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
