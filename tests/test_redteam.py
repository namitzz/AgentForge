"""Red-team review mode.

Covers:
  - prompt builder includes the spec's 15 inspection categories
  - JSON parser handles valid / fenced / malformed / empty responses
  - dry-run never calls an agent
  - replay mode (`--run`) reuses an existing run dir
  - PR mode + working-tree mode + empty-diff handling
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from agentforge.agents import base as agent_base
from agentforge.orchestrator import Orchestrator
from agentforge.prompts.redteam_prompt import (
    REQUIRED_KEYS,
    build_redteam_prompt,
    parse_redteam_response,
)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def test_prompt_contains_spec_categories():
    prompt = build_redteam_prompt(
        task="t", base_branch="main", head_branch="feature",
        changed_files=["a.py"], diff="",
        risk_summary="", policy_summary="", security_summary="",
    )
    # The 15 categories the spec asks for.
    expected_phrases = (
        "authentication bypass",
        "token / session",
        "password reset abuse",
        "user enumeration",
        "missing authorization checks",
        "missing input validation",
        "unsafe database changes",
        "migration risks",
        "secrets exposure",
        "unsafe logging",
        "destructive shell",
        "missing tests",
        "regression risk",
        "overbroad changes",
        "mismatch between the stated task and the diff",
    )
    for phrase in expected_phrases:
        assert phrase in prompt, f"red-team prompt missing category: {phrase!r}"


def test_prompt_includes_required_json_keys():
    prompt = build_redteam_prompt(
        task=None, base_branch="main", head_branch="x",
        changed_files=[], diff="",
        risk_summary="", policy_summary="", security_summary="",
    )
    for key in REQUIRED_KEYS:
        # Required keys appear inside the JSON schema block.
        assert f'"{key}"' in prompt, f"prompt missing required schema key: {key}"


def test_prompt_branch_info_present():
    prompt = build_redteam_prompt(
        task=None, base_branch="main", head_branch="feature/x",
        changed_files=["src/a.py"], diff="",
        risk_summary="", policy_summary="", security_summary="",
    )
    assert "base: main" in prompt
    assert "head: feature/x" in prompt
    assert "src/a.py" in prompt


# ---------------------------------------------------------------------------
# JSON parser
# ---------------------------------------------------------------------------

_VALID_RESPONSE = json.dumps({
    "status": "needs_changes",
    "risk_level": "high",
    "findings": [
        {
            "severity": "high",
            "file": "src/auth/reset.py",
            "issue": "Token expiry is not validated.",
            "why_it_matters": "Stale tokens permit account takeover.",
            "suggested_fix": "Reject tokens older than 15 minutes.",
        }
    ],
    "missing_tests": ["Expired token should be rejected"],
    "merge_recommendation": "do_not_merge",
    "summary": "Reset flow has critical gaps.",
})


def test_parser_accepts_valid_json():
    v = parse_redteam_response(_VALID_RESPONSE)
    assert v["status"] == "needs_changes"
    assert v["risk_level"] == "high"
    assert v["merge_recommendation"] == "do_not_merge"
    assert v["findings"][0]["severity"] == "high"
    assert v["missing_tests"] == ["Expired token should be rejected"]


def test_parser_strips_code_fences():
    wrapped = "```json\n" + _VALID_RESPONSE + "\n```"
    v = parse_redteam_response(wrapped)
    assert v["status"] == "needs_changes"


def test_parser_extracts_object_from_prose():
    polluted = "Sure! Here's the JSON:\n" + _VALID_RESPONSE + "\nHope that helps."
    v = parse_redteam_response(polluted)
    assert v["status"] == "needs_changes"


def test_parser_falls_back_to_needs_manual_review_on_invalid_json():
    v = parse_redteam_response("this is not json at all")
    assert v["status"] == "needs_manual_review"
    assert v["merge_recommendation"] == "do_not_merge"
    assert v["risk_level"] == "high"
    assert "raw_output" in v
    assert "this is not json" in v["raw_output"]


def test_parser_falls_back_on_empty_response():
    v = parse_redteam_response("")
    assert v["status"] == "needs_manual_review"
    assert v["merge_recommendation"] == "do_not_merge"


def test_parser_handles_unknown_status_field():
    bad = json.dumps({
        "status": "lgtm",  # not in the allowlist
        "risk_level": "low",
        "findings": [],
        "missing_tests": [],
        "merge_recommendation": "merge_ready",
        "summary": "ok",
    })
    v = parse_redteam_response(bad)
    assert v["status"] == "needs_manual_review"


def test_parser_normalises_missing_findings_to_empty():
    # findings/missing_tests omitted — should default to empty rather than fail.
    minimal = json.dumps({
        "status": "approved",
        "risk_level": "low",
        "merge_recommendation": "merge_ready",
        "summary": "fine",
    })
    v = parse_redteam_response(minimal)
    assert v["status"] == "approved"
    assert v["findings"] == []
    assert v["missing_tests"] == []


def test_parser_coerces_unrecognised_risk_level():
    bad = json.dumps({
        "status": "approved",
        "risk_level": "nuclear",  # not in allowlist
        "findings": [],
        "missing_tests": [],
        "merge_recommendation": "merge_ready",
        "summary": "ok",
    })
    v = parse_redteam_response(bad)
    # We coerce rather than fail — falls back to "high" conservatively.
    assert v["risk_level"] == "high"


# ---------------------------------------------------------------------------
# Orchestrator integration (uses a tiny tmp git repo)
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: Path) -> None:
    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@x",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@x",
    })
    subprocess.run(["git", *args], cwd=str(cwd), env=env,
                   check=True, capture_output=True, text=True)


@pytest.fixture
def feature_branch_repo(tmp_path: Path) -> Path:
    """A repo with main + a feature branch that has one committed change."""
    _git(["init", "-b", "main"], tmp_path)
    _git(["config", "commit.gpgsign", "false"], tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text("def login(): pass\n", encoding="utf-8")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-m", "init"], tmp_path)

    _git(["checkout", "-b", "agentforge/redteam-test"], tmp_path)
    (tmp_path / "src" / "auth.py").write_text(
        "def login(email, password):\n    user.set_password(password)\n",
        encoding="utf-8",
    )
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-m", "weaken login"], tmp_path)
    return tmp_path


def test_redteam_dry_run_does_not_call_agent(feature_branch_repo, base_config, monkeypatch):
    def boom(self, prompt, role="generic"):
        raise AssertionError(f"agent {self.name} was invoked during dry-run (role={role})")
    monkeypatch.setattr(agent_base.CLIAgent, "run", boom)

    monkeypatch.chdir(feature_branch_repo)
    orch = Orchestrator(config=base_config, cwd=feature_branch_repo)
    result = orch.redteam(task=None, dry_run=True, base="main")
    assert result.dry_run is True
    assert result.budget["ai_calls"] == 0


def test_redteam_dry_run_writes_redteam_prompt(feature_branch_repo, base_config, monkeypatch):
    monkeypatch.chdir(feature_branch_repo)
    orch = Orchestrator(config=base_config, cwd=feature_branch_repo)
    result = orch.redteam(task="Tighten login", dry_run=True, base="main")
    prompts = json.loads((Path(result.run_dir) / "prompts.json").read_text())
    assert "redteam" in prompts
    assert "authentication bypass" in prompts["redteam"]
    # base/head propagated.
    assert "base: main" in prompts["redteam"]


def test_redteam_pr_mode_records_diff_and_security_report(feature_branch_repo, base_config, monkeypatch):
    monkeypatch.chdir(feature_branch_repo)
    orch = Orchestrator(config=base_config, cwd=feature_branch_repo)
    result = orch.redteam(task="Tighten login", dry_run=True, base="main")
    rd = Path(result.run_dir)
    assert (rd / "diff.patch").exists()
    assert (rd / "security_report.json").exists()
    assert (rd / "policy_report.json").exists()
    assert (rd / "risk_report.json").exists()


def test_redteam_empty_diff_fails_safely(tmp_path, base_config, monkeypatch):
    _git(["init", "-b", "main"], tmp_path)
    _git(["config", "commit.gpgsign", "false"], tmp_path)
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-m", "init"], tmp_path)

    monkeypatch.chdir(tmp_path)
    orch = Orchestrator(config=base_config, cwd=tmp_path)
    # No working-tree diff. The redteam command should produce a structured
    # failure rather than crash.
    result = orch.redteam(task=None, dry_run=True)
    assert result.status == "failed"
    assert result.failure is not None
    assert "no diff" in result.failure["message"].lower()


def test_redteam_replay_uses_saved_diff(feature_branch_repo, base_config, monkeypatch):
    """Run once to produce artifacts, then re-run with --run pointing at that dir."""
    monkeypatch.chdir(feature_branch_repo)
    orch = Orchestrator(config=base_config, cwd=feature_branch_repo)
    first = orch.redteam(task="Initial", dry_run=True, base="main")

    # Drop the redteam_review.json that dry-run did NOT write (it only writes
    # the prompt + diff + reports), then replay.
    rd = Path(first.run_dir)
    assert (rd / "diff.patch").exists()

    replay = orch.redteam(task="Replay it", dry_run=True, run=rd)
    # Same dir reused.
    assert Path(replay.run_dir) == rd
    # Task in manifest was updated.
    task_data = json.loads((rd / "task.json").read_text())
    assert task_data["task"] == "Replay it"


def test_redteam_replay_missing_dir_is_structured_failure(tmp_path, base_config, monkeypatch):
    monkeypatch.chdir(tmp_path)
    orch = Orchestrator(config=base_config, cwd=tmp_path)
    result = orch.redteam(task=None, dry_run=True, run=tmp_path / "no-such-run")
    assert result.status == "failed"
    assert result.failure is not None


def test_redteam_invalid_json_marks_needs_manual_review(feature_branch_repo, base_config, monkeypatch):
    """When the reviewer returns garbage, the saved verdict must be
    ``needs_manual_review`` with the raw output preserved."""
    from agentforge.agents.base import AgentResponse

    def bad_json_response(self, prompt, role="generic"):
        return AgentResponse(
            agent=self.name, role=role, prompt_chars=len(prompt),
            output="LGTM, ship it!", exit_code=0, error=None,
        )

    monkeypatch.setattr(agent_base.CLIAgent, "run", bad_json_response)
    monkeypatch.chdir(feature_branch_repo)
    orch = Orchestrator(config=base_config, cwd=feature_branch_repo)
    # Non-dry-run so the (mocked) reviewer actually fires.
    result = orch.redteam(task="Tighten login", dry_run=False, base="main")

    rd = Path(result.run_dir)
    verdict_path = rd / "redteam_review.json"
    assert verdict_path.exists()
    verdict = json.loads(verdict_path.read_text())
    assert verdict["status"] == "needs_manual_review"
    assert verdict["merge_recommendation"] == "do_not_merge"
    assert "raw_output" in verdict
    assert "LGTM" in verdict["raw_output"]
