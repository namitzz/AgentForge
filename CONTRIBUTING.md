# Contributing to AgentForge

Thanks for your interest. AgentForge is a small, focused MVP — contributions are welcome, especially for bug fixes, additional agent adapters, and tighter tests.

## Local setup

```bash
git clone <this repo>
cd AgentForge
python -m pip install -r requirements.txt
pip install pytest
python -m pytest tests/
```

That's it. You don't need the Claude or Codex CLIs installed to develop or run the test suite — they're only invoked at runtime.

## Trying it without an LLM

Use dry-run mode. Every command supports it:

```bash
cd /path/to/some/git/repo
python -m agentforge init
python -m agentforge solve "Add password reset validation" --dry-run
python -m agentforge plan "Refactor user model" --dry-run
python -m agentforge review-pr --dry-run
```

Dry-run scans the repo, runs risk scoring + policy checks, builds the exact prompts, prints the budget estimate, and writes the full artifact set under `.agentforge/runs/<timestamp>/`. It never calls Claude or Codex and never modifies files. It's the easiest way to develop and test changes locally.

## Filing issues

Helpful issue reports include:

- AgentForge version (`python -c "import agentforge; print(agentforge.__version__)"`)
- Python version and OS
- The exact command you ran
- What you expected vs what happened
- If possible, the contents of `.agentforge/runs/<latest>/` (it has the manifest, prompts, budget, and policy/risk reports — usually enough to reproduce)

Please redact any sensitive paths or task descriptions before sharing.

## Pull requests

1. Keep changes small and focused. One feature or fix per PR.
2. Match the existing code style (type hints, dataclasses where helpful, no clever metaprogramming).
3. Add or update tests under `tests/`. The full suite must pass: `python -m pytest tests/`.
4. Update the README or USAGE.md if you change user-visible behavior.
5. Update `CHANGELOG.md` under `## Unreleased`.

## Coding style

- Python 3.11+.
- Type hints on public functions and dataclass fields.
- Prefer dataclasses for structured data over plain dicts.
- Keep modules small. If a file is getting past ~500 lines, consider splitting.
- Errors should be loud and clear. Use specific exceptions (`BudgetExceeded`, `AgentUnavailable`, `GitError`) and surface them with actionable messages.
- Cross-platform: tests run on Linux in CI, but the CLI also runs on Windows and macOS. Avoid POSIX-only assumptions (subprocess args, path separators).
- No emojis in code or docstrings unless a user requests them.

## Safety expectations

AgentForge takes safety seriously. PRs that weaken these are unlikely to be accepted.

- **Never call destructive git commands.** Only `git checkout -b` into fresh branches. No `reset --hard`, no `push --force`, no branch deletion.
- **Never bypass the secret-file filter.** Files matching `secret_files:` or any policy `block:` pattern must be excluded from prompts at scan time.
- **Never exceed the budget silently.** `BudgetManager.enforce_planned_within_caps()` must be called before any agent invocation that wasn't already accounted for in the up-front estimate.
- **Never auto-merge, push, or open PRs on the user's behalf.** AgentForge stops at the agent branch.
- **Never hide failed tests.** If a step fails, log it, include it in `final_summary.md`, and set `stopped_early=true` with a clear `stop_reason`.

## Adding a new agent adapter

If you want to support an additional agent (beyond Claude Code and OpenAI Codex):

1. Subclass `CLIAgent` in `agentforge/agents/` with a sensible `name`.
2. Expose it from `agentforge/agents/__init__.py`.
3. Wire it into `Orchestrator._agent()` as a new `kind` branch.
4. Add a `<your>_command` field to `Config` and the default `config.yaml`.
5. Add a brief mention to the README's Comparison or Routing rules section.

Keep adapters thin. They should pass the prompt as a quoted argument and capture stdout — that's it.
