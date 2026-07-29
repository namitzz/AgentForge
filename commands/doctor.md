---
description: Run AgentForge's environment + config health check.
allowed-tools: Bash, Read
---

Run AgentForge's health check and report the results.

1. Pick the working AgentForge command: try `agentforge doctor`; if `agentforge` is not found, run `python -m agentforge doctor`. If neither works, tell the user to install it with `pip install -e .` from the AgentForge repo, then stop.

2. Summarize which checks passed, which are warnings, and any failures. The key one for real runs is the **Claude CLI** row — if it shows a warning, the `claude` CLI is missing or not on PATH; if runs fail with "Not logged in", the user needs to authenticate `claude` (or set `ANTHROPIC_API_KEY`). Remind them that `--dry-run` works without any of that.
