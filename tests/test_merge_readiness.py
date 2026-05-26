"""Tests for the merge readiness engine.

Builds tiny synthetic run directories with curated artifact JSON, then
checks that each scoring rule and hard cap behaves as documented.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentforge.merge_readiness import (
    LEVEL_DO_NOT_MERGE,
    LEVEL_NEEDS_WORK,
    LEVEL_READY,
    LEVEL_READY_WITH_CAUTION,
    MergeReadinessEngine,
    calculate_for_run,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _write_json(run_dir: Path, name: str, data: dict) -> None:
    (run_dir / name).write_text(json.dumps(data), encoding="utf-8")


def _build_run(tmp_path: Path, name: str = "run-1") -> Path:
    """A clean baseline run that should score READY."""
    run = tmp_path / name
    run.mkdir(parents=True)
    _write_json(run, "task.json", {
        "run_id": name, "mode": "solve", "task": "ok",
        "dry_run": False, "stopped_early": False, "stop_reason": None,
    })
    _write_json(run, "risk_report.json", {
        "risk_level": "LOW", "score": 20, "review_required": False,
        "tests_required": False, "human_approval_required": False,
    })
    _write_json(run, "policy_report.json", {
        "blocked_files": [], "matched_files": [],
        "require_review": False, "require_tests": False,
        "require_human_approval": False, "triggering_policies": [],
    })
    _write_json(run, "security_report.json", {
        "blocked_files": [], "suspicious_files": [],
        "prompt_injection_warnings": [], "command_risk": "low",
        "command_blocked": False, "safe_to_continue": True,
    })
    _write_json(run, "budget.json", {
        "ai_calls": 1, "review_loops": 0, "chars_sent": 100,
        "files_sent": 1, "max_ai_calls": 5, "max_review_loops": 1,
        "max_total_chars": 80000, "max_files_sent": 8,
        "dry_run": False, "stopped_early": False, "stop_reason": None,
    })
    _write_json(run, "review.json", {
        "status": "approved", "risk_level": "low", "issues": [],
        "summary": "ok",
    })
    (run / "test_result.txt").write_text(
        "$ pytest\nexit_code: 0\n--- stdout ---\nOK\n--- stderr ---\n",
        encoding="utf-8",
    )
    return run


# ---------------------------------------------------------------------------
# Baseline + level mapping
# ---------------------------------------------------------------------------

def test_clean_run_scores_ready(tmp_path):
    run = _build_run(tmp_path)
    r = calculate_for_run(run)
    assert r.level == LEVEL_READY
    assert r.score >= 90
    assert "Tests passed" in r.passed
    assert "No secret files were sent" in r.passed
    assert r.blockers == []


def test_score_clamped_to_0_100(tmp_path):
    """Hit every deduction at once; score should bottom out at 0."""
    run = _build_run(tmp_path)
    _write_json(run, "failure_report.json", {"status": "failed", "message": "x"})
    _write_json(run, "security_report.json", {
        "blocked_files": [{"file": "a", "pattern": "p"}],
        "suspicious_files": [],
        "prompt_injection_warnings": [{"file": "b", "phrase": "x"}],
        "command_blocked": True, "safe_to_continue": False,
    })
    (run / "test_result.txt").write_text(
        "$ pytest\nexit_code: 1\n--- stdout ---\nfail\n--- stderr ---\n",
        encoding="utf-8",
    )
    _write_json(run, "review.json", {"status": "needs_changes", "risk_level": "high", "issues": [], "summary": "no"})
    _write_json(run, "risk_report.json", {"risk_level": "HIGH", "human_approval_required": True})
    _write_json(run, "policy_report.json", {
        "blocked_files": [], "matched_files": [],
        "require_review": True, "require_tests": True,
        "require_human_approval": True, "triggering_policies": [],
    })
    _write_json(run, "budget.json", {"stopped_early": True, "stop_reason": "x", "dry_run": False})
    r = calculate_for_run(run)
    assert r.score == 0
    assert r.level == LEVEL_DO_NOT_MERGE


# ---------------------------------------------------------------------------
# Individual deductions / blockers
# ---------------------------------------------------------------------------

def test_blocker_tests_failed(tmp_path):
    run = _build_run(tmp_path)
    (run / "test_result.txt").write_text(
        "$ pytest\nexit_code: 1\n--- stdout ---\nx\n--- stderr ---\n",
        encoding="utf-8",
    )
    r = calculate_for_run(run)
    assert "Tests failed" in r.blockers
    assert r.level != LEVEL_READY
    assert r.score < 90


def test_blocker_needs_changes(tmp_path):
    run = _build_run(tmp_path)
    _write_json(run, "review.json", {
        "status": "needs_changes", "risk_level": "medium",
        "issues": [], "summary": "fix this",
    })
    r = calculate_for_run(run)
    assert "Reviewer requested changes" in r.blockers
    assert r.level != LEVEL_READY


def test_blocker_safe_to_continue_false(tmp_path):
    run = _build_run(tmp_path)
    _write_json(run, "security_report.json", {
        "blocked_files": [], "suspicious_files": [],
        "prompt_injection_warnings": [], "command_blocked": True,
        "safe_to_continue": False,
    })
    r = calculate_for_run(run)
    assert any("safe_to_continue" in b.lower() or "refused" in b.lower() for b in r.blockers)
    assert r.level != LEVEL_READY


def test_blocker_failure_report_present(tmp_path):
    run = _build_run(tmp_path)
    _write_json(run, "failure_report.json", {
        "status": "failed", "error_category": "AGENT_ERROR",
        "message": "claude not found", "step_failed": "solve",
        "safe_to_retry": False, "suggested_fix": [], "partial_artifacts_written": [],
        "timestamp": "2026-01-01T00:00:00",
    })
    r = calculate_for_run(run)
    assert any("failed" in b.lower() for b in r.blockers)
    assert r.level != LEVEL_READY


def test_warning_high_risk_deducts(tmp_path):
    run = _build_run(tmp_path)
    _write_json(run, "risk_report.json", {
        "risk_level": "HIGH", "score": 85,
        "review_required": True, "tests_required": True,
        "human_approval_required": False,
    })
    r = calculate_for_run(run)
    assert any("HIGH" in w for w in r.warnings)
    # Just one HIGH-risk deduction (15): baseline 100 - 15 = 85 -> READY_WITH_CAUTION.
    assert r.level == LEVEL_READY_WITH_CAUTION


def test_warning_medium_risk_smaller_deduction(tmp_path):
    run = _build_run(tmp_path)
    _write_json(run, "risk_report.json", {
        "risk_level": "MEDIUM", "score": 50,
        "human_approval_required": False,
    })
    r = calculate_for_run(run)
    # 100 - 8 = 92 -> still READY (medium risk alone isn't enough to demote).
    assert r.score == 92
    assert r.level == LEVEL_READY


def test_human_approval_caps_below_ready(tmp_path):
    """Approval required is a never-READY condition. Score 85 + cap = 85 anyway,
    but the level must NOT be READY."""
    run = _build_run(tmp_path)
    _write_json(run, "policy_report.json", {
        "blocked_files": [], "matched_files": [],
        "require_review": False, "require_tests": False,
        "require_human_approval": True, "triggering_policies": ["x"],
    })
    r = calculate_for_run(run)
    assert r.level != LEVEL_READY
    assert any("approval" in w.lower() for w in r.warnings)


def test_tests_did_not_run_deducts(tmp_path):
    run = _build_run(tmp_path)
    (run / "test_result.txt").write_text(
        "$ \nexit_code: 0\n--- stdout ---\n(no test command configured)\n--- stderr ---\n",
        encoding="utf-8",
    )
    r = calculate_for_run(run)
    assert any("Tests did not run" in w for w in r.warnings)


def test_policy_requires_tests_but_did_not_run_blocks(tmp_path):
    run = _build_run(tmp_path)
    _write_json(run, "policy_report.json", {
        "blocked_files": [], "matched_files": [],
        "require_review": False, "require_tests": True,
        "require_human_approval": False, "triggering_policies": ["x"],
    })
    (run / "test_result.txt").write_text(
        "$ \nexit_code: 0\n--- stdout ---\n(no test command configured)\n--- stderr ---\n",
        encoding="utf-8",
    )
    r = calculate_for_run(run)
    assert any("Policy requires tests" in b for b in r.blockers)


def test_secrets_blocked_warning(tmp_path):
    run = _build_run(tmp_path)
    _write_json(run, "security_report.json", {
        "blocked_files": ["src/keys.py"],
        "suspicious_files": [],
        "prompt_injection_warnings": [],
        "command_blocked": False, "safe_to_continue": True,
    })
    r = calculate_for_run(run)
    # Score 100 - 25 = 75 -> READY_WITH_CAUTION.
    assert r.score == 75
    assert any("secret" in w.lower() for w in r.warnings)


def test_injection_warnings_deduct(tmp_path):
    run = _build_run(tmp_path)
    _write_json(run, "security_report.json", {
        "blocked_files": [],
        "suspicious_files": ["docs/x.md"],
        "prompt_injection_warnings": [
            {"file": "docs/x.md", "phrase": "ignore previous instructions"}
        ],
        "command_blocked": False, "safe_to_continue": True,
    })
    r = calculate_for_run(run)
    assert r.score == 95     # -5 from injection
    assert any("injection" in w.lower() for w in r.warnings)


def test_budget_stopped_early_deduct(tmp_path):
    run = _build_run(tmp_path)
    _write_json(run, "budget.json", {
        "ai_calls": 1, "review_loops": 0, "chars_sent": 100,
        "files_sent": 1, "max_ai_calls": 5, "max_review_loops": 1,
        "max_total_chars": 80000, "max_files_sent": 8,
        "dry_run": False, "stopped_early": True,
        "stop_reason": "tests passed and review not required",
    })
    r = calculate_for_run(run)
    assert r.score == 95
    assert any("stopped early" in w.lower() for w in r.warnings)


# ---------------------------------------------------------------------------
# Hard caps + level transitions
# ---------------------------------------------------------------------------

def test_never_ready_when_tests_failed(tmp_path):
    run = _build_run(tmp_path)
    (run / "test_result.txt").write_text(
        "$ pytest\nexit_code: 1\n--- stdout ---\nx\n--- stderr ---\n",
        encoding="utf-8",
    )
    r = calculate_for_run(run)
    assert r.level != LEVEL_READY
    assert r.score < 90


def test_never_ready_when_review_needs_changes(tmp_path):
    run = _build_run(tmp_path)
    _write_json(run, "review.json", {
        "status": "needs_changes", "risk_level": "medium",
        "issues": [], "summary": "nope",
    })
    r = calculate_for_run(run)
    assert r.level != LEVEL_READY


# ---------------------------------------------------------------------------
# Output shape + summary text
# ---------------------------------------------------------------------------

def test_to_dict_has_required_fields(tmp_path):
    run = _build_run(tmp_path)
    d = calculate_for_run(run).to_dict()
    for key in (
        "score", "level", "summary",
        "passed", "warnings", "blockers",
        "recommendation", "deductions",
    ):
        assert key in d, f"missing field: {key}"


def test_summary_mentions_auth_when_policy_matched_auth(tmp_path):
    """The example summary in the spec calls out auth-related touches."""
    run = _build_run(tmp_path)
    _write_json(run, "policy_report.json", {
        "blocked_files": [],
        "matched_files": [
            {"policy": "Auth changes require review",
             "path": "src/auth/login.py", "reason": "match"}
        ],
        "require_review": False, "require_tests": False,
        "require_human_approval": True,
        "triggering_policies": ["Auth changes require review"],
    })
    r = calculate_for_run(run)
    assert "auth" in r.summary.lower()


def test_recommendation_mentions_approval_when_required(tmp_path):
    run = _build_run(tmp_path)
    _write_json(run, "policy_report.json", {
        "blocked_files": [], "matched_files": [],
        "require_review": False, "require_tests": False,
        "require_human_approval": True, "triggering_policies": ["x"],
    })
    r = calculate_for_run(run)
    assert "approval" in r.recommendation.lower()


def test_human_summary_renders_expected_block(tmp_path):
    run = _build_run(tmp_path)
    text = "\n".join(calculate_for_run(run).human_summary())
    assert "Merge readiness:" in text
    assert "Score:" in text
    assert "Level:" in text
    assert "Recommendation:" in text


# ---------------------------------------------------------------------------
# Resilience to malformed / missing artifacts
# ---------------------------------------------------------------------------

def test_run_dir_must_exist(tmp_path):
    with pytest.raises(NotADirectoryError):
        MergeReadinessEngine(tmp_path / "no-such-dir")


def test_missing_artifacts_treated_as_warnings(tmp_path):
    run = tmp_path / "empty"
    run.mkdir()
    r = calculate_for_run(run)
    # Without any artifacts, baseline is 100, no deductions fire — but
    # several "report missing" warnings should appear.
    assert any("missing" in w.lower() for w in r.warnings)


def test_placeholder_artifacts_are_ignored(tmp_path):
    """Placeholder files (from dry-run / aborted runs) shouldn't be treated
    as real signals."""
    run = tmp_path / "ph"
    run.mkdir()
    _write_json(run, "review.json", {"placeholder": True, "reason": "dry-run preview"})
    _write_json(run, "risk_report.json", {"placeholder": True, "reason": "x"})
    r = calculate_for_run(run)
    # No "Reviewer requested changes" blocker should fire from a placeholder.
    assert all("requested changes" not in b.lower() for b in r.blockers)


def test_malformed_json_artifact_does_not_crash(tmp_path):
    run = tmp_path / "bad"
    run.mkdir()
    (run / "security_report.json").write_text("this is not json", encoding="utf-8")
    # Must not raise.
    r = calculate_for_run(run)
    assert isinstance(r.score, int)
    assert any("security report missing" in w.lower() for w in r.warnings)


def test_dry_run_run_is_noted_in_warnings(tmp_path):
    run = _build_run(tmp_path)
    _write_json(run, "task.json", {
        "run_id": "x", "mode": "solve", "task": "x",
        "dry_run": True, "stopped_early": True,
        "stop_reason": "dry-run - no agent calls made",
    })
    r = calculate_for_run(run)
    assert any("dry-run" in w.lower() for w in r.warnings)
