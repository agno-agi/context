---
name: review-and-improve
description: Repo-wide consistency sweep for @context — diff docs against code (the context agent and its providers wired as documented, every env var documented, every path real, every script behaving as advertised), auto-fix mechanical drift, and flag anything bigger. Use when the user wants to review the repo for consistency, prep a public release, or clean up drift after a refactor ("review the repo", "is everything consistent before we ship", "run the drift sweep"). This is a deliberate full sweep, not a quick lint.
---

# Review and Improve

You are sweeping the whole repo for public-consumption readiness — docs accuracy, the context agent reachable end to end, scripts that actually do what the docs claim, no stale env vars, format + validate clean. Most drift is mechanical (renamed file, missing entry in `example.env`, a provider missing from the architecture diagram) and you fix it in place. The rest is a punch list you surface to the user.

This is a **recurring sweep** — meant to be re-run regularly. On a clean repo it ends with "no diffs"; on a dirty one it brings everything back to coherent.

[`AGENTS.md`](../../../AGENTS.md) is the source of truth for repo conventions; [`CLAUDE.md`](../../../CLAUDE.md) is a symlink to it — edit once, both update.

## What you auto-fix vs. what you flag

**Auto-fix in place** (no asking):

- Stale file paths in any doc.
- Missing entries in [`example.env`](../../../example.env) for env vars the code actually reads.
- Stale entries in `example.env` for vars nothing reads — delete unless the surrounding comment block describes them as optional/future ("alternate model providers", "future feature"). Flag instead of fixing if intent is unclear.
- Architecture diagram in `AGENTS.md` missing a wired provider or runtime skill (or listing one that's gone).
- An agent file on disk not imported in [`app/main.py`](../../../app/main.py) (rare — single-agent product, but the AGENTS.md recipe allows more; add the import + append to `agents=[...]`).
- Missing `quick_prompts` block for a registered agent (draft three from the agent's `INSTRUCTIONS`; flag the new entries so the user can refine).
- Missing or wrong cross-links between skill files in `.agents/skills/`.
- Single-line factual claim in one doc contradicted by another doc or by code (e.g. one doc says "hot-reload picks up new agents" while another says a restart is required) — auto-fix the doc, not the code.

**Flag, don't fix** (surface for the user):

- Section-level doc rewrites (a premise is now wrong).
- Code changes beyond imports (instructions, tools, model swaps).
- Dependency edits in [`pyproject.toml`](../../../pyproject.toml).
- Anything in [`db/`](../../../db/), [`compose.yaml`](../../../compose.yaml), or [`Dockerfile`](../../../Dockerfile).
- Failing eval cases or failing live agents — recommend the right follow-up prompt; don't fix here.

## 0. Preconditions

- Live container reachable: `curl -sSf http://localhost:8000/health` returns 200. If not, ask the user to `docker compose up -d --build` first — Step 4 needs a live container. (`docker compose ps` is unreliable from worktrees or alternate clones — trust the health probe.)
- If multiple worktrees of this repo exist on disk, only one container can bind to localhost:8000 — Step 4 will reflect whichever repo last brought the container up, not necessarily this worktree's `app/main.py`. Step 4 has a cross-check for this.
- Recommend a feature branch so auto-fixes are easy to revert: `git checkout -b review/$(date +%Y%m%d)`.

## 1. Scope check

Restate the surface area in 4-5 lines so the user can redirect before you read everything:

- Top-level docs: [`README.md`](../../../README.md), [`AGENTS.md`](../../../AGENTS.md), [`example.env`](../../../example.env), and the workflow skills in [`.agents/skills/`](../../../.agents/skills/).
- Code: [`app/`](../../../app/), [`agents/`](../../../agents/), [`db/`](../../../db/), [`evals/`](../../../evals/), [`scripts/`](../../../scripts/).
- Configs: [`compose.yaml`](../../../compose.yaml), [`Dockerfile`](../../../Dockerfile), [`pyproject.toml`](../../../pyproject.toml), [`railway.json`](../../../railway.json).

Skip: `.venv/`, `*_cache/`, `.git/`, anything generated.

If the user has a specific concern (recent refactor, prepping a public release, a doc they think is stale), fold it in now.

## 2. Inventory

Read every file in scope. These reads are independent — fan them out across subagents (or parallel `Read`/`grep` calls) and collect the results rather than walking the repo serially. Build a mental model of:

- **Registered agents** — what's imported in `app/main.py`'s `agents=[...]`? (Expected: `context`.)
- **Agent files on disk** — what's in [`agents/`](../../../agents/)?
- **Wired providers** — what's in `create_context_providers()` in [`agents/sources.py`](../../../agents/sources.py), and which are env-gated?
- **Runtime skills** — what folders are in [`skills/`](../../../skills/), and does each `SKILL.md`'s `name` match its directory?
- **Env vars actually read** — grep `os.environ`, `os.getenv`, `getenv(`, plus settings/config modules.
- **Quick prompts** — what's in [`app/config.yaml`](../../../app/config.yaml) under `chat.quick_prompts`?
- **Eval cases** — what's in [`evals/cases.py`](../../../evals/cases.py)?
- **Scripts** — for each file in [`scripts/`](../../../scripts/), what does it actually do? (Headers and the first few lines are usually enough.)

Don't write anything yet — read first, fix once.

## 3. Consistency pass

The bulk of the work. Diff each pair below; auto-fix per the rules at the top. The diffing is read-only, so parallelize it freely — but apply the fixes serially so two edits never race on the same file.

| Check | Where | Common drift |
|---|---|---|
| Every agent file is registered | [`agents/`](../../../agents/) ↔ `app/main.py` | New agent file not imported |
| Every registered agent has quick prompts | `app/main.py` ↔ `app/config.yaml` | Agent added without prompts |
| Every env var in code is documented | code grep ↔ `AGENTS.md` env table + `example.env` | New var added without entries |
| Every var in `example.env` is read somewhere | `example.env` ↔ code grep | Stale var nobody reads |
| Every path mentioned in docs exists | `README.md`, `AGENTS.md`, `.agents/skills/*/SKILL.md` ↔ filesystem | Renamed or deleted file |
| Every script mentioned in docs is real + does what's claimed | docs ↔ `scripts/` | Renamed or behavior drifted |
| Architecture diagram matches wired providers + skills | `AGENTS.md` Architecture section ↔ `agents/sources.py`, `skills/` | Provider or skill added/removed without a doc update |
| Eval cases reference real agents + tools | `evals/cases.py` ↔ `agents/` | Slug renamed or tool removed |
| Runtime skills are loadable | `skills/*/SKILL.md` frontmatter ↔ folder names | `name` ≠ directory, malformed frontmatter (degrades to "no skills" at startup) |
| `Key Files` table in `AGENTS.md` matches reality | `AGENTS.md` ↔ filesystem | Renamed file, deleted file, new file not listed |
| Cross-links between skill files resolve | `.agents/skills/*/SKILL.md` ↔ skill names | Renamed skill, broken link |
| `.mcp.json` servers and the skills that reference them agree | `.mcp.json` ↔ `.agents/skills/*/SKILL.md` | URL changed, server renamed |

## 4. Live container smoke

First, confirm the live container is serving *this* repo's agents — not a stale clone or a different worktree. Compare the API's registered agents against what you parsed from `app/main.py`:

```bash
curl -s http://localhost:8000/agents | jq -r '.[].id' | sort
```

If the list doesn't match the slugs in `agents=[...]`, flag it — Step 4 will be testing the wrong code. Common causes: the container is bound to a different repo path, or `docker compose restart` is needed. Stop and surface to the user.

For each agent registered in `app/main.py`, hit it with one of its `quick_prompts`. **Identity decides the surface on `context`:** compose treats `owner@context.local` (and the `anon` default) as the owner, so owner-path probes must send that id — a made-up `user_id` would smoke the capture-only non-owner surface instead. Probe both: the owner path with a quick prompt, and the boundary with any other id (expect a polite capture-only reply, no data readback). The probes don't share state, so fire them concurrently (background the cURLs) and collect the results:

```bash
curl -sS -X POST http://localhost:8000/agents/<slug>/runs \
  -F "message=<one of the quick_prompts for this slug>" \
  -F "user_id=owner@context.local" \
  -F "stream=false" \
  -o /tmp/review-<slug>.json \
  -w "HTTP %{http_code} in %{time_total}s\n"

jq -r '.content // .' < /tmp/review-<slug>.json | head -20
```

Pass = HTTP 200, non-empty content, no errors in the container logs:

```bash
docker logs context-api --since 30s 2>&1 | grep -E "Running: \w+\(" | head -40
```

(`Running: <tool>(` is the tool-call line shape agno emits when `AGNO_DEBUG=True`, which compose sets for dev. Without `AGNO_DEBUG` expect no matches — `HTTP 200` and a non-empty body are then your only signal.)

Quality issues (response is plausible but wrong, missing citations, wrong tool fired) are out of scope — note them and recommend the `improve-agent` skill (autonomous) or the `extend-agent` skill (user-driven) depending on whether the user has a specific fix in mind.

## 5. Format + validate

```bash
source .venv/bin/activate  # if not already active
./scripts/format.sh
./scripts/validate.sh
```

`format.sh` auto-fixes. `validate.sh` reports. If validate fails, surface the errors verbatim — type and lint errors usually point at real bugs introduced since the last sweep, not noise to suppress.

## 6. Evals (ask before running)

`python -m evals` hits OpenAI — costs money and takes a few minutes. Ask before running:

> Run `python -m evals` to confirm no agent regressed? (Hits OpenAI; takes 1-3 minutes.)

If yes, run `python -m evals`. If any case fails, add it to "Needs your call" with the `eval-and-improve` skill as the recommended follow-up. If the user declines, skip this step entirely — it does not affect the rest of the report.

## 7. Report

If nothing was fixed and nothing flagged, skip the first two blocks below and just print: *"Repo is consistent and the live container is healthy. No follow-up needed."* No commit suggested.

Otherwise, wrap up with three blocks, in order:

**Fixed automatically** — one line per change, with file path. Terse.

**Needs your call** — flagged items, ranked by severity. For each: one-line description, file (and line if useful), recommended action.

**Diff + next step**:

```bash
git diff --stat
```

- Suggested commit message — `chore: review-and-improve sweep` plus one short bullet per fix bucket.
- Recommended follow-up — usually the `improve-agent` skill (if a live agent looked off) or the `eval-and-improve` skill (if evals failed).

A clean sweep takes 3-5 minutes (10+ if the venv needs to be created). A dirty one is 15-30, mostly because live smoke surfaces agent regressions you have to triage.
