# Privacy

AgentForge is a local developer tool. Source code, prompts, diffs, file paths, repo names, and secrets never leave your machine in normal operation, and they never leave it via telemetry either.

## Telemetry is off by default

Out of the box AgentForge collects nothing. No network requests are made. The telemetry module is not even imported at runtime when telemetry is disabled, and the `urllib` import is gated behind `settings.enabled`.

Verify the current state at any time:

```bash
python -m agentforge telemetry status
```

## How to enable it

```bash
python -m agentforge telemetry enable
```

The command prints the full list of fields that *will* be collected and the full list of categories that will *never* be collected, then asks for confirmation. On accept it:

1. Generates a fresh **anonymous UUID** via `uuid.uuid4()` — not derived from your machine, hostname, MAC, git config, username, or any other stable identifier.
2. Writes settings to `.agentforge/telemetry/settings.json`.

If you provide `--endpoint <url>`, events are POSTed to that HTTPS endpoint. If you don't, events are written **locally only** to `.agentforge/telemetry/events.jsonl` so you can inspect them and decide later whether to ship them somewhere.

## How to disable it

```bash
python -m agentforge telemetry disable
```

This clears the anonymous ID and sets `enabled=false`. Local event log is not touched. To remove the log too:

```bash
python -m agentforge telemetry clear
```

## What IS collected

The complete list. This is a closed-set allowlist defined in `agentforge/telemetry.py:ALLOWED_FIELDS`. Adding a new field requires editing the source.

| Field | Value |
|---|---|
| `agentforge_version` | this package's version string |
| `command_type` | one of `init`, `plan`, `solve`, `review`, `review-pr`, `status`, `test`, `telemetry` |
| `dry_run` | whether `--dry-run` was passed |
| `risk_level` | `LOW` / `MEDIUM` / `HIGH` from the local risk engine |
| `policy_trigger_count` | how many policies matched (count only) |
| `security_warning_count` | count of security findings (count only) |
| `ai_calls_used` | integer |
| `planned_ai_calls` | integer (up-front estimate) |
| `review_loops_used` | integer (0 or 1) |
| `run_duration_ms` | wall-clock duration of the run |
| `stopped_early` | bool |
| `error_category` | one of the `ErrorCategory` values, or `null` on success |
| `os_family` | `windows` / `macos` / `linux` / `other` |
| `python_version` | e.g. `3.11` |
| `anonymous_id` | random UUID generated when telemetry was enabled |
| `event_timestamp` | local ISO timestamp |

That's it. The orchestrator never touches the telemetry module — the CLI layer extracts these scalars from `RunResult` and hands them to `telemetry.build_event()`, which constructs the dict field-by-field and applies a final allowlist filter.

## What is NEVER collected

Defended by source code (the allowlist) and by tests (`tests/test_telemetry.py` parametrises every forbidden key below and asserts it never appears in an event):

- source code, file contents, prompts, diffs, test output
- file paths, repo names, branch names, task descriptions
- usernames, email addresses, environment variables
- secrets, API keys, command stdout / stderr
- anything derived from the machine (hostname, MAC, git config)

## Where data is stored

| Path | Contents |
|---|---|
| `.agentforge/telemetry/settings.json` | `enabled`, `anonymous_id`, `endpoint` |
| `.agentforge/telemetry/events.jsonl` | Local-only event log (one event per line). Capped at 1000 most recent events. |

Both files are inside the project directory you run AgentForge from. Nothing is stored globally on your machine.

## How to inspect what would be sent

```bash
python -m agentforge telemetry preview
```

Prints the most recent locally-logged event as JSON. No network call.

## How to delete everything

```bash
python -m agentforge telemetry clear
```

Removes `settings.json` and `events.jsonl`. To also remove the run artifacts:

```bash
rm -rf .agentforge/
```

## Failure mode

If telemetry is enabled and sending fails (no network, endpoint down, malformed event), the failure is **silently swallowed**. Telemetry cannot break `agentforge solve` or any other command. This is enforced by:

- `emit()` returns `"send_failed"` instead of raising
- The CLI integration in `_emit_telemetry_for_run()` wraps the call in a broad `try/except Exception: pass`
- Network requests use a 3-second timeout

## Reporting privacy issues

If you find that AgentForge collects something it shouldn't, please open a private security advisory on the GitHub repository (Security tab → Report a vulnerability). See [SECURITY.md](SECURITY.md) for the full reporting process.
