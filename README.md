# @context - a professional alter ego

@context is a self-hosted alter ego: it captures your work context and organizes it using a private database and knowledge base. @context is designed with privacy and security as a first principle, you own everything - your keys, your cloud, your data.

@context runs in two modes:

1. **Owner mode:** all tools available: capture context (*"met Kyle from Agno, follow up next week"*), retrieve context (*"prep me for the 2pm"*), prepare context (*"process today"*)
2. **Guest mode:** teammates (*and their agents*) can leave updates in your queue. Guests can only add context, never retrieve it.

@context runs on Agno's AgentOS runtime, so user identity is verified on every request. The boundary between the two modes is enforced via code by only adding tools based on the user's role (owner vs guest).

> Built on [Agno](https://docs.agno.com).

## Scope

@context has five jobs.

1. **Maintain a database.** Share *"met Kyle from Agno, wants a partnership, follow up next week"* and it stores a contact, a note, and a dated reminder without you picking a form or a field.
2. **Maintain a knowledge base.** @context can manage product specs, customer interviews, project briefs and research using a neatly maintained knowledge base.
3. **Recall and synthesize.** Ask *"what's my week plan?"* and @context reads Slack, its database (projects, contacts, notes, reminders), and its knowledge base (specs, briefs, design docs) to draft your week. It can also run on a schedule. Before *"your 2pm with Kyle"* it assembles a short brief from the contact details, the last note, the open reminder, and the relevant Slack threads.
4. **Represent you.** Your teammates (and their agents) can talk to your @context. A teammate types *"@your-context fixed the auth bug"* and it's saved to your queue. Whenever you ask for a **rundown** you get the latest picture. This improves your signal:noise ratio.
5. **Act, with your approval.** Connect [Gmail and Calendar](docs/GOOGLE.md) and it can send follow-ups and put meetings on your calendar. Every act tool waits for your sign-off before it executes.

@context also runs **playbooks** defined under `skills/`. Reusable workflows like *"plan my week"*, *"process today"*, and *"prep for the weekly meeting"* can be executed on a schedule in a somewhat deterministic manner.

## Security

@context is an alter ego with access to a lot of sensitive information. The security boundaries need to be airtight.

The design permits anyone to write to it but only you can read or act through it. To everyone else it is a polite notetaker that only captures. Although it does remember who it is talking to: each caller gets their own user-memory, kept entirely separate from yours.

The boundary between owner and guest is enforced in code. The tools available to each role are chosen from the caller's verified identity before the model runs. A guest's session never gets a read tool, so data leaks are prevented by design.

Acting on your behalf is also a double-gated operation. Sending an email or changing your calendar requires two things: 1) the act tool only exists when the agent is responding to the owner, and 2) every tool call pauses for explicit approval before it executes. This is enforced by the `requires_confirmation` and `approval_type="required"` settings on the external action tools (`update_gmail`, `update_calendar`).

