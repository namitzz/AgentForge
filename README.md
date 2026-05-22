# AgentForge

[![CI](https://github.com/your-org/agentforge/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/agentforge/actions/workflows/ci.yml)
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

```bash
pip install -r requirements.txt
cd ~/code/my-app
python -m agentforge init
```

Edit `config.yaml` to point at your installed agent CLIs and to add any policies you want enforced.

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
