# @context - your professional alter ego

@context is a self-hosted professional alter ego: it captures your work context and organizes it using a database and knowledge base. @context is built with privacy and security as a first principle, you own everything — your keys, your cloud, your data.

@context runs in two modes:

1. **Owner mode:** all tools available: capture context (*"met Kyle from Agno, follow up next week"*), retrieve context (*"prep me for the 2pm"*), prepare context (*"process today"*)
2. **Guest mode:** teammates (*and their agents*) can leave updates in your queue. Guests can only add context, never retrieve it.

@context runs on Agno's AgentOS runtime, so user identity is verified on every request. The boundary between the two modes is enforced via code by only adding tools based on the user's role (owner vs guest).

> Built on [Agno](https://docs.agno.com).

## Scope

@context has five jobs:

1. **Maintain a database.** Share *"met Kyle from Agno, wants a partnership, follow up next week"* and it stores a contact, a note, and a dated reminder without you picking forms or fields.
2. **Maintain a knowledge base.** @context can manage product specs, customer interviews, project briefs and research using a neatly maintained knowledge base.
3. **Recall and synthesize.** Ask *"what's our week plan?"* and @context explores Slack, its database (projects, contacts, notes, reminders), and its knowledge base (product specs, briefs, design docs) to draft a plan for the week. @context can also run on a schedule, so before "your 2pm with Kyle" it can assemble a short brief by scanning through its database (contact details, last note, open reminder) and slack threads.
4. **Represent you.** Your teammates (and their agents) can talk to your @context. A teammate types *"@your-context fixed the auth bug"* and it's saved to your queue. Whenever you ask for a **rundown** you get the latest picture. This improves your signal:noise ratio.
5. **Act, with your approval.** Connect [Gmail and Calendar](docs/GOOGLE.md) and it can send follow-ups and put meetings on your calendar. Every act tool waits for your sign-off before it executes.

Finally, @context can run playbooks defined under `skills/`. Reusable workflows like "plan my week", "process today", "prep for the weekly meeting" can be executed on a schedule in a somewhat deterministic manner.

## Security

@context is an alter ego with access to a lot of sensitive information, so the security boundaries need to be airtight.

@context's design permits anyone to write to it, but only you can read or act through it.

To everyone but you, it's a polite notetaker that only captures — though it does remember who it's talking to: each caller gets their own memory, kept entirely separate from yours.

The tools available to each role are defined in code and are applied to the agent based on the caller's verified identity.

For @context to take an external action on your behalf - sending an email, changing your calendar - the act tool is double-gated: 1) the act tools only exist for the owner, and 2) every action needs your sign-off.

Read [`docs/SECURITY.md`](docs/SECURITY.md) for more details.

Additionally, everything runs locally or in your cloud, inside your VPC, with your data in your database.

Security and privacy is built into the design.

## Get started

