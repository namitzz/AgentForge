# AgentForge — 2-minute demo

AgentForge is a **cost-aware control plane for AI coding agents** that adds budget caps, risk scoring, policy checks, security scanning, and audit logs so a developer stays in charge of every change.

This demo runs entirely **locally** with **zero AI calls** — you don't need the Claude CLI logged in, an API key, or a network connection.

## Setup (10 seconds)

You only need Python 3.11+, git, and AgentForge installed:

```bash
git clone https://github.com/namitzz/AgentForge.git
cd AgentForge
pip install -e .
```

After install, `agentforge --help` works on your PATH.

## Run the demo

The repo ships a tiny dependency-free project at `demo-projects/tiny-python-app/`. The demo task asks AgentForge to harden the password-reset flow — exactly the kind of change that should trip every guardrail.

```bash
cd demo-projects/tiny-python-app

# 1. one-time setup
agentforge init

# 2. preview the full pipeline (no AI, no edits, no branch)
agentforge solve "Add password reset validation to the login flow" --dry-run

# 3. score the run for merge readiness
agentforge readiness

# 4. run the stricter red-team review on the same diff
agentforge redteam --dry-run
```

## What you should see

The `solve --dry-run` output (abridged):

```
Dry run: enabled
No external agents will be called.
No files will be modified.

Files that would be sent:
  - src/auth/login.py
  - src/auth/password_reset.py
  - src/utils/validators.py
  - tests/test_auth.py

Risk assessment:
- Level: HIGH
- Score: 85/100
- Reasons:
  - Task mentions high-risk topics: login, password, auth
  - Selected file paths include sensitive areas: auth/

Policy checks:
- Blocked files: none
- Review required: yes
- Tests required: yes
- Human approval required: yes
- Reasons:
  - Auth changes require review

Security checks:
- Blocked secret files: none
- Prompt-injection warnings: 0
- Command risk: low
- Safe to continue: yes

Agent decision:
- Decision: FULL_PIPELINE
- Planned AI calls: 3
- Agents:
  - Planner: claude
  - Implementer: claude
  - Reviewer: claude
- Reasons:
  - HIGH risk task
  - Human approval required before merge

Run artifacts saved to:
  .agentforge/runs/<timestamp>/
```

And `agentforge readiness`:

```
Merge readiness:
- Score: 25/100
- Level: DO_NOT_MERGE
- Recommendation: Do not merge. Investigate failures before retrying.
```

`DO_NOT_MERGE` is correct here — this is a dry-run preview, so no real tests ran and no review was recorded. A real run that passes tests would score 90+ READY.

## Inspect the audit trail

Every run writes a complete artifact set:

```bash
# Bash / zsh
ls .agentforge/runs/$(ls -t .agentforge/runs | head -1)/

# PowerShell
Get-ChildItem .agentforge/runs | Sort-Object LastWriteTime -Descending | Select-Object -First 1

# Or just list the runs and pick by timestamp:
ls .agentforge/runs/
ls .agentforge/runs/<timestamp>/
```

The interesting files:

| File | What's inside |
|---|---|
| `task.json` | run manifest: timestamps, command, agent_workflow, classifier verdict |
| `risk_report.json` | LOW/MEDIUM/HIGH + score + reasons + recommended workflow |
| `policy_report.json` | blocked files + escalations |
| `security_report.json` | secret scan + prompt-injection scan + command-safety verdict |
| `decision_report.json` | NO_AI / SINGLE_AGENT / IMPLEMENT_AND_REVIEW / FULL_PIPELINE |
| `prompts.json` | the exact prompts that would have been sent |
| `budget.json` | planned vs actual AI calls + chars |
| `merge_readiness.json` | 0–100 merge-readiness score + reasons |
| `final_summary.md` | human-readable wrap-up |

## What this demo proves

1. **Local-first.** Zero network, zero AI, zero file edits. Everything that fires is deterministic Python.
2. **Cost-aware.** The decision engine + budget estimate plan exactly how many AI calls a real run would make *before* any are placed.
3. **Risk-aware.** The risk engine spots "login + password + auth" as HIGH-risk from the task description alone.
4. **Policy-aware.** YAML policies escalate auth-path changes to mandatory review + human approval.
5. **Security-aware.** Scans for AWS / GitHub / OpenAI / Anthropic / JWT / PEM keys in selected file contents, prompt-injection phrases, and refuses dangerous test commands.
6. **Auditable.** Every decision lands as structured JSON on disk. No black-box decisions.

## Next steps

- Browse [USAGE.md](USAGE.md) for the full command reference.
- Read [README.md](README.md) for the design rationale.
- See [examples/sample-run/](examples/sample-run/) for what a fully-populated real run looks like.
- See [docs/roadmap-issues.md](docs/roadmap-issues.md) for what's next.
