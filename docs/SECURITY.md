# Security & Authorization

How `@context` enforces the owner/guest boundary. This is the heart of the
product: **anyone can write to your context. Only you can read it — or act
through it.**

---

## The model in one paragraph

`@context` is an alter-ego. A teammate @-mentions it (in Slack, say) to file an
update; the owner gets briefings, moves items to acknowledged, and lets context
act on their behalf. That **asymmetry is the security model**, and it's enforced
**in code from a trusted identity** — never in the prompt (a prompt rule is
exactly what prompt injection defeats). It only works because the owner runs the
deploy: their database, their knowledge base, their keys.

## Threat model

| We protect | Against | Mechanism |
|---|---|---|
| The owner's stored context (CRM, knowledge base, queue) | Any guest caller reading it | Identity-conditioned toolset — guests get no read tools |
| The ack axis (what's "handled") | Anyone but the owner marking items done/acknowledged | Only the owner's toolset has the ack tool |
| Acting *as* the owner (changing the calendar) | The model doing it unprompted; guests triggering it | Owner-only act tool + a per-call approval gate — the run pauses until the owner confirms (L6). Email is draft-only, so @context never sends. |
| Reading / acting / filing through the MCP server | Any non-owner reaching the `/mcp` connector | Owner-only, fail-closed gate — JWT then an owner check that 401s everyone else; DNS-rebinding protection on (L7) |
| Identity itself | A caller or the model forging "I am the owner" | Trusted identity from verified JWT / Slack HMAC, not the request body |
| Data at rest | Cross-user reads via the OS REST API | `user_isolation` + `user_id`-scoped engines |

Out of scope (assumptions): we trust the Slack workspace and the IdP that mints
JWTs; we trust the owner's own machine and deploy. Single-owner deploy.

---

## Where identity comes from (trust roots)

Identity always arrives normalized on `run_context.user_id`. Two inbound paths,
two roots — both compared against one `OWNER_ID`. (A third, narrower root
covers the scheduler — see below.)

**HTTP / UI — JWT.** When AgentOS authorization is on (production), the JWT
middleware verifies the token signature and the run route prefers the verified
`sub` over any caller-supplied `user_id` form field — so identity is
non-forgeable. ⚠️ With authorization off / no `JWT_VERIFICATION_KEY`, the run
falls back to the **forgeable** form `user_id`. **Production must run with auth
on.** `@context` gates `authorization` on `RUNTIME_ENV == "prd"`.

**Slack — HMAC + event author.** Slack requests are verified by HMAC-SHA256 over
the raw body (with a replay window), and the author is `event["user"]` — outside
the signed body, so the model can't forge it. With `resolve_user_identity=True`
the Slack interface maps that to the user's **email** and sets it as the run's
`user_id`. Set `resolve_user_identity=True` so the owner check is against a
stable email.

**Scheduler — internal service token.** AgentOS's scheduler triggers runs over
HTTP, authenticated with the OS's *internal service token* (auto-generated per
process, or pinned via `INTERNAL_SERVICE_TOKEN` for multi-replica deploys). The
auth middleware resolves that token to the verified identity `"__scheduler__"`,
and — like a JWT `sub` — the run route prefers it over any payload `user_id`.
`is_owner` accepts it whenever an owner is configured: scheduled playbooks (the
`queue-reminders` sweep) are the owner's own automation, so they run with the
owner surface and key their writes under the canonical id. The trust chain: only the
in-process scheduler holds the token, and *creating* schedules requires
authenticated access to the OS routes in the first place.

**Normalization.** `OWNER_ID` holds the owner's identity in each space (JWT
`sub` and/or Slack email), comma-separated. `is_owner(run_context)`
([`app/identity.py`](../app/identity.py)) compares `run_context.user_id` against
it. Everything downstream keys off that one verdict, derived **fresh per run**.
(`OWNER_NAME` is a display name rendered into prompts — cosmetic only;
`is_owner` never matches against it.)

---

## Enforcement layers (defense in depth)

### L1 — Identity-conditioned toolset (primary)

The owner-vs-other decision is made **before the model runs**, by choosing the
toolset from the trusted identity. [`context_tools()`](../agents/context.py) is a
callable `tools=` resolved per run (`cache_callables=False`):

