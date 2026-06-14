# Scaling @context

@context is a personal alter-ego — one person's context, one running instance.
So it ships on **a single replica** (`numReplicas: 1` in
[`railway.json`](../railway.json)), which is plenty: a single container handles
your traffic, the hourly reminder sweep, and scheduled playbooks without
breaking a sweat. You don't need to think about this unless you're deliberately
running it for heavier or shared use.

## Running more than one replica

If you do scale out (bump `numReplicas`, or run several instances behind one
domain), two things matter:

- **Pin `INTERNAL_SERVICE_TOKEN`.** The scheduler authenticates its run
  triggers to AgentOS with this token. It's auto-generated per process, so with
  more than one replica each would generate a different one and the triggers
  wouldn't line up. Set a fixed value in `.env.production` and sync it so every
  replica shares it. (Already noted next to the scheduler in
  [`AGENTS.md`](../AGENTS.md).)

- **The Gmail/Calendar token rides every replica fine.** Each replica decodes
  the same `GMAIL_TOKEN_JSON_B64` / `CALENDAR_TOKEN_JSON_B64` env var to its own
  local token file at boot (see [`docs/GOOGLE.md`](GOOGLE.md)). They each refresh
  independently using the shared refresh token, which is stable and safe to use
  from several instances at once — no coordination or shared volume needed. The
  short-lived access token a replica refreshes to is local and disposable; the
  durable part comes back from the env var on every restart.

Postgres (sessions, memory, the structured store, the queue) is already shared,
so the data layer needs nothing special — the reminder sweep claims each due
reminder atomically, so even concurrent sweeps fire each one exactly once.

## When you might actually want to

The honest answer for a personal alter-ego is "rarely." Reach for more than one
replica if you're putting @context in front of a whole team on Slack and want
headroom/redundancy, or you're running heavy scheduled work alongside live
traffic. For one person, one replica is the right default — scale up only when
you can point at the load that needs it.
