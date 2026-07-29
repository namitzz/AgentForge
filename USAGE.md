# Using AgentForge

Practical notes for running it on real code. The README has the why; this is the how.

## Install

You need Python 3.11+, git, and the `claude` CLI on your PATH.

```
pip install -e .
```

Install the Claude CLI if you don't have it yet:

```
npm i -g @anthropic-ai/claude-code && claude login
```

AgentForge is Claude-only by default. If you want to swap another coding-agent CLI into a role, install that CLI and point `<role>` at it in `config.yaml` — but nothing beyond `claude` is required.

AgentForge just shells out to those binaries. It doesn't touch auth or API keys.

## Setup

From inside the repo you want to work on:

```
python -m agentforge init
```

That writes `config.yaml` and creates `.agentforge/runs/`. Add the runs dir to your `.gitignore`. Use `--force` to overwrite an existing config.

Open `config.yaml` and look at:

- `default_test_command` (what AgentForge runs to verify changes)
- `claude_command` / `codex_command` (only matters if your installed CLIs use different flags)
- the budget caps near the top

## Commands

- `init` — write `config.yaml` and the runs dir
- `doctor` — health check: Python, git, config, CLIs, security defaults, telemetry
- `plan "task"` — produce a plan, don't touch any files
- `solve "task"` — plan, branch, edit, test, review
- `review` — review your current working-tree `git diff` (optionally `--task "..."` for context)
- `review-pr` — review your current branch vs main/master (PR-style, no GitHub)
- `test` — run the configured test command
- `status` — show the last run
- `telemetry` — `status` / `enable` / `disable` / `preview` / `clear` (off by default)

`solve` prompts before it does anything. Pass `--yes` (or `-y`) to skip the prompt in scripts. Every command takes `-c path/to/config.yaml` if you keep the config somewhere non-default.

## Dry run

Every workflow command (`plan`, `solve`, `review`, `review-pr`) accepts `--dry-run`. In that mode AgentForge:

- scans the repo, classifies the task, picks files
- runs the local policy + risk + security engines
- builds the exact prompts that would be sent
- prints the planned workflow, file list, budget estimate
- writes the full artifact set under `.agentforge/runs/<timestamp>/`

It does **not** call Claude or Codex, modify any files, or create a branch. Use it before any real run on a new repo and as a smoke test in CI.

## Reviewing artifacts

After any run, the most useful files under `.agentforge/runs/<latest>/`:

- `final_summary.md` — human-readable wrap-up. Same content as `agentforge status`.
- `risk_report.json` — `risk_level`, `score`, reasons, recommended workflow.
- `policy_report.json` — which policies fired, which files were blocked.
- `security_report.json` — blocked files, suspicious files, prompt-injection warnings, command verdict.
- `budget.json` — planned vs actual AI calls + chars, `stopped_early` + `stop_reason`.
- `failure_report.json` — present **only** when something went wrong; check first when a run fails.
- `selected_files.json` — the files the implementer actually got to see.
- `prompts.json` — the exact prompts each agent received. Inspect if you suspect a leak or want to debug agent output.

Open the run directory directly:

```bash
# Bash / zsh
ls .agentforge/runs/$(ls -t .agentforge/runs | head -1)/

# Cross-platform: list timestamps and pick
ls .agentforge/runs/
ls .agentforge/runs/<timestamp>/
```

## What `solve` actually does

1. Scan the repo. No AI.
2. Classify the task (bug, feature, refactor, tests, docs, unknown).
3. Pick relevant files. Capped by `max_files_sent`, `max_chars_per_file`, and `max_total_chars`.
4. Plan it. Claude by default. Skipped for bug fixes, tests, and docs.
5. `git checkout -b agentforge/<slug>`.
6. Implement. Claude by default.
7. Run your tests.
8. Review the diff with Claude. Sometimes skipped for low-risk passing runs.
9. One revision pass if review says `needs_changes`. Then stop.
10. Write artifacts to `.agentforge/runs/<timestamp>/`.

