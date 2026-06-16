# Context MCP server

`@context` exposes itself as an **MCP server** so you can use it from MCP clients — Claude Code, Codex, the Claude and ChatGPT desktop apps, Cursor, and (once deployed) the web clients.

It's **owner-only** and on by default — [`app/main.py`](../app/main.py) mounts it at `/mcp`. It runs the agent as *you*, so never expose it without auth.

## The tool

`use_context(message, session_id?)` runs the *real* `context` agent ([`app/mcp.py`](../app/mcp.py)) as the owner — your full read/write/act surface behind one call. The agent decides what to do, so the same tool covers:

- **look things up** — "what's waiting on me?", "what do we know about Acme?", "what's on my calendar this week?"
- **save / update** — "met Sarah from Acme, follow up Friday", "we decided to ship MCP first"
- **act** — "draft a reply to Sarah", "tell the team the deck is ready"

One tool, not several: the client gets one obvious door for anything about your work, instead of a read-vs-write routing decision. `tools/list` returns exactly `["use_context"]` (input schema: `message` required, `session_id` optional — pass a stable `session_id` to continue a thread).

## Before you start

Bring `@context` up locally and confirm the endpoint is live:

```sh
docker compose up -d

curl -sS --max-time 10 -o /dev/null -w '%{http_code}\n' \
  -X POST http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
# 200 = up. (400 means the Host header isn't on the allowlist — see "How it's secured".)
```

Local dev runs without JWT, so any client on this machine that reaches `http://localhost:8000/mcp` is treated as **you, the owner** — the keyless-local-as-owner shortcut the rest of dev uses ([`app/mcp.py`](../app/mcp.py), `_resolve_caller_id`). That's the point locally, and the reason you don't expose a dev instance: anything on your machine that can reach the port gets your surface.

## Quick connect (one command)

From the repo root, with the stack up:

```sh
python scripts/connect.py            # add @context (local) to every MCP client found
python scripts/connect.py --production  # add the deployed instance (URL + JWT from .env.production)
python scripts/connect.py --dry-run  # preview, write nothing
python scripts/connect.py --remove   # undo
```

It detects Claude Code, Codex, the Claude Desktop app, and Cursor and wires @context into each — running `claude mcp add` / `codex mcp add` for the CLIs, writing an `mcp-remote` bridge into `claude_desktop_config.json` for the desktop app, and a native `{url, headers}` entry into `~/.cursor/mcp.json` for Cursor (absolute `npx` path resolved where a bridge is used, existing keys preserved, a timestamped backup made, anything already configured skipped). For Claude Code it also **always-allows** the `use_context` tool (adds `mcp__context__use_context` to `permissions.allow` in `~/.claude/settings.json`) so the agent never prompts you before calling it — see [Claude Code (CLI)](#claude-code-cli) below. Pure stdlib, so no venv needed. Useful flags: `--clients claude-code codex claude-desktop cursor` to limit the set, `--url` for a non-default endpoint, `--config-path` to point at a non-standard desktop config.

**`--production`** targets your deployed instance: it reads `AGENTOS_URL` from `.env.production`, derives `https://<your-domain>/mcp`, and threads `Authorization: Bearer <JWT>` into every client for you. The JWT is read from `CONTEXT_MCP_JWT` in `.env.production`, else `--token <JWT>`, else you're prompted — and you **self-issue** that token rather than copying one from os.agno.com (see [Self-issued production token](#self-issued-production-token) below). Claude Code gets the token via `--header`; Codex via `--bearer-token-env-var CONTEXT_JWT` (so it stays out of Codex's config — `export CONTEXT_JWT=<JWT>` in your shell); Claude Desktop via the bridge's `--header`; Cursor via the `headers` block in `~/.cursor/mcp.json`. Switching a client from local to prod? CLI clients match by name, so re-run with `--force`. The full setup — minting the token, what lands where — is in [Self-issued production token](#self-issued-production-token) below; the [README](../README.md#connect-production-context-mcp-server) has the one-command quick-start.

The per-client sections below are what it automates — reach for them to do it by hand, or to understand exactly what each form writes.

## Claude Code (CLI)

```sh
claude mcp add -s user --transport http context http://localhost:8000/mcp
claude mcp list      # context: http://localhost:8000/mcp (HTTP) - ✓ Connected
```

**Scope: `user`.** @context is a personal, machine-wide endpoint you want in *every* project, so register it at user scope (`-s user`). The default `local` scope would limit it to the current directory; `project` scope writes a shared `.mcp.json` into the repo, which would push a localhost-only, owner-bound connector onto everyone who clones it — wrong for a personal endpoint. The client then picks up `use_context` and uses it on its own; you rarely have to name @context.

**Always-allow the tool.** `claude mcp add` registers the server but doesn't grant it, so Claude Code prompts you on every call. `scripts/connect.py` adds the permission for you; to do it by hand, drop the tool's rule into `permissions.allow` in `~/.claude/settings.json` (user scope, to match the server registration):

```jsonc
{ "permissions": { "allow": ["mcp__context__use_context"] } }
```

