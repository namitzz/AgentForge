# Roadmap issues

Eight issues to file in GitHub after the 0.1.0 release. Each is sized for a single focused PR and should be implementable without new external services, new auth, or any move away from local-first.

Copy each block into a new GitHub issue.

---

## 1. Add real token estimation

**Description.** The budget engine currently counts characters (`chars_sent`) as a proxy for token usage. Replace this with the agent CLI's reported token usage when available, falling back to a per-model approximation when not.

**Acceptance criteria.**

- New `tokens_used` field on `BudgetSnapshot`, written to `budget.json`.
- `BudgetManager.record_call()` accepts an optional `tokens: int | None` argument.
- Per-model fallback estimator (e.g. `~4 chars/token` for Claude / GPT-class models) when no token count is reported.
- Existing character-based caps stay intact; new optional `max_tokens_per_run` cap added to `config.yaml`.
- README budget table mentions tokens alongside chars.
- All existing tests still pass; new test covers the fallback path.

---

## 2. Add more agent adapters

**Description.** Only Claude Code and OpenAI Codex are first-class today. Add at least one more CLI-driven coding agent (candidates: Aider, Cursor CLI, an OpenAI-compatible local endpoint, or `ollama`-backed adapter).

**Acceptance criteria.**

- New `agentforge/agents/<name>_agent.py` subclassing `CLIAgent`.
- Registered in `Orchestrator._agent()` factory.
- Documented in the default `config.yaml` template and the routing-rules section of the README.
- Tests cover the adapter's wiring (no real CLI required — use the same `monkeypatch.setattr(CLIAgent, "run", ...)` pattern as `tests/test_dry_run.py`).
- Doctor command picks the new agent up under "optional".

---

## 3. Expand agent scorecards with trends + dashboard

**Description.** The base scorecards already ship (`agentforge/scorecards.py`). Add per-task-type breakdown, last-N-runs trend lines (text-rendered, no charting library), and a per-day rollup in the JSON file.

**Acceptance criteria.**

- New filters: `agentforge scorecards --since 7d` and `--task-type bug_fix`.
- Text view shows simple trend arrows (`↑` / `↓` / `=`) vs the prior week for each metric.
- JSON file gains a `history: [{date, ...counts}]` array, capped at 90 days.
- Existing flat counters remain (back-compat).
- Tests cover the time-window filter and trend computation.

---

## 4. Add GitHub PR body generation

**Description.** After a real `solve`, emit a Markdown PR body summarising the change. The user copy-pastes it into `gh pr create` (or any web UI). No GitHub API call.

**Acceptance criteria.**

- New `pr_body.md` artifact written by `solve` on real runs only (never in dry-run).
- Sections: task, plan summary, files changed + diff stats, risk + policy + security verdict, test outcome, reviewer JSON summary.
- Never includes the raw diff or any secret-pattern matches.
- New command `agentforge pr-body --run <path>` to render or re-render.
- Tests: artifact is written; structure is stable; no diff body present.

---

## 5. Add sandbox / worktree execution

**Description.** Today `solve` creates a branch in the user's working tree. Add an opt-in `--sandbox` flag that runs the implementer + tests inside a `git worktree` so the user's working tree is untouched until they explicitly merge.

**Acceptance criteria.**

- `agentforge solve "..." --sandbox` creates a worktree at `.agentforge/worktrees/<run_id>/`.
- Tests run inside the worktree, not the main tree.
- On clean exit, the worktree path is printed and left in place for the user to inspect.
- New helper `agentforge cleanup-worktrees` removes stale ones with explicit confirmation.
- The only destructive op used is `git worktree remove`, gated on user confirmation.
- Cross-platform (Windows path handling tested).

---

## 6. Add richer language-aware context selection

**Description.** Today files are picked by token overlap with the task description. Add lightweight language-aware heuristics: include imports / callers of a file under change, prefer files with declarations matching task tokens, deprioritise generated or vendored code.

**Acceptance criteria.**

- New strategies in `context_builder.py` behind a config knob (`context.strategy: tokens | imports | both`, default `tokens` for back-compat).
- Uses only stdlib `ast` for Python; no third-party parsers.
- Generated / vendored directories detected via existing `ignore_dirs` + a new `generated_dirs` config list.
- Tests cover the import-graph selector on a tiny Python sample repo.
- Default behaviour unchanged when the flag is at its default value.

---

## 7. Add team policy packs

**Description.** Reusable `policies:` snippets that a team can drop into `config.yaml` via include. Ship two starter packs: `auth-strict` (auth + login + session + token paths require review + tests + approval) and `data-migration-strict` (migrations + schema files require approval + tests).

**Acceptance criteria.**

- `agentforge/policy_packs/` directory with at least the two named YAML files.
- `agentforge init --pack auth-strict` writes those policies into the generated `config.yaml`.
- New `agentforge policy list-packs` command lists available packs with one-line descriptions.
- Documented in the Policy rules README section.
- Tests cover pack loading + collision behaviour with existing user policies.

---

## 8. Add local-only enterprise mode

**Description.** A meta-mode that turns on the most conservative defaults at once: `no_code_leak_mode`, a tight budget, both starter policy packs, mandatory merge-readiness ≥ 70 before any commit, telemetry disabled, scorecards local-only.

**Acceptance criteria.**

- `agentforge init --enterprise` writes the relevant config bundle.
- `agentforge doctor` reports `Enterprise mode: enabled` when detected (by inspecting the active config).
- New "Enterprise mode" section in the README explaining what it turns on and *why each setting matters*.
- No new external dependencies, no new authentication, no new network calls.
- Tests cover the init flow + doctor detection.
