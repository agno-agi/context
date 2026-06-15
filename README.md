# @context - professional context manager

@context is a self-hosted context manager. It organizes your work context into a private CRM and knowledge base so you can stay on top of things.

It plugs into clients like claude, chatGPT, claude code, and codex, and gives them a single source of @context about your work. I use it with claude code to manage product specs. Connect @context to slack and gmail, and you get a powerful chief of staff with context about everything.

> Your AI tools are users of context, not competitors.

@context is built with privacy and security as first principles. It runs in two modes:

1. **Owner mode.** You get every tool. Capture context (*"met Kyle from Agno, follow up next week"*), retrieve context (*"give me a rundown of my day"*), and prepare context (*"process today"*).
2. **Guest mode.** Teammates (*and their agents*) can leave updates in your queue. You get briefed when you ask for a rundown.

@context runs on Agno's AgentOS runtime, so user identity is verified on every request, and tools are assigned by role (owner or guest).

> Built on [Agno](https://docs.agno.com).

## Scope

@context has five jobs.

1. **Maintain a CRM.** Share *"met Kyle from Agno, wants a partnership, follow up next week"*, and it stores a contact, a note, and a dated reminder without you picking forms or fields.
2. **Maintain a knowledge base.** @context writes product specs, parses customer interview notes, manages project briefs, and runs deep research, then keeps it all neatly organized in one place.
3. **Run your day, plan your week, prep ahead.** @context runs repeatable playbooks to make things easier. A few come built in, and you should customize them and add your own. Here are the included ones:
   - **Rundown** *("what's on today?")*: a prioritized brief of things on your plate. One digest instead of five apps: the updates teammates (and their agents) left in your queue, reminders that are due, today's meetings, the emails you missed, and the Slack threads worth a look.
   - **Week plan** *("what's my week?")*: priorities for the week. Runs Sunday evening and lands in your DMs, so you start the week with 🔥
   - **Prep** *("prep for my 2pm with Kyle")*: a tight pre-meeting brief covering who they are, notes, past threads, what's still open, email and Slack exchanges, and public background from the web for contacts you don't know yet.

   @context runs these playbooks on demand or on a schedule. The daily rundown and weekly plan DM the brief straight to you.
4. **Represent you.** Your teammates (and their agents) can share non-urgent updates with your @context. A teammate types *"@your-context my claude fixed the auth bug"*, and it lands in your queue and surfaces in your next rundown. It works outbound too. Your @context can message people and channels on Slack on your behalf, and @-mention a teammate's @context to drop an update in *their* queue. That's how a team's contexts talk to each other (the [context network](docs/NETWORK.md)). This keeps your signal-to-noise high.
5. **Draft and schedule.** Connect [Gmail and Calendar](docs/GOOGLE.md), and @context reads your real inbox and calendar, drafts your follow-ups straight into Gmail for you to send, and sends calendar changes to your approvals queue.

## Security

@context is an alter ego with access to a lot of sensitive information, so the security boundaries need to be AIRTIGHT.

Agno's AgentOS makes two things possible:

1. **Verify the user making the request.** AgentOS extracts the `user_id` from the JWT or the Slack request, so we can tell whether the caller is the owner or a guest.
2. **Assign tools by role.** Based on that, we add the right tools to the agent.

This model lets us build a system that anyone can write to, but only you can read from or act through. To everyone else, it is a polite notetaker that only captures. Although it does remember who it is talking to: each caller gets their own user-memory, kept entirely separate from yours.

External actions are double gated. Changing your calendar (`update_calendar`) pauses for explicit approval before it runs, using AgentOS's `requires_confirmation` and `approval_type="required"` settings. Email goes a step further. `update_gmail` can *only* draft, so the follow-up waits in your Gmail drafts for you to review and send. It never sends on its own.

Everything runs locally or in your own cloud, inside your VPC. Every byte of data lives in your own database: the CRM, the knowledge base, and the inbox.

Read [`docs/SECURITY.md`](docs/SECURITY.md) for more details.

## Get started

> Requires [Docker](https://www.docker.com/get-started/) installed and running.

```sh
git clone https://github.com/agno-agi/context.git
cd context

# Configure credentials
cp example.env .env
# Open .env: set OPENAI_API_KEY, and set OWNER_ID to the email you sign in to os.agno.com with.
# OWNER_NAME is an optional display name, set it as your name.

# Run on Docker
docker compose up -d --build
```

Confirm it is live at [http://localhost:8000/docs](http://localhost:8000/docs).

## AgentOS UI

@context runs on AgentOS, which comes with a web UI for managing and monitoring @context. Use the AgentOS UI to chat with @context, view sessions, approve actions and more.

<img width="3066" height="2046" alt="Local Context AgentOS" src="https://github.com/user-attachments/assets/ee4b789a-1612-4b5d-9bd4-37e68ede91c4" />

1. Open [os.agno.com](https://os.agno.com) and sign in with your email (the same one you set as `OWNER_ID`).
2. Click **Connect AgentOS → Local**.
3. Enter `http://localhost:8000`, name it "Local Context" and connect.
4. Click on the chat button under Context.
5. Try one of the quick prompts.

## MCP server

The main way to use @context is from an MCP client like Claude Code, Codex, Claude, and ChatGPT. Connect your favorite AI tools to @context's MCP server at `http://localhost:8000/mcp`.

> Note: @context's MCP server is **owner-only**, so keep an eye on security.

### Add @context to MCP clients automatically

Add @context to every MCP client on your machine with one command:

```sh
python scripts/connect.py
```

The script finds Claude Code, Codex, and the Claude Desktop app, and registers @context with each. Use `--dry-run` to preview and `--remove` to undo. Once you've deployed, the same script points your clients at the live instance — see [Connect production @context MCP server](#connect-production-context-mcp-server).

### Add @context to MCP clients manually

For CLI clients, run the following commands:

```sh
claude mcp add -s user --transport http context http://localhost:8000/mcp   # Claude Code (user scope)

codex mcp add --url http://localhost:8000/mcp context                       # Codex
```

**Claude Desktop** needs that bridge in `claude_desktop_config.json`, because its "Add custom connector" dialog only accepts `https` URLs. Add this (keep any existing keys) and restart the app:

```json
{
  "mcpServers": {
    "context": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8000/mcp", "--transport", "http-only"]
    }
  }
}
```

See [`docs/MCP.md`](docs/MCP.md) for more details.

## Slack

Slack is where @context comes alive. It's the interface where I (@ashpreetbedi) use it the most and the interface that allows your team (and their agents) to talk to @context.

To set it up, you need to:
1. Create a Slack app
2. Get the Bot User OAuth Token and Signing Secret
3. Set the environment variables in `.env` or `.env.production`
4. Restart the application

Read [`docs/SLACK.md`](docs/SLACK.md) for the Slack setup guide.

## @context Knowledge Base

@context comes with a knowledge base that acts as its second brain. @context stores everything from product specs and research notes to "what I know about X" pages in this knowledge base.

The knowledge base is stored on the filesystem by default (a gitignored `knowledge/` folder in this repo) but I highly recommend pointing it to a git repo or notion database for production. See [`docs/KNOWLEDGE.md`](docs/KNOWLEDGE.md) for the full guide.

Try:
- *Write a one-pager on the advantages of building our own agent-platform*
- *Write up a decision: we're standardizing on agno*
- *What in my knowledge base needs attention?*

## @context CRM

@context comes with a CRM that gives it structured memory about people, projects, meetings, reminders, notes and contacts.

This auto-managing crm is @context's superpower. Use it to manage projects, meetings, reminders, notes, and contacts. @context maps what you tell it onto the right table - no forms, no fields - and can create new tables on demand. Try:
- *"Add Dana Reyes, Head of Platform at Acme, dana@acme.com - and remind me to send her the integration spec next Tuesday."*
- *"Who do I know at Acme?"*
- *"What reminders do I have coming up?"*
- *"Tell me about Northwind."*

@context's database lives in the `crm` Postgres schema: writes are confined to that schema and every row is scoped to your `user_id`, so a guest can't see this data. See [`docs/CRM.md`](docs/CRM.md) for the schema, the filing rules, and the write boundary.

## Run in production

@context runs anywhere that runs a Docker container.

For a quick deployment, the repo includes a script to run on Railway. The `scripts/railway/up.sh` script will run @context as a service with Postgres on the same private network. It reads credentials from `.env.production`, and creates a public domain you connect to in the AgentOS UI.

> Requires the [Railway CLI](https://docs.railway.com/cli#installing-the-cli)

### 1. Production env

Create the production environment file.

```sh
cp .env .env.production
```

The deploy scripts read `.env.production` first and fall back to `.env` if it doesn't exist.

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
5. Set the deploy branch to `main` and click **Deploy**

### 6. Point Slack at production

If you set Slack up locally, your Slack app's request URLs still point at your local @context via the ngrok tunnel.

Repoint the `/slack/events` and `/slack/interactions` request URLs to your Railway domain. AgentOS must already be deployed and serving traffic so Slack's URL re-verification passes.

See [`docs/SLACK.md`](docs/SLACK.md#moving-from-local-to-production) for full steps.

## Connect production @context MCP server

Once @context is deployed (you have a Railway domain), point your MCP clients at the production endpoint instead of localhost. The deployed server is JWT-gated, so this needs a bearer token. For the MCP server, we mint our own token and push it to Railway. This is scripted end to end:

```sh
source .venv/bin/activate          # mint needs pyjwt + cryptography (in requirements)
./scripts/setup_production_mcp.sh   # mint token → push public key → wire MCP clients
```

`setup_production_mcp.sh` runs three steps. Re-run it any time to rotate the token:

1. [`scripts/mint_mcp_jwt.py`](scripts/mint_mcp_jwt.py) — self-issues an RS256 keypair (private key stays local in gitignored `secrets/`) and writes the public key + a signed admin token to `.env.production`.
2. [`scripts/railway/env-sync.sh`](scripts/railway/env-sync.sh) — pushes the **public** key to Railway so the deploy trusts your token (the token itself stays off the server).
3. [`scripts/connect.py --production`](scripts/connect.py) — threads the token into Claude Code, Codex, and Claude Desktop.

You self-issue the token instead of copying one from os.agno.com, and @context trusts your key *alongside* the os.agno.com one — so the [AgentOS UI](#agentos-ui) keeps working too.

See [`docs/MCP.md`](docs/MCP.md#self-issued-production-token) for the full details: where the token comes from, per-client specifics (Codex's `$CONTEXT_JWT`, switching local→prod), ChatGPT/Claude web, and how it's secured.

## Connect @context knowledge base to Git

When testing locally we can use the local `knowledge/` folder to store the knowledge base. But in production we need to back the knowledge base with a durable solution like a Git repo.

Here's how to connect @context's knowledge base to a Git repo.

1. Open [github.com/new](https://github.com/new) and create a new repo for your @context's knowledge base.
   - Name: `your-username/your-context`
   - Visibility: Mark the repo as private.
   - Add README: Yes
2. Mint a GitHub token with push access to the repo.
   - Open [github.com/settings/personal-access-tokens](https://github.com/settings/personal-access-tokens) and create a new fine-grained token.
   - Click on **Generate new token**
   - Name: `Your Context`
   - Expiration: **No expiration**
   - Repository access: **Only select repositories** and select the repo you created in step 1.
   - **Add Permissions** -> **Select Contents**
   - Remember to update Access to **read and write**
   - Generate token and copy the token.
3. Add both to `.env.production`:
   ```sh
   KNOWLEDGE_REPO_URL=https://github.com/you/your-specs.git
   KNOWLEDGE_GITHUB_TOKEN=ghp_...
   ```
4. Sync to Railway:
   ```sh
   ./scripts/railway/env-sync.sh
   ```

See [`docs/KNOWLEDGE.md`](docs/KNOWLEDGE.md) for the full guide.

## Connect Gmail and Calendar

You can connect your Gmail and Calendar to @context to ground the rundown and meeting prep in your real inbox and calendar.

See [`docs/GOOGLE.md`](docs/GOOGLE.md) for more details.

## Understanding the codebase

@context has three main components. Review them in order.

### The app (`app/`)

@context is a FastAPI application running the AgentOS runtime. [`app/main.py`](app/main.py) is the entrypoint and [`app/settings.py`](app/settings.py) holds shared settings. [`app/identity.py`](app/identity.py) is where identity is validated. It looks dense, but all it does is check whether `user_id` is in the `OWNER_ID` list (comma-separated). [`app/mcp.py`](app/mcp.py) is the owner-only MCP server — one tool (`ask_context`) that lets you read, act, and file through @context from the Claude/ChatGPT desktop apps and CLI clients (see [MCP server](#mcp-server)).

### The agents (`agents/`)

The main agent is [`agents/context.py`](agents/context.py). `context_tools()` adds tools to the agent based on the caller's role, and `caller_information()` adds the matching instructions.

The supporting files:

- [`agents/instructions.py`](agents/instructions.py) defines the role-specific instructions.
- [`agents/sources.py`](agents/sources.py) defines the context providers (crm, knowledge, workspace, web, Slack, Gmail, Calendar) and how each registers its `query_` / `update_` tools.
- [`agents/inbox.py`](agents/inbox.py) defines the inbound queue: `submit_update` (anyone), then `rundown` / `acknowledge` (you only).
- [`agents/policy.py`](agents/policy.py) defines the pre-hook and tool-hook that back the owner/guest boundary.
- [`workflows/`](workflows/) defines the runnable `Workflow` objects (the reminder sweep, the digests) and `dm_owner`; [`app/schedules.py`](app/schedules.py) registers their crons. The reminder sweep (`workflows/reminders.py`) files due reminders into the inbound queue, run hourly by the `queue-reminders` schedule.

### The skills (`skills/`)

The repo has **two distinct kinds of skill**. Keep them separate.

- **Runtime skills** ([`skills/`](skills/)) are playbooks the deployed @context agent runs **for its owner**, invoked in natural language ("plan my week") and owner-gated. Add your own as needed.
- **Coding-agent workflows** ([`.agents/skills/`](.agents/skills/)) are `/slash-command` workflows your *coding agent* (Claude Code, Codex, others) runs while **developing this repo**. They are covered under [Working with coding agents](AGENTS.md#working-with-coding-agents).

Here are the runtime skills that are included in the repo:

- [`skills/week-plan/SKILL.md`](skills/week-plan/SKILL.md).
- [`skills/daily-rundown/SKILL.md`](skills/daily-rundown/SKILL.md).
- [`skills/prep-for/SKILL.md`](skills/prep-for/SKILL.md).
- [`skills/process-today/SKILL.md`](skills/process-today/SKILL.md).
- [`skills/research/SKILL.md`](skills/research/SKILL.md).
- [`skills/knowledge-review/SKILL.md`](skills/knowledge-review/SKILL.md).

## Evals

@context comes with an eval suite ([`evals/`](evals/)) for regression testing. It's tests the claim that: *anyone can write, only you can read.*

Run it:

```sh
python -m evals                # run the full suite
python -m evals -v             # stream the full agent run
python -m evals --case <name>  # one case
```

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | yes | none | OpenAI key for models and embeddings. |
| `OWNER_ID` | prd | none | Comma-separated identities that count as the owner (JWT `sub` and/or Slack email). First is canonical. Unset means capture-only for everyone. |
| `OWNER_NAME` | no | canonical `OWNER_ID` | Display name rendered into the prompt. Cosmetic, never matched as an identity. |
| `RUNTIME_ENV` | no | `prd` | `dev` enables hot-reload and disables JWT. Compose sets this to `dev` for local. |
| `JWT_VERIFICATION_KEY` | prd | none | Public key from os.agno.com. Required when `RUNTIME_ENV=prd`. |
| `CONTEXT_SELF_VERIFICATION_KEY` | no | none | A second JWT public key the app *also* trusts, alongside the os.agno.com key — your own, so tokens you self-issue with `scripts/mint_mcp_jwt.py` verify (the os.agno.com UI keeps working). Written by that script; pushed to the server by `env-sync.sh`. See [Connect production @context MCP server](#connect-production-context-mcp-server). |
| `CONTEXT_MCP_JWT` | no | none | The self-issued bearer token `scripts/connect.py --production` threads into your MCP clients. Client-side only (lives in `.env.production`, never pushed to the server). Minted by `scripts/mint_mcp_jwt.py`. |
| `AGENTOS_URL` | no | `http://127.0.0.1:8000` | Scheduler base URL. Also anchors the MCP server's Host allowlist — set it to your Railway/ngrok domain so the deployed or tunnelled `/mcp` endpoint accepts that Host (see [`docs/MCP.md`](docs/MCP.md)). |
| `INTERNAL_SERVICE_TOKEN` | no | auto-generated | Scheduler-to-OS auth token. The deploy runs 2 replicas, which share one — `scripts/railway/up.sh` pins it automatically (override in `.env.production`). See [`docs/SCALING.md`](docs/SCALING.md). |
| `PARALLEL_API_KEY` | no | none | Switches the `web` source from keyless Parallel MCP to the authenticated SDK (higher rate ceiling); recommended for production. Get a key at [platform.parallel.ai](https://platform.parallel.ai/settings?tab=api-keys). |
| `SLACK_BOT_TOKEN` / `SLACK_SIGNING_SECRET` | no | none | Both enable the Slack interface. The bot token alone activates the `slack` source (`query_slack` + the ungated `update_slack` send tool) and auto-arms the scheduled digests. See [`docs/SLACK.md`](docs/SLACK.md). |
| `DAILY_DIGEST_CRON` / `WEEKLY_DIGEST_CRON` | no | `0 13 * * *` / `0 22 * * 0` | UTC cron for the Slack-delivered daily rundown and weekly plan (only armed when Slack is set). See [`docs/SLACK.md`](docs/SLACK.md). |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_PROJECT_ID` | no | none | Connect your Gmail + Calendar; mint tokens with `python scripts/google_mint_tokens.py`. See [`docs/GOOGLE.md`](docs/GOOGLE.md). |
| `GMAIL_TOKEN_JSON_B64` / `CALENDAR_TOKEN_JSON_B64` | no | none | Minted Gmail/Calendar tokens as base64, so they survive a deploy. The entrypoint restores them at startup. See [`docs/GOOGLE.md`](docs/GOOGLE.md). |
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
