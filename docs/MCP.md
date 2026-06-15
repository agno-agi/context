# Context MCP server

`@context` exposes itself as an **MCP server** so you can use it from MCP clients — Claude Code, Codex, the Claude and ChatGPT desktop apps, and (once deployed) the web clients.

It's **always on** — [`app/main.py`](../app/main.py) mounts it at `/mcp`, it's not a setting you opt into — and **owner-only**: it runs the agent as *you*, so never expose it without auth.

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
# 200 = up. (421 means the Host header isn't on the allowlist — see "How it's secured".)
```

Local dev runs without JWT, so any client on this machine that reaches `http://localhost:8000/mcp` is treated as **you, the owner** — the keyless-local-as-owner shortcut the rest of dev uses ([`app/mcp.py`](../app/mcp.py), `_resolve_caller_id`). That's the point locally, and the reason you don't expose a dev instance: anything on your machine that can reach the port gets your surface.

## Claude Code (CLI)

```sh
claude mcp add -s user --transport http context http://localhost:8000/mcp
claude mcp list      # context: http://localhost:8000/mcp (HTTP) - ✓ Connected
```

**Scope: `user`.** @context is a personal, machine-wide endpoint you want in *every* project, so register it at user scope (`-s user`). The default `local` scope would limit it to the current directory; `project` scope writes a shared `.mcp.json` into the repo, which would push a localhost-only, owner-bound connector onto everyone who clones it — wrong for a personal endpoint. The client then picks up `use_context` and uses it on its own; you rarely have to name @context.

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

## Claude / ChatGPT desktop apps

The desktop apps run on your machine, so they *can* reach `http://localhost:8000/mcp` — but how you add it depends on the build.

**Config-file + stdio bridge (works everywhere).** The desktop apps' config-file MCP support is stdio-only, so bridge the HTTP endpoint with [`mcp-remote`](https://www.npmjs.com/package/mcp-remote). For Claude Desktop, add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

> **`PATH` gotcha.** GUI apps on macOS don't inherit your shell `PATH`, so the app may fail to launch a bare `npx`. If the server doesn't connect, set `"command"` to the absolute path — find it with `which npx` (e.g. `/opt/homebrew/bin/npx` for a Homebrew Node).

**Why not the "Add custom connector" UI?** Recent Claude Desktop builds also offer **Settings → Connectors → Add custom connector (BETA)**. It's the wrong door for @context for two confirmed reasons: it **rejects `http://` URLs** ("URL must start with 'https'"), and its only auth option is **OAuth** (Client ID / Secret) — there's no field for the static `Authorization: Bearer <JWT>` our server uses, so even a deployed HTTPS instance won't authenticate through it. The config-file bridge above is the path that works: it takes the plain localhost URL and can carry a static bearer header.

## ChatGPT / cloud clients (deploy or tunnel)

Cloud clients — ChatGPT on the web, Claude on the web — run on a remote server and **cannot reach your laptop**. They need a public HTTPS URL. Two ways, the same two we use for Slack.

**Deploy it (recommended).** Deploy `@context` (the Railway steps in the [README](../README.md)) and you get a public domain; the endpoint is `https://<your-domain>/mcp`. Production (`RUNTIME_ENV=prd`) turns JWT on, so the server is properly owner-gated. Add the connector with:

- **URL**: `https://<your-domain>/mcp`
- **Auth header**: `Authorization: Bearer <JWT>` — the token os.agno.com mints for your AgentOS (the same one the REST API uses).
- Set `AGENTOS_URL` to your domain so the server accepts that Host (DNS-rebinding allowlist — see below).

**Tunnel for a quick test (ngrok).**

```sh
ngrok http 8000
# Set AGENTOS_URL to the tunnel domain so the server accepts that Host,
# then use https://<id>.ngrok.app/mcp
```

> ⚠️ A tunnel to a **dev** instance has no JWT, so the owner gate falls back to "you" for *anyone who has the URL* — an open door to your context. Only tunnel a `RUNTIME_ENV=prd` run (real JWT), or keep it ephemeral and shut it down right after.

**ChatGPT note.** ChatGPT reaches remote MCP servers through **Connectors** and the **Responses API** — both public-HTTPS only. The Responses API `mcp` tool is the smoothest path for a static-token server: pass `server_url` plus `headers: {Authorization: "Bearer <JWT>"}`. The consumer connector UI leans on OAuth and tier-gates some features, so the API path is the easier one today. (Documented from the API contract — not live-tested here.)

## How it's secured

- **Owner-only, in code.** In prod the same JWT middleware AgentOS uses validates the token, then `OwnerOnlyMiddleware` 401s anyone who isn't in `OWNER_ID` — it never falls back to the guest surface. An unauthenticated call, a valid non-owner token, and the scheduler sentinel are all rejected. (Details: [`SECURITY.md`](SECURITY.md) L7.)
- **DNS-rebinding protection** is on, because an always-on local server is exactly what it protects. The Host allowlist is anchored on localhost (so the desktop/CLI case needs no config) plus the host from `AGENTOS_URL` (so a deploy or tunnel works — point `AGENTOS_URL` at that domain). A request with any other Host is rejected with **421** (verified locally).
- **Acting.** Reads, drafting email, Slack messages, and filing all run to completion. The one approval-gated act tool — `update_calendar` — still pauses for approval, and there's no approval affordance over MCP, so the tool returns a note telling you to approve it in the AgentOS chat UI and ask it to continue.

## Verifying it runs as the owner

With the stack up, point a streamable-HTTP MCP client at `http://localhost:8000/mcp` (any of the clients above, or a short script using the `mcp` Python SDK's `streamablehttp_client`). `tools/list` returns `["use_context"]`; calling it with a workspace question — *"what is the MCP endpoint path and which file defines it?"* — comes back citing real repo files (proof the owner toolset is threaded through), and a statement to remember gets filed into your context.
