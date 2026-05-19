# AgentForge

A **cost-aware multi-agent coding orchestrator**. Use Claude Code and OpenAI
Codex-style agents together in a structured workflow that minimises wasted AI
calls and keeps a human in the loop.

> Multi-agent does **not** mean unlimited agent-to-agent chatter. AgentForge
> runs a fixed pipeline, sends only relevant context, reviews diffs (not whole
> files), allows at most one revision loop, and stops as soon as tests pass and
> the reviewer is happy.

---

## Why this exists

Most "multi-agent" setups burn tokens by letting agents converse until they
agree. AgentForge replaces the chat loop with a deterministic pipeline:

```
user task
  → local repo scan         (no AI)
  → task classification     (no AI, heuristic)
  → minimal context build   (no AI)
  → planning                (1 AI call, planner agent)
  → git branch              (no AI)
  → implementation          (1 AI call, coding agent, gets only relevant files)
  → tests                   (no AI)
  → diff-only review        (1 AI call, reviewer agent, sees ONLY the diff)
  → optional revision       (≤ 1 extra AI call, gated)
  → final summary           (no AI)
```

Defaults keep total spend under **5 AI calls** and **80k characters** per run.

---

## How it saves usage

| Optimisation | What it does |
|---|---|
| Task classification (local) | Cheap bug fixes skip the planner entirely. Docs skip the reviewer. |
| Minimal context | Only the top-N files relevant to the task are sent — never the whole repo. |
| Per-file + total caps | Every file is capped (`max_chars_per_file`); the prompt as a whole is capped (`max_total_chars`). |
| Diff-only review | The reviewer never sees full source — only `git diff`. |
| Bounded revision loop | At most `max_review_loops` revision pass (default 1). |
| Early stop | If tests pass and review approves, the run ends. |
| Hard budget | `BudgetExceeded` is raised before going over `max_ai_calls_per_run`. |
| Ignore list | `.git`, `node_modules`, `venv`, `dist`, `build`, secret files, binaries — never scanned, never sent. |

---

## Install

Requires Python 3.11+, `git`, and (for full runs) the `claude` and/or `codex`
CLIs installed and authenticated.

```bash
pip install -r requirements.txt
```

Then from the project you want to operate on:

```bash
python -m agentforge init
```

This drops a `config.yaml` and creates `.agentforge/runs/`.

---

## Configure

Open `config.yaml` and confirm the CLI commands match your installed agents:

```yaml
claude_command: "claude --print"
codex_command: "codex exec"

agents:
  planner: claude
  implementer: codex
  reviewer: claude

max_ai_calls_per_run: 5
max_review_loops: 1
max_files_sent: 8
max_chars_per_file: 12000
max_total_chars: 80000
```

If the underlying CLI isn't installed, AgentForge fails fast with a clear
message rather than silently doing nothing.

**No API keys live in this repo.** The agent CLIs handle their own auth.

---

## Commands

```bash
python -m agentforge init
python -m agentforge plan "Add rate limiting to the /search endpoint"
python -m agentforge solve "Fix the off-by-one in pagination"
python -m agentforge review --task "Add Stripe webhook signature check"
python -m agentforge test
python -m agentforge status
```

| Command | What it does |
|---|---|
| `init`   | Writes `config.yaml` and `.agentforge/runs/`. |
| `plan`   | Scans → classifies → produces an implementation plan. Does **not** edit files. |
| `solve`  | Full pipeline: plan → branch → implement → test → diff-review → optional revision. |
| `review` | Reviews the current `git diff` only. Sends no repo context. |
| `test`   | Runs the `default_test_command` from `config.yaml`. |
| `status` | Shows the latest run, budget used, diff stats, and review verdict. |

---

## Routing rules

Built into [agentforge/task_classifier.py](agentforge/task_classifier.py):

| Task type | Planner | Implementer | Reviewer |
|---|---|---|---|
| Refactor / security-sensitive | Claude | Codex | Claude (always) |
| Bug fix | — | Codex | Claude (only if tests fail or risky files changed) |
| Tests | — | Codex | — (unless requested) |
| Docs | — | Claude | — |
| Feature / unknown | Claude | Codex | Claude |

You can override per-role defaults in `config.yaml > agents:`.

---

## Run artifacts

Every run writes to `.agentforge/runs/<timestamp>/`:

```
task.json           the input task + classification
repo_summary.json   compact view of the repo at scan time
plan.md             planner output
test_result.txt     test command stdout/stderr + exit code
diff.patch          git diff after implementation
review.json         reviewer's structured JSON verdict
budget.json         AI calls + chars sent
final_summary.md    human-readable end-of-run summary
```

`agentforge status` reads the most recent of these.

---

## Safety

- **No destructive git commands.** AgentForge only `checkout -b` into a fresh
  branch (`agentforge/<slug>`). It never force-pushes, never resets, never
  deletes branches. If the working tree is dirty, it refuses to create a new
  branch and tells you why.
- **Secret files are never read or sent.** Anything in `secret_files:` (default:
  `.env`, `.env.local`, `credentials.json`) is filtered out during scanning.
- **Binaries are skipped.** Files are sniffed for NUL bytes before reading.
- **Cross-platform.** Works on Windows, macOS, and Linux. All paths are
  POSIX-normalised when sent to agents.

---

## Limitations (MVP)

- No web UI.
- No autonomous PR creation. The user reviews the branch + summary, then
  pushes / opens the PR themselves.
- Token counting is approximated by **character count**. Good enough to keep
  spend bounded; not accurate to the cent.
- File scanning is filesystem-only — no AST parsing, no embeddings.
- The reviewer's revision loop is capped at 1. AgentForge will not loop until
  "perfection" — that's where most multi-agent setups burn money.
- Agent adapters are CLI subprocess wrappers. Direct SDK integration is a
  future extension.

---

## Project layout

```
agentforge/
  main.py                CLI (typer)
  orchestrator.py        the pipeline
  config.py              YAML loader
  task_classifier.py     heuristic classifier
  context_builder.py     minimal-context picker
  budget.py              hard budget caps
  logger.py              per-run artifact writer
  agents/
    base.py              CLIAgent base class
    claude_agent.py
    codex_agent.py
    local_agent.py       no-LLM operations
  tools/
    file_scanner.py
    git_tools.py         safe git wrappers
    diff_tools.py
    test_runner.py
  prompts/
    planning_prompt.py
    implementation_prompt.py
    review_prompt.py
  storage/runs/          (created at runtime as .agentforge/runs/)
config.yaml
requirements.txt
README.md
```
