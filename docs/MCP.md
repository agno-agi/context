# Context MCP server

`@context` exposes itself as an **MCP server** so you can use context from your favorite MCP clients like Claude and ChatGPT.

Desktop apps can reach it on localhost with zero setup.
CLI clients like claude code and codex can reach it on localhost with zero setup.
Cloud clients can reach an ngrok tunnel or a deployed instance.

The client automatically learns what `@context` is and uses it on its own, so you often don't even have to ask for it by name.

It's **always on** — not a setting you opt into — and **owner-only**:

It runs the agent as *you*, so remember to never expose this server without security.

## The two tools

Both run the *real* `context` agent ([`app/mcp.py`](../app/mcp.py)) as the owner,
so they get your full read/write surface. They differ only in *when* the client
should reach for them:

| Tool | For | Examples |
|---|---|---|
| `ask_context(message, session_id?)` | Reading / acting | "what's waiting on me?", "what do we know about Acme?", "draft a reply to Sarah" |
| `update_context(message, session_id?)` | Filing / updating | "met Sarah from Acme, follow up Friday", "we decided to ship MCP first", "remind me to review the deck tomorrow" |

`session_id` is optional — pass a stable one to continue a thread.

## Use it from a desktop app (local, zero setup)

The desktop apps run on your machine, so they can reach `http://localhost:8000/mcp`
directly. Bring `@context` up locally (`docker compose up -d`) and add a connector:

- **URL**: `http://localhost:8000/mcp`
- **Auth**: none locally (dev runs without JWT; the server binds to you as the
  owner — the same keyless-local-as-owner shortcut the rest of dev uses).

Claude Desktop / ChatGPT desktop will list `ask_context` and `update_context`.
That's the whole setup.

> Localhost only works from an app on the **same machine**. A cloud model
> (ChatGPT on the web, Claude on the web) runs on a remote server and cannot
> reach your laptop — for those, deploy or tunnel (below).

## Use it from the cloud (deploy, or ngrok)

Cloud clients need a public HTTPS URL. Two ways, the same two we use for Slack:

**Deploy it (recommended).** Deploy `@context` (see the Railway steps in the
[README](../README.md)) and you get a public domain. The MCP endpoint is
`https://<your-domain>/mcp`. In production `RUNTIME_ENV=prd` turns JWT on, so the
server is properly owner-gated. Add the connector with:

- **URL**: `https://<your-domain>/mcp`
- **Auth header**: `Authorization: Bearer <JWT>` — the token os.agno.com mints
  for your AgentOS (the same one the REST API uses).

**Tunnel for a quick test (ngrok).** Same trick as local Slack dev:

```bash
ngrok http 8000
# Point AGENTOS_URL at the tunnel domain so the server accepts that Host
# (DNS-rebinding protection — see below), then use https://<id>.ngrok.app/mcp
```

⚠️ A tunnel to a **dev** instance has no JWT, so the owner gate falls back to
"you" for *anyone who has the URL* — i.e. an open door to your context. Only
tunnel a `RUNTIME_ENV=prd` run (real JWT), put auth on the tunnel, or keep it
ephemeral and shut it down right after.

### ChatGPT specifics

ChatGPT reaches remote MCP servers through **Connectors** and the **Responses
API** — both public-HTTPS only, same as above. The smoothest path for these two
tools is the Responses API `mcp` tool: pass `server_url` + `headers:
{Authorization: "Bearer <JWT>"}`, which works with our static token. The consumer
connector UI leans on OAuth and tier-gates some features, so the API / developer
path is the easier one today.

## How it's secured

- **Owner-only, in code.** In prod the same JWT middleware AgentOS uses validates
  the token, then `OwnerOnlyMiddleware` 401s anyone who isn't in `OWNER_ID` — it
  never falls back to the guest surface. An unauthenticated call, a valid
  non-owner token, and the scheduler sentinel are all rejected. (Details:
  [`SECURITY.md`](SECURITY.md) L7.)
- **DNS-rebinding protection** is on, since an always-on local server is exactly
  what it protects. The Host allowlist is anchored on localhost (so the desktop
  case needs no config) plus the host from `AGENTOS_URL` (so a deploy or tunnel
  works — point `AGENTOS_URL` at that domain). A request with any other Host is
  rejected with 421.
- **Acting.** Reads, drafting email, Slack messages, and filing all run to
  completion. The one approval-gated act tool — `update_calendar` — still pauses
  for approval, and there's no approval affordance over MCP, so the tool returns
  a note telling you to approve it in the AgentOS chat UI and ask it to continue.

## Verifying locally

With the stack up, point a streamable-HTTP MCP client at
`http://localhost:8000/mcp` (mirroring `cookbook/05_agent_os/mcp_demo/test_client.py`
in the Agno repo). `list_tools` returns `["ask_context", "update_context"]`;
`ask_context` with a workspace question comes back citing real files (proof the
owner toolset is threaded through), and `update_context` files what you tell it.
