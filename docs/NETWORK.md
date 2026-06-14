# The context network

> Every teammate runs their own @context. They reach each other by messaging over Slack. The owner/guest rule holds across the network: anyone (or their agent) can write to a context, only its owner can read it.

This explains how @context instances message each other today, why it's safe, and the bigger version that's deferred.

## The idea

A team adopts @context one person at a time. Each deployment is single-owner: my context is mine, yours is yours. The value grows when they form a network. My context can reach you, reach your context, and leave you the kind of non-urgent update a teammate would, without crossing the read boundary that makes each context trustworthy.

## How it works today: over Slack

No new protocol, no directory, no extra auth. Two pieces that already exist:

1. **Sending.** `update_slack`, the owner's Slack send tool (see [SLACK.md](SLACK.md)). The owner can have their context @-mention another person's @context.
2. **Receiving.** The target context's Slack interface ([app/main.py](../app/main.py)). An @-mention is an inbound Slack event. The interface resolves the sender's verified Slack identity and runs the target context as that sender.

So a message from my context to yours travels:

```
my @context  --update_slack-->  Slack  --@mention-->  your @context
  (owner: me)                                          (sees sender = me)
                                                              |
                                       I'm not your OWNER_ID, so I'm a guest
                                                              |
                                                  submit_update -> your queue
```

My identity isn't your `OWNER_ID`, so your context gives my message the guest surface. It files an update in your queue (`from_person = me`, `ack_status = new`) and tells me it was passed along. It never reads your data back to me. Your next rundown surfaces it like any other teammate update.

### Why it's safe

The network doesn't weaken the security model, it reuses it. Every cross-context message is the same capture-only write ([SECURITY.md](SECURITY.md), L2) a person makes, just arriving over Slack. The receiving context decides owner vs guest in code, from the verified Slack identity. So:

- An agent can write to a peer's queue (the point) but can't read the peer's context. No read tool is ever in a guest's hand.
- `from_person` is the verified sender, not a model argument, so a context can't spoof who a message is from.
- Sending is ungated because Slack messaging is ordinary communication ([SECURITY.md](SECURITY.md), L6). The boundary is enforced on the receiving side, in code.

### Setup

Nothing beyond the standard Slack setup ([SLACK.md](SLACK.md)) on each deployment. The two contexts need to share a Slack workspace (or be in Slack Connect channels), each installed as its own app with its own bot user, so they can @-mention each other. The owner drives it in plain language ("tell Dana's context the Q3 deck is ready") and the `update_slack` sub-agent resolves the handle and posts.

## Deferred: a direct network (HTTP)

Slack messaging needs a shared Slack surface. The bigger version, where my context calls your context's API directly across orgs with no shared Slack, is deferred. What it would take, noted so we build it on purpose:

- **A directory.** Store each contact's context endpoint (e.g. a `context_url` column on `crm.contacts`) so "message Dana's context" resolves to a URL. The contacts table becomes the address book.
- **An outbound tool**, `message_context(contact, message)`, that POSTs to the peer's `/agents/context/runs` with my verified identity as the `user_id`. The peer's guest path files it. Owner-only, like every send tool.
- **The hard part: auth between contexts.** A production peer runs JWT auth, so an inbound POST needs a token it will verify. That means a shared secret per peer, a token the peer mints for known senders, or a small handshake. Until that's designed, the direct path only works against dev/unauthenticated peers, which isn't shippable.
- **Abuse surface.** Outbound POSTs to owner-set URLs, rate limits, and a way to block a noisy peer.

The Slack path covers the common case (a team on one workspace) with no new trust surface, so it ships first. The direct HTTP network is the next piece, for when cross-org reach is needed.
