"""Run logging: writes per-run artifacts under .agentforge/runs/<timestamp>/.

Every run writes a stable set of artifact files. When a run is cut short
(dry-run, budget exhausted, missing agent CLI, etc) the artifacts that didn't
get produced are still written as placeholders explaining what happened — so
status / CI / external tooling can rely on the files existing.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


RUNS_ROOT = Path(".agentforge") / "runs"

# Canonical list of per-run artifacts. Keep this in sync with README + USAGE.
ARTIFACT_NAMES: tuple[str, ...] = (
    "task.json",
    "repo_summary.json",
    "selected_files.json",
    "plan.md",
    "prompts.json",
    "policy_report.json",
    "risk_report.json",
    "test_result.txt",
    "diff.patch",
    "review.json",
    "budget.json",
    "final_summary.md",
)


class RunLogger:
    """Stores all artifacts for a single AgentForge run."""

    def __init__(self, root: Path | None = None, run_id: str | None = None) -> None:
        ts = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
        base = root if root is not None else RUNS_ROOT
        self.run_id = ts
        self.dir = base / ts
        self.dir.mkdir(parents=True, exist_ok=True)

    # --- low-level writers --------------------------------------------
    def write_json(self, name: str, data: Any) -> Path:
        path = self.dir / name
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        return path

    def write_text(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.write_text(text or "", encoding="utf-8")
        return path

    # --- typed savers used by the orchestrator ------------------------
    def save_task(self, task: dict) -> Path:
        return self.write_json("task.json", task)

    def save_repo_summary(self, summary: dict) -> Path:
        return self.write_json("repo_summary.json", summary)

    def save_selected_files(self, selected: list[dict]) -> Path:
        return self.write_json("selected_files.json", selected)

    def save_plan(self, plan_md: str) -> Path:
        return self.write_text("plan.md", plan_md)

    def save_prompts(self, prompts: dict[str, str]) -> Path:
        return self.write_json("prompts.json", prompts)

    def save_policy_report(self, report: dict) -> Path:
        return self.write_json("policy_report.json", report)

    def save_risk_report(self, report: dict) -> Path:
        return self.write_json("risk_report.json", report)

    def save_test_result(self, result_text: str) -> Path:
        return self.write_text("test_result.txt", result_text)

    def save_diff(self, diff_text: str) -> Path:
        return self.write_text("diff.patch", diff_text)

    def save_review(self, review: dict) -> Path:
        return self.write_json("review.json", review)

    def save_final_summary(self, summary_md: str) -> Path:
        return self.write_text("final_summary.md", summary_md)

    def save_budget(self, budget: dict) -> Path:
        return self.write_json("budget.json", budget)

    # --- placeholders -------------------------------------------------
    def fill_missing_placeholders(self, reason: str) -> list[str]:
        """For every canonical artifact that doesn't exist yet, write a
        placeholder file explaining why. Returns the list of filenames filled."""
        filled: list[str] = []
        for name in ARTIFACT_NAMES:
            path = self.dir / name
            if path.exists():
                continue
            if name.endswith(".json"):
                self.write_json(name, {
                    "placeholder": True,
                    "reason": reason,
                })
            else:
                self.write_text(name, f"(placeholder — {reason})\n")
            filled.append(name)
        return filled


def latest_run_dir(root: Path | None = None) -> Path | None:
    """Return the most recently created run directory, or None."""
    base = root if root is not None else RUNS_ROOT
    if not base.exists():
        return None
    candidates = [p for p in base.iterdir() if p.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)