Typical full run: 2–3 AI calls. A bug fix that passes tests: 1. A docs change: 1.

## After a run

You're on the agent's branch with uncommitted edits. Look at them:

```
git diff main
python -m agentforge status
```

Merge yourself when you're happy:

```
git add -A && git commit -m "..."
git checkout main
git merge agentforge/your-task-slug
```

Throw it out if you're not:

```
git checkout main
git branch -D agentforge/your-task-slug
```

AgentForge won't commit, push, merge, or rebase. Anything that touches history is on you.

## What's in a run dir

```
task.json           your task + how it was classified
repo_summary.json   files seen at scan time
plan.md             planner output
diff.patch          implementer's changes
test_result.txt     test stdout/stderr + exit code
review.json         reviewer verdict
budget.json         calls + chars used vs caps
final_summary.md    wrap-up
```

`review.json` looks like:

```
{
  "status": "approved" | "needs_changes",
  "risk_level": "low" | "medium" | "high",
  "issues": [{"file": "...", "problem": "...", "suggested_fix": "..."}],
  "summary": "..."
}
```

## Writing a task

Be specific. Both the classifier and the file picker key off the words in your task.

Works:

- `fix the off-by-one in pagination on /search`
- `add Stripe webhook signature verification to billing handler`
- `refactor storage layer to use the new connection pool`
- `write unit tests for the markdown parser`

Doesn't work:

- `fix it`
- `make it better`

Split tasks that span unrelated areas into separate runs.

## Budget

```
max_ai_calls_per_run: 5
max_review_loops: 1
max_files_sent: 8
max_chars_per_file: 12000
max_total_chars: 80000
```

Hitting any of these aborts the run. The message tells you which cap blew. The partial run still gets saved. Actual spend lives in `.agentforge/runs/<latest>/budget.json`.

## Swapping agents (optional)

AgentForge ships Claude-only — every role defaults to `claude` and you don't need to touch this. If you have another coding-agent CLI installed and want it in a role, point that role at it in `config.yaml`:

```
agents:
  planner: claude
  implementer: claude   # e.g. change to "codex" if you have that CLI
  reviewer: claude
```

Per-task-type routing (bug fixes skip the planner, etc) lives in `task_classifier.py`. Fork it if you want different rules — there's no YAML hook for that yet.

If your Claude CLI uses different flags:

```
claude_command: "claude --print"
```

The task prompt gets appended as a final quoted arg.

## CI

```
python -m agentforge solve "regenerate openapi types" --yes
```

Exit codes:

- `0` — run finished (reviewer verdict doesn't change this)
- `1` — you declined the prompt, or something fatal happened (no git repo, dirty tree, missing CLI, budget blown)

Read `review.json` and `test_result.txt` if you need to decide whether to open a PR from the branch.

## Safety

- The only destructive-looking git command is `checkout -b`.
- A dirty working tree blocks the run.
- `secret_files` get filtered at scan time. The agent never sees them.
- Binary files (NUL bytes in the first 1KB) are skipped.
- Budget caps are enforced before each call.

## Troubleshooting

**`'claude' not found on PATH`** — install the CLI, restart the shell, check `claude --version`.

**`branch 'agentforge/xxx' already exists`** — delete it or change task wording.

**`Uncommitted changes detected`** — commit or stash first.

**`AI call budget exhausted`** — raise `max_ai_calls_per_run`, or split the task.

**Reviewer returned non-JSON** — it gets marked `needs_changes` and the raw output is saved. Read the diff yourself.

**`agentforge test` fails but local tests pass** — different env or cwd. Update `default_test_command`.

**Hangs on the confirm prompt in CI** — pass `--yes`.

## Example

```
cd ~/code/my-app
python -m agentforge init
python -m agentforge plan "add caching to the user lookup endpoint"
# read .agentforge/runs/*/plan.md

python -m agentforge solve "add caching to the user lookup endpoint"
git diff main

git add -A && git commit -m "feat: cache user lookups"
git checkout main
git merge agentforge/add-caching-to-the-user-lookup-endpoint
```
