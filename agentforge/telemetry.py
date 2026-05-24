"""Privacy-first anonymous telemetry.

Hard guarantees this module enforces in code:

  - **Off by default.** ``load_settings()`` defaults ``enabled`` to False.
  - **Closed-set allowlist.** ``ALLOWED_FIELDS`` is the only set of keys
    that ever leaves this module. ``build_event()`` constructs the dict
    field-by-field; it does not accept arbitrary kwargs.
  - **No network when disabled.** ``emit()`` returns immediately when
    ``settings.enabled`` is False — no urllib import path is touched.
  - **Anonymous ID.** Generated only when telemetry is enabled, via
    ``uuid.uuid4()``. Not derived from machine, user, hostname, or git
    config. Cleared on disable.
  - **Sending failures never bubble.** Network errors are swallowed so a
    flaky endpoint can't break ``agentforge solve``.

What is NEVER collected (defended by the allowlist + tests):

  - source code, file contents, prompts, diffs, test output
  - file paths, repo names, branch names, task descriptions
  - usernames, email addresses, environment variables
  - secrets, API keys, command stdout/stderr

What IS collected when telemetry is enabled (see ``ALLOWED_FIELDS``):

  - AgentForge version
  - command type (``init``/``plan``/``solve``/``review``/``review-pr``/``status``)
  - dry_run flag
  - risk level (LOW/MEDIUM/HIGH)
  - count of triggering policies
  - count of security warnings
  - AI calls used + planned
  - review loops used
  - run duration in milliseconds
  - stopped_early flag
  - error_category (only when the run failed)
  - OS family (windows/macos/linux/other)
  - Python major.minor version (e.g. ``3.11``)
  - the anonymous UUID + an event timestamp
"""

from __future__ import annotations

import json
import platform
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import __version__


# The single source of truth for what may leave this module.
ALLOWED_FIELDS: frozenset[str] = frozenset({
    "agentforge_version",
    "command_type",
    "dry_run",
    "risk_level",
    "policy_trigger_count",
    "security_warning_count",
    "ai_calls_used",
    "planned_ai_calls",
    "review_loops_used",
    "run_duration_ms",
    "stopped_early",
    "error_category",
    "os_family",
    "python_version",
    # Routing metadata (no IDs, no paths)
    "anonymous_id",
    "event_timestamp",
})

ALLOWED_COMMAND_TYPES: frozenset[str] = frozenset({
    "init", "plan", "solve", "review", "review-pr", "status",
    "test", "telemetry",
})

# Default file locations under .agentforge/.
TELEMETRY_DIR = Path(".agentforge") / "telemetry"
SETTINGS_FILE = TELEMETRY_DIR / "settings.json"
EVENTS_FILE = TELEMETRY_DIR / "events.jsonl"

# Hard cap on the local event log so we don't grow unboundedly.
MAX_LOCAL_EVENTS = 1000


# --- Settings -------------------------------------------------------------

@dataclass
class TelemetrySettings:
    enabled: bool = False
    anonymous_id: str | None = None
    endpoint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "anonymous_id": self.anonymous_id,
            "endpoint": self.endpoint,
        }


def _project_root(cwd: Path | str = ".") -> Path:
    return Path(cwd).resolve()


def _settings_path(cwd: Path | str = ".") -> Path:
    return _project_root(cwd) / SETTINGS_FILE


def _events_path(cwd: Path | str = ".") -> Path:
    return _project_root(cwd) / EVENTS_FILE


def load_settings(cwd: Path | str = ".") -> TelemetrySettings:
    """Load the JSON settings sidecar. Returns disabled defaults if absent
    or unreadable. Never raises on missing / malformed files — privacy
    failure mode is to do nothing."""
    p = _settings_path(cwd)
    if not p.exists() or not p.is_file():
        return TelemetrySettings()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return TelemetrySettings()
    if not isinstance(data, dict):
        return TelemetrySettings()
    return TelemetrySettings(
        enabled=bool(data.get("enabled", False)),
        anonymous_id=(data.get("anonymous_id") or None) if isinstance(data.get("anonymous_id"), (str, type(None))) else None,
        endpoint=(data.get("endpoint") or None) if isinstance(data.get("endpoint"), (str, type(None))) else None,
    )


def save_settings(settings: TelemetrySettings, cwd: Path | str = ".") -> Path:
    p = _settings_path(cwd)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")
    return p


def enable(cwd: Path | str = ".", endpoint: str | None = None) -> TelemetrySettings:
    """Turn telemetry on. Generates a fresh anonymous UUID."""
    settings = TelemetrySettings(
        enabled=True,
        anonymous_id=str(uuid.uuid4()),
        endpoint=endpoint,
    )
    save_settings(settings, cwd)
    return settings


def disable(cwd: Path | str = ".") -> TelemetrySettings:
    """Turn telemetry off. Clears the anonymous ID so a future enable
    starts fresh."""
    settings = TelemetrySettings(enabled=False, anonymous_id=None, endpoint=None)
    save_settings(settings, cwd)
    return settings


def clear_local_data(cwd: Path | str = ".") -> None:
    """Delete the settings file and the local events log."""
    for p in (_settings_path(cwd), _events_path(cwd)):
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass


# --- Event construction ---------------------------------------------------

def _os_family() -> str:
    name = platform.system().lower()
    if name == "darwin":
        return "macos"
    if name in ("windows", "linux"):
        return name
    return "other"