> Requires [Docker](https://www.docker.com/get-started/) installed and running.

```sh
git clone https://github.com/agno-agi/context.git
cd context

# Configure credentials
cp example.env .env
# Open .env: set OPENAI_API_KEY, and set OWNER_ID to the email you'll
# sign in to os.agno.com with (that's how the UI resolves you as the owner).
# OWNER_NAME is an optional display name you can set.

# Run on Docker
docker compose up -d --build
```

Confirm it's live at [http://localhost:8000/docs](http://localhost:8000/docs).

Connect to the AgentOS UI to interact with @context:
1. Open [os.agno.com](https://os.agno.com), sign in with your email (should be the same as your OWNER_ID).
2. Click **Add OS → Local**
3. Enter `http://localhost:8000` and name it "Local Context"
4. Connect

### Try it

Chat with it at [os.agno.com](https://os.agno.com)

<!-- TODO: Add a screenshot of the AgentOS UI -->

Or use the API directly. Pass the email you set as `OWNER_ID` as the `user_id` so the run gets the owner surface — the AgentOS UI does this for you, but a raw request has to send it (any other id is treated as a guest):

```sh
curl -s -X POST http://localhost:8000/agents/context/runs \
  -F "message=Met Kyle from Agno, wants a partnership. Follow up next week" \
  -F "user_id=owner@example.com" \
  -F "stream=false"
```

> Imagine building a product on top of this API.

## Understanding the codebase

@context has 3 main components:
1. The app under `app/`
2. The agents under `agents/`
3. The skills under `skills/`

Review them in order.

### The app

@context is a FastAPI application running the AgentOS runtime. See [`app/main.py`](app/main.py) for the main entrypoint and [`app/settings.py`](app/settings.py) for shared settings. Read through [`app/identity.py`](app/identity.py) to understand how identity is validated. It looks overwhelming but all we're trying to do is check if (user_id is in the OWNER_ID list).

### The agents

The main agent file is [`agents/context.py`](agents/context.py). `context_tools()` adds the tools to the agent based on the caller's role (owner vs guest).

Same with `caller_information()`, which adds the instructions to the agent based on the caller's role.

There are also a few other agent files that are worth reviewing:
- [`agents/instructions.py`](agents/instructions.py) defines the instructions for the agent based on the caller's role (owner vs guest).
- [`agents/sources.py`](agents/sources.py) defines the context providers available to the agent (crm, knowledge, workspace, web, Slack, Gmail, Calendar) and how each registers its `query_` / `update_` tools.
- [`agents/inbox.py`](agents/inbox.py) defines the inbound queue: `submit_update` (anyone) → `rundown` / `acknowledge` (you only).
- [`agents/reminders.py`](agents/reminders.py) defines the reminder sweep: `fire_due_reminders` files due reminders into the inbound queue, run on a daily schedule.
- [`agents/policy.py`](agents/policy.py) defines the pre-hook and tool-hook that enforce the owner/guest boundary.

### The skills

The repo has **two distinct kinds of skill** — don't confuse them:

- **Runtime skills** ([`skills/`](skills/)) — playbooks the deployed @context agent runs **for its owner**, invoked in natural language ("plan my week") and owner-gated. These are the ones meant here; add your own as needed.
- **Coding-agent workflows** ([`.agents/skills/`](.agents/skills/)) — `/slash-command` workflows your *coding agent* (Claude Code, Codex, …) runs while **developing this repo**. Covered under [Build with coding agents](#extending), not here.

The runtime skills, each a `<name>/SKILL.md` folder:
- [`skills/week-plan/SKILL.md`](skills/week-plan/SKILL.md) — the week plan skill.
- [`skills/daily-rundown/SKILL.md`](skills/daily-rundown/SKILL.md) — the daily rundown skill.
- [`skills/prep-for/SKILL.md`](skills/prep-for/SKILL.md) — the prep-for skill.
- [`skills/process-today/SKILL.md`](skills/process-today/SKILL.md) — the process-today skill.

## Run in production

You can run @context anywhere that runs a docker container. For the lightest lift, the codebase comes with a deploy-to-railway script that runs @context as a service with Postgres on the same private network. It uses the credentials set in `.env.production` — `OWNER_ID` included and also creates a public domain for you, that you can connect to in the AgentOS UI.

> Requires the [Railway CLI](https://docs.railway.com/cli#installing-the-cli) and `railway login`.

### 1. Production env

```sh
cp .env .env.production
# Edit .env.production with production values
```

The deploy scripts read `.env.production` first and fall back to `.env`. `.env.production` is gitignored.

The one setting that makes the deploy *yours* is `OWNER_ID` — every identity that counts as you, your JWT `sub` and/or your Slack email, comma-separated:

```sh
# .env.production
OWNER_ID=owner@example.com
```

### 2. Deploy

```sh
./scripts/railway/up.sh
```

Provisions Postgres and the app service on the same private network, creates your public domain, and forwards everything set in `.env.production` — `OWNER_ID` included. `AGENTOS_URL` defaults to the new domain so the scheduler can reach AgentOS.

### 3. Claim it — the script pauses for this

Token-Based Authorization is on by default. Without `JWT_VERIFICATION_KEY`, the app refuses to serve traffic — the safe default for an agent that speaks for you. os.agno.com needs your domain to mint the key, so `up.sh` creates the domain first, prints it, and pauses:

> **Heads up.** Live connections at os.agno.com are a paid feature. Use coupon `PLATFORM30` for a one-month free trial.

1. Open [os.agno.com](https://os.agno.com), click **Add OS → Live**, enter the domain `up.sh` just printed, connect.
2. Enable **Token Based Authorization** and paste the public key into `.env.production` (full PEM block, no quotes):

   ```sh
   JWT_VERIFICATION_KEY=-----BEGIN PUBLIC KEY-----
   MIIBIjANBgkq...
   -----END PUBLIC KEY-----
   ```

3. Back in the terminal, press Enter — `up.sh` pushes the key and deploys. The first deploy comes up serving.

Skipped the pause (or set the key later)? Add it to `.env.production` and run `./scripts/railway/env-sync.sh` — Railway auto-redeploys.

### 4. Verify

```sh
railway logs --service agent-os      # watch it come up
```

For any env change later, edit `.env.production` and run `./scripts/railway/env-sync.sh`.

### 5. Redeploy after code changes

```sh
./scripts/railway/redeploy.sh
```

Or connect the repo in the Railway dashboard (agent-os service → Settings → Source) and set the deploy branch to `main` for auto-deploy on every push. The default deploy is two replicas at 4Gi / 2 vCPU — bump `numReplicas` and `limits` in [`railway.json`](railway.json) as usage grows.

## Talk to it from Slack

Slack is where @context becomes addressable. Set `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` and restart — the interface is wired up automatically, routed to `context` with verified identity. A teammate who @-mentions it files an update (capture-only, no readback); you get the full surface. The same door works for *their* agents — another agent walks through it exactly like a human does. [`docs/SLACK.md`](docs/SLACK.md) has the app manifest and the full setup; mirror the same conditional for Discord, Telegram, WhatsApp, or a custom UI.

## Connect Gmail and Calendar

This is where the alter-ego gets hands. With Google credentials configured, `query_gmail` / `query_calendar` ground the rundown and meeting prep in your real inbox and calendar — and `update_gmail` / `update_calendar` let @context draft the follow-up or book the slot, **pausing for your approval before anything leaves**. Acting as you is double-gated: the act tools exist only in the owner's toolset, and every call requires your explicit confirmation. [`docs/GOOGLE.md`](docs/GOOGLE.md) covers both auth paths (OAuth for personal accounts, service account for Workspace deploys).

## Extending

- **Scheduled runs.** `scheduler=True` is on, and one schedule ships registered: `fire-due-reminders` sweeps due reminders into your inbound queue every morning (see [`agents/reminders.py`](agents/reminders.py)). Add your own — e.g. a daily-rundown digest of meetings (next 7d) and due/overdue reminders posted to Slack. Scheduled runs carry the scheduler's verified identity and run with your owner surface. See [Agno scheduler docs](https://docs.agno.com/agent-os/scheduler).
- **More sources.** See [Adding a source](AGENTS.md#adding-a-source-the-common-extension). The wiki can move from local files to a Git backend (durable, audited) by setting `WIKI_REPO_URL` + `WIKI_GITHUB_TOKEN`.
- **The MCP read path.** The next bet: expose `query_*` over MCP, so your *other* agents — Claude Code, Cursor, whatever you run — can read through your @context instead of starting cold. The asymmetry already covers it: their reads ride your verified identity.
- **Build with coding agents.** The repo ships **coding-agent workflows** (in [`.agents/skills/`](.agents/skills/), symlinked into `.claude/` for Claude Code) for the agent-development lifecycle — `/extend-agent`, `/improve-agent`, `/eval-and-improve`, `/review-and-improve`. These are distinct from the runtime skills under [`skills/`](skills/): they run in *your* coding agent and edit @context's code, not in the deployed agent. Because the code, traces, and iteration tools all live in one place, a coding agent can read, change, and harden @context end to end.

### Lock in behavior with evals

The eval suite ([`evals/`](evals/)) is the regression net. Each case checks the response with an LLM judge and/or a tool-call assertion — including the capture→file loop and the guest boundary.

```sh
python -m evals                # run the suite
python -m evals -v             # stream the full agent run
python -m evals --case <name>  # one case
```

## Environment variables

`compose.yaml` sets the dev defaults (`RUNTIME_ENV=dev`, `AGNO_DEBUG=True`, `WAIT_FOR_DB=True`, a local `OWNER_ID` + `OWNER_NAME`) so local Docker runs hot-reload, skip JWT, and treat you as the owner. Production reads from `.env.production` via `./scripts/railway/env-sync.sh`.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | yes | none | OpenAI key for models and embeddings. |
| `OWNER_ID` | prd | none | Comma-separated identities that count as the owner (JWT `sub` and/or Slack email); first is canonical. Unset ⇒ capture-only for everyone. |
| `OWNER_NAME` | no | canonical `OWNER_ID` | Display name rendered into the prompt ("Ash's professional alter-ego"). Cosmetic — never matched as an identity. |
| `RUNTIME_ENV` | no | `prd` | `dev` enables hot-reload and disables JWT. Compose sets this to `dev` for local. |
| `JWT_VERIFICATION_KEY` | prd | none | Public key from os.agno.com. Required when `RUNTIME_ENV=prd`. |
| `AGENTOS_URL` | no | `http://127.0.0.1:8000` | Scheduler base URL. Set to your Railway domain in production. |
| `INTERNAL_SERVICE_TOKEN` | no | auto-generated | Scheduler-to-OS auth token. Set it when running more than one replica behind one URL. |
| `PARALLEL_API_KEY` | no | none | Switches the `web` source from keyless Parallel MCP to the authenticated SDK (higher rate ceiling). |
| `SLACK_BOT_TOKEN` / `SLACK_SIGNING_SECRET` | no | none | Both enable the Slack interface; the bot token alone activates the `slack` source. See [`docs/SLACK.md`](docs/SLACK.md). |
| `GOOGLE_SERVICE_ACCOUNT_FILE` / `GOOGLE_DELEGATED_USER` | no | none | Service-account path for the `gmail` + `calendar` sources (Workspace, headless). See [`docs/GOOGLE.md`](docs/GOOGLE.md). |
| `GOOGLE_SERVICE_ACCOUNT_JSON_B64` | no | none | The service-account key, base64 — for platforms without secret-file mounts; the entrypoint materializes it. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_PROJECT_ID` | no | none | OAuth client for the `gmail` + `calendar` sources (personal accounts; tokens minted locally). |
| `WIKI_REPO_URL` / `WIKI_GITHUB_TOKEN` | no | none | Set both to back the `knowledge` wiki with a Git repo instead of local files. Optional knobs: `WIKI_BRANCH` (default `main`), `WIKI_LOCAL_PATH`. |
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASS` / `DB_DATABASE` | no | matches compose | Postgres connection. |
| `DB_DRIVER` | no | `postgresql+psycopg` | SQLAlchemy driver. |
| `AGNO_DEBUG` | no | `False` | If `True`, Agno emits verbose debug logs. Compose sets this for dev. |
| `WAIT_FOR_DB` | no | `False` | If `True`, the entrypoint blocks on the DB before starting. Compose sets this. |

## Learn more

- [`docs/SECURITY.md`](docs/SECURITY.md) — the owner/guest security model.
- [`AGENTS.md`](AGENTS.md) — architecture and conventions (the source of truth for coding agents).
- [Context Providers](https://ashpreetbedi.com/context-providers) — the pattern this is built on.
- [Agno documentation](https://docs.agno.com) · [AgentOS introduction](https://docs.agno.com/agent-os/introduction) · [Agno on GitHub](https://github.com/agno-agi/agno) (drop a star if this is useful).
