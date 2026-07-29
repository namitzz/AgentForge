# No-Code-Leak Mode

A privacy-first mode for private or commercial repos where you still want the local guardrails (risk, policy, security, budget, merge readiness) but don't want **any** source code, file contents, or diff bodies leaving the machine.

This document covers **content privacy**. For **anonymous telemetry** (off by default, allowlisted fields only), see [PRIVACY.md](../PRIVACY.md) at the repo root.

```bash
agentforge plan      "Refactor user store" --no-code-leak
agentforge review                          --no-code-leak
agentforge review-pr --base main           --no-code-leak
agentforge redteam   --base main           --no-code-leak
agentforge solve     "..."                 --no-code-leak           # refused
agentforge solve     "..."                 --no-code-leak --dry-run # ok
```

Or enable it globally in `config.yaml`:

```yaml
privacy:
  no_code_leak_mode: true
```

The CLI flag overrides the config for that command. The config setting applies to every run unless `--no-code-leak` is passed explicitly.

## Behaviour

| Step | Normal mode | No-Code-Leak Mode |
|---|---|---|
| Repo scan, classifier, risk, policy, security, budget, decision | local | local (unchanged) |
| Planner prompt (paths + summary only — no contents) | sent | sent |
| Implementer prompt (file bodies) | sent | **never sent** |
| Review / PR-review / red-team diff body | sent | **redacted to stats only** |
| `solve` (real run) | runs | **refused with clean stop_reason** |
| `solve --dry-run` | runs locally | runs locally |
| `merge readiness`, `scorecards`, `doctor` | runs | runs |

When a reviewer prompt is generated under No-Code-Leak Mode, the diff body is replaced with:

```
[Diff content redacted by No-Code-Leak Mode]
Files changed: 3
Additions: +47
Deletions: -2
Changed file categories:
  - src/auth/*.py (2 files)
  - tests/*.py (1 file)
```

The reviewer sees stats + grouped file categories. No raw code. No leaf filenames in the diff section.

## Solve refusal

`solve` requires sending code to the implementer, so under No-Code-Leak Mode the CLI stops cleanly:

```
# AgentForge solve refused (No-Code-Leak Mode)

AgentForge will not send source code to external agents in
No-Code-Leak Mode. To proceed:
  - re-run with --dry-run to preview the pipeline locally
  - or disable privacy.no_code_leak_mode in config.yaml
  - or run local-only checks (plan, review, readiness)
```

`result.status` is `stopped_early` (not `failed`) — it's an intentional refusal, not an error.

## Artifact

Every run writes `.agentforge/runs/<id>/privacy_report.json`:

```json
{
  "no_code_leak_mode": true,
  "source_code_sent": false,
  "file_contents_sent": false,
  "diff_content_sent": false,
  "external_implementation_allowed": false,
  "redaction_applied": true,
  "notes": []
}
```

## CLI block

```
Privacy mode:
- No-Code-Leak Mode: enabled
- Source code sent to agents: no
- File contents sent to agents: no
- Diff content sent to agents: no
- External implementation calls allowed: no
```

## Limitations

- The mode redacts the **prompt that goes to the agent**. The local `.agentforge/runs/<id>/diff.patch` artifact still contains the real diff because it never leaves the machine — that's how the local checks stay useful.
- Path category grouping (`src/auth/*.py`) still reveals the directory layout. If even that is too much, structure your repo so sensitive subtrees live under a single top-level directory and add a custom policy to block them.
- The mode does not change agent CLIs' own logging behaviour. If your Claude or Codex install has analytics enabled, that's a separate concern handled by those tools.
