"""Run-manifest integration tests.

task.json is the top-level manifest for every run. After any flow finishes,
it must contain timestamps, the invoking command, the dry-run flag, the
selected agent workflow, and stopped_early + stop_reason.
"""

from __future__ import annotations

import json
from pathlib import Path

from agentforge.orchestrator import Orchestrator
from agentforge.run_artifacts import RunManifest, current_command, now_iso


def test_now_iso_is_parseable():
    from datetime import datetime
    parsed = datetime.fromisoformat(now_iso())
    assert parsed.year >= 2024


def test_current_command_returns_string():
    cmd = current_command()
    assert isinstance(cmd, str)
    assert len(cmd) > 0


def test_run_manifest_finalize_updates_fields():
    m = RunManifest(run_id="20260101-000000", mode="solve", task="x", dry_run=True)
    assert m.ended_at is None
    m.finalize(stopped_early=True, stop_reason="dry-run preview")
    assert m.ended_at is not None
    assert m.stopped_early is True
    assert m.stop_reason == "dry-run preview"


def test_run_manifest_to_dict_has_all_required_keys():
    m = RunManifest(run_id="r", mode="solve", task="t", dry_run=False)
    d = m.to_dict()
    for key in (
        "run_id", "mode", "task", "dry_run",
        "started_at", "ended_at",
        "command", "agentforge_version",
        "agent_workflow", "classification",
        "stopped_early", "stop_reason",
    ):
        assert key in d, f"missing manifest field: {key}"


def test_solve_writes_full_manifest_to_task_json(sample_repo, base_config, monkeypatch):
    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(config=base_config, cwd=sample_repo)
    result = orch.solve("update auth handler", dry_run=True)

    task_data = json.loads((Path(result.run_dir) / "task.json").read_text())

    # Required manifest fields.
    assert task_data["mode"] == "solve"
    assert task_data["task"] == "update auth handler"
    assert task_data["dry_run"] is True
    assert task_data["started_at"]
    assert task_data["ended_at"]
    assert task_data["command"]
    assert task_data["agentforge_version"]
    assert task_data["stopped_early"] is True
    assert task_data["stop_reason"]

    # Agent workflow names the three roles, never empty.
    workflow = task_data["agent_workflow"]
    assert "planner" in workflow
    assert "implementer" in workflow
    assert "reviewer" in workflow
    assert workflow["implementer"] is not None

    # Classification block still present for solve/plan flows.
    assert task_data["classification"] is not None


def test_plan_writes_full_manifest_to_task_json(sample_repo, base_config, monkeypatch):
    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(config=base_config, cwd=sample_repo)
    result = orch.plan_only("Fix typo in README", dry_run=True)

    task_data = json.loads((Path(result.run_dir) / "task.json").read_text())
    assert task_data["mode"] == "plan"
    assert task_data["dry_run"] is True
    assert task_data["ended_at"]
    assert task_data["agent_workflow"]["implementer"] is not None
