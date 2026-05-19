"""Run logging: writes per-run artifacts under .agentforge/runs/<timestamp>/."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


RUNS_ROOT = Path(".agentforge") / "runs"


class RunLogger:
    """Stores all artifacts for a single AgentForge run."""

    def __init__(self, root: Path | None = None, run_id: str | None = None) -> None:
        ts = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
        base = root if root is not None else RUNS_ROOT
        self.run_id = ts
        self.dir = base / ts
        self.dir.mkdir(parents=True, exist_ok=True)

    # --- writers -------------------------------------------------------
    def write_json(self, name: str, data: Any) -> Path:
        path = self.dir / name
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        return path

    def write_text(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.write_text(text or "", encoding="utf-8")
        return path

    # --- helpers used by orchestrator ---------------------------------
    def save_task(self, task: dict) -> Path:
        return self.write_json("task.json", task)

    def save_repo_summary(self, summary: dict) -> Path:
        return self.write_json("repo_summary.json", summary)

    def save_plan(self, plan_md: str) -> Path:
        return self.write_text("plan.md", plan_md)

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


def latest_run_dir(root: Path | None = None) -> Path | None:
    """Return the most recently created run directory, or None."""
    base = root if root is not None else RUNS_ROOT
    if not base.exists():
        return None
    candidates = [p for p in base.iterdir() if p.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)
