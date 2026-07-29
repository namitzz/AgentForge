---
description: Produce an AgentForge implementation plan for a task without editing any files.
argument-hint: [task description] [--dry-run]
allowed-tools: Bash, Read
---

The user wants an AgentForge plan for this task (no files will be changed):

**$ARGUMENTS**

1. Pick the working AgentForge command: try `agentforge --version`, else `python -m agentforge --version`; use whichever works as `AF`. If neither works, tell the user to run `pip install -e .` from the repo and stop.

2. Run:
   ```
   AF plan "<the task text, flags stripped>" <any flags the user passed>
   ```
   Suggest adding `--dry-run` if the user wants to preview the routing and risk with no Claude call.

3. Read the newest `.agentforge/runs/<timestamp>/` folder and summarize `plan.md`, the risk level, and the recommended workflow. Note that `plan` edits nothing and creates no branch.
