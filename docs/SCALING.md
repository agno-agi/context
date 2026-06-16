# Scaling @context

@context is a personal alter-ego — one person's context, one logical instance
backed by one shared Postgres. It ships on a **single replica**
(`numReplicas: 1` in [`railway.json`](../railway.json), 4Gi / 2 vCPU), and that
default is deliberate: the **remote MCP server needs it**.

## Why one replica (the MCP reason)

The owner's main way in is the MCP server (`use_context` / `ask_context` at
`/mcp` — see [`docs/MCP.md`](MCP.md)). MCP's streamable-HTTP transport is
**stateful**: the client opens a session (a POST that returns an
`Mcp-Session-Id`) and then keeps a server→client SSE stream open against *that
session*. The session lives **in memory on the replica that created it**.

Railway's HTTP proxy load-balances across replicas with **no session affinity**
(no sticky sessions). So with two replicas, the session created on replica A is
unknown to replica B — the SSE stream and the next call get round-robined to the
wrong replica and fail with **`Session not found` (-32600)** and intermittent
**`502 Bad Gateway`** on the SSE stream. (AgentOS has no shared/cross-replica MCP
session store today, so there's no in-app fix either.)

With **one replica** that whole class of failure is impossible — every request
lands on the one process that holds the session. For a single-owner personal
agent that's the right trade: one container comfortably handles one person's
traffic, the hourly reminder sweep, and the scheduled playbooks.

The cost: you give up zero-downtime rolling deploys and basic fault tolerance —
a deploy briefly drops the connection during the swap, and if the container
falls over there's no second one to carry traffic. For a tool you restart
rarely and talk to all day, a few seconds of downtime on deploy is a fine price
for an MCP connection that doesn't flake.

## The HA machinery is still here (harmless at one replica)

Two things @context does so it *can* run on more than one replica safely are
still wired in — they're no-ops at one replica, and ready if you scale up:

- **A shared `INTERNAL_SERVICE_TOKEN`.** The scheduler authenticates its run
  triggers to AgentOS with this token. It's auto-generated per process, so if
  each replica minted its own, a trigger signed by one would be rejected by the
  other (~half the time). [`scripts/railway/up.sh`](../scripts/railway/up.sh)
  pins one value at provision time and forwards it to the service, so every
  replica shares it — set your own in `.env.production` to override.

- **An HA-safe scheduler.** Every replica runs the scheduler loop, but each due
  job is claimed via a row-level lease on `agno_schedules`: the first replica to
  claim it runs it, the others skip. So the hourly reminder sweep and the
  daily/weekly digests fire **once**, not once per replica. (Belt and braces:
  the reminder sweep also claims each reminder atomically, so even concurrent
  sweeps would surface each one exactly once.)

The Gmail/Calendar token rides every replica fine, too: each decodes the same
`GMAIL_TOKEN_JSON_B64` / `CALENDAR_TOKEN_JSON_B64` env var to its own local
token file at boot (see [`docs/GOOGLE.md`](GOOGLE.md)) and refreshes
independently using the shared, stable refresh token — no coordination or
shared volume needed.

## Running more replicas

You *can* bump `numReplicas` and `limits` in [`railway.json`](../railway.json)
for redundancy or to put @context in front of a whole team — the shared-token
and scheduler arrangements above hold at three or four replicas with nothing new
to configure.

The **one caveat is the remote MCP server**: as above, it gets unreliable past
one replica because Railway can't pin a session to a replica. So scale up only
if you don't depend on the remote MCP path (e.g. you drive @context purely
through Slack), or put session affinity in front of it yourself. Everything else
— Slack, the schedules, the digests, the HTTP API — is happy at any replica
count.

## Capacity vs. redundancy

Replicas give you redundancy; they don't raise the ceiling for a single request.
Each replica still has the same 4Gi / 2 vCPU limit, so if the container is being
OOM-killed or crash-looping, adding replicas won't fix it — raise
`limits.memory` / `limits.cpu` in [`railway.json`](../railway.json) (or fix the
underlying spike) instead. `railway logs --service agent-os` shows the restart
reason.
</content>
</invoke>
