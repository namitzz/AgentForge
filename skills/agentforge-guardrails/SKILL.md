---
name: agentforge-guardrails
description: Use when the user is about to make a risky or sensitive code change with AI assistance (anything touching authentication, login, passwords, tokens, sessions, permissions, payments/billing, database migrations, schemas, secrets, or deployment/production config) and wants cost-aware, auditable guardrails. Routes the change through AgentForge to get a local risk score, policy + security checks, a budget estimate, and an auditable run record before and after edits. Also use when the user explicitly asks for AgentForge, a risk check, a merge-readiness score, a diff-only review, or a "dry run" preview of what an AI coding change would cost.
---

# AgentForge guardrails

AgentForge is a local-first control plane for Claude coding runs. It wraps a coding task with deterministic, local checks (risk scoring, policy rules, secret/injection scanning, budget caps) and writes an auditable trail to `.agentforge/runs/<timestamp>/`. Use it to make Claude-assisted changes safer and cheaper — especially on sensitive code. (Claude is the default agent for every role; other CLI adapters are swappable in config but not required.)

## When to reach for this

- The task touches a **sensitive area**: auth/login/logout, passwords, tokens/JWT/sessions, permissions/roles, payment/billing, database migrations/schemas/models, secrets/env, or deployment/production config.
- The user wants to **preview cost or routing** before spending tokens.
- The user wants a **diff-only review** or a **merge-readiness score**.
- The user is worried about **AI cost** or **leaking code/secrets** to an agent.

## How to use it

Prefer the slash commands this plugin ships (`/agentforge:solve`, `/agentforge:plan`, `/agentforge:review`, `/agentforge:readiness`, `/agentforge:doctor`). If you are driving it directly, use the CLI via Bash:

1. **Check it is installed.** `agentforge --version`. If missing, tell the user to run `pip install -e .` from the AgentForge repo, then stop — do not fake results.

2. **Preview first, for free.** For anything non-trivial, start with a dry run — it makes **zero AI calls**, edits nothing, and still produces the full risk/policy/security/budget report:
   ```
   agentforge solve "<task>" --dry-run
   ```
   Read the newest `.agentforge/runs/<timestamp>/` folder and tell the user the risk level, the agent decision (how many AI calls a real run would make), any policy escalations, and security findings.

3. **Respect the guardrails.** If risk is HIGH or policy requires human approval, surface that to the user and do not proceed to a real run without their explicit go-ahead. If `security_report.json` reports `safe_to_continue: false` or blocked secret files, stop and explain.

4. **Privacy.** If the repo is private/commercial and the user does not want code sent to an agent, add `--no-code-leak` (or set `privacy.no_code_leak_mode: true` in `config.yaml`). In that mode `solve` refuses to send source and stops cleanly; `plan` and `review` still work on stats only.

5. **Score before merging.** After a real run, `agentforge readiness` rolls the artifacts into a 0-100 merge-readiness verdict.

## Ground rules

- AgentForge **never** pushes, merges, or commits. The user reviews the diff (`git diff main`) and merges themselves. Never do it for them.
- The risk and security checks are **heuristic and best-effort**, not a guarantee. Present them as a safety layer on top of human review, not a replacement for it.
- Every decision is written to disk as JSON. When you summarize a run, cite the actual artifact values rather than guessing.

See the repo `README.md`, `DEMO.md`, and `docs/` for full details.
