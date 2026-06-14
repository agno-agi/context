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
- **Coding-agent workflows** ([`.agents/skills/`](.agents/skills/)) are `/slash-command` workflows your *coding agent* (Claude Code, Codex, others) runs while **developing this repo**. They are covered under [Working with coding agents](AGENTS.md#working-with-coding-agents).

Here are the runtime skills that are included in the repo:

- [`skills/week-plan/SKILL.md`](skills/week-plan/SKILL.md).
- [`skills/daily-rundown/SKILL.md`](skills/daily-rundown/SKILL.md).
- [`skills/prep-for/SKILL.md`](skills/prep-for/SKILL.md).
- [`skills/process-today/SKILL.md`](skills/process-today/SKILL.md).

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

## @context in Slack

Slack is where @context comes alive. It's the interface where I (@ashpreetbedi) use it the most and the interface that allows your team (and their agents) to talk to @context.

To set it up, you need to:
1. Create a Slack app
2. Get the Bot User OAuth Token and Signing Secret
3. Set the environment variables in `.env` or `.env.production`
4. Restart the application

Read [`docs/SLACK.md`](docs/SLACK.md) for the Slack setup guide.

Notes:
- Agno's AgentOS sets up the Slack interface when the `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` env vars are set.
- The `resolve_user_identity=True` flag tells the AgentOS to resolve the Slack user identity to an email, which is what `OWNER_ID` matches against.
- See [`app/main.py`](app/main.py) for the implementation.

## Connect Gmail and Calendar

With Google credentials configured, `query_gmail` / `query_calendar` ground the rundown and meeting prep in your real inbox and calendar. `update_gmail` / `update_calendar` draft the follow-up or book the slot, pausing for your approval before anything leaves.

Acting as you is double-gated: the act tools exist only in your toolset, and every call requires your explicit confirmation. [`docs/GOOGLE.md`](docs/GOOGLE.md) covers both auth paths (OAuth for personal accounts, service account for Workspace deploys).

## Evals

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

- [`AGENTS.md`](AGENTS.md): architecture and conventions (source of truth for coding agents).
- [Agno documentation](https://docs.agno.com)
- [AgentOS introduction](https://docs.agno.com/agent-os/introduction)
- [Agno on GitHub](https://github.com/agno-agi/agno) (drop a star if this is useful).