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


def test_snapshot_human_summary_mentions_caps(base_config):
    b = BudgetManager(base_config)
    b.record_call("claude", "planner", 500)
    b.record_files_sent(3)
    lines = b.snapshot().human_summary()
    joined = "\n".join(lines)
    assert "AI calls: 1/3" in joined
    assert "Files sent: 3/5" in joined
    assert "Stopped early: no" in joined


def test_stopped_early_flag(base_config):
    b = BudgetManager(base_config)
    b.mark_stopped_early(True)
    assert b.snapshot().stopped_early is True
