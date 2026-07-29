# Changelog

All notable changes to AgentForge are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project uses [SemVer](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- **Claude Code plugin + marketplace.** The repo now ships `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`, so it can be installed as a Claude Code plugin (`/plugin marketplace add namitzz/AgentForge` → `/plugin install agentforge@agentforge-marketplace`). Adds `/agentforge:solve|plan|review|readiness|doctor` slash commands (in `commands/`) and an auto-invoked `agentforge-guardrails` skill (in `skills/`) that routes risky changes through AgentForge's local checks. Commands fall back to `python -m agentforge` when the console script isn't on PATH. See [docs/plugin.md](docs/plugin.md). Validated with `claude plugin validate`.

### Changed

- **Claude-only by default.** Every role (planner / implementer / reviewer) now defaults to `claude`; the previous `implementer: codex` default is gone. Other coding-agent CLI adapters remain swappable in `config.yaml` but nothing beyond the `claude` CLI is required. `agentforge doctor` now checks only the agent CLIs actually referenced by the configured roles, so an unused Codex no longer shows a warning. Risk-report workflow text and docs updated to Claude-first wording.

## 0.1.0 - 2026-05-22

Initial MVP release.

### Added

- **Cost-aware workflow.** Fixed pipeline (scan → classify → context → policy → risk → plan → branch → implement → test → diff-only review → optional revision → summary). Defaults cap each run at 5 AI calls and 80k characters.
- **Dry-run mode.** `--dry-run` on `plan`, `solve`, `review`, and `review-pr`. Scans, classifies, picks files, builds the exact prompts, prints the budget estimate, and writes the full artifact set — without calling any external agent.
- **Risk scoring.** Local `RiskEngine` classifies tasks as LOW / MEDIUM / HIGH on a 0-100 scale based on keywords + selected file paths. Each level recommends a workflow and sets `review_required` / `tests_required` / `human_approval_required` flags. HIGH-risk runs gate on human approval.
- **Policy checks.** Declarative YAML rules in `config.yaml > policies:` with `block:` patterns (drop files from context) and `match:` patterns (force review, force tests, require human approval). Decisions saved to `policy_report.json`.
- **Project rules memory.** `.agentforge/project_rules.md` (created by `init`) is included in every prompt so per-repo conventions don't need to be retyped.
- **Budget control.** Up-front estimate printed before any agent call; final summary after. Tracks planned vs actual AI calls and characters, files sent, review loops, dry-run flag, stopped_early flag, and stop_reason.
- **Run artifacts.** Every run writes 12 structured files under `.agentforge/runs/<timestamp>/` including a full manifest (`task.json` with timestamps, command, agent_workflow), `prompts.json`, `risk_report.json`, `policy_report.json`, `selected_files.json`, `diff.patch`, and `final_summary.md`. Missing artifacts get placeholders.
- **PR review mode.** `agentforge review-pr` reviews the current branch against `main` (or `master`) without running the full solve pipeline. Local-only; never pushes, never opens GitHub PRs.
- **Multi-agent routing.** Task classifier picks the cheapest valid route per task type. Bug fixes skip the planner; docs skip the reviewer; tests skip both. Risk and policy can override and force review on.
- **Safe git.** Only `git checkout -b` into fresh branches. Dirty trees block branch creation. No force-push, reset, or auto-merge.
- **Pytest suite.** 87 tests covering classifier, policy engine, risk engine, budget manager, file scanner, context builder, run logger, manifest, project rules, dry-run guarantees, and review-pr.
- **GitHub Actions CI.** Python 3.11, installs requirements, runs pytest, smoke-tests `python -m agentforge --help` and `init`. Does not require Claude or Codex.
- **Worked example.** `examples/sample-run/` contains all 12 artifacts for a realistic HIGH-risk password-reset task so the audit trail is readable without running the tool.

### Notes

- Token usage is approximated by character count. Token-accurate budgeting is on the roadmap.
- Agent adapters are CLI subprocess wrappers (`claude`, `codex`). Direct SDK integration is a future option.
- The reviewer is always given the diff only — never full source files.
