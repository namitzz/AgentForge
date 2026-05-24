"""Failure handling: status model, FailureReport, top-level wrappers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentforge.agents import base as agent_base
from agentforge.failure import (
    ErrorCategory,
    FailureReport,
    RunStatus,
    build_failure_report,
    categorize_exception,
)
from agentforge.orchestrator import Orchestrator


# --- Unit: categorisation -------------------------------------------------

def test_categorize_agent_unavailable():
    from agentforge.agents.base import AgentUnavailable
    assert categorize_exception(AgentUnavailable("nope")) == ErrorCategory.AGENT_ERROR


def test_categorize_budget_exceeded():
    from agentforge.budget import BudgetExceeded
    assert categorize_exception(BudgetExceeded("over")) == ErrorCategory.BUDGET_ERROR


def test_categorize_git_error():
    from agentforge.tools.git_tools import GitError
    assert categorize_exception(GitError("bad")) == ErrorCategory.GIT_ERROR


def test_categorize_keyboard_interrupt():
    # KeyboardInterrupt is a BaseException, not Exception.
    assert categorize_exception(KeyboardInterrupt()) == ErrorCategory.UNKNOWN_ERROR


def test_categorize_file_not_found():
    assert categorize_exception(FileNotFoundError()) == ErrorCategory.CONFIG_ERROR


def test_categorize_permission_error():
    assert categorize_exception(PermissionError()) == ErrorCategory.ARTIFACT_ERROR


def test_categorize_unknown():
    assert categorize_exception(ValueError("x")) == ErrorCategory.UNKNOWN_ERROR


# --- Unit: FailureReport schema ------------------------------------------

def test_failure_report_to_dict_has_required_fields():
    r = build_failure_report(
        status=RunStatus.FAILED,
        exception=FileNotFoundError("config.yaml"),
        message="config.yaml not found",
        step_failed="config",
        partial_artifacts=["task.json"],
    )
    d = r.to_dict()
    for key in (
        "status", "error_category", "message", "step_failed",
        "safe_to_retry", "suggested_fix",
        "partial_artifacts_written", "timestamp",
    ):
        assert key in d, f"missing field: {key}"


def test_failure_report_agent_error_not_safe_to_retry():
    from agentforge.agents.base import AgentUnavailable
    r = build_failure_report(
        status=RunStatus.FAILED,
        exception=AgentUnavailable("'claude' not on PATH"),
        message="agent missing",
        step_failed="planning",
        partial_artifacts=[],
    )
    assert r.error_category == ErrorCategory.AGENT_ERROR.value
    assert r.safe_to_retry is False
    assert any("install" in s.lower() for s in r.suggested_fix)


def test_failure_report_budget_error_is_safe_to_retry():
    from agentforge.budget import BudgetExceeded
    r = build_failure_report(
        status=RunStatus.FAILED,
        exception=BudgetExceeded("hit"),
        message="budget hit",
        step_failed="planning",
        partial_artifacts=[],
    )
    assert r.error_category == ErrorCategory.BUDGET_ERROR.value
    assert r.safe_to_retry is True


def test_failure_report_human_summary_format():
    from agentforge.agents.base import AgentUnavailable
    r = build_failure_report(
        status=RunStatus.FAILED,
        exception=AgentUnavailable("'claude' not on PATH"),
        message="Claude command was not found.",
        step_failed="planning",
        partial_artifacts=[],
    )
    text = "\n".join(r.human_summary())
    assert "AgentForge stopped safely." in text
    assert "Reason: Claude command was not found." in text
    assert "Suggested fix:" in text
    assert "Retrying without changes will hit the same error." in text


# --- Integration: dry-run completion ------------------------------------

def test_dry_run_status_is_dry_run_completed(sample_repo, base_config, monkeypatch):
    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(config=base_config, cwd=sample_repo)
    result = orch.solve("update auth handler", dry_run=True)
    assert result.status == "dry_run_completed"
    assert result.failure is None
    # No failure_report.json should exist on a clean run.
    assert not (Path(result.run_dir) / "failure_report.json").exists()


# --- Integration: empty-response detection ------------------------------

def test_empty_agent_response_becomes_failed(sample_repo, base_config, monkeypatch):
    """Exit 0 with empty stdout should be treated as a failure, not a blank plan."""
    from agentforge.agents.base import AgentResponse

    def empty_response(self, prompt, role="generic"):
        return AgentResponse(
            agent=self.name, role=role, prompt_chars=len(prompt),
            output="   \n   ", exit_code=0, error=None,
        )

    monkeypatch.setattr(agent_base.CLIAgent, "run", empty_response)
    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(config=base_config, cwd=sample_repo)
    result = orch.plan_only("Add caching to user lookup")
    assert result.status == "failed"
    assert result.failure is not None
    assert "empty response" in result.failure["message"].lower()
    assert (Path(result.run_dir) / "failure_report.json").exists()


# --- Integration: top-level KeyboardInterrupt ---------------------------

def test_keyboard_interrupt_is_caught_and_written(sample_repo, base_config, monkeypatch):
    def interrupt(self, prompt, role="generic"):
        raise KeyboardInterrupt()

    monkeypatch.setattr(agent_base.CLIAgent, "run", interrupt)
    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(config=base_config, cwd=sample_repo)
    result = orch.plan_only("Add caching to user lookup")
    assert result.status == "failed"
    assert result.failure is not None
    assert "interrupted" in result.failure["message"].lower()
    assert result.failure["error_category"] == ErrorCategory.UNKNOWN_ERROR.value
    # Failure report is on disk.
    report = json.loads((Path(result.run_dir) / "failure_report.json").read_text())
    assert report["safe_to_retry"] is True


# --- Integration: unexpected exception ----------------------------------

def test_unexpected_exception_is_caught_and_written(sample_repo, base_config, monkeypatch):
    def boom(self, prompt, role="generic"):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(agent_base.CLIAgent, "run", boom)
    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(config=base_config, cwd=sample_repo)
    result = orch.plan_only("Add caching to user lookup")
    assert result.status == "failed"
    assert result.failure is not None
    assert "synthetic failure" in result.failure["message"]
    assert (Path(result.run_dir) / "failure_report.json").exists()


# --- Integration: partial artifacts ------------------------------------

def test_failure_report_lists_partial_artifacts(sample_repo, base_config, monkeypatch):
    def boom(self, prompt, role="generic"):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(agent_base.CLIAgent, "run", boom)
    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(config=base_config, cwd=sample_repo)
    result = orch.solve("Add caching to user lookup")
    assert result.failure is not None
    artifacts = result.failure["partial_artifacts_written"]
    # task.json + several others should have been written before the crash.
    # The list is captured *before* failure_report.json itself is written,
    # so that file is intentionally NOT in this list.
    assert "task.json" in artifacts
    assert "failure_report.json" not in artifacts
    # Failure report exists on disk regardless.
    assert (Path(result.run_dir) / "failure_report.json").exists()