def _python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def build_event(
    *,
    command_type: str,
    dry_run: bool,
    risk_level: str | None,
    policy_trigger_count: int,
    security_warning_count: int,
    ai_calls_used: int,
    planned_ai_calls: int,
    review_loops_used: int,
    run_duration_ms: int,
    stopped_early: bool,
    error_category: str | None,
    anonymous_id: str | None,
) -> dict[str, Any]:
    """Construct an event dict strictly from allowlisted scalars.

    This function does NOT accept arbitrary kwargs by design. Adding a new
    field requires editing both the signature and ``ALLOWED_FIELDS``.
    """
    if command_type not in ALLOWED_COMMAND_TYPES:
        command_type = "unknown"

    event: dict[str, Any] = {
        "agentforge_version":     str(__version__),
        "command_type":           command_type,
        "dry_run":                bool(dry_run),
        "risk_level":             (risk_level or None),
        "policy_trigger_count":   int(policy_trigger_count or 0),
        "security_warning_count": int(security_warning_count or 0),
        "ai_calls_used":          int(ai_calls_used or 0),
        "planned_ai_calls":       int(planned_ai_calls or 0),
        "review_loops_used":      int(review_loops_used or 0),
        "run_duration_ms":        int(run_duration_ms or 0),
        "stopped_early":          bool(stopped_early),
        "error_category":         (error_category or None),
        "os_family":              _os_family(),
        "python_version":         _python_version(),
        "anonymous_id":           anonymous_id,
        "event_timestamp":        datetime.now().isoformat(timespec="seconds"),
    }

    # Defense in depth: drop anything that snuck in not on the allowlist.
    return {k: v for k, v in event.items() if k in ALLOWED_FIELDS}


def assert_event_safe(event: dict[str, Any]) -> None:
    """Raise if an event contains any key outside the allowlist. Used by
    tests; called by emit() as a final guard before any I/O."""
    extra = set(event.keys()) - ALLOWED_FIELDS
    if extra:
        raise ValueError(f"telemetry event has disallowed keys: {sorted(extra)}")


# --- Emission -------------------------------------------------------------

def emit(event: dict[str, Any], cwd: Path | str = ".") -> str:
    """Send or persist an event according to current settings.

    Returns the action taken: "disabled" | "logged" | "sent" | "send_failed".
    Never raises — privacy failure mode is to do nothing.
    """
    settings = load_settings(cwd)
    if not settings.enabled:
        return "disabled"

    try:
        assert_event_safe(event)
    except ValueError:
        # Refuse to send a malformed event rather than risk a leak.
        return "send_failed"

    if settings.endpoint:
        return _post_event(event, settings.endpoint)
    return _append_local(event, cwd)


def _append_local(event: dict[str, Any], cwd: Path | str) -> str:
    path = _events_path(cwd)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Keep the file from growing without bound.
        if path.exists():
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
                if len(lines) >= MAX_LOCAL_EVENTS:
                    lines = lines[-(MAX_LOCAL_EVENTS - 1):]
                    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            except OSError:
                pass
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
        return "logged"
    except OSError:
        return "send_failed"


def _post_event(event: dict[str, Any], endpoint: str) -> str:
    # Imported lazily so disabled telemetry doesn't even touch urllib.
    import urllib.error
    import urllib.request

    try:
        body = json.dumps(event).encode("utf-8")
        req = urllib.request.Request(
            url=endpoint,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json",
                     "User-Agent": f"AgentForge/{__version__}"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            resp.read()  # drain
        return "sent"
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return "send_failed"


# --- Preview --------------------------------------------------------------

def latest_event(cwd: Path | str = ".") -> dict[str, Any] | None:
    """Return the most recent locally-logged event, or None."""
    path = _events_path(cwd)
    if not path.exists():
        return None
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return None
    if not lines:
        return None
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return None


def collected_field_descriptions() -> list[tuple[str, str]]:
    """For the enable-confirmation message + PRIVACY.md."""
    return [
        ("agentforge_version",     "this package's version string"),
        ("command_type",           "init / plan / solve / review / review-pr / status"),
        ("dry_run",                "whether --dry-run was passed"),
        ("risk_level",             "LOW / MEDIUM / HIGH from the local risk engine"),
        ("policy_trigger_count",   "how many policies matched (count only)"),
        ("security_warning_count", "count of security findings (count only)"),
        ("ai_calls_used",          "how many agent calls the run made"),
        ("planned_ai_calls",       "the up-front estimate"),
        ("review_loops_used",      "0 or 1"),
        ("run_duration_ms",        "wall-clock duration of the run"),
        ("stopped_early",          "whether the run stopped before completion"),
        ("error_category",         "category from failure_report.json (null on success)"),
        ("os_family",              "windows / macos / linux / other"),
        ("python_version",         "e.g. 3.11"),
        ("anonymous_id",           "a random UUID generated only when telemetry is enabled"),
        ("event_timestamp",        "local ISO timestamp"),
    ]


def never_collected() -> list[str]:
    """What we promise never to send. Used by enable-prompt + PRIVACY.md."""
    return [
        "source code, file contents, prompts, diffs, test output",
        "file paths, repo names, branch names, task descriptions",
        "usernames, email addresses, environment variables",
        "secrets, API keys, command stdout / stderr",
        "anything derived from the machine (hostname, MAC, git config)",
    ]
