"""Project rules: load/write helpers + integration with prompts and orchestrator."""

from __future__ import annotations

import json
from pathlib import Path

from agentforge.orchestrator import Orchestrator
from agentforge.project_rules import (
    DEFAULT_PROJECT_RULES,
    PROJECT_RULES_REL_PATH,
    load_project_rules,
    project_rules_status,
    write_default_project_rules,
)
from agentforge.prompts.implementation_prompt import build_implementation_prompt
from agentforge.prompts.planning_prompt import build_planning_prompt
from agentforge.prompts.review_prompt import (
    build_pr_review_prompt,
    build_review_prompt,
)


def test_write_default_creates_file(tmp_path):
    p = write_default_project_rules(tmp_path)
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "Project Rules" in text
    assert "Keep changes small and focused" in text


def test_write_default_is_idempotent(tmp_path):
    p1 = write_default_project_rules(tmp_path)
    p1.write_text("# my custom rules\n- be nice\n", encoding="utf-8")
    p2 = write_default_project_rules(tmp_path)
    assert p1 == p2
    assert p2.read_text(encoding="utf-8").startswith("# my custom rules")


def test_write_default_overwrite_replaces(tmp_path):
    p = write_default_project_rules(tmp_path)
    p.write_text("# custom\n", encoding="utf-8")
    write_default_project_rules(tmp_path, overwrite=True)
    assert "Keep changes small" in p.read_text(encoding="utf-8")


def test_load_returns_none_when_missing(tmp_path):
    assert load_project_rules(tmp_path) is None


def test_load_returns_none_for_empty_file(tmp_path):
    p = tmp_path / PROJECT_RULES_REL_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("   \n  \t  \n", encoding="utf-8")
    assert load_project_rules(tmp_path) is None


def test_load_returns_text_when_present(tmp_path):
    write_default_project_rules(tmp_path)
    text = load_project_rules(tmp_path)
    assert text is not None
    assert "Keep changes small and focused" in text


def test_status_helper(tmp_path):
    present, n = project_rules_status(tmp_path)
    assert present is False
    assert n == 0
    write_default_project_rules(tmp_path)
    present, n = project_rules_status(tmp_path)
    assert present is True
    assert n > 0


def test_planning_prompt_includes_rules():
    rules = "# Project Rules\n- never delete migrations"
    prompt = build_planning_prompt(
        task="t", task_type="feature", repo_summary="", relevant_files=[],
        project_rules=rules,
    )
    assert "# Project rules" in prompt
    assert "never delete migrations" in prompt


def test_planning_prompt_handles_missing_rules():
    prompt = build_planning_prompt(
        task="t", task_type="feature", repo_summary="", relevant_files=[],
    )
    assert "no project rules file found" in prompt


def test_implementation_prompt_includes_rules():
    prompt = build_implementation_prompt(
        task="t", plan="p", files=[], max_chars_per_file=100,
        secret_files=[".env"], project_rules="- be careful",
    )
    assert "- be careful" in prompt


def test_review_prompt_includes_rules():
    prompt = build_review_prompt(
        task="t", plan="p", diff="d", test_result="r",
        project_rules="- always run tests",
    )
    assert "always run tests" in prompt


def test_pr_review_prompt_includes_rules():
    prompt = build_pr_review_prompt(
        task="t", base_branch="main", head_branch="feature",
        changed_files=["a.py"], diff="", risk_summary="", policy_summary="",
        project_rules="- enforce ratelimit",
    )
    assert "enforce ratelimit" in prompt


def test_dry_run_emits_rules_status_when_present(sample_repo, base_config, monkeypatch):
    write_default_project_rules(sample_repo)
    events: list[str] = []
    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(
        config=base_config, cwd=sample_repo,
        on_event=lambda msg: events.append(msg),
    )
    orch.solve("add caching to user lookup", dry_run=True)
    joined = "\n".join(events)
    assert "Project rules: loaded" in joined


def test_dry_run_emits_rules_missing_when_absent(sample_repo, base_config, monkeypatch):
    events: list[str] = []
    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(
        config=base_config, cwd=sample_repo,
        on_event=lambda msg: events.append(msg),
    )
    orch.solve("add caching to user lookup", dry_run=True)
    joined = "\n".join(events)
    assert "Project rules: none found" in joined


def test_solve_planner_prompt_contains_project_rules(sample_repo, base_config, monkeypatch):
    """Integration: rules content lands inside prompts.json after a solve."""
    rules_file = sample_repo / PROJECT_RULES_REL_PATH
    rules_file.parent.mkdir(parents=True, exist_ok=True)
    rules_file.write_text(
        "# Project Rules\n- never touch payment files without review\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(config=base_config, cwd=sample_repo)
    result = orch.solve("update auth handler", dry_run=True)

    prompts = json.loads((Path(result.run_dir) / "prompts.json").read_text())
    assert "never touch payment files" in prompts["planner"]
    assert "never touch payment files" in prompts["implementer"]
