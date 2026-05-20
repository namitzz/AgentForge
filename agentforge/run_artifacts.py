"""Run manifest helpers.

Every AgentForge run writes ``task.json`` as its top-level manifest. This
module builds and finalizes that manifest so the orchestrator doesn't have
to construct the same dict in three places.

The manifest captures:

  - the user task and run mode (plan / solve / review)
  - the actual CLI command that started the run
  - start + end timestamps
  - dry_run flag
  - the agent workflow that was selected for the run
  - the classifier verdict
  - stopped_early + stop_reason (filled in at the end)
  - AgentForge version
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from . import __version__


def now_iso() -> str:
    """Local-time ISO 8601 timestamp, second precision."""
    return datetime.now().isoformat(timespec="seconds")


def current_command() -> str:
    """A human-readable approximation of how the user invoked AgentForge.

    Reconstructs from ``sys.argv``. The canonical prefix is
    ``python -m agentforge`` regardless of how the entrypoint was resolved.
    """
    raw_argv = list(sys.argv) or [""]
    first = raw_argv[0]
    if (
        first.endswith("__main__.py")
        or first.endswith("agentforge")
        or (
            first.endswith("main.py")
            and "agentforge" in first.replace("\\", "/")
        )
    ):
        # Prefix is fixed and never quoted.
        prefix = "python -m agentforge"
        rest = raw_argv[1:]
    else:
        prefix = first or "agentforge"
        rest = raw_argv[1:]

    quoted: list[str] = []
    for arg in rest:
        if not arg:
            continue
        if any(ch in arg for ch in (' ', '\t', '"', "'")):
            escaped = arg.replace('"', '\\"')
            quoted.append(f'"{escaped}"')
        else:
            quoted.append(arg)

    return " ".join([prefix, *quoted]) if quoted else prefix


@dataclass
class RunManifest:
    """Top-level metadata for one AgentForge run.

    Build at the start of the run, mutate as the run progresses, then call
    :meth:`finalize` before returning. The dict form is what gets written to
    ``task.json``.
    """

    run_id: str
    mode: str               # "plan" | "solve" | "review"
    task: str
    dry_run: bool
    started_at: str = field(default_factory=now_iso)
    ended_at: str | None = None
    command: str = field(default_factory=current_command)
    agentforge_version: str = __version__
    agent_workflow: dict[str, str | None] = field(default_factory=dict)
    classification: dict[str, Any] | None = None
    stopped_early: bool = False
    stop_reason: str | None = None

    def finalize(self, stopped_early: bool, stop_reason: str | None) -> None:
        self.ended_at = now_iso()
        self.stopped_early = stopped_early
        self.stop_reason = stop_reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "mode": self.mode,
            "task": self.task,
            "dry_run": self.dry_run,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "command": self.command,
            "agentforge_version": self.agentforge_version,
            "agent_workflow": dict(self.agent_workflow),
            "classification": self.classification,
            "stopped_early": self.stopped_early,
            "stop_reason": self.stop_reason,
        }


# --- formatting helpers -----------------------------------------------------

ARTIFACT_DESCRIPTIONS: dict[str, str] = {
    "task.json": "input task + run manifest (start/end, command, workflow)",
    "repo_summary.json": "file inventory at scan time",
    "selected_files.json": "files chosen for the context window",
    "plan.md": "planner output (markdown)",
    "prompts.json": "exact prompts sent to each agent",
    "policy_report.json": "blocked files + escalations",
    "risk_report.json": "LOW/MEDIUM/HIGH + score + reasons + recommended workflow",
    "test_result.txt": "test stdout/stderr + exit code",
    "diff.patch": "implementer's changes",
    "review.json": "reviewer verdict (structured JSON)",
    "budget.json": "AI calls + chars used vs caps",
    "final_summary.md": "human-readable end-of-run wrap-up",
}
