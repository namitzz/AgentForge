# Sample run

This folder shows exactly what `.agentforge/runs/<timestamp>/` looks like after a real AgentForge run. The files were hand-crafted (no real AI was called) but they match the schemas AgentForge actually writes, so you can use this to understand the audit trail without setting up the agent CLIs.

**Task:** `Add password reset validation to the login flow`

**Risk:** HIGH (auth + login + password keywords plus selected paths under `src/auth/`)

**Outcome:** approved with two non-blocking follow-up suggestions, 3 AI calls used, no revision loop needed.

## Files

| File | What's inside |
|---|---|
| [task.json](task.json)                 | run manifest: timestamps, command, agent workflow, classification, stopped_early / stop_reason |
| [repo_summary.json](repo_summary.json) | file inventory at scan time (42 files, top dirs, language counts) |
| [selected_files.json](selected_files.json) | the 5 files actually sent to the implementer |
| [risk_report.json](risk_report.json)   | LOW/MEDIUM/HIGH + score + reasons + recommended workflow |
| [policy_report.json](policy_report.json) | blocked files + escalations from the policy engine |
| [security_report.json](security_report.json) | secret content scan + injection warnings + command safety verdict |
| [budget.json](budget.json)             | planned vs actual AI calls and characters |
| [prompts.json](prompts.json)           | the exact prompts sent to each agent (planner, implementer, reviewer) |
| [plan.md](plan.md)                     | the planner's output |
| [diff.patch](diff.patch)               | the change the implementer produced |
| [test_result.txt](test_result.txt)     | test stdout/stderr + exit code |
| [review.json](review.json)             | reviewer verdict in structured JSON |
| [final_summary.md](final_summary.md)   | human-readable wrap-up |

## How to read this

1. Open `task.json` — see what was asked, when, and how AgentForge classified it.
2. Open `risk_report.json` — see why the run was scored HIGH and what workflow was recommended.
3. Open `policy_report.json` — see which YAML policies triggered, and which files would have been blocked from being sent.
4. Open `budget.json` — see the up-front estimate (`planned_*`) vs. the actuals.
5. Open `plan.md` — read the implementation plan that the planner produced.
6. Open `diff.patch` — read the actual change.
7. Open `test_result.txt` — confirm the tests still pass.
8. Open `review.json` — read the reviewer's structured verdict.
9. Open `final_summary.md` — see what the CLI prints at the end.

Everything in this folder is safe to read or commit. There are no real secrets, tokens, or credentials.
