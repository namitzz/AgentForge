import pytest

from agentforge.budget import BudgetExceeded, BudgetManager


def test_records_calls_and_chars(base_config):
    b = BudgetManager(base_config)
    b.record_call("claude", "planner", 1000)
    b.record_call("codex", "implementer", 2000)
    snap = b.snapshot()
    assert snap.ai_calls == 2
    assert snap.chars_sent == 3000


def test_exceeds_max_ai_calls(base_config):
    b = BudgetManager(base_config)
    for _ in range(base_config.max_ai_calls_per_run):
        b.record_call("claude", "x", 100)
    with pytest.raises(BudgetExceeded):
        b.record_call("claude", "x", 100)


def test_exceeds_max_total_chars(base_config):
    b = BudgetManager(base_config)
    with pytest.raises(BudgetExceeded):
        b.record_call("claude", "x", base_config.max_total_chars + 1)


def test_review_loop_cap(base_config):
    b = BudgetManager(base_config)
    b.record_review_loop()
    with pytest.raises(BudgetExceeded):
        b.record_review_loop()


def test_estimate_summary_format(base_config):
    b = BudgetManager(base_config)
    b.set_dry_run(True)
    b.record_planned(ai_calls=3, chars=8_200)
    b.record_files_sent(5)
    lines = b.snapshot().estimate_summary()
    joined = "\n".join(lines)
    assert "Budget estimate:" in joined
    assert "Planned AI calls: 3/3" in joined
    assert "Files selected: 5/5" in joined
    assert "Estimated chars sent: 8,200" in joined
    assert "Review loops allowed: 1" in joined
    assert "Dry run: yes" in joined


def test_record_planned_does_not_raise(base_config):
    # Storing the estimate must never fail — the orchestrator emits the
    # numbers first, then enforces. Validation lives on a separate method.
    b = BudgetManager(base_config)
    b.record_planned(ai_calls=999, chars=999_999)
    assert b.snapshot().planned_ai_calls == 999


def test_enforce_planned_within_caps_raises_when_over(base_config):
    b = BudgetManager(base_config)
    b.record_planned(ai_calls=base_config.max_ai_calls_per_run + 1, chars=100)
    with pytest.raises(BudgetExceeded):
        b.enforce_planned_within_caps()


def test_enforce_planned_within_caps_chars_too_big(base_config):
    b = BudgetManager(base_config)
    b.record_planned(ai_calls=1, chars=base_config.max_total_chars + 1)
    with pytest.raises(BudgetExceeded):
        b.enforce_planned_within_caps()


def test_summary_format_at_end(base_config):
    b = BudgetManager(base_config)
    b.record_call("claude", "planner", 500)
    b.record_files_sent(3)
    b.mark_stopped_early(True, reason="tests passed and review not required")
    lines = b.snapshot().human_summary()
    joined = "\n".join(lines)
    assert "Budget summary:" in joined
    assert "AI calls used: 1/3" in joined
    assert "Files sent: 3/5" in joined
    assert "Stopped early: yes" in joined
    assert "Stop reason: tests passed and review not required" in joined


def test_snapshot_to_dict_has_all_fields(base_config):
    b = BudgetManager(base_config)
    b.set_dry_run(True)
    b.record_planned(ai_calls=2, chars=10_000)
    d = b.snapshot().to_dict()
    for key in (
        "ai_calls", "review_loops", "chars_sent", "files_sent",
        "max_ai_calls", "max_review_loops", "max_total_chars",
        "max_files_sent", "max_chars_per_file",
        "planned_ai_calls", "planned_chars_sent",
        "dry_run", "stopped_early", "stop_reason",
    ):
        assert key in d, f"missing budget field: {key}"
