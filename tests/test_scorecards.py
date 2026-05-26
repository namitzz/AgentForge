"""Local agent scorecards: storage, ingestion, resilience."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentforge.scorecards import (
    SCHEMA_VERSION,
    Scorecard,
    ScorecardStore,
    update_from_run_dir,
)


# ---------------------------------------------------------------------------
# Helpers — synthesise a run directory with the artifacts the ingester reads
# ---------------------------------------------------------------------------

def _write_json(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


def _make_run(
    tmp_path: Path,
    *,
    name: str = "run-1",
    dry_run: bool = False,
    workflow: dict | None = None,
    started_at: str = "2026-05-26T12:00:00",
    ended_at: str = "2026-05-26T12:00:03",
    tests_exit_code: int | None = 0,
    review_status: str | None = "approved",
    risk_level: str = "LOW",
    failure: bool = False,
    call_log: list[dict] | None = None,
) -> Path:
    run = tmp_path / name
    run.mkdir(parents=True)
    _write_json(run / "task.json", {
        "run_id": name,
        "mode": "solve",
        "task": "demo",
        "dry_run": dry_run,
        "started_at": started_at,
        "ended_at": ended_at,
        "agent_workflow": workflow or {
            "planner": "claude",
            "implementer": "codex",
            "reviewer": "claude",
        },
        "classification": None,
        "stopped_early": False,
        "stop_reason": None,
    })
    _write_json(run / "budget.json", {
        "ai_calls": len(call_log or []) or 0,
        "review_loops": 0,
        "chars_sent": sum(int(c.get("prompt_chars", 0)) for c in (call_log or [])),
        "files_sent": 3,
        "dry_run": dry_run,
        "stopped_early": False,
        "stop_reason": None,
        "call_log": call_log or [],
    })
    _write_json(run / "risk_report.json", {"risk_level": risk_level})
    if review_status is not None:
        _write_json(run / "review.json", {
            "status": review_status,
            "risk_level": risk_level.lower(),
            "issues": [],
            "summary": "ok",
        })
    if tests_exit_code is not None:
        (run / "test_result.txt").write_text(
            f"$ pytest\nexit_code: {tests_exit_code}\n--- stdout ---\n--- stderr ---\n",
            encoding="utf-8",
        )
    if failure:
        _write_json(run / "failure_report.json", {
            "status": "failed",
            "error_category": "AGENT_ERROR",
            "message": "synthetic",
            "step_failed": "solve",
            "safe_to_retry": False,
            "suggested_fix": [],
            "partial_artifacts_written": [],
            "timestamp": started_at,
        })
    return run


# ---------------------------------------------------------------------------
# Scorecard dataclass
# ---------------------------------------------------------------------------

def test_scorecard_defaults_to_zeros():
    c = Scorecard(agent="claude", role="reviewer")
    assert c.tasks_attempted == 0
    assert c.average_chars_sent == 0
    assert c.average_duration_ms == 0
    assert c.last_used_at is None


def test_scorecard_round_trip_through_dict():
    c = Scorecard(agent="codex", role="implementer",
                  tasks_attempted=5, tasks_completed=4,
                  total_chars_sent=10_000, chars_samples=5)
    restored = Scorecard.from_dict(c.to_dict())
    assert restored.agent == "codex"
    assert restored.role == "implementer"
    assert restored.tasks_attempted == 5
    assert restored.tasks_completed == 4
    assert restored.average_chars_sent == 2_000


# ---------------------------------------------------------------------------
# Store load / save / resilience
# ---------------------------------------------------------------------------

def test_store_missing_file_starts_empty(tmp_path):
    store = ScorecardStore(tmp_path / "scorecards.json")
    assert store.cards() == []
    assert store.was_missing is True
    assert store.was_corrupted is False


def test_store_save_then_reload_preserves_data(tmp_path):
    path = tmp_path / "scorecards.json"
    s1 = ScorecardStore(path)
    card = s1.get_or_create("claude", "reviewer")
    card.tasks_attempted = 3
    card.review_approvals = 2
    s1.save()

    s2 = ScorecardStore(path)
    assert len(s2.cards()) == 1
    c = s2.cards()[0]
    assert c.agent == "claude"
    assert c.role == "reviewer"
    assert c.tasks_attempted == 3
    assert c.review_approvals == 2


def test_store_corrupted_json_starts_empty_and_flags(tmp_path):
    path = tmp_path / "scorecards.json"
    path.write_text("this is not json", encoding="utf-8")
    store = ScorecardStore(path)
    assert store.cards() == []
    assert store.was_corrupted is True


def test_store_recreates_after_corruption(tmp_path):
    path = tmp_path / "scorecards.json"
    path.write_text("garbage", encoding="utf-8")
    store = ScorecardStore(path)
    assert store.was_corrupted is True
    # Updating + saving overwrites the corrupted file with valid JSON.
    store.get_or_create("codex", "implementer").tasks_attempted = 1
    store.save()
    reloaded = ScorecardStore(path)
    assert reloaded.was_corrupted is False
    assert reloaded.cards()[0].tasks_attempted == 1


def test_store_rejects_unknown_role_on_load(tmp_path):
    path = tmp_path / "scorecards.json"
    path.write_text(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "scorecards": [
            {"agent": "claude", "role": "narrator", "tasks_attempted": 7},
            {"agent": "codex",  "role": "implementer", "tasks_attempted": 3},
        ],
    }), encoding="utf-8")
    store = ScorecardStore(path)
    cards = store.cards()
    # The "narrator" entry is silently dropped.
    assert {(c.agent, c.role) for c in cards} == {("codex", "implementer")}


def test_reset_removes_file(tmp_path):
    path = tmp_path / "scorecards.json"
    store = ScorecardStore(path)
    store.get_or_create("claude", "reviewer").tasks_attempted = 1
    store.save()
    assert path.exists()
    store.reset()
    assert not path.exists()
    assert store.cards() == []


# ---------------------------------------------------------------------------
# update_from_run_dir — the core ingestion logic
# ---------------------------------------------------------------------------

def test_dry_run_only_increments_dry_runs_seen(tmp_path):
    run = _make_run(tmp_path, dry_run=True, name="dr-1")
    store = ScorecardStore(tmp_path / "scorecards.json")
    assert update_from_run_dir(store, run) is True
    for c in store.cards():
        assert c.dry_runs_seen == 1
        assert c.tasks_attempted == 0
        assert c.tasks_completed == 0
        assert c.failures == 0


def test_real_run_credits_attempts_and_completion(tmp_path):
    run = _make_run(tmp_path, name="ok-1",
                    review_status="approved", risk_level="LOW",
                    tests_exit_code=0)
    store = ScorecardStore(tmp_path / "scorecards.json")
    update_from_run_dir(store, run)
    by_role = {(c.agent, c.role): c for c in store.cards()}
    assert by_role[("claude", "planner")].tasks_attempted == 1
    assert by_role[("claude", "planner")].tasks_completed == 1
    assert by_role[("codex", "implementer")].tests_passed_after_agent == 1
    assert by_role[("claude", "reviewer")].review_approvals == 1


def test_failure_report_increments_failures_not_completions(tmp_path):
    run = _make_run(tmp_path, name="fail-1", failure=True,
                    tests_exit_code=None, review_status=None)
    store = ScorecardStore(tmp_path / "scorecards.json")
    update_from_run_dir(store, run)
    for c in store.cards():
        assert c.tasks_attempted == 1
        assert c.failures == 1
        assert c.tasks_completed == 0


def test_failed_tests_increment_implementer_counter(tmp_path):
    run = _make_run(tmp_path, name="failtest-1",
                    review_status="needs_changes",
                    tests_exit_code=1)
    store = ScorecardStore(tmp_path / "scorecards.json")
    update_from_run_dir(store, run)
    impl = next(c for c in store.cards() if c.role == "implementer")
    assert impl.tests_failed_after_agent == 1
    assert impl.tests_passed_after_agent == 0


def test_needs_changes_increments_reviewer_counter(tmp_path):
    run = _make_run(tmp_path, name="nc-1",
                    review_status="needs_changes",
                    tests_exit_code=1)
    store = ScorecardStore(tmp_path / "scorecards.json")
    update_from_run_dir(store, run)
    rev = next(c for c in store.cards() if c.role == "reviewer")
    assert rev.review_needs_changes == 1
    assert rev.review_approvals == 0


def test_high_risk_review_counter(tmp_path):
    run = _make_run(tmp_path, name="hr-1",
                    risk_level="HIGH", review_status="approved")
    store = ScorecardStore(tmp_path / "scorecards.json")
    update_from_run_dir(store, run)
    rev = next(c for c in store.cards() if c.role == "reviewer")
    assert rev.high_risk_reviews == 1


def test_call_log_drives_per_role_average_chars(tmp_path):
    run = _make_run(
        tmp_path, name="cl-1",
        call_log=[
            {"agent": "claude", "role": "planner",           "prompt_chars": 1200},
            {"agent": "codex",  "role": "implementer",       "prompt_chars": 3000},
            {"agent": "codex",  "role": "implementer-revision", "prompt_chars": 2000},
            {"agent": "claude", "role": "reviewer",          "prompt_chars": 800},
        ],
    )
    store = ScorecardStore(tmp_path / "scorecards.json")
    update_from_run_dir(store, run)
    by_role = {c.role: c for c in store.cards()}
    assert by_role["planner"].average_chars_sent == 1200
    # Implementer + implementer-revision both attributed to implementer.
    assert by_role["implementer"].average_chars_sent == (3000 + 2000) // 2
    assert by_role["reviewer"].average_chars_sent == 800


def test_two_runs_accumulate(tmp_path):
    store = ScorecardStore(tmp_path / "scorecards.json")
    update_from_run_dir(store, _make_run(tmp_path, name="r1",
                                         review_status="approved"))
    update_from_run_dir(store, _make_run(tmp_path, name="r2",
                                         review_status="needs_changes",
                                         tests_exit_code=1))
    rev = next(c for c in store.cards() if c.role == "reviewer")
    assert rev.tasks_attempted == 2
    assert rev.review_approvals == 1
    assert rev.review_needs_changes == 1


def test_workflow_with_none_agent_is_skipped(tmp_path):
    run = _make_run(tmp_path, name="partial",
                    workflow={"planner": None, "implementer": "codex", "reviewer": None})
    store = ScorecardStore(tmp_path / "scorecards.json")
    update_from_run_dir(store, run)
    assert {(c.agent, c.role) for c in store.cards()} == {("codex", "implementer")}


def test_missing_run_dir_returns_false(tmp_path):
    store = ScorecardStore(tmp_path / "scorecards.json")
    assert update_from_run_dir(store, tmp_path / "no-such-run") is False


def test_last_used_at_is_recorded(tmp_path):
    run = _make_run(tmp_path, name="t-1",
                    ended_at="2026-05-26T12:30:00")
    store = ScorecardStore(tmp_path / "scorecards.json")
    update_from_run_dir(store, run)
    assert all(c.last_used_at == "2026-05-26T12:30:00" for c in store.cards())


def test_duration_split_across_active_roles(tmp_path):
    # 3-second run, three active roles -> ~1000ms each.
    run = _make_run(tmp_path, name="d-1",
                    started_at="2026-05-26T12:00:00",
                    ended_at="2026-05-26T12:00:03")
    store = ScorecardStore(tmp_path / "scorecards.json")
    update_from_run_dir(store, run)
    for c in store.cards():
        assert c.average_duration_ms == 1000


# ---------------------------------------------------------------------------
# Rendering + schema
# ---------------------------------------------------------------------------

def test_render_text_empty_message(tmp_path):
    store = ScorecardStore(tmp_path / "scorecards.json")
    out = store.render_text()
    assert "Agent scorecards" in out
    assert "no runs recorded yet" in out


def test_render_text_includes_each_agent_role(tmp_path):
    store = ScorecardStore(tmp_path / "scorecards.json")
    update_from_run_dir(store, _make_run(tmp_path, name="r1",
                                         review_status="approved"))
    text = store.render_text()
    assert "Claude as planner" in text
    assert "Codex as implementer" in text
    assert "Claude as reviewer" in text
    assert "Approved: 1" in text


def test_to_dict_has_schema_version(tmp_path):
    store = ScorecardStore(tmp_path / "scorecards.json")
    d = store.to_dict()
    assert d["schema_version"] == SCHEMA_VERSION
    assert "scorecards" in d
