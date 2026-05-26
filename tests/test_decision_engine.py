"""Tests for the agent decision engine.

Pure unit tests for the engine itself (LOW/MEDIUM/HIGH/UNKNOWN, policy
overrides, security short-circuit, budget short-circuit, empty-context
shortcut) plus an orchestrator integration test that decision_report.json
is written and reflects the right level.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentforge.decision_engine import (
    DECISION_ARTIFACT_NAME,
    Decision,
    DecisionEngine,
    DecisionInputs,
    build_inputs_from_reports,
    decide,
)
from agentforge.orchestrator import Orchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inputs(**overrides) -> DecisionInputs:
    defaults: dict = dict(
        task_text="example task",
        task_type="feature",
        risk_level="LOW",
        require_review=False,
        require_tests=False,
        require_human_approval=False,
        safe_to_continue=True,
        selected_files_count=3,
        estimated_prompt_chars=2_000,
        max_total_chars=80_000,
        max_ai_calls=5,
        planner_agent="claude",
        implementer_agent="codex",
        reviewer_agent="claude",
        dry_run=False,
    )
    defaults.update(overrides)
    return DecisionInputs(**defaults)


# ---------------------------------------------------------------------------
# LOW-risk paths
# ---------------------------------------------------------------------------

def test_low_docs_task_no_files_recommends_no_ai():
    """Empty context + LOW docs + no policy escalation = NO_AI."""
    r = decide(_inputs(task_type="docs", risk_level="LOW", selected_files_count=0))
    assert r.decision == Decision.NO_AI.value
    assert r.planned_ai_calls == 0
    assert r.safe_to_continue is True
    assert all(a is None for a in r.recommended_agents.values())


def test_low_docs_with_files_is_single_agent():
    r = decide(_inputs(task_type="docs", risk_level="LOW", selected_files_count=1))
    assert r.decision == Decision.SINGLE_AGENT.value
    assert r.planned_ai_calls == 1
    assert r.recommended_agents["implementer"] == "codex"
    assert r.recommended_agents["planner"] is None
    assert r.recommended_agents["reviewer"] is None


def test_low_code_task_is_single_agent():
    r = decide(_inputs(task_type="feature", risk_level="LOW"))
    assert r.decision == Decision.SINGLE_AGENT.value
    assert r.recommended_agents["planner"] is None
    assert r.recommended_agents["reviewer"] is None


def test_low_bug_fix_is_single_agent():
    r = decide(_inputs(task_type="bug_fix", risk_level="LOW"))
    assert r.decision == Decision.SINGLE_AGENT.value
    assert r.recommended_agents["planner"] is None


# ---------------------------------------------------------------------------
# MEDIUM-risk paths
# ---------------------------------------------------------------------------

def test_medium_task_is_implement_and_review():
    r = decide(_inputs(task_type="feature", risk_level="MEDIUM"))
    assert r.decision == Decision.IMPLEMENT_AND_REVIEW.value
    assert r.planned_ai_calls == 2
    assert r.recommended_agents["planner"] is None
    assert r.recommended_agents["reviewer"] == "claude"


def test_medium_refactor_skips_planner_includes_reviewer():
    r = decide(_inputs(task_type="refactor", risk_level="MEDIUM"))
    assert r.decision == Decision.IMPLEMENT_AND_REVIEW.value
    assert r.recommended_agents["planner"] is None


# ---------------------------------------------------------------------------
# HIGH-risk paths
# ---------------------------------------------------------------------------

def test_high_task_is_full_pipeline():
    r = decide(_inputs(task_type="security", risk_level="HIGH"))
    assert r.decision == Decision.FULL_PIPELINE.value
    assert r.planned_ai_calls == 3
    assert r.recommended_agents["planner"] == "claude"
    assert r.recommended_agents["implementer"] == "codex"
    assert r.recommended_agents["reviewer"] == "claude"


def test_high_task_with_approval_mentions_approval_reason():
    r = decide(_inputs(
        task_type="security", risk_level="HIGH",
        require_human_approval=True,
    ))
    assert r.decision == Decision.FULL_PIPELINE.value
    assert any("approval" in s.lower() for s in r.reasons)


def test_high_bug_fix_still_skips_planner():
    """A bug fix never gets a planner, even at HIGH risk — Codex can fix
    bugs directly."""
    r = decide(_inputs(task_type="bug_fix", risk_level="HIGH"))
    assert r.recommended_agents["planner"] is None
    assert r.recommended_agents["reviewer"] == "claude"
    # implementer + reviewer = IMPLEMENT_AND_REVIEW
    assert r.decision == Decision.IMPLEMENT_AND_REVIEW.value


# ---------------------------------------------------------------------------
# UNKNOWN / defaults
# ---------------------------------------------------------------------------

def test_unknown_risk_defaults_to_full_pipeline():
    r = decide(_inputs(task_type="unknown", risk_level="UNKNOWN"))
    assert r.decision == Decision.FULL_PIPELINE.value
    assert r.recommended_agents["planner"] == "claude"
    assert r.recommended_agents["reviewer"] == "claude"


# ---------------------------------------------------------------------------
# Policy escalations
# ---------------------------------------------------------------------------

def test_policy_require_review_upgrades_low_to_two_calls():
    """A LOW task with policy.require_review must include the reviewer."""
    r = decide(_inputs(task_type="feature", risk_level="LOW", require_review=True))
    assert r.decision == Decision.IMPLEMENT_AND_REVIEW.value
    assert r.recommended_agents["reviewer"] == "claude"
    assert any("policy" in s.lower() for s in r.reasons)


def test_policy_require_human_approval_surfaces_as_reason():
    r = decide(_inputs(task_type="feature", risk_level="LOW", require_human_approval=True))
    # Approval doesn't add an agent — it's a gate. But the reason is recorded.
    assert any("approval" in s.lower() for s in r.reasons)


# ---------------------------------------------------------------------------
# Safety / budget short-circuits
# ---------------------------------------------------------------------------

def test_security_unsafe_blocks_everything():
    r = decide(_inputs(safe_to_continue=False, risk_level="LOW"))
    assert r.decision == Decision.NO_AI.value
    assert r.safe_to_continue is False
    assert all(a is None for a in r.recommended_agents.values())
    assert any("security" in s.lower() or "refused" in s.lower() for s in r.reasons)


def test_budget_overrun_blocks_everything():
    r = decide(_inputs(
        risk_level="HIGH",
        estimated_prompt_chars=200_000,
        max_total_chars=80_000,
    ))
    assert r.decision == Decision.NO_AI.value
    assert r.safe_to_continue is False
    assert any("budget" in s.lower() or "exceed" in s.lower() for s in r.reasons)


# ---------------------------------------------------------------------------
# Build-inputs helper
# ---------------------------------------------------------------------------

def test_build_inputs_aggregates_policy_and_risk_signals():
    inputs = build_inputs_from_reports(
        task_text="x",
        task_type="feature",
        risk_report={"risk_level": "MEDIUM", "review_required": True,
                     "tests_required": True, "human_approval_required": False},
        policy_report={"require_review": False, "require_tests": False,
                       "require_human_approval": True, "triggering_policies": []},
        security_report={"safe_to_continue": True},
        selected_files_count=5,
        estimated_prompt_chars=12_345,
        max_total_chars=80_000,
        max_ai_calls=5,
        planner_agent="claude",
        implementer_agent="codex",
        reviewer_agent="claude",
        dry_run=False,
    )
    # Either policy OR risk turning a flag on must surface as True.
    assert inputs.require_review is True
    assert inputs.require_tests is True
    assert inputs.require_human_approval is True
    assert inputs.safe_to_continue is True


def test_build_inputs_missing_security_defaults_safe():
    inputs = build_inputs_from_reports(
        task_text="x", task_type="docs",
        risk_report=None, policy_report=None, security_report=None,
        selected_files_count=0, estimated_prompt_chars=0,
        max_total_chars=80_000, max_ai_calls=5,
        planner_agent="claude", implementer_agent="codex", reviewer_agent="claude",
        dry_run=False,
    )
    assert inputs.safe_to_continue is True
    assert inputs.risk_level == "UNKNOWN"


# ---------------------------------------------------------------------------
# Output shape + human summary
# ---------------------------------------------------------------------------

def test_to_dict_has_required_fields():
    d = decide(_inputs()).to_dict()
    for key in (
        "decision", "recommended_agents", "planned_ai_calls",
        "reasons", "skipped_steps", "safe_to_continue",
    ):
        assert key in d


def test_human_summary_starts_with_header_and_decision():
    text = "\n".join(decide(_inputs(risk_level="HIGH")).human_summary())
    assert "Agent decision:" in text
    assert "Decision:" in text
    assert "Planned AI calls:" in text
    assert "Planner: claude" in text
    assert "Implementer: codex" in text
    assert "Reviewer: claude" in text


def test_dry_run_mode_surfaces_in_reasons():
    text = "\n".join(decide(_inputs(dry_run=True)).human_summary())
    assert "dry-run" in text.lower()


# ---------------------------------------------------------------------------
# Orchestrator integration
# ---------------------------------------------------------------------------

def test_solve_dry_run_writes_decision_report(sample_repo, base_config, monkeypatch):
    """With a realistic budget, an auth task should land on the full
    pipeline branch. (The base_config fixture caps chars very tightly,
    which intentionally trips NO_AI — see the next test for that path.)"""
    base_config.max_total_chars = 200_000  # loosen budget for this check
    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(config=base_config, cwd=sample_repo)
    result = orch.solve("update auth handler", dry_run=True)

    artifact = Path(result.run_dir) / DECISION_ARTIFACT_NAME
    assert artifact.exists(), "decision_report.json should be written by solve"
    data = json.loads(artifact.read_text())
    for key in (
        "decision", "recommended_agents", "planned_ai_calls",
        "reasons", "skipped_steps", "safe_to_continue",
    ):
        assert key in data
    # An auth task should escalate to a reviewing pipeline.
    assert data["decision"] in ("FULL_PIPELINE", "IMPLEMENT_AND_REVIEW")


def test_solve_decision_is_no_ai_when_budget_too_tight(sample_repo, base_config, monkeypatch):
    """The default tight fixture budget should force NO_AI for any
    real task, with safe_to_continue=false."""
    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(config=base_config, cwd=sample_repo)
    result = orch.solve("update auth handler", dry_run=True)
    data = json.loads((Path(result.run_dir) / DECISION_ARTIFACT_NAME).read_text())
    assert data["decision"] == "NO_AI"
    assert data["safe_to_continue"] is False
    assert any("budget" in r.lower() or "exceed" in r.lower() for r in data["reasons"])


def test_plan_dry_run_writes_decision_report(sample_repo, base_config, monkeypatch):
    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(config=base_config, cwd=sample_repo)
    result = orch.plan_only("Refactor user profile component", dry_run=True)
    artifact = Path(result.run_dir) / DECISION_ARTIFACT_NAME
    assert artifact.exists()


def test_decision_emitted_to_event_stream(sample_repo, base_config, monkeypatch):
    """The 'Agent decision:' header should appear in the orchestrator's
    on_event stream during dry-run."""
    events: list[str] = []
    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(
        config=base_config, cwd=sample_repo,
        on_event=lambda msg: events.append(msg),
    )
    orch.solve("Fix typo in README", dry_run=True)
    joined = "\n".join(events)
    assert "Agent decision:" in joined
    assert "Decision:" in joined