This only governs Claude Code's local prompt — the server stays JWT + owner-gated and fail-closed (see [`docs/SECURITY.md`](SECURITY.md) L7), so allow-listing the tool here doesn't widen the production boundary. `python scripts/connect.py --remove` takes the rule back out.

For a deployed instance, add the auth header:

```sh
claude mcp add -s user --transport http \
  --header "Authorization: Bearer <JWT>" \
  context https://<your-domain>/mcp
```

## Codex (CLI)

```sh
codex mcp add --url http://localhost:8000/mcp context
codex mcp get context     # transport: streamable_http
```

`--url` registers a streamable-HTTP server — Codex writes it to `~/.codex/config.toml` as `[mcp_servers.context]`. No experimental flags are needed for an unauthenticated local server. For a deployed instance, put the JWT in an env var and point Codex at it:

```sh
export CONTEXT_JWT=<JWT>
codex mcp add --url https://<your-domain>/mcp --bearer-token-env-var CONTEXT_JWT context
```

## Claude Desktop

Claude Desktop runs on your machine, so it *can* reach `http://localhost:8000/mcp` — just not through its connector UI (that's the wrong door; see below). Use the config file instead. `scripts/connect.py` writes this for you; to do it by hand:

**Config-file + stdio bridge.** Claude Desktop's config-file MCP support is stdio-only, so bridge the HTTP endpoint with [`mcp-remote`](https://www.npmjs.com/package/mcp-remote). Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

Restart the app and `use_context` shows up under the app's tools. (Verified: `mcp-remote` connects to the local server over StreamableHTTP and proxies it to the app over stdio.) For a deployed instance, swap the URL for `https://<your-domain>/mcp` and pass the token with `--header "Authorization: Bearer <JWT>"` in the `args`.

> **`PATH` gotcha.** GUI apps on macOS don't inherit your shell `PATH`, so the app may fail to launch a bare `npx`. If the server doesn't connect, set `"command"` to the absolute path — find it with `which npx` (e.g. `/opt/homebrew/bin/npx` for a Homebrew Node). On Windows, Claude Desktop can't exec `npx.cmd` directly — use `"command": "cmd"` with `"args": ["/c", "npx", "-y", "mcp-remote", …]`. `scripts/connect.py` writes the right form for your OS automatically (the Windows path is best-effort — untested by us, since we develop on macOS).

**Why not the "Add custom connector" UI?** Recent Claude Desktop builds also offer **Settings → Connectors → Add custom connector (BETA)**. It's the wrong door for @context for two confirmed reasons: it **rejects `http://` URLs** ("URL must start with 'https'"), and its only auth option is **OAuth** (Client ID / Secret) — there's no field for the static `Authorization: Bearer <JWT>` our server uses, so even a deployed HTTPS instance won't authenticate through it. The config-file bridge above is the path that works: it takes the plain localhost URL and can carry a static bearer header.

## Cursor

Cursor speaks remote MCP **natively** — no `mcp-remote` bridge, no npx. `scripts/connect.py` writes this for you (it's one of the default clients); to do it by hand, add a `{url, headers}` entry to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "context": {
      "url": "https://<your-domain>/mcp",
      "headers": { "Authorization": "Bearer <JWT>" }
    }
  }
}
```

Restart Cursor and `use_context` shows up under its MCP tools. For a local instance, drop the `headers` block and use `http://localhost:8000/mcp` (no auth in dev). Same self-issued token as everywhere else (see [Self-issued production token](#self-issued-production-token) below).

## ChatGPT desktop

ChatGPT desktop has **no local MCP config** — there's no `claude_desktop_config.json` equivalent to write a stdio bridge into (verified on macOS by inspecting the app's support dir: only connectors/"Work with Apps" pairings, no `mcpServers`). It reaches MCP servers only as a **remote HTTPS connector**, so the one way to use @context from ChatGPT is a deployed or tunnelled HTTPS instance — the next section.

## ChatGPT web / Claude web / cloud (deploy or tunnel)

Cloud clients — ChatGPT on the web, Claude on the web — run on a remote server and **cannot reach your laptop**. They need a public HTTPS URL. Two ways, the same two we use for Slack.

**Deploy it (recommended).** Deploy `@context` (the Railway steps in the [README](../README.md)) and you get a public domain; the endpoint is `https://<your-domain>/mcp`. Production (`RUNTIME_ENV=prd`) turns JWT on, so the server is properly owner-gated. Add the connector with:

