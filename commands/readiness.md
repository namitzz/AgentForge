---
description: Score the latest AgentForge run 0-100 for merge readiness.
argument-hint: [--run .agentforge/runs/<timestamp>]
allowed-tools: Bash, Read
---

The user wants a merge-readiness score for an AgentForge run.

1. Pick the working AgentForge command: try `agentforge --version`, else `python -m agentforge --version`; use whichever works as `AF`. If neither works, tell the user to `pip install -e .` and stop.

2. Run (pass a `--run <path>` if the user gave one, otherwise it scores the latest run):
   ```
   AF readiness $ARGUMENTS
   ```

3. Report the score (0-100), the level (READY / READY_WITH_CAUTION / NEEDS_WORK / DO_NOT_MERGE), the recommendation, and the top blockers or warnings. Be explicit that a low score on a `--dry-run` preview is expected, because no real tests or review actually executed.
