# AgentForge

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

## Policy and safety

Declarative governance lives in `config.yaml`:

```yaml
policies:
  - name: "Auth changes require review"
    match:
      - "auth/**"
      - "**/login*"
    require_review: true
    require_tests: true

  - name: "Never send secrets to AI"
    block:
      - ".env"
      - "*.pem"
      - "credentials.json"
      - "**/secrets*"

  - name: "Database changes require human approval"
    match:
      - "migrations/**"
      - "**/schema.sql"
    require_human_approval: true
```

`block:` patterns are dropped from the context before any prompt is built. `match:` patterns escalate the run (force review, force tests, prompt for human approval). Decisions are saved to `policy_report.json`.

Safety guarantees:

- Only non-destructive git is used: `checkout -b` into a fresh branch.
- Uncommitted changes block branch creation.
- Secret files are filtered at scan time, before any prompt is built.
- Binaries are skipped (NUL-byte sniff).
- No API keys in this repo. Agent CLIs handle their own auth.
- AgentForge never commits, pushes, or merges. You do.

## Run artifacts

Every run produces a stable artifact set under `.agentforge/runs/<timestamp>/`:

```
task.json            input task + classifier verdict
repo_summary.json    file inventory at scan time
selected_files.json  files chosen for the context window
plan.md              planner output (markdown)
prompts.json         exact prompts sent to each agent
policy_report.json   blocked files + escalations
risk_report.json     LOW/MEDIUM/HIGH + score + reasons + recommended workflow
test_result.txt      test stdout/stderr + exit code
diff.patch           implementer's changes
review.json          reviewer verdict (structured JSON)
budget.json          AI calls + chars used vs caps
final_summary.md     human-readable wrap-up
```

Artifacts that didn't get produced (dry-run, early stop, aborted run) are filled with placeholders explaining what happened, so CI and downstream tooling can rely on every file existing.

See [examples/sample-run/](examples/sample-run/) for a realistic example.

## Example commands

```bash
python -m agentforge init                                       # one-time setup
python -m agentforge plan  "fix the off-by-one in pagination"   # plan only
python -m agentforge solve "fix the off-by-one in pagination"   # full pipeline
python -m agentforge solve "fix pagination" --dry-run           # preview, zero AI
python -m agentforge review --task "added webhook check"        # review current diff
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
  policy.py              declarative governance rules
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
