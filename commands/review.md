---
description: Run an AgentForge PR-style, diff-only review of the current branch against a base.
argument-hint: [--base main] [--task "context"] [--dry-run] [--no-code-leak]
allowed-tools: Bash, Read
---

The user wants an AgentForge review of the current changes.

**$ARGUMENTS**

1. Pick the working AgentForge command: try `agentforge --version`, else `python -m agentforge --version`; use whichever works as `AF`. If neither works, tell the user to `pip install -e .` and stop.

2. Run a PR-style review. Pass through any `--base`, `--task`, `--dry-run`, or `--no-code-leak` flags the user included; if no base was given, let AgentForge auto-detect (main, then master):
   ```
   AF review-pr <flags>
   ```
   The reviewer only ever sees the diff, never full source files.

3. Read `review.json` (and `security_report.json`) from the newest `.agentforge/runs/<timestamp>/` folder and summarize: the verdict (approved / needs_changes), risk level, and any concrete issues raised. If the reviewer returned non-JSON, report it was flagged for manual review rather than treating it as approved.