Finally, everything runs locally or in your own cloud, inside your VPC, with every byte of data (context's database, context's knowledge base, context's inbox) being stored in your own database.

Read [`docs/SECURITY.md`](docs/SECURITY.md) for more details.

## Get started

> Requires [Docker](https://www.docker.com/get-started/) installed and running.

```sh
git clone https://github.com/agno-agi/context.git
cd context

# Configure credentials
cp example.env .env
# Open .env: set OPENAI_API_KEY, and set OWNER_ID to the email you sign in to
# os.agno.com with (that is how the UI resolves you as the owner).
# OWNER_NAME is an optional display name, set it as your or your company's name.

# Run on Docker
docker compose up -d --build
```

Confirm it is live at [http://localhost:8000/docs](http://localhost:8000/docs).

Connect the AgentOS UI to interact with @context:

1. Open [os.agno.com](https://os.agno.com) and sign in with your email (the same one you set as `OWNER_ID`).
2. Click **Add OS → Local**.
3. Enter `http://localhost:8000` and name it "Local Context".
4. Connect.

### Try it

Chat with it at [os.agno.com](https://os.agno.com)

<!-- TODO: add a screenshot of the AgentOS UI -->

Or call the API directly. Pass the email you set as `OWNER_ID` as the `user_id` so the run gets the owner surface. The AgentOS UI does this for you.

```sh
curl -s -X POST http://localhost:8000/agents/context/runs \
  -F "message=Met Kyle from Agno, wants a partnership. Follow up next week" \
  -F "user_id=owner@example.com" \
  -F "stream=false"
```

> Imagine building products on top of this API!

## Understanding the codebase

@context has three main components. Review them in order.

### The app (`app/`)

@context is a FastAPI application running the AgentOS runtime. [`app/main.py`](app/main.py) is the entrypoint and [`app/settings.py`](app/settings.py) holds shared settings. [`app/identity.py`](app/identity.py) is where identity is validated. It looks dense, but all it does is check whether `user_id` is in the `OWNER_ID` list (comma-separated).

### The agents (`agents/`)

The main agent is [`agents/context.py`](agents/context.py). `context_tools()` adds tools to the agent based on the caller's role, and `caller_information()` adds the matching instructions.

The supporting files:

- [`agents/instructions.py`](agents/instructions.py) defines the role-specific instructions.
- [`agents/sources.py`](agents/sources.py) defines the context providers (crm, knowledge, workspace, web, Slack, Gmail, Calendar) and how each registers its `query_` / `update_` tools.
- [`agents/inbox.py`](agents/inbox.py) defines the inbound queue: `submit_update` (anyone), then `rundown` / `acknowledge` (you only).
- [`agents/reminders.py`](agents/reminders.py) defines the reminder sweep: `fire_due_reminders` files due reminders into the inbound queue on a daily schedule.
- [`agents/policy.py`](agents/policy.py) defines the pre-hook and tool-hook that back the owner/guest boundary.

### The skills (`skills/`)

The repo has **two distinct kinds of skill**. Keep them separate.

- **Runtime skills** ([`skills/`](skills/)) are playbooks the deployed @context agent runs **for its owner**, invoked in natural language ("plan my week") and owner-gated. Add your own as needed.
- **Coding-agent workflows** ([`.agents/skills/`](.agents/skills/)) are `/slash-command` workflows your *coding agent* (Claude Code, Codex, others) runs while **developing this repo**. They are covered under [Extending](#extending).

Here are the runtime skills that are included in the repo:

- [`skills/week-plan/SKILL.md`](skills/week-plan/SKILL.md).
- [`skills/daily-rundown/SKILL.md`](skills/daily-rundown/SKILL.md).
- [`skills/prep-for/SKILL.md`](skills/prep-for/SKILL.md).
- [`skills/process-today/SKILL.md`](skills/process-today/SKILL.md).

## Run in production

@context runs anywhere that runs a Docker container.

The repo includes script to run on Railway. The `scripts/railway/up.sh` script will run @context as a service with Postgres on the same private network. It reads credentials from `.env.production`, and creates a public domain you connect to in the AgentOS UI.

> Requires the [Railway CLI](https://docs.railway.com/cli#installing-the-cli) and `railway login`.

### 1. Production env

```sh
cp .env .env.production
# Edit .env.production with production values
```

The deploy scripts read `.env.production` first and falls back to `.env` if it doesn't exist.

Remember to set `OWNER_ID` and `OWNER_NAME`. List every identity that should be considered as the owner, AgentOS email, Slack email.

```sh
# .env.production
OWNER_ID=owner@example.com
```

### 2. Deploy

```sh
./scripts/railway/up.sh
```

This provisions Postgres and the app service on the same private network, creates your public domain, and forwards everything in `.env.production`. `AGENTOS_URL` defaults to the new domain so the scheduler can reach AgentOS.

### 3. Claim it

Token-Based Authorization is on by default. Without `JWT_VERIFICATION_KEY`, the app refuses to serve traffic. That is the safe default for an agent that speaks for you. os.agno.com needs your domain to mint the key, so `up.sh` creates the domain first, prints it, and pauses.

> **Heads up.** Live connections at os.agno.com are a paid feature. Use coupon `PLATFORM30` for a one-month free trial.

1. Open [os.agno.com](https://os.agno.com), click **Add OS → Live**, enter the domain `up.sh` printed, and connect.
2. Enable **Token Based Authorization** and paste the public key into `.env.production` (full PEM block, no quotes):

   ```sh
   JWT_VERIFICATION_KEY=-----BEGIN PUBLIC KEY-----
   MIIBIjANBgkq...
   -----END PUBLIC KEY-----
   ```

3. Back in the terminal, press Enter. `up.sh` pushes the key and deploys. The first deploy comes up serving.

Set the key later? Add it to `.env.production` and run `./scripts/railway/env-sync.sh`. Railway auto-redeploys.

### 4. Verify

```sh
railway logs --service agent-os      # watch it come up
```

For any later env change, edit `.env.production` and run `./scripts/railway/env-sync.sh`.

### 5. Redeploy after code changes

```sh
./scripts/railway/redeploy.sh
```

Or connect the repo in the Railway dashboard (agent-os service → Settings → Source) and set the deploy branch to `main` for auto-deploy on every push. The default deploy is two replicas at 4Gi / 2 vCPU. Raise `numReplicas` and `limits` in [`railway.json`](railway.json) as usage grows.

## Talk to it from Slack

Slack is where @context becomes addressable. Set `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` and restart. The interface wires up automatically, routed to `context` with verified identity. A teammate who @-mentions it files an update, capture-only with no readback. You get the full surface. The same door works for their agents. Another agent walks through it exactly like a human does.

[`docs/SLACK.md`](docs/SLACK.md) has the app manifest and the full setup. Mirror the same conditional for Discord, Telegram, WhatsApp, or a custom UI.

## Connect Gmail and Calendar

This is where the alter ego gets hands. With Google credentials configured, `query_gmail` / `query_calendar` ground the rundown and meeting prep in your real inbox and calendar. `update_gmail` / `update_calendar` draft the follow-up or book the slot, pausing for your approval before anything leaves.

Acting as you is double-gated: the act tools exist only in your toolset, and every call requires your explicit confirmation. [`docs/GOOGLE.md`](docs/GOOGLE.md) covers both auth paths (OAuth for personal accounts, service account for Workspace deploys).

## Extending

- **Scheduled runs.** `scheduler=True` is on, and one schedule ships registered: `fire-due-reminders` sweeps due reminders into your inbound queue every morning (see [`agents/reminders.py`](agents/reminders.py)). Add your own, like a morning digest of meetings (next 7 days) and due-or-overdue reminders posted to Slack. Scheduled runs carry the scheduler's verified identity and run with your owner surface. See the [Agno scheduler docs](https://docs.agno.com/agent-os/scheduler).
- **More sources.** Wire a new `ContextProvider` in [`agents/sources.py`](agents/sources.py). The wiki can move from local files to a Git backend (durable, audited) by setting `WIKI_REPO_URL` + `WIKI_GITHUB_TOKEN`.
- **The MCP read path.** The next bet: expose `query_*` over MCP so your other agents (Claude Code, Cursor, whatever you run) read through your @context instead of starting cold. The asymmetry already covers it. Their reads ride your verified identity.
- **Build with coding agents.** The repo includes coding-agent workflows in [`.agents/skills/`](.agents/skills/), symlinked into `.claude/` for Claude Code, for the agent-development lifecycle: `/extend-agent`, `/improve-agent`, `/eval-and-improve`, `/review-and-improve`. These run in your coding agent and edit @context's code. They are distinct from the runtime skills under [`skills/`](skills/), which run in the deployed agent. Because the code, traces, and iteration tools all live in one place, a coding agent can read, change, and harden @context end to end.

### Lock in behavior with evals

The eval suite ([`evals/`](evals/)) is the regression net. Each case checks the response with an LLM judge and/or a tool-call assertion, covering the capture-to-file loop and the guest boundary.

```sh
python -m evals                # run the suite
python -m evals -v             # stream the full agent run
python -m evals --case <name>  # one case
```

## Environment variables

`compose.yaml` sets the dev defaults (`RUNTIME_ENV=dev`, `AGNO_DEBUG=True`, `WAIT_FOR_DB=True`, a local `OWNER_ID` + `OWNER_NAME`), so local Docker runs hot-reload, skip JWT, and treat you as the owner. Production reads from `.env.production` via `./scripts/railway/env-sync.sh`.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | yes | none | OpenAI key for models and embeddings. |
| `OWNER_ID` | prd | none | Comma-separated identities that count as the owner (JWT `sub` and/or Slack email). First is canonical. Unset means capture-only for everyone. |
| `OWNER_NAME` | no | canonical `OWNER_ID` | Display name rendered into the prompt. Cosmetic, never matched as an identity. |
| `RUNTIME_ENV` | no | `prd` | `dev` enables hot-reload and disables JWT. Compose sets this to `dev` for local. |
| `JWT_VERIFICATION_KEY` | prd | none | Public key from os.agno.com. Required when `RUNTIME_ENV=prd`. |
| `AGENTOS_URL` | no | `http://127.0.0.1:8000` | Scheduler base URL. Set to your Railway domain in production. |
| `INTERNAL_SERVICE_TOKEN` | no | auto-generated | Scheduler-to-OS auth token. Set it when running more than one replica behind one URL. |
| `PARALLEL_API_KEY` | no | none | Switches the `web` source from keyless Parallel MCP to the authenticated SDK (higher rate ceiling). |
| `SLACK_BOT_TOKEN` / `SLACK_SIGNING_SECRET` | no | none | Both enable the Slack interface. The bot token alone activates the `slack` source. See [`docs/SLACK.md`](docs/SLACK.md). |
| `GOOGLE_SERVICE_ACCOUNT_FILE` / `GOOGLE_DELEGATED_USER` | no | none | Service-account path for the `gmail` + `calendar` sources (Workspace, headless). See [`docs/GOOGLE.md`](docs/GOOGLE.md). |
| `GOOGLE_SERVICE_ACCOUNT_JSON_B64` | no | none | The service-account key, base64, for platforms without secret-file mounts. The entrypoint materializes it. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_PROJECT_ID` | no | none | OAuth client for the `gmail` + `calendar` sources (personal accounts, tokens minted locally). |
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