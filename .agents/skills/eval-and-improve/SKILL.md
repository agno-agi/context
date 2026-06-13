---
name: eval-and-improve
description: Run this repo's eval suite (python -m evals), diagnose every failing case, and fix in scope (agent instructions, or the eval case when its assertion was wrong) until all cases pass. Use whenever the user wants to run the evals, check for regressions, or fix a red eval suite ("run the evals", "why is a case failing", "make the eval suite green"). Targets the committed cases in evals/cases.py; for ad-hoc probing of one agent's live behavior use improve-agent instead.
---

# Eval and Improve

You're running @context's eval suite, diagnosing every failure, fixing what's in scope, and stopping when all cases pass. Surface area is two files: [`evals/cases.py`](../../../evals/cases.py) (declares cases) and [`evals/__main__.py`](../../../evals/__main__.py) (runner). Each case uses agno's built-in [`AgentAsJudgeEval`](https://docs.agno.com/evals/agent-as-judge) (LLM judge against a `criteria` rubric, binary pass/fail) and/or [`ReliabilityEval`](https://docs.agno.com/evals/reliability) (asserts which tools fired) — no custom DSL.

## 0. Preconditions

- Postgres reachable on 5432: `nc -z localhost 5432` returns 0. If not, `docker compose up -d context-db` from the source repo. (`docker compose ps` is unreliable from worktrees or alternate clones.)
- Venv active: `source .venv/bin/activate`. If `.venv` doesn't exist (fresh checkout or worktree), run `./scripts/venv_setup.sh` first. `evals/cases.py` imports the agents directly from `agents/`, so no AgentOS server has to be running.
- `.env` populated with `OPENAI_API_KEY`. `evals/__main__.py` calls `evals.dotenv.load_dotenv()` at startup, so you do not need to source `.env` first. Worktrees don't inherit `.env` (it's gitignored) — copy it from the source repo if missing.

## 1. Run the suite

```bash
python -m evals               # full suite, concise (response + judge verdicts)
python -m evals -v            # stream the full agent run with rich panels + eval tables
python -m evals --case <name> # single case while iterating
```

Output ends with a summary block. Exit code is 0 on all-pass, non-zero on any failure or error.

The full suite hits OpenAI and runs 1-3 minutes — run it in the background so the session stays responsive and you're notified on completion. Keep `--case <name>` runs in the foreground while iterating; they're quick.

Stderr noise around MCP teardown (`RuntimeError: Event loop is closed`, httpx timeouts) at the end of a run is harmless — only the `Eval Summary` table and exit code count.

## 2. Diagnose each failure

For every failed case, decide which kind of failure it is and fix at the appropriate layer:

| Symptom | Likely cause | Where to fix |
|---|---|---|
| Judge fails, "answer is right but missing X" | Agent's instructions don't push for X | `agents/<slug>.py` — tighten the rule |
| Judge fails, response is fabricated | Agent hallucinated when it should have said it didn't know | Add a "if you can't find a real source, say so plainly" rule to the agent's instructions |
| Reliability fails: "missing tool X" | Agent didn't call the expected tool on this prompt | (a) Strengthen the routing rule in instructions, OR (b) the case is too narrow — broaden `expected_tool_calls` or drop the assertion |
| Reliability fails: "additional tool Y called" with `allow_additional_tool_calls=False` | Agent fanned out beyond the case's expectation | Tighten the agent's instructions OR set `allow_additional_tool_calls=True` |
| Non-owner case unexpectedly reads data (or an owner case is capture-only) | Case `user_id` doesn't exercise the surface you think — the runner pins `OWNER_ID=eval-owner`, and only that id gets the owner toolset | Check the case's `user_id` against `EVAL_OWNER` in `evals/cases.py` |
| Same case flips PASS/FAIL across consecutive runs with no code change | Judge variance — rubric is too loose | Re-run 2-3 times to confirm; if it keeps flipping, tighten the case's `criteria` (more specific, more falsifiable) |
| Single case fails on full suite but passes alone | Transient flake or upstream rate limit (429s, MCP shutdown traceback) | Re-run the case in isolation. If it passes, re-run the full suite. If 429s persist, back off — don't fix the agent. |
| Many cases fail at once | Broad regression — model swap, MCP server down, tool removed | Diagnose the root cause first; do NOT paper over with prompt edits |
| `eval_db` write errors | Postgres down or migration missing | Bring DB up; check `docker logs context-db` |

