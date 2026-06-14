# Federation — contexts talking to each other

> **One line:** every teammate runs their own `@context`; they reach each other
> by messaging over Slack, and the owner/guest asymmetry holds across the whole
> network — anyone (or their agent) can write to a context, only its owner can
> read it.

This doc describes how `@context` instances communicate today, why it's safe, and
the larger directory-based federation that's deferred to future work.

---

## The vision

A team adopts `@context` one person at a time. Each deployment is single-owner —
my context is mine, yours is yours — but the value compounds when they form a
network: my context can reach you, reach *your* context, and leave you the kind of
non-urgent update a teammate would. "Our contacts talk to each other." The goal is
a mesh of personal context agents that pass each other signal without ever
crossing the read boundary that makes each one trustworthy.

## How it works today: federation over Slack

No new protocol, no peer directory, no cross-org auth. It falls out of two pieces
that already exist:

1. **Sending** — `update_slack` (the owner's ungated Slack send tool, see
   [`docs/SLACK.md`](SLACK.md)). The owner can have their context **@-mention
   another person's `@context`** in a channel or DM.
2. **Receiving** — the target context's **Slack interface** ([`app/main.py`](../app/main.py)).
   An @-mention is an inbound Slack event; the interface resolves the *sender's*
   verified Slack identity and runs the target context under it.

Put them together and a message from my context to yours travels:

```
my @context ──update_slack──▶  Slack  ──@mention event──▶  your @context
   (owner: me)                                              (sees sender = me)
                                                                  │
                                              I am not your OWNER_ID, so I'm a GUEST
                                                                  │
                                                          submit_update ▶ your queue
```

Because my identity is not your `OWNER_ID`, **your** context hands my message the
capture-only surface: it files an update in your queue (`from_person = me`,
`ack_status = new`) and tells me it passed it along. It never reads your data back
to me. Your next rundown surfaces it like any other teammate update.

### Why this is safe

The security model isn't weakened by the network — it's *reused* by it. Every
cross-context message is just the **L2 capture-only write** ([`docs/SECURITY.md`](SECURITY.md))
arriving over Slack instead of from a human. The receiving context makes the
owner/guest decision in code from the verified Slack identity, exactly as it does
for a person. So:

- An agent can **write** to a peer's queue (that's the point) but can **never
  read** the peer's context — no read tool is ever in a guest's hand.
- `from_person` is the verified sender, not a model argument, so a context can't
  spoof who a federated update is from.
- The sending side is ungated because Slack messaging is ordinary communication
  ([`docs/SECURITY.md`](SECURITY.md) L6); the *receiving* side is where the
  boundary is enforced, and it's structural.

### Setup

Nothing beyond the standard Slack setup ([`docs/SLACK.md`](SLACK.md)) on each
deployment. The two contexts must share a Slack workspace (or be in
Slack-Connect channels), each installed as its own app with its own bot user, so
they can @-mention each other. The owner drives it in natural language — "tell
Dana's context the Q3 deck is ready" — and the `update_slack` sub-agent resolves
the handle and posts.

---

## Deferred: direct (HTTP) federation

Slack-based federation requires a shared Slack surface. The richer model — my
context calling **your** context's API directly, across orgs, with no shared
Slack — is deferred. Sketch of what it would take, captured so we build it
deliberately rather than half:

- **A peer directory.** Store each contact's context endpoint (e.g. a
  `context_url` column on `context.contacts`), so "message Dana's context"
  resolves to a URL. The contacts table becomes the address book.
- **An outbound tool** — `message_context(contact, message)` — that POSTs to the
  peer's `/agents/context/runs` with my verified identity as the `user_id`. The
  peer's existing guest path files it. (Owner-only, like every send tool.)
- **The hard part: cross-context auth.** A production peer runs JWT auth
  (`RUNTIME_ENV=prd`), so an inbound POST needs a token the peer will verify. That
  means either a shared secret per peer, a capability token the peer mints for
  known senders, or a small federation handshake. Until that's designed, direct
  federation only works against dev/unauthenticated peers, which isn't shippable.
- **Abuse surface.** Outbound POSTs to owner-configured URLs (SSRF is bounded by
  the directory being owner-curated), rate limits, and a way for an owner to
  block a noisy peer.

The Slack path above covers the stated need (a team on a shared workspace) with
zero new trust surface, so it ships first. Direct HTTP federation is the next
spec when cross-org reach is needed.
