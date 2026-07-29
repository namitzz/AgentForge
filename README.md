# AgentForge

[![CI](https://github.com/namitzz/AgentForge/actions/workflows/ci.yml/badge.svg)](https://github.com/namitzz/AgentForge/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> **AgentForge is a local-first control plane for Claude coding runs.** It helps developers decide when to call Claude versus run a free local check, while enforcing budgets, risk scoring, policy checks, security scanning, and auditable run artifacts. Ships Claude-only; runs on the command line or as a Claude Code plugin.

> **Status: MVP / experimental / developer-controlled.** Designed for safe AI-assisted coding workflows on a single machine. Not production-ready. Not a hosted service. Not a replacement for human code review. See [Not yet implemented](#not-yet-implemented) below.

## Quick demo

The whole demo runs locally with **no AI calls, no network, no API keys**:

```bash
git clone https://github.com/namitzz/AgentForge.git
cd AgentForge
pip install -e .

cd demo-projects/tiny-python-app
agentforge init
agentforge solve "Add password reset validation to the login flow" --dry-run
agentforge status
```

The dry-run preview produces a full audit trail (risk report, policy report, security report, decision report, prompts, budget, merge-readiness score, ...) under `.agentforge/runs/<timestamp>/`. See [DEMO.md](DEMO.md) for the full flow and expected output.

## Use it as a Claude Code plugin

This repo doubles as a **Claude Code plugin marketplace**. Install it to get `/agentforge:*` slash commands and an auto-invoked guardrail skill inside your normal Claude Code session:

```
/plugin marketplace add namitzz/AgentForge
/plugin install agentforge@agentforge-marketplace
```

Then `pip install -e .` once so the `agentforge` CLI the commands call is on PATH. Full details, commands, and local-dev install in [docs/plugin.md](docs/plugin.md).

## What works today

Every item below is implemented in this repo and covered by tests:

- ✅ **Dry-run mode.** `--dry-run` works on `plan`, `solve`, `review`, `review-pr`, and `redteam`. Builds the full prompt set without calling any agent. Writes complete artifacts.
- ✅ **Local risk scoring.** Keyword + path heuristic → LOW (0–39) / MEDIUM (40–69) / HIGH (70–100) score per task. Saved to `risk_report.json`.
- ✅ **Policy checks.** Declarative YAML (`block:` / `match:` / `require_review` / `require_tests` / `require_human_approval`) → `policy_report.json`.
- ✅ **Security checks.** Local scans for secrets in selected file contents (AWS / GitHub / OpenAI / Anthropic / JWT / PEM / SSH / etc.), prompt-injection phrases, and destructive shell commands → `security_report.json`.
- ✅ **Budget estimates + summaries.** Up-front "planned AI calls / chars" + final "actuals" with `stopped_early` and `stop_reason`. Hard caps enforced before each call.
- ✅ **Run artifacts.** Every run writes a stable set of structured JSON / Markdown files under `.agentforge/runs/<timestamp>/`. Placeholders fill in for skipped steps.
- ✅ **PR-style local diff review.** `agentforge review-pr` (working branch vs base) and `agentforge review` (working-tree diff). Diff-only — the reviewer never sees full source.
- ✅ **Red-team review.** `agentforge redteam` with a stricter adversarial prompt and richer structured findings.
- ✅ **Merge-readiness score.** `agentforge readiness` rolls existing artifacts into one 0–100 verdict (READY / READY_WITH_CAUTION / NEEDS_WORK / DO_NOT_MERGE).
- ✅ **Agent decision engine.** Reports `NO_AI / SINGLE_AGENT / IMPLEMENT_AND_REVIEW / FULL_PIPELINE` before any agent is called.
- ✅ **No-Code-Leak Mode.** `--no-code-leak` (or `privacy.no_code_leak_mode: true`) prevents source / file bodies / diff bodies from ever reaching an agent.
- ✅ **Demo project.** Self-contained `demo-projects/tiny-python-app/` exercises the whole pipeline.
- ✅ **Doctor / onboarding.** `agentforge doctor` audits the environment + config. `agentforge init` writes starter files with friendly next-step guidance.
- ✅ **Agent scorecards.** Local per-(agent, role) tally across runs (`.agentforge/scorecards.json`).
- ✅ **Optional anonymous telemetry.** Off by default. Closed-set allowlist of scalars only — never code, paths, prompts, or secrets. See [PRIVACY.md](PRIVACY.md).

## Not yet implemented

Being honest about the gaps so you can decide whether AgentForge fits your need:

- ❌ **No web UI.** CLI only.
- ❌ **No hosted service.** AgentForge runs on your machine and only your machine.
- ❌ **No automatic GitHub PR creation.** You inspect with `git diff main` and merge / push yourself. PR-body generation is on the roadmap.
- ❌ **No token-accurate billing.** Costs are character-based today; token counts are on the roadmap.
- ❌ **No guarantee of perfect security detection.** The secret + injection scanners are pattern-based and best-effort. Obfuscated secrets or novel injection phrasings can slip through.
- ❌ **No replacement for human code review.** AgentForge layers checks on top of human judgement; it does not replace it.

See [docs/roadmap-issues.md](docs/roadmap-issues.md) for the eight follow-up issues sized for individual PRs.

## How the workflow works

```
user task
  -> local repo scan        (no AI)
  -> task classification    (no AI, heuristic)
  -> minimal context build  (no AI)
  -> policy check           (no AI)
  -> risk scoring           (no AI)
  -> security scan          (no AI)
  -> decision engine        (no AI)
  -> planning               (1 AI call, optional)
  -> isolated git branch    (no AI)
  -> implementation         (1 AI call, only relevant files)
  -> tests                  (no AI)
  -> diff-only review       (1 AI call, sees only the diff)
  -> optional revision      (<= 1 extra AI call)
  -> summary + artifacts    (no AI)
```

Most of the pipeline uses zero AI. Defaults cap each run at 5 AI calls and 80k characters.

## What makes AgentForge different

- **Budget-first design.** Hard caps on AI calls, files sent, characters sent, and review loops. Enforced *before* each call, not after.
- **Diff-only review.** The reviewer never sees full source. A 10k-line repo with a 50-line change costs a 50-line review prompt.
- **Risk scoring.** Every task is scored LOW / MEDIUM / HIGH locally before any agent runs.
- **Policy rules.** Declarative YAML to block secrets, force review on risky paths, and gate on human approval.
- **Audit-friendly run logs.** Every run writes a stable set of structured artifacts.
- **Local-first scanning.** Repo walking, secret filtering, binary detection — all local.
- **No endless agent debate.** One pipeline, at most one revision pass, then stop.
- **Claude-first, not locked in.** Ships Claude-only for every role. Agents are thin CLI adapters, so you can swap another coding-agent CLI into any role in `config.yaml` if you want. No SDK lock-in.

## Deep dives

Detailed docs live in [`docs/`](docs/) so this README stays scannable:

| Topic | File |
|---|---|
| Budget control | [docs/budget.md](docs/budget.md) |
| Policy rules | [docs/policies.md](docs/policies.md) |
| Security defaults | [docs/security.md](docs/security.md) |
| No-Code-Leak Mode (content privacy) | [docs/privacy.md](docs/privacy.md) |
| Run artifacts | [docs/run-artifacts.md](docs/run-artifacts.md) |
| Failure handling + error categories | [docs/failure-handling.md](docs/failure-handling.md) |
| Demo (full walkthrough) | [DEMO.md](DEMO.md) |
| Usage reference | [USAGE.md](USAGE.md) |
| Anonymous telemetry (off by default) | [PRIVACY.md](PRIVACY.md) |
| Reporting a vulnerability | [SECURITY.md](SECURITY.md) |
| Roadmap (8 issues) | [docs/roadmap-issues.md](docs/roadmap-issues.md) |
| Release checklist | [docs/release-checklist.md](docs/release-checklist.md) |

## Install

Requires Python 3.11+, git, and (for real runs) the `claude` CLI on PATH.

### Editable install (recommended)

```bash
git clone https://github.com/namitzz/AgentForge.git
cd AgentForge

python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# Windows (cmd)
.venv\Scripts\activate.bat
# macOS / Linux
source .venv/bin/activate

pip install -e .

# Optional dev extras (pytest)
pip install -e ".[dev]"

# Verify
agentforge --help
agentforge doctor
```

`python -m agentforge ...` works without `pip install -e .` if you'd rather not install.

## Risk scoring at a glance

Before any agent runs, AgentForge scores the task on 0–100 and maps to LOW (0–39) / MEDIUM (40–69) / HIGH (70–100):

```
LOW     agentforge plan "Fix typo in README"
MEDIUM  agentforge plan "Refactor the user profile component"
HIGH    agentforge plan "Add password reset to login flow"
```

The full breakdown is written to `risk_report.json` for every run, with `reasons` and a `recommended_workflow`.

## Example commands

```bash
agentforge init                                       # one-time setup
agentforge doctor                                     # environment check
agentforge plan  "fix the off-by-one in pagination"   # plan only
agentforge solve "fix the off-by-one in pagination"   # full pipeline
agentforge solve "fix pagination" --dry-run           # preview, zero AI
agentforge review --task "added webhook check"        # review working-tree diff
agentforge review-pr --base main                      # PR-style branch review
agentforge redteam --dry-run                          # stricter adversarial review
agentforge readiness                                  # 0-100 merge-readiness score
agentforge status                                     # show last run
agentforge scorecards                                 # per-agent stats
agentforge telemetry status                           # show telemetry state (off by default)
```

| Command | Flags | What it does |
|---|---|---|
| `init`       | `--force`, `-c PATH` | Writes `config.yaml`, `.agentforge/project_rules.md`, runs dir. |
| `doctor`     | `-c PATH` | Health check. Always exits 0; warnings inform. |
| `plan`       | `--dry-run`, `--no-code-leak`, `-c PATH` | Plan only. No edits. |
| `solve`      | `--yes/-y`, `--dry-run`, `--no-code-leak`, `-c PATH` | Full pipeline. |
| `review`     | `--task TEXT`, `--dry-run`, `--no-code-leak`, `-c PATH` | Review working-tree diff. |
| `review-pr`  | `--task`, `--base`, `--dry-run`, `--no-code-leak`, `-c PATH` | PR-style branch review. |
| `redteam`    | `--task`, `--base`, `--run PATH`, `--dry-run`, `--no-code-leak`, `-c PATH` | Adversarial review. |
| `readiness`  | `--run PATH`, `-c PATH` | Compute merge-readiness score for a run. |
| `status`     | `-c PATH` | Show last run summary. |
| `test`       | `-c PATH` | Run configured test command. |
| `scorecards` | `--json`, sub: `reset` | Per-agent stats across runs. |
| `telemetry`  | sub: `status` / `enable` / `disable` / `preview` / `clear` | Manage anonymous telemetry (off by default). |

See [USAGE.md](USAGE.md) for the full reference.

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

## Safety guarantees

- Only non-destructive git: `checkout -b` into a fresh branch. Never `push --force`, `reset --hard`, or branch delete.
- Uncommitted changes block branch creation.
- Secret files filtered at scan time, before any prompt is built.
- Binaries skipped (NUL-byte sniff).
- No API keys in this repo. Agent CLIs handle their own auth.
- AgentForge never commits, pushes, or merges. You do.

> These are guarantees about what the orchestrator code does. They are not a guarantee that an agent's *suggested* code is correct or safe — always inspect the diff before merging.

## Roadmap

Eight tightly-scoped follow-ups are detailed in [`docs/roadmap-issues.md`](docs/roadmap-issues.md), each with a title, description, and acceptance criteria ready to paste into a GitHub issue:

1. Add real token estimation (replace char-based budget proxy with agent-reported tokens)
2. Add more agent adapters (Aider / Cursor CLI / local OpenAI-compatible endpoint)
3. Expand agent scorecards with trends + per-task-type breakdown
4. Add GitHub PR body generation (`pr_body.md` artifact, no GitHub API call)
5. Add sandbox / worktree execution (`--sandbox` flag, isolates the user's tree)
6. Add richer language-aware context selection (import-graph aware)
7. Add team policy packs (`auth-strict`, `data-migration-strict`)
8. Add local-only enterprise mode (meta-flag for all conservative defaults)

PRs welcome. The release checklist in [`docs/release-checklist.md`](docs/release-checklist.md) covers what to do before tagging the next version.

## Limitations

- No web UI.
- No auto-PR creation. You push and open the PR yourself.
- Character-based budget approximation, not real token counts.
- Filesystem-only context selection. No AST, no embeddings yet.
- One revision pass max.
- Agent adapters wrap CLIs via subprocess. Direct SDK integration would be a future extension.
- Pattern-based security checks are best-effort, not a guarantee.

## Suggested GitHub metadata

Repository description:

> Cost-aware guardrails for Claude coding runs — CLI + Claude Code plugin.

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
  risk_engine.py         LOW / MEDIUM / HIGH scoring
  security.py            local secret / injection / command scans
  privacy.py             No-Code-Leak Mode
  decision_engine.py     agent routing recommendation
  merge_readiness.py     0-100 merge-readiness score
  scorecards.py          local per-agent stats
  telemetry.py           opt-in anonymous telemetry
  failure.py             status model + failure reports
  logger.py              per-run artifact writer
  agents/                CLI adapters (Claude / Codex / local)
  tools/                 file scanner, git wrappers, diff, tests
  prompts/               planner / implementer / reviewer / redteam prompts
tests/                   pytest suite (300+ tests)
docs/                    deep-dive documentation
examples/sample-run/     example artifact directory
demo-projects/           a tiny safe project for live demos
.github/workflows/ci.yml
config.yaml
```
