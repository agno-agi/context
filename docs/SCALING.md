# Scaling @context

@context is a personal alter-ego — one person's context, one logical instance
backed by one shared Postgres. But "one instance" isn't "one container": it
ships on **two replicas** (`numReplicas: 2` in [`railway.json`](../railway.json),
4Gi / 2 vCPU each), which is Agno's default Railway footprint. Two replicas buy
two things a single container can't:

- **Zero-downtime rolling deploys** — one replica keeps serving while the other
  restarts on a new build.
- **Basic fault tolerance** — if one falls over, the other carries the traffic.

For a service you talk to all day and that runs scheduled work in the
background, that redundancy is the right default — it's about staying up, not
horizontal scale for load. Both replicas share one Postgres (sessions, memory,
the structured store, the queue), so they're interchangeable: any replica can
serve any request, and the data layer needs nothing special.

## What multiple replicas need — both already handled

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

## Running more (or fewer)

Bump `numReplicas` and `limits` in [`railway.json`](../railway.json) as usage
grows — say, putting @context in front of a whole team on Slack, or running
heavy scheduled work alongside live traffic. Everything above still holds at
three or four replicas; there's nothing new to configure.

You *can* drop to `numReplicas: 1` to halve the cost if you don't need
zero-downtime deploys — a single container handles one person's traffic, the
hourly sweep, and scheduled playbooks without breaking a sweat. The token and
scheduler arrangements above are harmless at one replica, so it's a pure config
change.

## Capacity vs. redundancy

Replicas give you redundancy; they don't raise the ceiling for a single request.
Each replica still has the same 4Gi / 2 vCPU limit, so if one is being
OOM-killed or crash-looping, adding replicas won't fix it — raise
`limits.memory` / `limits.cpu` in [`railway.json`](../railway.json) (or fix the
underlying spike) instead. `railway logs --service agent-os` shows the restart
reason.
