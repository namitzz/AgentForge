---
description: Run a coding task through AgentForge's full guardrail pipeline (risk, policy, security, budget) and summarize the run.
argument-hint: [task description] [--dry-run] [--no-code-leak]
allowed-tools: Bash, Read
---

The user wants to run this task through AgentForge's `solve` pipeline:

**$ARGUMENTS**

Do the following:

1. Pick the AgentForge command that works on this machine: try `agentforge --version`; if that isn't found, try `python -m agentforge --version`. Use whichever works as `AF` below. If neither works, tell the user to install it first:
   ```
   pip install -e .
   ```
   from the AgentForge repo, then stop.

2. Run the solve, passing along any flags the user included in the arguments (for example `--dry-run` or `--no-code-leak`). If the user did **not** include `--dry-run` and the task text mentions anything sensitive (auth, login, password, token, payment, migration, secrets), first tell them a real run makes live Claude calls and costs tokens, and suggest a `--dry-run` preview. Only proceed with a real run if they clearly asked for one.
   ```
   AF solve "<the task text, flags stripped>" <any flags>
   ```

3. When it finishes, find the newest folder under `.agentforge/runs/` and read `final_summary.md` (plus `risk_report.json`, `policy_report.json`, `security_report.json`, `budget.json`, and `decision_report.json` if you need detail). Summarize for the user:
   - risk level + score
   - which agents the decision engine chose, and how many AI calls were planned vs used
   - any policy escalations (review / tests / human approval) and security findings
   - the run status and where the artifacts live

4. Remind the user that AgentForge never pushes or merges — they inspect the diff (`git diff main`) and merge themselves.
