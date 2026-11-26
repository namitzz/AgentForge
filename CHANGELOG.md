# Changelog

All notable changes to AgentForge are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project uses [SemVer](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Changed

- License changed from MIT to PolyForm Noncommercial 1.0.0 for AgentForge and the HiddenInk directory edition. Earlier versions remain MIT.

## 0.3.1 - 2026-11-26

### Fixed

- England, Scotland and Wales flag emojis (built from Unicode tag characters) are no longer reported as hidden messages. Hidden tag text elsewhere is still caught.
- Default grid carbon intensity raised from 400 to 475 gCO2e/kWh, close to the 2024 global average (Ember: 473). UK guidance corrected to about 130 (2025 average ~126 to 154 depending on source).

## 0.3.0 - 2026-11-26

### Added

- **Everyday checks for non-coders in the Claude app.** New `everyday-checks` skill with `/preflight`, `/privacy`, `/safety` and `/footprint` commands. They work in plain chat with no CLI or install, using a standalone standard-library checker (`skills/everyday-checks/scripts/afcheck.py`).
  - Privacy: secrets and API keys, passwords, Luhn-checked card numbers, IBANs (mod-97), UK sort codes and account numbers, National Insurance, SSN and passport numbers, dates of birth, emails, phones, postcodes, IPs. Writes a redacted safe copy with consistent placeholders.
  - Safety: invisible Unicode tag text (decoded and shown), zero-width and direction-override characters, injection phrases, fake system markers, hidden or white HTML, instructions in HTML comments or base64, Word hidden text, data-leak image links, disguised links, look-alike letters, dangerous commands. Writes a cleaned copy.
  - Footprint: energy, CO2e and everyday comparisons for a document, task or chat, with saving tips.
- Reads .txt, .md, .csv, .json, .html, .eml, .docx and (when available) .pdf.

### Changed

- Plugin description rewritten for general users.

## 0.2.0 - 2026-11-26

### Added

- **Carbon used vs saved.** Carbon tracking: estimated CO2e used by Claude calls and saved by avoided calls, in the budget estimate, end-of-run summary, `final_summary.md` and `budget.json`. Configurable under `carbon:` in `config.yaml` (`agentforge/carbon.py`, `docs/carbon.md`).
- **Claude Code plugin + marketplace.** The repo now ships `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`, so it can be installed as a Claude Code plugin (`/plugin marketplace add namitzz/AgentForge` → `/plugin install agentforge@agentforge-marketplace`). Adds `/agentforge:solve|plan|review|readiness|doctor` slash commands (in `commands/`) and an auto-invoked `agentforge-guardrails` skill (in `skills/`) that routes risky changes through AgentForge's local checks. Commands fall back to `python -m agentforge` when the console script isn't on PATH. See [docs/plugin.md](docs/plugin.md). Validated with `claude plugin validate`.

### Fixed

- `agentforge --version` now works. The plugin's slash commands use it to detect the CLI, so before this fix they wrongly told users to install AgentForge.

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
