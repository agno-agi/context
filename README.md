# @context - a professional alter ego

@context is a self-hosted alter ego: it captures your work context and organizes it using a private crm and knowledge base. @context is designed with privacy and security as a guiding principle. You own everything - your keys, your cloud, your data.

@context runs in two modes:

1. **Owner mode:** all tools available: capture context (*"met Kyle from Agno, follow up next week"*), retrieve context (*"give me a rundown of my day"*), prepare context (*"process today"*)
2. **Guest mode:** teammates (*and their agents*) can leave updates in your queue. You get briefed when you ask for a rundown.

@context runs on Agno's AgentOS runtime, so user identity is verified on every request and tools are assigned based on the user's role (owner vs guest). (JWT-based auth + RBAC).

> Built on [Agno](https://docs.agno.com).

## Scope

@context has five jobs.

1. **Maintain a crm.** Share *"met Kyle from Agno, wants a partnership, follow up next week"* and it stores a contact, a note, and a dated reminder without you picking forms or fields.
2. **Maintain a knowledge base.** @context can write product specs, parse notes from customer interviews, manage project briefs and conduct deep research, and maintain it all in a neatly organized knowledge base.
3. **Run your day, plan your week, prep for what's next.** @context can run playbooks to run your day, plan your week, and prep for meetings. @context comes with a few playbooks but you should definitely customize and add your own. Here are the included ones:
   - **Rundown** *("what's on today?")* — a prioritized brief of things on your plate, one digest instead of five apps: the updates teammates (and their agents) left in your queue, reminders that are due, today's meetings, the emails you missed, and the Slack threads worth a look.
   - **Week plan** *("what's my week?")* — priorities for the week. Run this on a schedule sunday night to start your week with 🔥
   - **Prep** *("prep for my 2pm with Kyle")* — a tight pre-meeting brief: who they are, notes, past threads, what's still open, email and Slack exchanges, and — for not known contacts — public background pulled from the web.

   @context can run these playbooks on demand or on a schedule, and send the results to Slack.
4. **Represent you.** Your teammates (and their agents) can share non-urgent updates with your @context. A teammate types *"@your-context my claude fixed the auth bug"* and it's saved to your queue — surfacing in your next rundown. This keeps your signal-to-noise high.
5. **Act, with your approval.** Connect [Gmail and Calendar](docs/GOOGLE.md) and it can send follow-ups and put meetings on your calendar. Tools that take external actions explicitly wait for your approval on the AgentOS UI before they execute.

## Security

@context is an alter ego with access to a lot of sensitive information and the security boundaries need to be AIRTIGHT.

Agno's AgentOS makes it possible to:
1. Verify the user making the request. AgentOS extracts the `user_id` from the JWT or Slack request. This allows us to determine if the request is from the owner or a guest.
2. Based on the user's role (owner or guest), we can choose the right tools to add to the agent.

This security model enables us to design a system that permits anyone to write to it but only you can read or act through it. To everyone else it is a polite notetaker that only captures. Although it does remember who it is talking to: each caller gets their own user-memory, kept entirely separate from yours.

To push our security boundary even further, tools that take external actions like sending an email or changing your calendar pause for explicit approval before they run. AgentOS makes this possible with the `requires_confirmation` and `approval_type="required"` settings on sensitive tools like `update_gmail` and `update_calendar`.

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
2. Click **Connect AgentOS → Local**.
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

## @context in Slack

Slack is where @context comes alive. It's the interface where I (@ashpreetbedi) use it the most and the interface that allows your team (and their agents) to talk to @context.

To set it up, you need to:
1. Create a Slack app
2. Get the Bot User OAuth Token and Signing Secret
3. Set the environment variables in `.env` or `.env.production`
4. Restart the application

Read [`docs/SLACK.md`](docs/SLACK.md) for the Slack setup guide.

Notes:
- Agno's AgentOS automatically sets up the Slack interface when the `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` env vars are set.
- The `resolve_user_identity=True` flag tells the AgentOS to resolve the Slack user identity to an email, which is what `OWNER_ID` matches against to determine the caller's role (owner or guest).

## @context Knowledge Base

@context comes with a filesystem-backed **document store** that gives it long-term **document memory**. @context uses `query_knowledge` to read, `update_knowledge` to write to this knowledge base.

Use the knowledge base to manage design specs, runbooks, decisions, and "what I know about X" pages.

@context's knowledge base is filesystem-backed by default (a gitignored `knowledge/` folder), but we highly recommend backing it with a Git repo. See [`docs/KNOWLEDGE.md`](docs/KNOWLEDGE.md) for more details and how to use Git as a backend.

This lets @context handle requests like:
- *"What do we know about the Acme partnership?"* — sweeps the knowledge base (and the CRM) and tells you honestly if it's still just a stub.
- *"Summarize the agent-factories spec — the design and where it stands."* — resolves the index → the spec folder, citing the sub-files.
- *"What's our pgvector standard for new services?"*
- *"Write up a decision: we're standardizing on pgvector 18."* — files it as the next ADR in the right spec's `decisions.md`.

## @context Database (CRM)

@context comes with a Postgres-backed **database** that gives it long-term **structured memory**. @context uses `query_crm` to read, `update_crm` to write to this database.

Use the database to manage projects, meetings, reminders, notes, and contacts. @context maps what you tell it onto the right table — no forms, no fields — and can create new tables on demand.

@context's database lives in the `context` Postgres schema: writes are confined to that schema and every row is scoped to your `user_id`, so a guest's capture can never read back across the boundary. See [`docs/CRM.md`](docs/CRM.md) for the schema, the filing rules, and the write boundary.

This lets @context handle requests like:
- *"Add Dana Reyes, Head of Platform at Acme, dana@acme.com — and remind me to send her the integration spec next Tuesday."* — one sentence, two writes (a contact *and* a dated reminder), with "next Tuesday" resolved to a date.
- *"Who do I know at Acme?"*
- *"What reminders do I have coming up?"* — time-aware: pending reminders by due date.
- *"Tell me about Northwind."* — sweeps contacts, notes, projects, reminders, and meetings by tag, and folds in the knowledge base.

## Run in production

@context runs anywhere that runs a Docker container.

The repo includes script to run on Railway. The `scripts/railway/up.sh` script will run @context as a service with Postgres on the same private network. It reads credentials from `.env.production`, and creates a public domain you connect to in the AgentOS UI.

> Requires the [Railway CLI](https://docs.railway.com/cli#installing-the-cli)

### 1. Production env

Create the production environment file.

```sh
cp .env .env.production
```

The deploy scripts read `.env.production` first and falls back to `.env` if it doesn't exist.

### 2. Deploy

Run the `up.sh` script to run @context + postgres on Railway.

First, login to Railway.

```sh
railway login
```

Then run the `up.sh` script.

```sh
./scripts/railway/up.sh
```

The script will now pause and wait for you to mint the JWT verification key.

### 3. Enable Token Based Authorization

Token-Based Authorization is on by default. Without the `JWT_VERIFICATION_KEY` environment variable in `.env.production`, the AgentOS will not serve traffic. That is the safe default for an agent that has access to sensitive information. You can issue and verify your own JWT (see [BYO JWT](https://docs.agno.com/agent-os/security/authorization/self-hosted)) or mint a JWT verification key at [os.agno.com](https://os.agno.com).

The `up.sh` script pauses and waits for you to add the JWT verification key to `.env.production`. Here's how you can get one from os.agno.com:

1. Open [os.agno.com](https://os.agno.com), click **Connect AgentOS → Live**
2. The `up.sh` script will print the AgentOS domain, paste it into the input field.
3. Enable **Token Based Authorization** and click **Connect**.
4. Copy the public key and paste it into `.env.production`.
5. Back in the terminal, press Enter. `up.sh` will read the key and deploy the AgentOS service to Railway.

### 4. Verify

You can verify the deployment on the Railway dashboard or in the terminal by watching the logs:

```sh
railway logs --service agent-os
```

If you add/update any values in `.env.production`, you can sync them to Railway with:

```sh
./scripts/railway/env-sync.sh
```

### 5. Redeploy after code changes

If you make code changes (which you most definitely will), you can redeploy the AgentOS service to Railway with:

```sh
./scripts/railway/redeploy.sh
```

Or enable auto-deploy in the Railway dashboard:

1. Open the Railway dashboard
2. Navigate to the agent-os service
3. Click **Settings**
4. Click **Source** and select the git repo for this project
5. Set the deploy branch to `main` and click **Save (or Deploy)**

### 6. Point Slack at production

If you set Slack up locally, your Slack app's request URLs still point at your ngrok tunnel — i.e. your laptop — so events never reach the deployed instance.

Repoint the `/slack/events` and `/slack/interactions` request URLs to your Railway domain. AgentOS must already be deployed and serving (JWT key in place) so Slack's URL re-verification passes.

See [`docs/SLACK.md`](docs/SLACK.md#moving-from-local-to-production) for full steps.

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
- [`agents/reminders.py`](agents/reminders.py) defines the reminder sweep: `queue_reminders` files due reminders into the inbound queue, run hourly by the `queue-reminders` workflow schedule.
- [`agents/policy.py`](agents/policy.py) defines the pre-hook and tool-hook that back the owner/guest boundary.

### The skills (`skills/`)

The repo has **two distinct kinds of skill**. Keep them separate.

- **Runtime skills** ([`skills/`](skills/)) are playbooks the deployed @context agent runs **for its owner**, invoked in natural language ("plan my week") and owner-gated. Add your own as needed.
- **Coding-agent workflows** ([`.agents/skills/`](.agents/skills/)) are `/slash-command` workflows your *coding agent* (Claude Code, Codex, others) runs while **developing this repo**. They are covered under [Working with coding agents](AGENTS.md#working-with-coding-agents).

Here are the runtime skills that are included in the repo:

- [`skills/week-plan/SKILL.md`](skills/week-plan/SKILL.md).
- [`skills/daily-rundown/SKILL.md`](skills/daily-rundown/SKILL.md).
- [`skills/prep-for/SKILL.md`](skills/prep-for/SKILL.md).
- [`skills/process-today/SKILL.md`](skills/process-today/SKILL.md).

## Connect Gmail and Calendar

With Google credentials configured, `query_gmail` / `query_calendar` ground the rundown and meeting prep in your real inbox and calendar. `update_gmail` / `update_calendar` draft the follow-up or book the slot, pausing for your approval before anything leaves.

Acting as you is double-gated: the act tools exist only in your toolset, and every call requires your explicit confirmation. [`docs/GOOGLE.md`](docs/GOOGLE.md) covers both auth paths (OAuth for personal accounts, service account for Workspace deploys).

## Evals

The eval suite ([`evals/`](evals/)) is the regression net, and it's built around the one claim that matters: *anyone can write, only you can read.* A deterministic gate proves — with no model in the loop — that a guest's resolved toolset is exactly `submit_update`; adversarial guest cases confirm it refuses to read or leak owner data (even under a prompt-injection that tells it to act as you), and owner cases confirm it actually captures, retrieves, and admits what it can't find. Tool-call and trace-level checks are the spine; an LLM judge corroborates.

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
| `KNOWLEDGE_REPO_URL` / `KNOWLEDGE_GITHUB_TOKEN` | no | none | Set both to back the `knowledge` base with a Git repo instead of local files. Optional knobs: `KNOWLEDGE_BRANCH` (default `main`), `KNOWLEDGE_LOCAL_PATH`. |
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASS` / `DB_DATABASE` | no | matches compose | Postgres connection. |
| `DB_DRIVER` | no | `postgresql+psycopg` | SQLAlchemy driver. |
| `AGNO_DEBUG` | no | `False` | If `True`, Agno emits verbose debug logs. Compose sets this for dev. |
| `WAIT_FOR_DB` | no | `False` | If `True`, the entrypoint blocks on the DB before starting. Compose sets this. |

## Learn more

- [`AGENTS.md`](AGENTS.md): architecture and conventions (source of truth for coding agents).
- [Agno documentation](https://docs.agno.com)
- [AgentOS introduction](https://docs.agno.com/agent-os/introduction)
- [Agno on GitHub](https://github.com/agno-agi/agno) (drop a star if this is useful).