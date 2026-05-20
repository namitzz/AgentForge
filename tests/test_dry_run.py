"""Dry-run must never invoke a real agent CLI.

We monkeypatch subprocess.run so any actual shell-out blows up the test.
This makes it impossible for a regression to silently start calling Claude
or Codex in dry-run mode.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge.logger import ARTIFACT_NAMES
from agentforge.orchestrator import Orchestrator


@pytest.fixture
def blow_up_on_subprocess(monkeypatch):
    import subprocess as sp

    def boom(*args, **kwargs):
        raise AssertionError(
            f"subprocess.run was called in dry-run mode: args={args!r}"
        )

    # Block the orchestrator's agent CLIs. We still allow git_tools' subprocess
    # calls in non-git temp dirs to be a no-op via is_git_repo's own check.
    monkeypatch.setattr(sp, "run", boom)
    return boom


def test_solve_dry_run_writes_all_artifacts(sample_repo, base_config, monkeypatch):
    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(config=base_config, cwd=sample_repo)
    result = orch.solve("fix pagination off-by-one", dry_run=True)

    assert result.dry_run is True
    assert result.branch is None
    assert result.aborted_reason is None
    for name in ARTIFACT_NAMES:
        assert (Path(result.run_dir) / name).exists(), f"missing artifact: {name}"


def test_solve_dry_run_makes_no_subprocess_calls_for_agents(
    sample_repo, base_config, monkeypatch
):
    # Stub out the agent CLI invocation path. If something tries to call it,
    # the test fails loudly. We don't stub git_tools because is_git_repo
    # short-circuits cleanly when there's no .git directory.
    from agentforge.agents import base as agent_base

    def boom(self, prompt, role="generic"):
        raise AssertionError(
            f"agent {self.name} was invoked during dry-run (role={role})"
        )

    monkeypatch.setattr(agent_base.CLIAgent, "run", boom)

    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(config=base_config, cwd=sample_repo)
    result = orch.solve("add caching to user lookup", dry_run=True)
    assert result.dry_run is True
    assert result.budget["ai_calls"] == 0


def test_plan_dry_run_does_not_call_agent(sample_repo, base_config, monkeypatch):
    from agentforge.agents import base as agent_base

    monkeypatch.setattr(
        agent_base.CLIAgent,
        "run",
        lambda self, prompt, role="generic": (_ for _ in ()).throw(
            AssertionError(f"agent {self.name} called in plan dry-run")
        ),
    )
    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(config=base_config, cwd=sample_repo)
    result = orch.plan_only("refactor auth flow", dry_run=True)
    assert result.dry_run is True
    assert result.budget["ai_calls"] == 0


def test_dry_run_emits_budget_estimate(sample_repo, base_config, monkeypatch):
    events: list[str] = []
    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(
        config=base_config,
        cwd=sample_repo,
        on_event=lambda msg: events.append(msg),
    )
    result = orch.solve("add caching to user lookup", dry_run=True)
    joined = "\n".join(events)
    assert "Budget estimate:" in joined
    assert "Planned AI calls:" in joined
    assert "Files selected:" in joined
    assert "Estimated chars sent:" in joined
    assert "Dry run: yes" in joined
    # The final summary should also include a stop reason for dry-run.
    assert result.budget["stop_reason"]


def test_dry_run_emits_planned_workflow(sample_repo, base_config, monkeypatch):
    events: list[str] = []
    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(
        config=base_config,
        cwd=sample_repo,
        on_event=lambda msg: events.append(msg),
    )
    orch.solve("add caching to user lookup", dry_run=True)
    joined = "\n".join(events)
    assert "Dry run: enabled" in joined
    assert "No external agents will be called." in joined
    assert "No files will be modified." in joined
    assert "Planned workflow:" in joined
    # Implementation step must be enumerated.
    assert "implementation prompt would be generated" in joined.lower()


def test_dry_run_writes_risk_report(sample_repo, base_config, monkeypatch):
    import json

    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(config=base_config, cwd=sample_repo)
    result = orch.solve("update auth handler", dry_run=True)

    risk = json.loads((Path(result.run_dir) / "risk_report.json").read_text())
    assert risk.get("risk_level") in ("LOW", "MEDIUM", "HIGH")
    assert risk.get("score") is not None
    # "auth" in task + selected paths under src/auth should land HIGH.
    assert risk["risk_level"] == "HIGH"
    assert risk["human_approval_required"] is True

    # Run result mirrors the artifact.
    assert result.risk_report is not None
    assert result.risk_report["risk_level"] == "HIGH"


def test_dry_run_drops_blocked_files_from_selected(sample_repo, base_config, monkeypatch):
    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(config=base_config, cwd=sample_repo)
    result = orch.solve("update auth handler", dry_run=True)

    import json

    selected = json.loads((Path(result.run_dir) / "selected_files.json").read_text())
    paths = {entry["path"] for entry in selected}
    assert ".env" not in paths
    assert "credentials.json" not in paths

    policy_report = json.loads((Path(result.run_dir) / "policy_report.json").read_text())
    # Auth path triggers require_review.
    assert policy_report.get("require_review") is True
