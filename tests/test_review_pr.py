"""PR-style review-pr command + orchestrator method."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from agentforge.orchestrator import Orchestrator
from agentforge.tools import git_tools


def _git(args: list[str], cwd: Path) -> None:
    env = os.environ.copy()
    # Deterministic commits, no signing.
    env.update({
        "GIT_AUTHOR_NAME": "AgentForge Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "AgentForge Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    })
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def pr_repo(tmp_path: Path) -> Path:
    """A repo with `main` and a feature branch carrying a committed change.

    Layout on `main`:
      src/auth/login.py        (initial)
      src/utils/validators.py  (initial)
    Layout on feature branch (`agentforge/add-validation`):
      src/auth/login.py        (modified)
      src/utils/validators.py  (modified - adds validate_password_strength)
    """
    _git(["init", "-b", "main"], tmp_path)
    _git(["config", "commit.gpgsign", "false"], tmp_path)

    (tmp_path / "src" / "auth").mkdir(parents=True)
    (tmp_path / "src" / "utils").mkdir(parents=True)
    (tmp_path / "src" / "auth" / "login.py").write_text(
        "def reset_password(new):\n    user.set_password(new)\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "utils" / "validators.py").write_text(
        "def is_valid_email(v):\n    return '@' in v\n",
        encoding="utf-8",
    )
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-m", "initial"], tmp_path)

    _git(["checkout", "-b", "agentforge/add-validation"], tmp_path)
    (tmp_path / "src" / "utils" / "validators.py").write_text(
        "def is_valid_email(v):\n    return '@' in v\n\n"
        "def validate_password_strength(p):\n"
        "    if len(p) < 10:\n        return False, 'short'\n"
        "    return True, 'ok'\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "auth" / "login.py").write_text(
        "from ..utils.validators import validate_password_strength\n\n"
        "def reset_password(new):\n"
        "    ok, reason = validate_password_strength(new)\n"
        "    if not ok:\n        return 400, reason\n"
        "    user.set_password(new)\n",
        encoding="utf-8",
    )
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-m", "add password validation"], tmp_path)
    return tmp_path


def test_find_default_base_picks_main(pr_repo):
    assert git_tools.find_default_base(pr_repo) == "main"


def test_find_default_base_falls_back_to_master(tmp_path):
    _git(["init", "-b", "master"], tmp_path)
    _git(["config", "commit.gpgsign", "false"], tmp_path)
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-m", "init"], tmp_path)
    assert git_tools.find_default_base(tmp_path) == "master"


def test_find_default_base_returns_none_when_neither_exists(tmp_path):
    _git(["init", "-b", "develop"], tmp_path)
    _git(["config", "commit.gpgsign", "false"], tmp_path)
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-m", "init"], tmp_path)
    assert git_tools.find_default_base(tmp_path) is None


def test_changed_files_between_lists_branch_changes(pr_repo):
    files = git_tools.changed_files_between("main", "HEAD", pr_repo)
    assert set(files) == {"src/auth/login.py", "src/utils/validators.py"}


def test_diff_between_contains_added_function(pr_repo):
    diff = git_tools.diff_between("main", "HEAD", pr_repo)
    assert "validate_password_strength" in diff
    assert "+def validate_password_strength" in diff


def test_review_pr_dry_run_produces_full_artifact_set(pr_repo, base_config, monkeypatch):
    monkeypatch.chdir(pr_repo)
    orch = Orchestrator(config=base_config, cwd=pr_repo)
    result = orch.review_pr(task="Review password reset changes", dry_run=True)

    assert result.dry_run is True
    assert result.budget["ai_calls"] == 0
    assert result.aborted_reason is None

    # Manifest reflects PR-mode.
    task_data = json.loads((Path(result.run_dir) / "task.json").read_text())
    assert task_data["mode"] == "review-pr"
    assert task_data["dry_run"] is True

    # Risk should land HIGH for an auth+password change.
    risk = json.loads((Path(result.run_dir) / "risk_report.json").read_text())
    assert risk["risk_level"] == "HIGH"

    # Prompt actually references the branch + changed files + risk + policy.
    prompts = json.loads((Path(result.run_dir) / "prompts.json").read_text())
    prompt = prompts["reviewer"]
    assert "src/auth/login.py" in prompt
    assert "src/utils/validators.py" in prompt
    assert "Risk report" in prompt
    assert "Policy report" in prompt
    assert "base: main" in prompt
    assert "head: agentforge/add-validation" in prompt

    # Diff was captured.
    diff_text = (Path(result.run_dir) / "diff.patch").read_text()
    assert "validate_password_strength" in diff_text


def test_review_pr_does_not_call_agent_in_dry_run(pr_repo, base_config, monkeypatch):
    from agentforge.agents import base as agent_base

    def boom(self, prompt, role="generic"):
        raise AssertionError(
            f"agent {self.name} was invoked during dry-run (role={role})"
        )

    monkeypatch.setattr(agent_base.CLIAgent, "run", boom)
    monkeypatch.chdir(pr_repo)
    orch = Orchestrator(config=base_config, cwd=pr_repo)
    result = orch.review_pr(task=None, dry_run=True)
    assert result.budget["ai_calls"] == 0


def test_review_pr_raises_when_no_base_branch(tmp_path, base_config, monkeypatch):
    _git(["init", "-b", "develop"], tmp_path)
    _git(["config", "commit.gpgsign", "false"], tmp_path)
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-m", "init"], tmp_path)

    monkeypatch.chdir(tmp_path)
    orch = Orchestrator(config=base_config, cwd=tmp_path)
    with pytest.raises(RuntimeError, match="could not find a base branch"):
        orch.review_pr(dry_run=True)


def test_review_pr_respects_explicit_base(pr_repo, base_config, monkeypatch):
    # Create a second branch off main to use as the base, just to confirm
    # the orchestrator honours --base over auto-detection.
    _git(["checkout", "main"], pr_repo)
    _git(["checkout", "-b", "release"], pr_repo)
    _git(["checkout", "agentforge/add-validation"], pr_repo)

    monkeypatch.chdir(pr_repo)
    orch = Orchestrator(config=base_config, cwd=pr_repo)
    result = orch.review_pr(dry_run=True, base="release")
    prompts = json.loads((Path(result.run_dir) / "prompts.json").read_text())
    assert "base: release" in prompts["reviewer"]
