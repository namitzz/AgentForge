# Failure handling

Every run lands in one of five statuses:

| Status | Meaning |
|---|---|
| `completed` | Full pipeline ran end to end. |
| `dry_run_completed` | `--dry-run` finished without calling any agent. |
| `stopped_early` | Clean stop before completion (tests passed and review wasn't needed, the budget cap was hit cleanly, or No-Code-Leak Mode refused). |
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

## Error categories

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

## Timeouts

Agent and test commands honour `command_timeout_seconds` in `config.yaml` (default `600`). If a subprocess doesn't return in that many seconds, AgentForge stops it, marks the run `failed`, and writes a failure report. Lower it for tight CI; raise it for big refactors or slow test suites.

## Interrupted runs

`Ctrl+C` is caught at the top level. The run is marked `failed`, a failure report is written, and partial artifacts (everything that landed before the interrupt) are kept under `.agentforge/runs/<timestamp>/`. You can resume by re-running the same command — there is no shared state to clean up.

## Invalid agent JSON

If the reviewer returns text that isn't valid JSON (or wraps it in code fences), AgentForge:

1. Strips the most common wrappers (` ```json `, ` ``` `).
2. Tries to extract the first JSON object.
3. If both fail, saves the raw output and marks the verdict as `needs_changes` with `summary: "reviewer returned non-JSON output"` so a human can read it. The run is not aborted.