- **URL**: `https://<your-domain>/mcp`
- **Auth header**: `Authorization: Bearer <JWT>` — a token you self-issue (see [Self-issued production token](#self-issued-production-token) below); the `CONTEXT_MCP_JWT` value `scripts/mint_mcp_jwt.py` produces.
- Set `AGENTOS_URL` to your domain so the server accepts that Host (DNS-rebinding allowlist — see below).

**Tunnel for a quick test (ngrok).**

```sh
ngrok http 8000
# Set AGENTOS_URL to the tunnel domain so the server accepts that Host,
# then use https://<id>.ngrok.app/mcp
```

> ⚠️ A tunnel to a **dev** instance has no JWT, so the owner gate falls back to "you" for *anyone who has the URL* — an open door to your context. Only tunnel a `RUNTIME_ENV=prd` run (real JWT), or keep it ephemeral and shut it down right after.

**ChatGPT note.** ChatGPT reaches remote MCP servers through **Connectors** and the **Responses API** — both public-HTTPS only. The Responses API `mcp` tool is the smoothest path for a static-token server: pass `server_url` plus `headers: {Authorization: "Bearer <JWT>"}`. The consumer connector UI leans on OAuth and tier-gates some features, so the API path is the easier one today. (Documented from the API contract — not live-tested here.)

## Self-issued production token

The deployed server is JWT-gated, so every client needs a bearer token. You **self-issue** it rather than copying one from os.agno.com — which means the whole flow is scriptable and the token is durable (a config-file token you set once, not a short-lived browser session token).

**Why self-issue.** AgentOS verifies a JWT against any public key it's configured to trust, and [`verification_keys` is a list](https://docs.agno.com/agent-os/security/authorization/self-hosted) — it tries each until one matches. The deployed app trusts **two** keys: the os.agno.com control-plane key (`JWT_VERIFICATION_KEY`, appended automatically by AgentOS, so the [AgentOS UI](../README.md#agentos-ui) keeps working) **and** a key you own (`CONTEXT_SELF_VERIFICATION_KEY`, wired in [`app/main.py`](../app/main.py)). Both issuers work at once. os.agno.com holds the private half of *its* key, so it mints the UI's tokens; you hold the private half of *yours*, so you mint your own MCP token.

**Mint it.** [`scripts/mint_mcp_jwt.py`](../scripts/mint_mcp_jwt.py) (run in the venv — it needs `pyjwt` + `cryptography`):

```sh
python scripts/mint_mcp_jwt.py --write   # keypair (once) + signed admin token → .env.production
```

- Generates an RS256 keypair on first run. The **private** signing key lives in `secrets/` (gitignored, `chmod 600`) and never leaves your machine — the server only gets the public half.
- Writes `CONTEXT_SELF_VERIFICATION_KEY` (public key) and `CONTEXT_MCP_JWT` (a signed token: `sub` = your `OWNER_ID`, `scopes: ["agent_os:admin"]`, one-year expiry) to `.env.production`.
- `--rotate-key` regenerates the keypair (invalidates tokens minted with the old one); `--ttl-days N` and `--sub <id>` override the defaults.

**Then push + wire** (or run it all with one of the wrappers):

```sh
./scripts/railway/env-sync.sh           # push CONTEXT_SELF_VERIFICATION_KEY (the public key) to the deploy
python scripts/connect.py --production   # thread CONTEXT_MCP_JWT into your MCP clients
```

One script saves the steps: [`scripts/setup_context.sh`](../scripts/setup_context.sh) is the single production front door — `railway login` → reset client entries → mint (rotating the signing key) → `env-sync` → **`railway up` redeploy** (so a `railway.json` change like `numReplicas` lands) → wire all four clients → a "restart when you're ready" prompt. It never restarts your apps for you and never touches Postgres. Add **`--no-redeploy`** to skip the `railway up` step when you just want to rotate the token and rewire clients.

`env-sync.sh` pushes the public key but **skips `CONTEXT_MCP_JWT`** — the signing-grade token stays on your machine (read only by `connect.py`), never on the internet-facing box. The token starts verifying once Railway finishes redeploying with the new public key.

> Prefer not to run your own issuer? You can instead reuse an os.agno.com control-plane token — copy the `Authorization: Bearer …` value the UI sends (browser DevTools → Network → any request to your domain) and pass it as `--token`. It works, but those tokens expire, so it's better for a quick test than a token you paste into a client config.

## How it's secured

- **Owner-only, in code.** In prod the same JWT middleware AgentOS uses validates the token, then the `authorize` gate (`MCPServerConfig.authorize=_caller_is_owner`) 401s anyone who isn't in `OWNER_ID` — it never falls back to the guest surface. An unauthenticated call, a valid non-owner token, and the scheduler sentinel are all rejected. (Details: [`SECURITY.md`](SECURITY.md) L7.)
- **DNS-rebinding protection** is on (`MCPServerConfig.allowed_hosts`), because an always-on local server is exactly what it protects. The Host allowlist is anchored on localhost (so the desktop/CLI case needs no config) plus the host from `AGENTOS_URL` (so a deploy or tunnel works — point `AGENTOS_URL` at that domain). A request with any other Host is rejected with **400** (verified locally).
- **Acting.** Reads, drafting email, Slack messages, and filing all run to completion. The one approval-gated act tool — `update_calendar` — still pauses for approval, and there's no approval affordance over MCP, so the tool returns a note telling you to approve it in the AgentOS chat UI and ask it to continue.

## Verifying it runs as the owner

With the stack up, point a streamable-HTTP MCP client at `http://localhost:8000/mcp` (any of the clients above, or a short script using the `mcp` Python SDK's `streamablehttp_client`). `tools/list` returns `["use_context"]`; calling it with a workspace question — *"what is the MCP endpoint path and which file defines it?"* — comes back citing real repo files (proof the owner toolset is threaded through), and a statement to remember gets filed into your context.
