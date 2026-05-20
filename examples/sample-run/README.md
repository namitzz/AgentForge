# Sample run

This folder is what `.agentforge/runs/<timestamp>/` looks like after a successful `solve`. It's hand-crafted to be realistic — the files were not produced by a live run, but they match the schema AgentForge writes.

- [task.json](task.json) — the input task and the classifier's verdict
- [plan.md](plan.md) — the planner's output
- [policy_report.json](policy_report.json) — blocked files + escalations from the policy engine
- [review.json](review.json) — reviewer verdict (structured JSON)
- [budget.json](budget.json) — AI calls + characters spent vs caps
- [final_summary.md](final_summary.md) — human-readable end-of-run wrap-up

Not included in this sample (would also be present in a real run):
- `repo_summary.json` — file inventory at scan time
- `selected_files.json` — files chosen for the context window
- `prompts.json` — the exact prompts sent to each agent
- `diff.patch` — the implementer's changes
- `test_result.txt` — test stdout/stderr + exit code