```python
def context_tools(run_context):
    if not is_owner(run_context):
        return [submit_update]              # capture-only
    return [*all_provider_tools(), list_contexts, rundown, acknowledge, queue_reminders]  # full
```

The model **never sees** the privileged tools for a guest — so "don't answer
questions about the owner" is structural, not a prompt instruction.

The same gate covers **runtime skills** (owner-only playbooks in
[`skills/`](../skills/)). The `get_skill_*` access tools are added only in the
owner branch of `context_tools`, and the skills "browse" snippet only renders
in the owner branch of `caller_information` — so a guest's toolset *and* prompt
carry zero skill references. Skills are a
capability layered over the existing tools, not a new trust boundary.

**The prompt mirrors the toolset.** `caller_information` resolves the
identity-specific block of the system prompt per run: the owner gets the full
playbook (live provider list, routing, the queue, skills); everyone else gets
a capture-only guide that names the owner and states that the configured
providers are not accessible in this session. A guest's prompt never
advertises the owner surface.

### L2 — Capture-only surface + the one deliberate cross-user write

Guests get exactly one context tool: `submit_update`
([`agents/inbox.py`](../agents/inbox.py)). No `query_*`, no reads, no briefing.
It appends to the **owner's** queue (`crm.updates`, `user_id = OWNER`,
`from_person = <caller>`, `ack_status = 'new'`). This is the single allowed
cross-user operation, and it's safe because it's **append-only with no
readback** — a teammate can drop a note in your inbox but can't read your inbox.
`from_person` is taken from the verified identity, never a model argument, so a
caller can't spoof who an update is from.

