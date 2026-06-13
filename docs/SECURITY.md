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
deploy: their database, their wiki, their keys.

## Threat model

| We protect | Against | Mechanism |
|---|---|---|
| The owner's stored context (CRM, wiki, queue) | Any guest caller reading it | Identity-conditioned toolset — guests get no read tools |
| The ack axis (what's "handled") | Anyone but the owner marking items done/acknowledged | Only the owner's toolset has the ack tool |
| Acting *as* the owner (sending mail, changing the calendar) | The model doing it unprompted; guests triggering it | Owner-only act tools + a per-call approval gate — the run pauses until the owner confirms (L6) |
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
daily rundown) are the owner's own automation, so they run with the owner
surface and key their writes under the canonical id. The trust chain: only the
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
    return [*all_provider_tools(), list_contexts, rundown, acknowledge]  # full
```

The model **never sees** the privileged tools for a guest — so "don't answer
questions about the owner" is structural, not a prompt instruction.

The same gate covers **runtime skills** (owner-only playbooks in
[`skills/`](../skills/)). The `get_skill_*` access tools are added only in the
owner branch of `context_tools`, and the skills "browse" snippet only renders
in the owner branch of the `caller_information` `dependencies` resolver — so a
guest's toolset *and* prompt carry zero skill references. Skills are a
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
It appends to the **owner's** queue (`context.updates`, `user_id = OWNER`,
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
them, for them* — never blended into the owner's CRM, wiki, or queue.

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
  rewritten to the canonical `OWNER_ID`, so the structured store, wiki, and
  queue key under one identity instead of fragmenting per channel.
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
- The two-engine split on the `context` schema — a write-guarded engine
  (`search_path` + a SQLAlchemy guard rejecting writes to `public`/`ai`) and a
  Postgres-level read-only engine (`default_transaction_read_only=on`). See
  [`db/session.py`](../db/session.py).
- The `crm` read/write sub-agents scope every query to `user_id` in their
  tuned prompts.

### L6 — Acting as the owner requires explicit approval

Reading and filing stay inside the owner's own store. **Act tools** reach the
outside world *in the owner's name* — `update_gmail` sends email, `update_calendar`
changes the real calendar — so they get a second gate on top of L1:

- **Owner-only by construction (L1).** A guest's toolset never contains an
  act tool, same as every other privileged tool.
- **Approval-gated per call.** [`context_tools()`](../agents/context.py) flags
  every tool named in `ACT_TOOLS` ([`agents/sources.py`](../agents/sources.py))
  with `requires_confirmation` — agno pauses the run *before the tool executes*
  and resumes only when the owner confirms (in the os.agno.com chat UI, or via
  the continue-run API). The model cannot self-approve; declining discards the
  call.
- **Conservative sub-agents.** The Gmail write sub-agent drafts by default and
  sends only on an explicit "send"; the Calendar write sub-agent confirms
  ambiguous targets before touching events.

The asymmetry extends cleanly: *anyone can write **to** your context; only you
can read it — and nothing acts **as** you without your sign-off.* A scheduled
run that reaches an act tool pauses too — there's no one to approve
mid-schedule, so unattended automation can read and file but never send.

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
  structured store, wiki, and queue are unaffected (canonicalized). If
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
  with whatever scopes the configured service account or OAuth token carries —
  scope them to the one mailbox/calendar they should touch
  (see [`docs/GOOGLE.md`](GOOGLE.md)).
