# Budget control

Every run shows its budget twice. Once up front, as an **estimate** built from the routing + the prompts the orchestrator has prepared:

```
Budget estimate:
- Planned AI calls: 3/5
- Files selected: 5/8
- Estimated chars sent: 34,200
- Review loops allowed: 1
- Dry run: no
```

And once at the end, as a **summary** of the actuals:

```
Budget summary:
- AI calls used: 2/5
- Review loops used: 1/1
- Files sent: 5/8
- Estimated chars sent: 34,200
- Stopped early: no
```

The summary appends `Stop reason: ...` whenever a run stops short — for example because tests passed and review wasn't required (early stop), the agent CLI wasn't installed (abort), or the caller declined the human-approval prompt.

`BudgetManager` enforces these caps in `config.yaml`:

```yaml
max_ai_calls_per_run: 5
max_review_loops: 1
max_files_sent: 8
max_chars_per_file: 12000
max_total_chars: 80000
```

If the up-front estimate would exceed `max_ai_calls_per_run` or `max_total_chars`, the run aborts before any agent is contacted, with the exact message that exceeded the cap. If the estimate fits but an in-flight call would push us over, `BudgetExceeded` is raised at that point and `_finalize_aborted` writes a complete artifact set so the partial work is still inspectable.

> **Approximation note:** cost is character-based, not token-accurate. Good enough to keep spend bounded; not accurate to the cent. See the roadmap for an issue to replace the character proxy with agent-reported token counts.

Every run also writes the full structure to `.agentforge/runs/<timestamp>/budget.json`:

```json
{
  "ai_calls": 2,
  "review_loops": 1,
  "chars_sent": 34200,
  "files_sent": 5,
  "max_ai_calls": 5,
  "max_review_loops": 1,
  "max_total_chars": 80000,
  "max_files_sent": 8,
  "max_chars_per_file": 12000,
  "planned_ai_calls": 3,
  "planned_chars_sent": 35000,
  "dry_run": false,
  "stopped_early": false,
  "stop_reason": null,
  "call_log": [
    {"agent": "claude", "role": "planner",     "prompt_chars": 1200},
    {"agent": "codex",  "role": "implementer", "prompt_chars": 33000}
  ]
}
```

`call_log` is a per-call breakdown so [agent scorecards](../README.md#agent-scorecards) can attribute chars to the right agent.