**Per-user memory + profile — the one capability every caller keeps.**
The agent's `learning=LearningMachine(...)` — user profile + user memory, both
agentic ([`agents/context.py`](../agents/context.py)) — gives every caller —
owner or not — two learning tools (`update_user_memory`, `update_profile`),
outside the identity-conditioned toolset (the L4 tool-hook allowlists both so
the gate doesn't block them). This is deliberate: an alter-ego should remember
the people (and agents) who talk to it, so a returning teammate gets continuity.
It adds no read path into the owner's context: memories and profile fields are
keyed to the **caller's** verified `user_id` — closed over in code when the
tools are built per run, never a model argument — recall injects only that same
caller's data on later runs, and the OS learning routes are scoped by
`user_isolation` (L5). What a teammate tells @context is remembered *about
them, for them* — never blended into the owner's CRM, knowledge base, or queue.

### L3 — The ack axis is owner-only, for free

Every update carries two axes: *work status* (`done` / `in_progress` /
`blocked` — anyone may set via `submit_update`) × *ack status*
(`new → briefed → acknowledged` — **only the owner moves it**). "Give me a
rundown" = `ack_status <> 'acknowledged'`, grouped blocked → done → in
progress. Because only the owner's toolset contains `rundown` / `acknowledge`,
"only you can acknowledge" needs no extra check — it falls out of L1.

### L4 — Pre-hook and tool-hook (independent backstops)

[`agents/policy.py`](../agents/policy.py) re-asserts the boundary independently
of the toolset:

- `normalize_identity` (**pre-hook**) fails closed, then canonicalizes. In
  production a run carrying no verified identity is refused with
  `InputCheckError` (the one exception type a pre-hook may raise — everything
  else is silently swallowed); agno substitutes the agent-level `"anon"`
  default before hooks run, so that sentinel is what a bypassed-auth request
  looks like. Then any configured owner identity (Slack email, JWT `sub`) is
  rewritten to the canonical `OWNER_ID`, so the structured store, knowledge
  base, and queue key under one identity instead of fragmenting per channel.
- `enforce_capture_only` (**tool-hook**) gates *every* tool call: a guest may
  only invoke the capture-only allowlist — `submit_update` plus the per-caller
  learning tools (`update_user_memory` / `update_profile`, see L2). Anything
  else is soft-blocked:
  the hook returns refusal guidance instead of executing the tool, so no data
  is read or written but the model can still reply gracefully. If L1 ever
  regressed and handed a guest a privileged tool, this still blocks the call.

### L5 — Data at rest

- `AuthorizationConfig(user_isolation=True)` scopes the OS REST routes
  (sessions / memory / runs) to the verified JWT user.
- The two-engine split on the `crm` schema — a write-guarded engine
  (`search_path` + a SQLAlchemy guard rejecting writes to `public`/`ai`) and a
  Postgres-level read-only engine (`default_transaction_read_only=on`). See
  [`db/session.py`](../db/session.py).
- The `crm` read/write sub-agents scope every query to `user_id` in their
  tuned prompts.

### L6 — Acting as the owner requires explicit approval

Reading and filing stay inside the owner's own store. Two write tools reach
*the owner's name*, and they're handled differently by design:

- **Email is draft-only.** `update_gmail` can only create or edit a Gmail
  **draft** — the send tools are stripped from its write toolkit
  ([`_create_gmail_provider`](../agents/sources.py)), so @context physically
  cannot send. A draft is private and reversible (it waits in your Drafts until
  *you* send it), so it's *not* an act tool and needs no gate. The review step
  is the draft itself — stronger than an approval popup, because you can fix the
  wording before it goes.
- **Calendar is approval-gated.** `update_calendar` changes the real calendar,
  so it's the one tool in `ACT_TOOLS`. [`context_tools()`](../agents/context.py)
  flags it `requires_confirmation` — agno pauses the run *before it executes*
  and resumes only when the owner confirms (in the os.agno.com chat UI / the
  approvals queue, or via the continue-run API). The model cannot self-approve;
  declining discards the call.

**Messaging is not an act tool — it's ungated by design.** `update_slack` (post
to a channel, reply in a thread, DM a teammate, @-mention another person's
`@context`) is deliberately *not* in `ACT_TOOLS`. Sending a Slack message is
ordinary communication, not a high-stakes action taken *as* the owner, so it runs
ungated like any chat reply. It stays **owner-only** the same way every write tool
does (L1) — a guest never holds it — but it does **not** pause for approval. The
approval gate is reserved for the one genuinely sensitive outward action —
mutating the calendar (email only ever drafts, so it isn't gated). This ungated messaging is exactly what
lets contexts talk to each other, the context network — see [`docs/NETWORK.md`](NETWORK.md). (A
scheduled **digest** rides a separate, also-ungated path: it DMs the owner
*themselves* via `workflows/notify.py`, which is self-notification, not an outward
act.)

The asymmetry extends cleanly: *anyone can write **to** your context; only you
can read it — and nothing **sensitive** leaves **as** you without your sign-off.* You
send the email yourself (it's only ever a draft); the one gated action is the
calendar. A scheduled run that reaches the calendar act tool pauses too — there's
no one to approve mid-schedule, so unattended automation can read, draft, file,
and message, but never change the calendar. (To let @context send email for you,
re-enable the send tools and add `update_gmail` to `ACT_TOOLS` so sends are
approval-gated like the calendar — see [`docs/GOOGLE.md`](GOOGLE.md).)

### L7 — The MCP server is owner-only, fail-closed

The MCP server ([`app/mcp.py`](../app/mcp.py), [`docs/MCP.md`](MCP.md)) is
**on by default** and exposes one tool, `ask_context`, so the owner can drive
`@context` from MCP clients — the CLI clients (Claude Code, Codex) register it on
localhost with one command, the desktop apps through a small stdio bridge. It is
**not** a new trust boundary: it's the *same*
`context` agent reached over a different transport, so the whole owner/guest model
above still applies. What's specific to it is the door: it must admit only the
owner, and fail closed.

It's the **same "structural, not a prompt rule" pattern**, applied to a network
endpoint — the gate is in code, before the model runs:

- **JWT first (prod).** The server reuses the *same* `authorization_config`
  AgentOS uses for the REST API (passed in from [`app/main.py`](../app/main.py)),
  so the verified `sub` arrives identically — non-forgeable.
- **Owner check, then 401.** The `authorize=_caller_is_owner` gate
  (`MCPServerConfig`, run by AgentOS after JWT verification) rejects anyone who
  is not in `OWNER_ID` with **401** — it never falls back to the capture-only
  guest surface. An unauthenticated call, a valid non-owner token, and the
  `__scheduler__` sentinel are all rejected (the human read/act path is stricter
  than `is_owner` — the scheduler never calls it). With no owner configured the
  gate 401s everyone.
- **Owner identity threaded through.** AgentOS injects the verified JWT `sub`
  as the tool's `user_id` and hides it from the client-facing schema, so a caller
  can never supply or spoof it; `ask_context` re-checks it (`_caller_is_owner`)
  as defense in depth, then runs `context.arun(…, user_id=<canonical owner>)`, so
  `is_owner` is true and `context_tools` hands over the full read/act surface —
  the owner acts *as* the owner. The gated act tool (calendar) still pauses for
  approval (L6); there's no approver over MCP, so it returns a note pointing at
  the chat UI.
- **DNS-rebinding protection.** An always-on *local* MCP server is a classic
  DNS-rebinding target — and in dev there's no JWT, so a rebinding request would
  otherwise reach the owner surface. So host/origin validation is on
  (`MCPServerConfig.allowed_hosts`), anchored on localhost (the desktop case needs
  no config) plus the host from `AGENTOS_URL` (so a deploy / tunnel works). Any
  other Host is rejected with 400 before the gate even runs.

We use AgentOS's native MCP server (`enable_mcp_server=True`,
`mcp_config=context_mcp_config()`) — the owner gate, DNS-rebinding protection, and
`user_id` injection are all configured on the `MCPServerConfig`, so there's no
custom middleware to maintain. In dev (no JWT) the gate binds to the canonical
`OWNER_ID`, the same keyless-local-as-owner shortcut used elsewhere — dev-only.
The deterministic eval `mcp_server_is_owner_only` proves the gate accepts the
owner and 401s everyone else, no model in the loop.

---

## Identity → behavior

| Caller | Identity source | Toolset | Read owner data? | Move `ack_status`? | Act as the owner? |
|---|---|---|---|---|---|
| **Owner** | JWT `sub` / Slack email == `OWNER_ID` | full | ✅ | ✅ | ✅ after per-call approval |
| **Scheduler** | internal service token → `__scheduler__` | full (owner's automation) | ✅ | ✅ | ⏸ pauses — no one to approve |
| **Teammate** | Slack email ≠ `OWNER_ID` | `submit_update` + own per-user memory | ❌ | ❌ | ❌ |
| **Unauthenticated** (auth off) | forgeable — **prod disallows** | — | — | — | — |

---

## Residual risks / assumptions

- Trust in the Slack workspace and the JWT IdP (identity binding is theirs).
- **Single-owner deploy.** Multi-owner/tenant would need per-tenant `OWNER_ID`
  resolution and a per-request agent factory.
- `metadata` has no write protection — the verdict is always derived fresh per
  run rather than trusted from a prior write.
- **Per-channel memory and sessions for a multi-identity owner.** Agno captures
  the run's `user_id` for memory and session keying *before* pre-hooks run, so
  `normalize_identity` can't rewrite it there: an owner with distinct Slack and
  JWT identities gets per-channel memories and sessions (sessions deliberately
  so — the OS routes' `user_isolation` filters by the JWT identity). The
  structured store, knowledge base, and queue are unaffected (canonicalized). If
  cross-channel memory continuity matters, keep the identities aligned (mint
  the JWT `sub` as your email).
- `OWNER_ID` **fails closed**: unset means nobody is the owner and Context is
  capture-only for everyone. Production must set it (and run with auth on) —
  this also covers the scheduler identity, which is only honored once an owner
  is configured.
- **Whoever can create schedules acts with the owner surface.** Schedule CRUD
  rides the authenticated OS routes, so in practice that's the owner — but an
  operator you grant OS access to could schedule owner-surface runs. Same
  trust class as handing someone your deploy. (Act tools still pause for
  approval even on scheduled runs.)
- **Google credentials are deploy-held.** The Gmail/Calendar providers act
  with whatever scopes the connected OAuth token carries — scope them to the
  one mailbox/calendar they should touch (see [`docs/GOOGLE.md`](GOOGLE.md)).
