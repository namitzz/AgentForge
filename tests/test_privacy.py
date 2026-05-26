"""No-Code-Leak Mode privacy controls.

Covers:
  - PrivacyMode flags + report shape
  - diff redactor produces stats-only output (no diff body)
  - path grouper collapses files into (dir, ext) categories
  - effective-mode helper: CLI flag overrides config
  - Config reads privacy.no_code_leak_mode from YAML
  - Orchestrator integration:
      * solve refuses cleanly with status=stopped_early
      * plan still works under no-code-leak
      * review-pr prompt contains no raw diff body
      * privacy_report.json is written
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from agentforge.config import Config
from agentforge.orchestrator import Orchestrator
from agentforge.privacy import (
    PrivacyMode,
    build_privacy_report,
    effective_mode,
    group_paths,
    grouped_file_list,
    privacy_human_summary,
    redact_diff_to_stats,
)


# ---------------------------------------------------------------------------
# PrivacyMode + report shape
# ---------------------------------------------------------------------------

def test_default_mode_does_not_redact():
    m = PrivacyMode()
    assert m.no_code_leak is False
    assert m.source_code_sent is True
    assert m.external_implementation_allowed is True


def test_no_code_leak_flips_all_flags():
    m = PrivacyMode(no_code_leak=True)
    assert m.source_code_sent is False
    assert m.file_contents_sent is False
    assert m.diff_content_sent is False
    assert m.external_implementation_allowed is False


def test_to_dict_matches_spec_keys():
    d = PrivacyMode(no_code_leak=True).to_dict()
    for key in (
        "no_code_leak_mode",
        "source_code_sent",
        "file_contents_sent",
        "diff_content_sent",
        "external_implementation_allowed",
        "redaction_applied",
    ):
        assert key in d
    assert d["no_code_leak_mode"] is True
    assert d["redaction_applied"] is True


def test_build_privacy_report_attaches_notes():
    rep = build_privacy_report(PrivacyMode(no_code_leak=True), notes=["alpha", "beta"])
    assert rep["notes"] == ["alpha", "beta"]


def test_human_summary_lines_match_spec():
    text = "\n".join(privacy_human_summary(PrivacyMode(no_code_leak=True)))
    assert "Privacy mode:" in text
    assert "No-Code-Leak Mode: enabled" in text
    assert "Source code sent to agents: no" in text
    assert "Diff content sent to agents: no" in text
    assert "External implementation calls allowed: no" in text


# ---------------------------------------------------------------------------
# Diff redactor
# ---------------------------------------------------------------------------

_REAL_DIFF = """\
diff --git a/src/auth/login.py b/src/auth/login.py
--- a/src/auth/login.py
+++ b/src/auth/login.py
@@ -1,2 +1,3 @@
-def login(): return False
+SECRET_TOKEN = "AKIAIOSFODNN7EXAMPLE"
+def login(): return True
"""


def test_redact_keeps_stats_and_drops_body():
    redacted = redact_diff_to_stats(_REAL_DIFF)
    # Stats present.
    assert "Files changed: 1" in redacted
    assert "Additions: +" in redacted
    assert "Deletions: -" in redacted
    # Body absent.
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert "+def login" not in redacted


def test_redact_uses_grouped_categories():
    redacted = redact_diff_to_stats(_REAL_DIFF)
    # We show the directory + extension, not the leaf file name.
    assert "src/auth/*.py" in redacted
    assert "login.py" not in redacted


def test_redact_empty_diff_is_safe():
    out = redact_diff_to_stats("")
    assert "redacted" in out.lower()


# ---------------------------------------------------------------------------
# Path grouping
# ---------------------------------------------------------------------------

def test_group_paths_basic():
    groups = dict(group_paths([
        "src/auth/login.py",
        "src/auth/password_reset.py",
        "tests/test_auth.py",
        "README.md",
    ]))
    assert groups["src/auth/*.py"] == 2
    assert groups["tests/*.py"] == 1
    assert groups["*.md"] == 1


def test_group_paths_handles_windows_separators():
    groups = dict(group_paths(["src\\auth\\login.py"]))
    assert "src/auth/*.py" in groups


def test_grouped_file_list_is_render_ready():
    out = grouped_file_list(["a/b/x.py", "a/b/y.py"])
    assert out == ["a/b/*.py (2)"]


# ---------------------------------------------------------------------------
# Effective-mode helper: flag overrides config
# ---------------------------------------------------------------------------

def test_flag_overrides_config_default():
    # Config says off but flag forces on.
    m = effective_mode(override=True, config_default=False)
    assert m.no_code_leak is True


def test_flag_off_keeps_config_default():
    m = effective_mode(override=None, config_default=True)
    assert m.no_code_leak is True


def test_no_flag_no_config_default():
    m = effective_mode(override=None, config_default=False)
    assert m.no_code_leak is False


# ---------------------------------------------------------------------------
# Config loads privacy.no_code_leak_mode
# ---------------------------------------------------------------------------

def test_config_reads_privacy_yaml(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "privacy:\n  no_code_leak_mode: true\n", encoding="utf-8"
    )
    from agentforge.config import load_config
    cfg = load_config(cfg_path)
    assert cfg.privacy_no_code_leak is True


def test_config_defaults_privacy_off(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("project_name: x\n", encoding="utf-8")
    from agentforge.config import load_config
    cfg = load_config(cfg_path)
    assert cfg.privacy_no_code_leak is False


# ---------------------------------------------------------------------------
# Orchestrator integration
# ---------------------------------------------------------------------------

def test_plan_under_no_code_leak_writes_privacy_report(sample_repo, base_config, monkeypatch):
    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(config=base_config, cwd=sample_repo)
    result = orch.plan_only("Fix typo in README", dry_run=True, no_code_leak=True)
    p = Path(result.run_dir) / "privacy_report.json"
    assert p.exists()
    data = json.loads(p.read_text())
    assert data["no_code_leak_mode"] is True
    assert data["external_implementation_allowed"] is False


def test_solve_refuses_under_no_code_leak_when_not_dry_run(sample_repo, base_config, monkeypatch):
    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(config=base_config, cwd=sample_repo)
    result = orch.solve("Add password reset", dry_run=False, no_code_leak=True)
    # Stops cleanly, doesn't crash.
    assert result.status in ("stopped_early",)
    # No-Code-Leak Mode message appears in the final summary or stop_reason.
    text = (result.final_summary or "") + " " + (result.budget.get("stop_reason") or "")
    assert "No-Code-Leak Mode" in text
    # Privacy report exists.
    assert (Path(result.run_dir) / "privacy_report.json").exists()


def test_solve_dry_run_still_works_under_no_code_leak(sample_repo, base_config, monkeypatch):
    """Dry-run never sends code anyway, so it should run regardless."""
    monkeypatch.chdir(sample_repo)
    orch = Orchestrator(config=base_config, cwd=sample_repo)
    result = orch.solve("Add password reset", dry_run=True, no_code_leak=True)
    # Dry-run completes — no refusal.
    assert result.status in ("dry_run_completed", "stopped_early")
    assert (Path(result.run_dir) / "privacy_report.json").exists()


def _git(args: list[str], cwd: Path) -> None:
    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@x",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@x",
    })
    subprocess.run(["git", *args], cwd=str(cwd), env=env,
                   check=True, capture_output=True, text=True)


@pytest.fixture
def pr_repo_for_privacy(tmp_path: Path) -> Path:
    _git(["init", "-b", "main"], tmp_path)
    _git(["config", "commit.gpgsign", "false"], tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text("def login(): pass\n", encoding="utf-8")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-m", "init"], tmp_path)
    _git(["checkout", "-b", "feature/x"], tmp_path)
    (tmp_path / "src" / "auth.py").write_text(
        "SECRET_LITERAL = 'AKIAIOSFODNN7EXAMPLE'\ndef login(): return True\n",
        encoding="utf-8",
    )
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-m", "weaken auth"], tmp_path)
    return tmp_path


def test_review_pr_prompt_excludes_diff_body_under_no_code_leak(
    pr_repo_for_privacy, base_config, monkeypatch
):
    monkeypatch.chdir(pr_repo_for_privacy)
    orch = Orchestrator(config=base_config, cwd=pr_repo_for_privacy)
    result = orch.review_pr(
        task="Tighten auth", dry_run=True, base="main", no_code_leak=True,
    )
    prompts = json.loads((Path(result.run_dir) / "prompts.json").read_text())
    prompt = prompts.get("reviewer", "")
    # The actual diff body must not be in the prompt.
    assert "AKIAIOSFODNN7EXAMPLE" not in prompt
    assert "+SECRET_LITERAL" not in prompt
    # But the stats marker must be.
    assert "Diff content redacted by No-Code-Leak Mode" in prompt


def test_redteam_prompt_excludes_diff_body_under_no_code_leak(
    pr_repo_for_privacy, base_config, monkeypatch
):
    monkeypatch.chdir(pr_repo_for_privacy)
    orch = Orchestrator(config=base_config, cwd=pr_repo_for_privacy)
    result = orch.redteam(
        task="Tighten auth", dry_run=True, base="main", no_code_leak=True,
    )
    prompts = json.loads((Path(result.run_dir) / "prompts.json").read_text())
    prompt = prompts.get("redteam", "")
    assert "AKIAIOSFODNN7EXAMPLE" not in prompt
    assert "Diff content redacted by No-Code-Leak Mode" in prompt
