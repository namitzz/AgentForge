"""Local agent scorecards.

Tracks a small, deterministic set of stats per ``(agent, role)`` pair across
runs so a developer can see, locally, which agent performs best for planning,
implementation, and review.

Hard rules (defended below + in tests):

  - **Local only.** Stats live in ``.agentforge/scorecards.json`` inside the
    current project. Nothing leaves the machine.
  - **No new agent CLI required.** Updates read existing run artifacts
    (task.json, budget.json, review.json, test_result.txt, risk_report.json,
    failure_report.json). Missing files are skipped silently.
  - **Dry-runs don't count as completed tasks.** They bump ``dry_runs_seen``
    only.
  - **Resilient.** A missing or malformed ``scorecards.json`` is treated as
    empty + ``was_corrupted=True`` so callers can warn but the run never
    crashes on it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


SCORECARDS_DIR  = Path(".agentforge")
SCORECARDS_PATH = SCORECARDS_DIR / "scorecards.json"

# Schema version — bump if the on-disk shape changes.
SCHEMA_VERSION = 1

_ROLES: tuple[str, ...] = ("planner", "implementer", "reviewer")


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class Scorecard:
    agent: str
    role: str
    tasks_attempted: int = 0
    tasks_completed: int = 0
    failures: int = 0
    dry_runs_seen: int = 0
    # Running totals for averages — easier to merge than averages directly.
    total_chars_sent: int = 0
    chars_samples: int = 0
    total_duration_ms: int = 0
    duration_samples: int = 0
    # Reviewer-specific
    review_approvals: int = 0
    review_needs_changes: int = 0
    high_risk_reviews: int = 0
    # Implementer-specific
    tests_passed_after_agent: int = 0
    tests_failed_after_agent: int = 0
    # Bookkeeping
    last_used_at: str | None = None

    @property
    def average_chars_sent(self) -> int:
        if self.chars_samples <= 0:
            return 0
        return self.total_chars_sent // self.chars_samples

    @property
    def average_duration_ms(self) -> int:
        if self.duration_samples <= 0:
            return 0
        return self.total_duration_ms // self.duration_samples

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "role": self.role,
            "tasks_attempted": self.tasks_attempted,
            "tasks_completed": self.tasks_completed,
            "failures": self.failures,
            "dry_runs_seen": self.dry_runs_seen,
            "average_chars_sent": self.average_chars_sent,
            "average_duration_ms": self.average_duration_ms,
            "review_approvals": self.review_approvals,
            "review_needs_changes": self.review_needs_changes,
            "high_risk_reviews": self.high_risk_reviews,
            "tests_passed_after_agent": self.tests_passed_after_agent,
            "tests_failed_after_agent": self.tests_failed_after_agent,
            "last_used_at": self.last_used_at,
            # Running totals are also persisted so averages stay accurate
            # across loads/saves.
            "_total_chars_sent": self.total_chars_sent,
            "_chars_samples": self.chars_samples,
            "_total_duration_ms": self.total_duration_ms,
            "_duration_samples": self.duration_samples,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Scorecard":
        return cls(
            agent=str(data.get("agent", "")),
            role=str(data.get("role", "")),
            tasks_attempted=int(data.get("tasks_attempted", 0) or 0),
            tasks_completed=int(data.get("tasks_completed", 0) or 0),
            failures=int(data.get("failures", 0) or 0),
            dry_runs_seen=int(data.get("dry_runs_seen", 0) or 0),
            total_chars_sent=int(data.get("_total_chars_sent", 0) or 0),
            chars_samples=int(data.get("_chars_samples", 0) or 0),
            total_duration_ms=int(data.get("_total_duration_ms", 0) or 0),
            duration_samples=int(data.get("_duration_samples", 0) or 0),
            review_approvals=int(data.get("review_approvals", 0) or 0),
            review_needs_changes=int(data.get("review_needs_changes", 0) or 0),
            high_risk_reviews=int(data.get("high_risk_reviews", 0) or 0),
            tests_passed_after_agent=int(data.get("tests_passed_after_agent", 0) or 0),
            tests_failed_after_agent=int(data.get("tests_failed_after_agent", 0) or 0),
            last_used_at=data.get("last_used_at") or None,
        )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class ScorecardStore:
    """Read / write the per-project scorecards JSON.

    Loading a missing or malformed file is non-fatal: the store starts
    empty and ``was_corrupted`` is True so a caller (the CLI) can surface
    a warning before the next save replaces the file.
    """

    def __init__(self, path: Path | str = SCORECARDS_PATH) -> None:
        self.path = Path(path)
        self._cards: dict[tuple[str, str], Scorecard] = {}
        self.was_corrupted: bool = False
        self.was_missing: bool = False
        self._load()

    # ----- load / save -----
    def _load(self) -> None:
        if not self.path.exists():
            self.was_missing = True
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.was_corrupted = True
            return
        if not isinstance(data, dict):
            self.was_corrupted = True
            return
        for entry in data.get("scorecards") or []:
            if not isinstance(entry, dict):
                continue
            try:
                card = Scorecard.from_dict(entry)
            except (TypeError, ValueError):
                continue
            if not card.agent or card.role not in _ROLES:
                continue
            self._cards[(card.agent, card.role)] = card

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        out: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "scorecards": [c.to_dict() for c in self.cards()],
        }
        self.path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        # Once saved we consider the file healthy again.
        self.was_corrupted = False
        self.was_missing = False
        return self.path

    def reset(self) -> None:
        self._cards = {}
        if self.path.exists():
            try:
                self.path.unlink()
            except OSError:
                pass
        self.was_missing = True

    # ----- access -----
    def get_or_create(self, agent: str, role: str) -> Scorecard:
        key = (agent, role)
        if key not in self._cards:
            self._cards[key] = Scorecard(agent=agent, role=role)
        return self._cards[key]

    def cards(self) -> list[Scorecard]:
        return sorted(
            self._cards.values(),
            key=lambda c: (c.agent, _ROLES.index(c.role) if c.role in _ROLES else 99),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "scorecards": [c.to_dict() for c in self.cards()],
        }

    # ----- rendering -----
    def render_text(self) -> str:
        if not self._cards:
            return "Agent scorecards:\n  (no runs recorded yet)"
        lines: list[str] = ["Agent scorecards:", ""]
        for c in self.cards():
            lines.append(f"{c.agent.capitalize()} as {c.role}:")
            if c.role == "reviewer":
                lines.append(f"- Reviews: {c.tasks_attempted}")
                lines.append(f"- Approved: {c.review_approvals}")
                lines.append(f"- Needs changes: {c.review_needs_changes}")
                lines.append(f"- High-risk reviews: {c.high_risk_reviews}")
            elif c.role == "implementer":
                lines.append(f"- Tasks attempted: {c.tasks_attempted}")
                lines.append(f"- Tests passed after implementation: {c.tests_passed_after_agent}")
                lines.append(f"- Tests failed after implementation: {c.tests_failed_after_agent}")
            else:  # planner
                lines.append(f"- Plans attempted: {c.tasks_attempted}")
                lines.append(f"- Plans completed: {c.tasks_completed}")
            lines.append(f"- Failure count: {c.failures}")
            if c.dry_runs_seen:
                lines.append(f"- Dry runs seen: {c.dry_runs_seen}")
            if c.chars_samples:
                lines.append(f"- Average chars sent: {c.average_chars_sent:,}")
            if c.duration_samples:
                lines.append(f"- Average duration: {c.average_duration_ms:,} ms")
            if c.last_used_at:
                lines.append(f"- Last used: {c.last_used_at}")
            lines.append("")
        # Drop trailing blank line.
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Run-dir ingestion
# ---------------------------------------------------------------------------

def _read_json(run_dir: Path, name: str) -> dict | None:
    p = run_dir / name
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, dict) and data.get("placeholder"):
        return None
    return data if isinstance(data, dict) else None


def _test_outcome(run_dir: Path) -> str:
    """Return 'passed' / 'failed' / 'not_run' from test_result.txt."""
    p = run_dir / "test_result.txt"
    if not p.is_file():
        return "not_run"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return "not_run"
    if not text.strip() or text.startswith("(placeholder"):
        return "not_run"
    if "no test command configured" in text:
        return "not_run"
    m = re.search(r"exit_code:\s*(-?\d+)", text)
    if not m:
        return "not_run"
    try:
        return "passed" if int(m.group(1)) == 0 else "failed"
    except ValueError:
        return "not_run"


def _duration_ms(task: dict) -> int | None:
    started = task.get("started_at")
    ended = task.get("ended_at")
    if not started or not ended:
        return None
    try:
        delta = datetime.fromisoformat(str(ended)) - datetime.fromisoformat(str(started))
        return max(0, int(delta.total_seconds() * 1000))
    except (TypeError, ValueError):
        return None


def update_from_run_dir(store: ScorecardStore, run_dir: Path | str) -> bool:
    """Ingest one run directory into the store. Returns True if any
    scorecard was updated."""
    run = Path(run_dir)
    if not run.is_dir():
        return False

    task = _read_json(run, "task.json") or {}
    workflow = task.get("agent_workflow") or {}
    if not isinstance(workflow, dict) or not any(workflow.values()):
        return False

    dry_run = bool(task.get("dry_run"))
    last_used_at = task.get("ended_at") or task.get("started_at")
    duration = _duration_ms(task)

    budget = _read_json(run, "budget.json") or {}
    call_log = budget.get("call_log") if isinstance(budget.get("call_log"), list) else []

    review = _read_json(run, "review.json") or {}
    risk = _read_json(run, "risk_report.json") or {}
    failure = _read_json(run, "failure_report.json") or {}
    outcome = _test_outcome(run)

    risk_level = str(risk.get("risk_level") or "").upper()
    review_status = str(review.get("status") or "").lower()
    failed = bool(failure) and str(failure.get("status") or "").lower() == "failed"

    updated = False
    for role in _ROLES:
        agent = workflow.get(role)
        if not agent:
            continue
        card = store.get_or_create(str(agent), role)
        if last_used_at:
            card.last_used_at = str(last_used_at)

        if dry_run:
            card.dry_runs_seen += 1
            updated = True
            continue

        # Real run: attribute attempt + outcome.
        card.tasks_attempted += 1
        if failed:
            card.failures += 1
        else:
            card.tasks_completed += 1

        # Per-role chars from call_log when available.
        role_chars: list[int] = []
        for entry in call_log:
            if not isinstance(entry, dict):
                continue
            entry_role = str(entry.get("role") or "").lower()
            # The orchestrator names roles like "implementer-revision";
            # match by prefix so revisions count toward the implementer.
            if entry_role == role or entry_role.startswith(role + "-"):
                try:
                    role_chars.append(int(entry.get("prompt_chars") or 0))
                except (TypeError, ValueError):
                    continue
        if role_chars:
            card.total_chars_sent += sum(role_chars)
            card.chars_samples += len(role_chars)

        if duration is not None:
            active = sum(1 for a in workflow.values() if a)
            card.total_duration_ms += duration // max(1, active)
            card.duration_samples += 1

        if role == "reviewer":
            if review_status == "approved":
                card.review_approvals += 1
            elif review_status == "needs_changes":
                card.review_needs_changes += 1
            if risk_level == "HIGH":
                card.high_risk_reviews += 1
        elif role == "implementer":
            if outcome == "passed":
                card.tests_passed_after_agent += 1
            elif outcome == "failed":
                card.tests_failed_after_agent += 1

        updated = True

    return updated
