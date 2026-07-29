# Run artifacts

Every run leaves a complete audit trail under `.agentforge/runs/<timestamp>/`:

```
.agentforge/runs/20260520-141207/
├── task.json            input task + run manifest (start/end, command, workflow)
├── repo_summary.json    file inventory at scan time
├── selected_files.json  files chosen for the context window
├── risk_report.json     LOW/MEDIUM/HIGH + score + reasons + recommended workflow
├── policy_report.json   blocked files + escalations
├── security_report.json secret content scan + injection warnings + command safety verdict
├── decision_report.json NO_AI / SINGLE_AGENT / IMPLEMENT_AND_REVIEW / FULL_PIPELINE
├── privacy_report.json  No-Code-Leak Mode flags (always written)
├── budget.json          planned vs actual AI calls + chars + per-call breakdown
├── prompts.json         exact prompts sent to each agent
├── plan.md              planner output (markdown)
├── test_result.txt      test stdout/stderr + exit code
├── diff.patch           implementer's changes
├── review.json          reviewer verdict (structured JSON)
├── final_summary.md     human-readable wrap-up
├── merge_readiness.json (written by `agentforge readiness`)
├── redteam_review.json  (written by `agentforge redteam`)
└── failure_report.json  (only present when a run failed)
```

The first 12 files are always present after a successful run. When a step is skipped (dry-run, early stop, abort) the corresponding artifact is filled with a placeholder explaining what happened, so CI and downstream tooling can rely on every file existing.

The last three are conditional: `merge_readiness.json` is added by the readiness command, `redteam_review.json` by the redteam command, and `failure_report.json` only appears when a run failed — its presence itself is the signal.

## task.json — the run manifest

```json
{
  "run_id": "20260520-141207",
  "mode": "solve",
  "task": "Add Stripe webhook signature verification",
  "dry_run": false,
  "started_at": "2026-05-20T14:12:07",
  "ended_at":   "2026-05-20T14:12:34",
  "command": "python -m agentforge solve \"Add Stripe webhook signature verification\"",
  "agentforge_version": "0.1.0",
  "agent_workflow": {
    "planner":     "claude",
    "implementer": "codex",
    "reviewer":    "claude"
  },
  "classification": {
    "task_type": "security",
    "confidence": 0.8,
    "keywords_matched": ["security", "auth "],
    "routing": {"planner": "claude", "implementer": "codex", "reviewer": "claude", "require_review": true}
  },
  "stopped_early": false,
  "stop_reason": null
}
```

After every run the CLI prints the path so it's one click away:

```
Run artifacts saved to:
  .agentforge/runs/20260520-141207/
```

## See it without running it

A complete worked example is in [`examples/sample-run/`](../examples/sample-run/) — all artifacts for a realistic HIGH-risk task ("Add password reset validation to the login flow"), so you can understand the audit trail without installing any agent CLI.
