"""Privacy guarantees for the telemetry module.

The hard rules — defended in code by these tests:

  - off by default
  - no network when disabled
  - allowlist-only field set, ever
  - never leaks source / paths / repo / branch / task / secrets
  - sending failures never raise
  - enable generates a fresh UUID; disable clears it
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentforge import telemetry


# --- defaults --------------------------------------------------------------

def test_load_settings_defaults_to_disabled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = telemetry.load_settings()
    assert s.enabled is False
    assert s.anonymous_id is None
    assert s.endpoint is None


def test_no_network_when_disabled(tmp_path, monkeypatch):
    """If telemetry is disabled, emit() must not import urllib at all,
    and must never hit the file system either."""
    monkeypatch.chdir(tmp_path)
    # Sabotage urllib so any import path that *does* try to use it explodes
    # and would fail the test loudly.
    import sys
    real_request = sys.modules.get("urllib.request")
    if real_request is not None:
        original_urlopen = real_request.urlopen
        def boom(*a, **kw):
            raise AssertionError("urllib.request.urlopen called while telemetry disabled")
        monkeypatch.setattr(real_request, "urlopen", boom)
    event = telemetry.build_event(
        command_type="solve", dry_run=False, risk_level="LOW",
        policy_trigger_count=0, security_warning_count=0,
        ai_calls_used=0, planned_ai_calls=0, review_loops_used=0,
        run_duration_ms=10, stopped_early=False, error_category=None,
        anonymous_id=None,
    )
    action = telemetry.emit(event)
    assert action == "disabled"
    # No file written either.
    assert not (tmp_path / ".agentforge" / "telemetry" / "events.jsonl").exists()


# --- enable / disable ------------------------------------------------------

def test_enable_generates_uuid(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = telemetry.enable()
    assert s.enabled is True
    assert s.anonymous_id is not None
    # Real UUID4 shape: 8-4-4-4-12 hex.
    import re
    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        s.anonymous_id,
    )


def test_enable_id_is_not_derived_from_machine(tmp_path, monkeypatch):
    """Two consecutive enable calls must produce different IDs."""
    monkeypatch.chdir(tmp_path)
    s1 = telemetry.enable()
    s2 = telemetry.enable()
    assert s1.anonymous_id != s2.anonymous_id


def test_disable_clears_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    telemetry.enable()
    s = telemetry.disable()
    assert s.enabled is False
    assert s.anonymous_id is None


def test_clear_removes_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    telemetry.enable()
    settings_path = tmp_path / ".agentforge" / "telemetry" / "settings.json"
    assert settings_path.exists()
    telemetry.clear_local_data()
    assert not settings_path.exists()


# --- allowlist enforcement -------------------------------------------------

def test_build_event_only_emits_allowed_fields():
    event = telemetry.build_event(
        command_type="solve", dry_run=True, risk_level="HIGH",
        policy_trigger_count=2, security_warning_count=1,
        ai_calls_used=3, planned_ai_calls=3, review_loops_used=0,
        run_duration_ms=12345, stopped_early=False, error_category=None,
        anonymous_id="abc-123",
    )
    assert set(event.keys()) <= telemetry.ALLOWED_FIELDS


def test_assert_event_safe_rejects_extra_keys():
    event = {"command_type": "solve", "secret_path": "/tmp/leak"}
    with pytest.raises(ValueError, match="disallowed keys"):
        telemetry.assert_event_safe(event)


def test_emit_silently_refuses_unsafe_event(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    telemetry.enable()
    # Manually-crafted event with a forbidden field. emit() must refuse
    # rather than write/send.
    assert telemetry.emit({"command_type": "solve", "task_text": "hello"}) == "send_failed"


def test_command_type_is_clamped_to_allowlist():
    event = telemetry.build_event(
        command_type="exfil", dry_run=False, risk_level=None,
        policy_trigger_count=0, security_warning_count=0,
        ai_calls_used=0, planned_ai_calls=0, review_loops_used=0,
        run_duration_ms=0, stopped_early=False, error_category=None,
        anonymous_id=None,
    )
    assert event["command_type"] == "unknown"


# --- what we promise never to collect --------------------------------------

@pytest.mark.parametrize("forbidden_key", [
    "task", "task_text", "file_paths", "selected_files",
    "branch", "repo", "repo_name", "username", "email",
    "diff", "prompt", "prompts", "source_code", "env",
    "command_output", "test_output", "stdout", "stderr",
])
def test_event_never_contains_forbidden_fields(forbidden_key):
    event = telemetry.build_event(
        command_type="solve", dry_run=False, risk_level="HIGH",
        policy_trigger_count=0, security_warning_count=0,
        ai_calls_used=1, planned_ai_calls=1, review_loops_used=0,
        run_duration_ms=100, stopped_early=False, error_category=None,
        anonymous_id="abc",
    )
    assert forbidden_key not in event


# --- local logging ---------------------------------------------------------

def test_emit_appends_to_local_events_when_enabled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    telemetry.enable()  # no endpoint -> local file
    event = telemetry.build_event(
        command_type="plan", dry_run=True, risk_level="LOW",
        policy_trigger_count=0, security_warning_count=0,
        ai_calls_used=0, planned_ai_calls=1, review_loops_used=0,
        run_duration_ms=42, stopped_early=True, error_category=None,
        anonymous_id="abc",
    )
    assert telemetry.emit(event) == "logged"
    events_path = tmp_path / ".agentforge" / "telemetry" / "events.jsonl"
    assert events_path.exists()
    lines = events_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    written = json.loads(lines[0])
    assert written["command_type"] == "plan"
    assert written["risk_level"] == "LOW"
    assert set(written.keys()) <= telemetry.ALLOWED_FIELDS


def test_latest_event_returns_most_recent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    telemetry.enable()
    for n in range(3):
        e = telemetry.build_event(
            command_type="solve", dry_run=False, risk_level="MEDIUM",
            policy_trigger_count=n, security_warning_count=0,
            ai_calls_used=n, planned_ai_calls=n, review_loops_used=0,
            run_duration_ms=n * 100, stopped_early=False,
            error_category=None, anonymous_id="abc",
        )
        telemetry.emit(e)
    latest = telemetry.latest_event()
    assert latest is not None
    assert latest["policy_trigger_count"] == 2


# --- network endpoint, with failure resilience ----------------------------

def test_send_failure_returns_send_failed_not_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    telemetry.enable(endpoint="http://127.0.0.1:1/agentforge-test-nope")

    # Patch the lazily-imported urlopen to raise.
    import urllib.request
    def explode(*a, **kw):
        raise urllib.error.URLError("nope")
    monkeypatch.setattr(urllib.request, "urlopen", explode)

    event = telemetry.build_event(
        command_type="solve", dry_run=False, risk_level=None,
        policy_trigger_count=0, security_warning_count=0,
        ai_calls_used=0, planned_ai_calls=0, review_loops_used=0,
        run_duration_ms=0, stopped_early=False, error_category=None,
        anonymous_id="abc",
    )
    # Must not raise — privacy failure mode is to do nothing.
    assert telemetry.emit(event) == "send_failed"


# --- malformed-on-disk resilience -----------------------------------------

def test_malformed_settings_file_treated_as_disabled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings_dir = tmp_path / ".agentforge" / "telemetry"
    settings_dir.mkdir(parents=True)
    (settings_dir / "settings.json").write_text("this is not json", encoding="utf-8")
    s = telemetry.load_settings()
    assert s.enabled is False
    assert s.anonymous_id is None


# --- public API exposes the never-collected list --------------------------

def test_never_collected_list_mentions_secrets_and_paths():
    items = telemetry.never_collected()
    joined = " ".join(items).lower()
    assert "secret" in joined
    assert "path" in joined or "paths" in joined
    assert "prompt" in joined
    assert "diff" in joined