**Rule:** never weaken a case to make it green. Edit a case only when the assertion was wrong (overspecified rubric, wrong tool name, mismatch with how the agent's tools are named today). Catching a real regression is the whole point.

Quick test for "wrong assertion vs. real regression": read the response yourself. If it looks correct against the user's intent but the rubric flagged a missing detail, the rubric was overspecified. If the response is genuinely wrong, the agent's instructions need work.

## 3. Fix scope

In scope for this skill:

- `agents/<slug>.py` — instructions, tools, model.
- `evals/cases.py` — when an assertion was genuinely wrong.
- One-line config flips in `app/main.py` if a case requires it (rare).

Out of scope (flag for the user, don't do):

- Removing cases.
- Editing `db/` or `app/` to make a case pass.
- Editing agno itself.

For agent quality issues that need fast iteration against a live container (cURL probes, instruction tweaks), hand off to the `improve-agent` skill — its autonomous probe loop is faster than running the full eval suite per change. If the change is user-driven (add a tool, fix a known bug), use the `extend-agent` skill instead.

## 4. Re-run and stop

After each fix, re-run the failing case. Fixed several at once? Re-run them concurrently — background each `--case` invocation and collect the results — rather than serially:

```bash
python -m evals --case <name>
```

When all targeted cases pass, run the full suite once more to confirm nothing regressed:

```bash
python -m evals
```

Stop when `python -m evals` exits 0 **and** prints an `Eval Summary` block. If a re-run aborts mid-stream (no summary, regardless of exit code), treat it as inconclusive — re-run before declaring green.

## 5. Add a new case (if needed)

If diagnosing a failure reveals a missing assertion, add it to [`evals/cases.py`](../../../evals/cases.py):

```python
Case(
    name="<short_id>",
    agent=<the_agent>,
    input="<prompt>",
    # Either or both of:
    criteria="<rubric describing a correct response>",
    expected_tool_calls=("<tool_name>",),
)
```

Run `python -m evals --case <name>` to confirm it passes against the current agent. Commit the new case alongside any fixes.

## 6. Track regressions over time

Every case logs to Postgres via `db=eval_db`. Connect your AgentOS at [os.agno.com](https://os.agno.com) and view eval history — useful for catching slow drift on a weekly cron.

To run on a schedule, register the eval suite as a scheduled task on the AgentOS scheduler — see [agno scheduler docs](https://docs.agno.com/agent-os/scheduler).

---

## Reference: Case shape

```python
@dataclass(frozen=True)
class Case:
    name: str
    agent: Agent
    input: str

    # Identity the run is made under. Defaults to the owner (full toolset);
    # any other id exercises the capture-only non-owner surface.
    user_id: str = EVAL_OWNER

    # Judge (LLM rubric, binary pass/fail): set to enable.
    criteria: str | None = None

    # Reliability (tool-call assertion): set to enable.
    expected_tool_calls: tuple[str, ...] | None = None
    allow_additional_tool_calls: bool = True
```

The runner calls `agent.arun()` once per case and feeds the response into both checks, so cases that set both fields cost one agent run, not two.

**Identity is part of the case.** The runner pins `OWNER_ID=eval-owner` before importing the agent, so `user_id` decides which surface a case exercises: the default (`EVAL_OWNER`) gets the full owner toolset; any other id gets the capture-only non-owner surface — that's how the suite asserts the security boundary itself.
