# AgentForge

[![CI](https://github.com/namitzz/AgentForge/actions/workflows/ci.yml/badge.svg)](https://github.com/namitzz/AgentForge/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> Cost-aware governance for Claude, Codex, and future coding agents.

**AgentForge is not another coding agent. It is a cost-aware control plane for coding agents.**

It decides when to use Claude, when to use Codex, when to use local tools, and when to stop. The goal is not maximum agent chatter. The goal is minimum useful AI usage with reviewable, test-gated code changes.

## Why AgentForge exists

Most "multi-agent" tools let agents converse until they agree. That burns tokens, ignores the repo's risk surface, and produces changes nobody reviewed. AgentForge replaces that loop with a fixed pipeline:

- A local classifier picks the cheapest valid route for each task.
- Only the files the task needs are sent.
- The reviewer sees only the diff.
- One revision pass, then stop.
- Runs stop early when tests pass and risk is low.
- Every step is logged and budget-enforced.

If a task can run cheaper, AgentForge will run it cheaper. If it cannot run safely, AgentForge stops and asks.

## What makes AgentForge different

- **Budget-first design.** Hard caps on AI calls, files sent, characters sent, and review loops. Enforced *before* each call, not after.
- **Diff-only review.** The reviewer never sees full source. A 10k-line repo with a 50-line change costs a 50-line review prompt.
- **Risk scoring.** Every task is scored LOW / MEDIUM / HIGH locally before any agent runs. HIGH-risk changes require human approval.
- **Policy rules.** Declarative YAML to block secrets, force review on risky paths, and gate on human approval.
- **Audit-friendly run logs.** Every run writes a stable set of structured artifacts to `.agentforge/runs/<timestamp>/`.
- **Local-first scanning.** Repo walking, secret filtering, binary detection — all local.
- **No endless agent debate.** One pipeline, at most one revision pass, then stop.
- **Model-neutral architecture.** Agents are CLI adapters. Swap Claude for Codex per role in `config.yaml`. No SDK lock-in.

## How the workflow works

```
user task
  -> local repo scan        (no AI)
  -> task classification    (no AI, heuristic)
  -> minimal context build  (no AI)
  -> policy check           (no AI)
  -> risk scoring           (no AI)
  -> planning               (1 AI call, optional)
  -> isolated git branch    (no AI)
  -> implementation         (1 AI call, only relevant files)
  -> tests                  (no AI)
  -> diff-only review       (1 AI call, sees only the diff)
  -> optional revision      (<= 1 extra AI call)
  -> summary + artifacts    (no AI)
```

Seven of the eleven steps use zero AI. Defaults cap each run at 5 AI calls and 80k characters.

## How it saves AI usage

| Mechanism | What it does |
|---|---|
| Local task classification | Bug fixes skip the planner. Docs skip the reviewer. Tests skip both. |
| Minimal context | Top-N relevant files get sent. Never the whole repo. |
| Per-file + total caps | `max_chars_per_file` and `max_total_chars` enforced before any prompt is built. |
| Diff-only review | Reviewer prompt scales with change size, not repo size. |
| Bounded revision loop | One revision pass max. |
| Early stop | If tests pass and the diff is low-risk, review is skipped entirely. |
| Hard budget | `BudgetExceeded` raised before going over the cap. |
| Dry-run mode | Preview the exact prompts and routing decisions for free. |
| Risk-aware routing | LOW-risk changes get a lighter pipeline. |

## Budget control

Every run shows its budget twice. Once up front, as an **estimate** built from the routing + the prompts the orchestrator has prepared:

```
Budget estimate:
- Planned AI calls: 3/5
- Files selected: 5/8
- Estimated chars sent: 34,200
- Review loops allowed: 1
- Dry run: no
```

And once at the end, as a **summary** of the actuals:

```
Budget summary:
- AI calls used: 2/5
- Review loops used: 1/1
- Files sent: 5/8
- Estimated chars sent: 34,200
- Stopped early: no
```

The summary appends `Stop reason: ...` whenever a run stops short — for example because tests passed and review wasn't required (early stop), the agent CLI wasn't installed (abort), or the caller declined the human-approval prompt.

`BudgetManager` enforces these caps in `config.yaml`:

```yaml
max_ai_calls_per_run: 5
max_review_loops: 1
max_files_sent: 8
max_chars_per_file: 12000
max_total_chars: 80000
```

If the up-front estimate would exceed `max_ai_calls_per_run` or `max_total_chars`, the run aborts before any agent is contacted, with the exact message that exceeded the cap. If the estimate fits but an in-flight call would push us over, `BudgetExceeded` is raised at that point and `_finalize_aborted` writes a complete artifact set so the partial work is still inspectable.

Approximation note: cost is character-based, not token-accurate. Good enough to keep spend bounded; not accurate to the cent.

Every run also writes the full structure to `.agentforge/runs/<timestamp>/budget.json`:

```json
{
  "ai_calls": 2,
  "review_loops": 1,
  "chars_sent": 34200,
  "files_sent": 5,
  "max_ai_calls": 5,
  "max_review_loops": 1,
  "max_total_chars": 80000,
  "max_files_sent": 8,
  "max_chars_per_file": 12000,
  "planned_ai_calls": 3,
  "planned_chars_sent": 35000,
  "dry_run": false,
  "stopped_early": false,
  "stop_reason": null
}
```

## Risk scoring

Before any agent runs, AgentForge scores the task on a 0–100 scale and maps it to LOW (0–39), MEDIUM (40–69), or HIGH (70–100). The score combines task keywords with selected file paths.

```
$ python -m agentforge plan "Add password reset to login flow" --dry-run

Risk assessment:
- Level: HIGH
- Score: 75/100
- Reasons:
  - Task mentions high-risk topics: login, password
- Recommended workflow:
  - Claude planning required
  - Codex implementation allowed
  - Tests strongly recommended
  - Claude diff review required
  - Human approval required before merge
```

Examples by level:

```
LOW     python -m agentforge plan "Fix typo in README"
MEDIUM  python -m agentforge plan "Refactor the user profile component"
HIGH    python -m agentforge plan "Add password reset to login flow"
```

The full breakdown is written to `risk_report.json` for every run.

## Dry run

`--dry-run` is the way to try AgentForge without installing Claude, Codex, or any API key. It works on every workflow command:

```bash
python -m agentforge plan      "Fix the off-by-one in pagination"     --dry-run
python -m agentforge solve     "Add password reset validation"        --dry-run
python -m agentforge review    --task "added webhook check"           --dry-run
python -m agentforge review-pr --task "Review password reset changes" --dry-run
```

What dry-run **does**:

- Scans the repo, classifies the task, picks files for the context window.
- Runs local risk scoring + policy checks against the selected files.
- Builds the exact prompts that would be sent (planner, implementer, reviewer).
- Prints the planned agent workflow, the file list, the budget estimate.
- Writes the full artifact set under `.agentforge/runs/<timestamp>/` so you can inspect every prompt and decision.

What dry-run **does not** do:

- Call Claude or Codex.
- Modify any files.
- Create a git branch.
- Run any destructive command.

Sample output:

```
Dry run: enabled
No external agents will be called.
No files will be modified.

Planned workflow:
  1. Local scan
  2. Task classification
  3. Context selection
  4. Policy check
  5. Risk assessment
  6. Claude planning prompt would be generated
  7. Codex implementation prompt would be generated
  8. Tests would run
  9. Claude diff review prompt would be generated

Files that would be sent:
  - src/auth/login.py
  - src/auth/password_reset.py
  - src/auth/models.py
  - src/utils/validators.py
  - tests/test_auth.py

Risk assessment:
- Level: HIGH
- Score: 85/100
- Reasons:
  - Task mentions high-risk topics: login, password, auth
  - Selected file paths include sensitive areas: auth/, /auth.
- Recommended workflow:
  - Claude planning required
  - Codex implementation allowed
  - Tests strongly recommended
  - Claude diff review required
  - Human approval required before merge

Policy checks:
- Blocked files: none
- Review required: yes
- Tests required: yes
- Human approval required: yes
- Reasons:
  - Auth changes require review
  - Sensitive flows require human approval

Budget estimate:
- Planned AI calls: 3/5
- Files selected: 5/8
- Estimated chars sent: 42,180
- Review loops allowed: 1
- Dry run: yes

Run artifacts saved to:
  .agentforge/runs/20260522-141207/
```

Use it as a smoke test in CI, before any real `solve` on a new repo, or when the agent CLIs simply aren't installed yet. If an agent CLI is missing, AgentForge fails fast and explicitly suggests `--dry-run` in the error message.

## Project rules

`agentforge init` writes a starter file at `.agentforge/project_rules.md`. Anything you put there gets pasted verbatim into the planner, implementer, and reviewer prompts on every run — a small memory file so you don't have to repeat project conventions on the command line.

Default contents:

```markdown
# Project Rules

- Keep changes small and focused.
- Prefer existing project style.
- Do not modify authentication, security, database, or deployment files without review.
- Do not send secrets or environment files to AI agents.
- Explain risky changes clearly.
- Do not auto-merge or force-push changes.
```

Edit it to taste — code style, naming conventions, hard "don't touch" zones, framework-specific guidance, links to internal docs. The file is plain Markdown and free-form. If it's missing, the run continues safely and the CLI notes:

```
Project rules: none found (continuing safely; create .agentforge/project_rules.md to add project-specific guidance)
```

When it's present:

```
Project rules: loaded from .agentforge/project_rules.md (304 chars)
```

The rules show up in `prompts.json` as part of each agent's prompt, so the audit trail makes it clear what guidance was active for a given run. No database, no external service — just one Markdown file in your repo.

## Policy rules

Declarative governance lives in `config.yaml`:

```yaml
policies:
  - name: "Never send secrets to AI"
    block:
      - ".env"
      - "*.pem"
      - "credentials.json"
      - "**/secrets*"

  - name: "Auth changes require review"
    match:
      - "auth/**"
      - "**/login*"
      - "**/security*"
    require_review: true
    require_tests: true

  - name: "Database changes require human approval"
    match:
      - "migrations/**"
      - "**/schema.sql"
      - "**/models.py"
    require_human_approval: true
```

The `PolicyEngine` (in `agentforge/policy_engine.py`) evaluates these rules against the set of files the run is about to send to an agent. `block:` patterns are dropped from the context before any prompt is built. `match:` patterns escalate the run: force review, force tests, prompt for human approval. Decisions are saved to `policy_report.json`.

Sample terminal output:

```
Policy checks:
- Blocked files: .env
- Review required: yes
- Tests required: yes
- Human approval required: yes
- Reasons:
  - Auth changes require review
  - Never send secrets to AI
```

Pattern matching supports glob syntax (`**/x` for any depth, `dir/**` for everything under a dir, plain `fnmatch` otherwise). Empty pattern lists are skipped without error.

### Minimum secure-default config

If you want the most conservative posture, start from this. Tighten the budget caps, expand the secret file and policy lists, force review + tests + human approval for anything touching auth, secrets, or the database. Drop into `config.yaml`:

```yaml
# Tight budget. Fail closed when in doubt.
max_ai_calls_per_run: 3
max_review_loops: 0
max_files_sent: 5
max_chars_per_file: 8000
max_total_chars: 40000

# Files always filtered by name before any prompt is built.
secret_files:
  - .env
  - .env.local
  - .env.production
  - credentials.json
  - id_rsa
  - id_ed25519

policies:
  - name: "Never send secrets to AI"
    block:
      - ".env"
      - ".env.*"
      - "*.pem"
      - "*.key"
      - "credentials*"
      - "**/secrets*"
      - "**/private*"
      - "**/id_rsa*"
      - "**/id_ed25519*"

  - name: "Sensitive paths require human approval"
    match:
      - "**/auth*"
      - "**/login*"
      - "**/security*"
      - "migrations/**"
      - "**/schema*"
      - "**/models.py"
    require_review: true
    require_tests: true
    require_human_approval: true
```

On top of those rules, the content scanner in `agentforge/security.py` drops any file whose body matches a known credential pattern (AWS, GitHub, OpenAI, Anthropic, JWT, PEM private key, SSH key) regardless of its name. The pattern name lands in `security_report.json`; the actual secret value is never logged.

## Security defaults

Without any config changes, every run already does this:

| Layer | What it does | Default |
|---|---|---|
| Name filter | Drop files whose name matches `secret_files:` | `.env`, `.env.local`, `.env.production`, `credentials.json`, `service-account.json`, `secrets.yaml`, `secrets.yml`, `id_rsa`, `id_ed25519` |
| Policy `block:` | Drop files matching glob patterns | `.env`, `.env.*`, `*.pem`, `credentials.json`, `**/secrets*` |
| Secret value scan | Drop files whose **content** matches a vendor credential pattern | AWS keys, GitHub tokens, OpenAI / Anthropic keys, JWTs, PEM private keys, SSH keys, Slack / Google API keys |
| Env-marker scan | Warn on `API_KEY=`, `PASSWORD=`, `TOKEN=`, `SECRET=` with a non-placeholder value | files kept, flagged in `suspicious_files` |
| Prompt-injection scan | Warn on phrases like *ignore previous instructions*, *exfiltrate*, *disable safety*, *upload this code*, *print environment variables* | files kept, listed in `prompt_injection_warnings` |
| Command safety | Refuse to run `default_test_command` if it matches a destructive pattern | `rm -rf /`, `mkfs`, `dd of=/dev/...`, fork bomb, `curl | sh`, `format C:`, `del /s`, `rmdir /s`, `git push --force`, `git reset --hard`, `git clean -fd`, `shutdown` |
| Git operations | Only `git checkout -b` into fresh branches | no `push`, `reset`, `force-push`, or branch deletion |
| Reviewer scope | Diff only | full source never sent to the reviewer |

Every check runs locally. No network, no LLM, no third-party services. Findings land in `.agentforge/runs/<timestamp>/security_report.json`:

```json
{
  "blocked_files": ["src/utils/keys.py"],
  "suspicious_files": ["docs/notes.md"],
  "prompt_injection_warnings": [
    {"file": "docs/notes.md", "phrase": "ignore previous instructions"}
  ],
  "command_risk": "low",
  "command_blocked": false,
  "reasons": ["Dropped 1 file(s) containing secret patterns: aws_access_key"],
  "safe_to_continue": true
}
```

The matched secret value is **never** written to that file — only the pattern name and the file path.

Terminal output:

```
Security checks:
- Blocked secret files: src/utils/keys.py
- Prompt-injection warnings: 1
    - docs/notes.md: "ignore previous instructions"
- Command risk: low
- Safe to continue: yes
```

If you want the most conservative posture on top of these defaults, drop the [Minimum secure-default config](#minimum-secure-default-config) block above into your `config.yaml`.

## Merge readiness score

After any run (real or dry), AgentForge can roll up the artifacts into a single 0-100 score that answers "is this safe to merge?":

```bash
agentforge readiness                                 # score the latest run
agentforge readiness --run .agentforge/runs/<id>     # score a specific run
```

The engine reads `risk_report.json`, `policy_report.json`, `security_report.json`, `budget.json`, `review.json`, `test_result.txt`, `failure_report.json`, and `task.json` and applies a transparent set of deductions. It never calls an agent.

### Levels

| Score | Level | Meaning |
|---|---|---|
| 90–100 | `READY` | All core gates passed. Safe to merge. |
| 70–89  | `READY_WITH_CAUTION` | Core checks passed but warnings worth reviewing. |
| 40–69  | `NEEDS_WORK` | Several issues need attention before merging. |
| 0–39   | `DO_NOT_MERGE` | Critical issues block merge. |

### Hard caps

Regardless of arithmetic, the score is forced below `READY` (capped at 89) when any of these holds:

- tests failed
- review status is `needs_changes`
- security says `safe_to_continue: false`
- `failure_report.json` is present
- human approval is required but not yet recorded

### Deductions

| Trigger | Subtract |
|---|---|
| `failure_report.json` present with status `failed` | 35 |
| Security says `safe_to_continue: false` | 30 |
| Secret-bearing files were dropped | 25 |
| Tests failed | 25 |
| Tests did not run | 15 |
| Reviewer requested changes | 20 |
| Risk level `HIGH` | 15 |
| Risk level `MEDIUM` | 8 |
| Human approval required (not recorded) | 15 |
| Policy requires review but none recorded | 10 |
| Policy requires tests but they did not run | 10 |
| Run stopped early | 5 |
| Prompt-injection warnings present | 5 |

### CLI output

```
Merge readiness:
- Score: 78/100
- Level: READY_WITH_CAUTION
- Recommendation: Do not merge until human approval is recorded.

Passed:
  - No secret files were sent
  - Policy checks completed
  - Diff review completed and approved

Warnings:
  - Task classified as HIGH risk
  - Human approval required before merge

Blockers: (none)

Artifact: .agentforge/runs/<id>/merge_readiness.json
```

### JSON artifact

`merge_readiness.json` is written alongside the other artifacts. CI can grep `level` to gate a merge job:

```json
{
  "score": 78,
  "level": "READY_WITH_CAUTION",
  "summary": "The change passed core checks but requires human approval because it touches auth-related files.",
  "passed": ["No secret files were sent", "Policy checks completed", "Diff review completed and approved"],
  "warnings": ["Task classified as HIGH risk", "Human approval required before merge"],
  "blockers": [],
  "recommendation": "Do not merge until human approval is recorded.",
  "deductions": [
    {"reason": "HIGH risk task", "points": 15},
    {"reason": "Human approval required", "points": 15}
  ]
}
```

## Failure handling

Every run lands in one of five statuses:

| Status | Meaning |
|---|---|
| `completed` | Full pipeline ran end to end. |
| `dry_run_completed` | `--dry-run` finished without calling any agent. |
| `stopped_early` | Clean stop before completion (tests passed and review wasn't needed, or the budget cap was hit cleanly). |
| `failed` | An error prevented the run from completing. A `failure_report.json` is on disk. |
| `planned` | Reserved for future scheduled/queued runs. |

When something goes wrong AgentForge stops safely and writes `.agentforge/runs/<timestamp>/failure_report.json`:

```json
{
  "status": "failed",
  "error_category": "AGENT_ERROR",
  "message": "'claude' not found on PATH. Install it, or update the command in config.yaml.",
  "step_failed": "planning",
  "safe_to_retry": false,
  "suggested_fix": [
    "Install the missing agent CLI (claude / codex)",
    "Or update claude_command / codex_command in config.yaml",
    "Or run again with --dry-run to preview without calling an agent"
  ],
  "partial_artifacts_written": ["task.json", "repo_summary.json", "selected_files.json", "..."],
  "timestamp": "2026-05-24T14:12:34"
}
```

The CLI surfaces the same content:

```
AgentForge stopped safely.
Reason: 'claude' not found on PATH. Install it, or update the command in config.yaml.
Category: AGENT_ERROR
Step: planning
Safe to retry: no

Suggested fix:
  - Install the missing agent CLI (claude / codex)
  - Or update claude_command / codex_command in config.yaml
  - Or run again with --dry-run to preview without calling an agent
(Retrying without changes will hit the same error.)
```

### Error categories

| Category | Triggers | What to do |
|---|---|---|
| `AGENT_ERROR` | `claude` / `codex` CLI missing, timed out, or returned an empty response | Install the CLI, or `--dry-run`. Safe to retry: no. |
| `BUDGET_ERROR` | `max_ai_calls_per_run`, `max_total_chars`, or `max_review_loops` exceeded | Raise the cap or narrow the task. Safe to retry: yes (after config change). |
| `GIT_ERROR` | not a git repo, dirty tree, branch name conflict | `git init`, commit/stash, or rename branch. Safe to retry: yes. |
| `TEST_ERROR` | `default_test_command` refused by security check or failed at run time | Update the command, inspect `test_result.txt` and `security_report.json`. |
| `SECURITY_ERROR` | secret-bearing files or dangerous command detected | Fix the offending file or command; rotate any leaked secret. |
| `POLICY_ERROR` | a YAML policy blocked something the run needed | Adjust `policies:` in `config.yaml`. |
| `CONFIG_ERROR` | missing or malformed `config.yaml` | `agentforge init`, or pass `--config`. |
| `ARTIFACT_ERROR` | can't write to `.agentforge/runs/` (disk full, permissions) | Check disk and permissions. |
| `UNKNOWN_ERROR` | uncaught exception or `Ctrl+C` | Re-run with `--dry-run` to isolate. Open an issue with the failure report. |

### Timeouts

Agent and test commands honour `command_timeout_seconds` in `config.yaml` (default `600`). If a subprocess doesn't return in that many seconds, AgentForge stops it, marks the run `failed`, and writes a failure report. Lower it for tight CI; raise it for big refactors or slow test suites.

### Interrupted runs

`Ctrl+C` is caught at the top level. The run is marked `failed`, a failure report is written, and partial artifacts (everything that landed before the interrupt) are kept under `.agentforge/runs/<timestamp>/`. You can resume by re-running the same command — there is no shared state to clean up.

### Invalid agent JSON

If the reviewer returns text that isn't valid JSON (or wraps it in code fences), AgentForge:

1. Strips the most common wrappers (` ```json `, ` ``` `).
2. Tries to extract the first JSON object.
3. If both fail, saves the raw output and marks the verdict as `needs_changes` with `summary: "reviewer returned non-JSON output"` so a human can read it. The run is not aborted.

## Privacy and telemetry

Telemetry is **off by default**. AgentForge sends nothing over the network unless you explicitly opt in:

```bash
python -m agentforge telemetry status      # show current state
python -m agentforge telemetry enable      # prints what's collected, asks for confirmation
python -m agentforge telemetry preview     # show the latest event without sending
python -m agentforge telemetry disable     # turn it off, clear the anonymous ID
python -m agentforge telemetry clear       # delete all local telemetry data
```

When enabled, AgentForge collects a closed-set allowlist of fields: version, command type, dry-run flag, risk level, counts of policy / security findings, AI calls used vs planned, review loops used, run duration in ms, stopped-early flag, error category on failure, OS family, Python version, plus a random anonymous UUID generated at enable time.

It **never** collects: source code, file contents, prompts, diffs, file paths, repo names, branch names, task descriptions, usernames, emails, environment variables, secrets, or command stdout/stderr.

If you provide `--endpoint <url>` events are POSTed there (with a 3-second timeout and silent failure on error). Without an endpoint, events are written locally to `.agentforge/telemetry/events.jsonl` so you can inspect them and decide.

See [PRIVACY.md](PRIVACY.md) for the complete field list, the never-collected list, where data is stored, and how to delete it.

## Safety

- Only non-destructive git is used: `checkout -b` into a fresh branch.
- Uncommitted changes block branch creation.
- Secret files are filtered at scan time, before any prompt is built.
- Binaries are skipped (NUL-byte sniff).
- No API keys in this repo. Agent CLIs handle their own auth.
- AgentForge never commits, pushes, or merges. You do.

## Run artifacts

Every run leaves a complete audit trail under `.agentforge/runs/<timestamp>/`:

```
.agentforge/runs/20260520-141207/
├── task.json            input task + run manifest (start/end, command, workflow)
├── repo_summary.json    file inventory at scan time
├── selected_files.json  files chosen for the context window
├── risk_report.json     LOW/MEDIUM/HIGH + score + reasons + recommended workflow
├── policy_report.json   blocked files + escalations
├── security_report.json secret content scan + injection warnings + command safety verdict
├── budget.json          planned vs actual AI calls + chars
├── prompts.json         exact prompts sent to each agent
├── plan.md              planner output (markdown)
├── test_result.txt      test stdout/stderr + exit code
├── diff.patch           implementer's changes
├── review.json          reviewer verdict (structured JSON)
└── final_summary.md     human-readable wrap-up
```

The 12 files are always present. When a step is skipped (dry-run, early stop, abort) the corresponding artifact is filled with a placeholder explaining what happened, so CI and downstream tooling can rely on every file existing.

`task.json` is the top-level **run manifest**:

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

### See it without running it

A complete worked example is in [`examples/sample-run/`](examples/sample-run/) — all 12 artifacts for a realistic HIGH-risk task ("Add password reset validation to the login flow"), so you can understand the audit trail without installing any agent CLI.

## Example commands

```bash
python -m agentforge init                                       # one-time setup
python -m agentforge plan  "fix the off-by-one in pagination"   # plan only
python -m agentforge solve "fix the off-by-one in pagination"   # full pipeline
python -m agentforge solve "fix pagination" --dry-run           # preview, zero AI
python -m agentforge review --task "added webhook check"        # review working-tree diff
python -m agentforge review-pr --dry-run                        # PR-style branch review
python -m agentforge status                                     # latest run summary
```

`--dry-run` shows the routing, prompts, risk score, and policy decisions without spending any tokens. Useful when:

- the agent CLIs aren't installed yet
- you want to preview a risky task before paying for it
- you're using AgentForge in CI as a pre-flight check

### Dry-run example

```
$ python -m agentforge solve "Add password reset flow" --dry-run

Dry run: enabled
No external agents will be called.
No files will be modified.

Planned workflow:
  1. Local scan
  2. Task classification
  3. Context selection
  4. Policy check
  5. Risk assessment
  6. Claude planning prompt would be generated
  7. Codex implementation prompt would be generated
  8. Tests would run
  9. Claude diff review prompt would be generated
```

The run still writes the full artifact set (`task.json`, `risk_report.json`, `policy_report.json`, `prompts.json`, `budget.json`, ...) so you can inspect exactly what would have been sent. Steps that didn't execute are filled with placeholders explaining why.

If the agent CLI isn't installed, AgentForge fails fast and explicitly suggests `--dry-run`:

```
'claude' not found on PATH. Install it, or update the command in config.yaml.
Tip: the agent CLI doesn't seem to be installed. Re-run with --dry-run to
preview the full pipeline (scan, classify, risk score, prompts) without
calling any external agent.
```

## PR review mode

`agentforge review-pr` reviews the **current branch** against `main` (falling back to `master`) without needing the full `solve` workflow. Use it as a local-only second opinion before opening a real PR.

```bash
python -m agentforge review-pr
python -m agentforge review-pr --task "Review password reset changes"
python -m agentforge review-pr --base develop
python -m agentforge review-pr --dry-run
```

What it does:

1. Detects the current branch (`git rev-parse --abbrev-ref HEAD`).
2. Picks a base branch: `--base` if you passed one, else `main`, else `master`. Aborts cleanly if none of those exist.
3. Collects the branch-style diff (`git diff base...HEAD`) and the list of changed files.
4. Runs risk scoring on the task + changed paths.
5. Runs the policy engine on the changed paths (e.g. block secrets, force review on auth changes).
6. Builds a review prompt that includes: task, base + head branches, the changed file list, the local risk + policy summaries, and the diff. Saves it to `prompts.json`.
7. If `--dry-run`, prints the prompt size and stops. Otherwise calls the configured reviewer agent.
8. Saves the same artifact set as every other run.

The CLI prints:

```
- PR review: main...agentforge/add-password-validation
- Changed files (3): src/utils/validators.py, src/auth/login.py, tests/test_auth.py
- Risk assessment:
- - Level: HIGH
- - Score: 75/100
- Policy checks:
- - Review required: yes
- - Human approval required: yes
- Budget estimate:
- - Planned AI calls: 1/5
- ...
Run artifacts saved to:
  .agentforge/runs/20260521-001500/
```

What it does **not** do:

- Never pushes a branch.
- Never opens a GitHub PR.
- Never requires GitHub authentication or a `GITHUB_TOKEN`.
- Never merges anything. The branch is yours.

## Comparison

| Capability | AgentForge | Claude Code alone | Codex alone | Cursor / Copilot-style | Manual copy-paste |
|---|---|---|---|---|---|
| Multi-agent routing | yes | no | no | rarely | manual |
| Budget limits | enforced | per-message | per-message | per-message | none |
| Diff-only review | yes | no | no | no | no |
| Risk scoring | yes (local) | no | no | no | no |
| Policy rules | yes (YAML) | no | no | no | manual |
| Audit logs (per run) | yes | session-level | session-level | no | no |
| Human approval gate | yes | implicit | implicit | rare | manual |
| Local-first scanning | yes | yes | yes | varies | no |
| No endless agent conversation | guaranteed | n/a | n/a | not guaranteed | n/a |

## Install

Requires Python 3.11+, git, and (for real runs) the `claude` and/or `codex` CLIs.

### From source (editable install)

```bash
git clone https://github.com/namitzz/AgentForge.git
cd AgentForge

# Create + activate a virtualenv
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# Windows (cmd)
.venv\Scripts\activate.bat
# macOS / Linux
source .venv/bin/activate

# Install AgentForge as an editable package — gives you the `agentforge`
# console script and lets you edit the source in place.
pip install -e .

# (Optional) install dev extras (pytest)
pip install -e ".[dev]"
```

After install, the `agentforge` command is on your PATH:

```bash
agentforge --help
agentforge init
agentforge doctor
agentforge solve "Fix typo in README" --dry-run
```

### Without installing

If you'd rather not install, you can run the package as a module:

```bash
pip install -r requirements.txt
python -m agentforge init
python -m agentforge solve "Fix typo in README" --dry-run
```

Both invocations are first-class. The `agentforge` console script and `python -m agentforge` are equivalent.

### Per-project setup

```bash
cd ~/code/my-app
agentforge init
agentforge doctor
```

Edit `config.yaml` to point at your installed agent CLIs and to add any policies you want enforced.

## Demo

`demo-projects/tiny-python-app/` is a tiny, dependency-free Python app (login + reset-password + email validator) included specifically so you can exercise the full AgentForge pipeline without having a project of your own. **No secrets, no external services.**

```bash
# Option 1 — one-shot script
python scripts/demo_dry_run.py

# Option 2 — manual
cd demo-projects/tiny-python-app
python -m agentforge init
python -m agentforge solve "Add password reset validation to the login flow" --dry-run
```

Expected output (abridged):

```
Dry run: enabled
No external agents will be called.
No files will be modified.

Planned workflow:
  1. Local scan
  2. Task classification
  3. Context selection
  4. Policy check
  5. Risk assessment
  6. Claude planning prompt would be generated
  7. Codex implementation prompt would be generated
  8. Tests would run
  9. Claude diff review prompt would be generated

Security checks:
- Blocked secret files: none
- Prompt-injection warnings: 0
- Command risk: low
- Safe to continue: yes

Files that would be sent:
  - src/auth/login.py
  - src/auth/password_reset.py
  - src/utils/validators.py
  - tests/test_auth.py
  - README.md

Risk assessment:
- Level: HIGH
- Score: 85/100
- Reasons:
  - Task mentions high-risk topics: login, password
  - Selected file paths include sensitive areas: auth/

Policy checks:
- Blocked files: none
- Review required: yes
- Tests required: yes
- Reasons:
  - Auth changes require review

Budget estimate:
- Planned AI calls: 3/5
- Files selected: 5/8
- Estimated chars sent: ~6,800
- Review loops allowed: 1
- Dry run: yes

Run artifacts saved to:
  .agentforge/runs/<timestamp>/
```

After the run, inspect:

```bash
ls demo-projects/tiny-python-app/.agentforge/runs/
cat demo-projects/tiny-python-app/.agentforge/runs/<latest>/final_summary.md
```

The demo project also ships a tiny stdlib test suite:

```bash
cd demo-projects/tiny-python-app
python -m unittest discover -s tests
```

See [demo-projects/tiny-python-app/README.md](demo-projects/tiny-python-app/README.md) for details.

### Try it in 2 minutes

You can exercise the entire pipeline without installing Claude or Codex — `--dry-run` mode runs the scan, classifier, policy + risk + security checks, and prompt builders locally, then writes the full artifact set.

```bash
git clone <this repo>
cd AgentForge
pip install -r requirements.txt

# Set up config + .agentforge/ in a project of your choice
cd ~/code/my-app
python -m agentforge init

# Verify environment + show what's optional
python -m agentforge doctor

# Run end-to-end with no AI calls
python -m agentforge solve "Fix typo in README" --dry-run

# Inspect the audit trail
python -m agentforge status
ls .agentforge/runs/
```

`agentforge doctor` reports Python version, git availability, whether the CWD is a repo, presence of `config.yaml` / `project_rules.md`, Claude/Codex CLIs (flagged as warnings if missing — dry-run still works), test command, security defaults, and telemetry state.

## Roadmap

Rough order of priority:

- Token-accurate budgeting using agent-reported usage. Today we count characters.
- Per-task policy overrides (`--policy` flag).
- YAML hook for per-task-type routing. Today it lives in `task_classifier.py`.
- Open a draft PR via `gh` from the agent branch after human approval.
- Embeddings-based context selection as an opt-in upgrade.
- Additional agent adapters beyond Claude Code and Codex CLI.
- Multi-language test-runner auto-detection.
- Run replay: re-run a failed run with the same prompts and a different agent.

PRs welcome.

## Limitations

- No web UI.
- No auto-PR creation. You push and open the PR yourself.
- Character-based budget approximation, not real token counts.
- Filesystem-only context selection. No AST, no embeddings yet.
- One revision pass max.
- Agent adapters wrap CLIs via subprocess. Direct SDK integration would be a future extension.

## Suggested GitHub metadata

Repository description:

> Cost-aware control plane for Claude, Codex, and AI coding agents.

Topics:

`ai-agents`, `coding-agent`, `claude-code`, `codex`, `multi-agent`, `developer-tools`, `ai-code-review`, `git`, `cli-tool`, `agent-orchestration`, `ai-governance`

## Project layout

```
agentforge/
  main.py                CLI (typer)
  orchestrator.py        the pipeline
  config.py              YAML loader
  task_classifier.py     heuristic classifier
  context_builder.py     minimal-context picker
  budget.py              hard budget caps + reporting
  policy_engine.py       declarative governance rules
  project_rules.py       loads .agentforge/project_rules.md
  risk_engine.py         LOW / MEDIUM / HIGH scoring
  logger.py              per-run artifact writer
  agents/                CLI adapters (Claude / Codex / local)
  tools/                 file scanner, git wrappers, diff, tests
  prompts/               planner / implementer / reviewer prompts
tests/                   pytest suite
examples/sample-run/     example artifact directory
.github/workflows/ci.yml
config.yaml
```
