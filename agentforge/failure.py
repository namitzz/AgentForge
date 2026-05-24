"""Run status model + structured failure reporting.

When something goes wrong AgentForge should stop safely, write a clear
``failure_report.json`` to the run directory, and surface a structured
"Reason / Suggested fix" block to the operator. This module centralises
all of that so the orchestrator and CLI don't have to ad-hoc the format.

Status model:
  - ``planned``            – not used at rest yet; reserved for future
                             scheduled / queued runs.
  - ``dry_run_completed``  – ``--dry-run`` finished without calling an agent.
  - ``completed``          – full pipeline ran end to end.
  - ``stopped_early``      – clean stop before completion (e.g. tests
                             passed and review wasn't required, or budget
                             cap hit cleanly).
  - ``failed``             – an error prevented the run from completing.

Error categories track the *kind* of failure so the suggested-fix table
can give the operator something concrete to do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class RunStatus(str, Enum):
    PLANNED = "planned"
    DRY_RUN_COMPLETED = "dry_run_completed"
    COMPLETED = "completed"
    STOPPED_EARLY = "stopped_early"
    FAILED = "failed"


class ErrorCategory(str, Enum):
    CONFIG_ERROR = "CONFIG_ERROR"
    AGENT_ERROR = "AGENT_ERROR"
    GIT_ERROR = "GIT_ERROR"
    TEST_ERROR = "TEST_ERROR"
    BUDGET_ERROR = "BUDGET_ERROR"
    POLICY_ERROR = "POLICY_ERROR"
    SECURITY_ERROR = "SECURITY_ERROR"
    ARTIFACT_ERROR = "ARTIFACT_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


# Per-category guidance shown to the operator.
SUGGESTED_FIXES: dict[ErrorCategory, list[str]] = {
    ErrorCategory.AGENT_ERROR: [
        "Install the missing agent CLI (claude / codex)",
        "Or update claude_command / codex_command in config.yaml",
        "Or run again with --dry-run to preview without calling an agent",
    ],
    ErrorCategory.BUDGET_ERROR: [
        "Raise max_ai_calls_per_run / max_total_chars in config.yaml",
        "Or narrow the task / reduce max_files_sent",
        "Inspect .agentforge/runs/<latest>/budget.json for the actual usage",
    ],
    ErrorCategory.GIT_ERROR: [
        "Run inside a git repository (`git init` if you haven't)",
        "Commit or stash uncommitted changes before retrying",
        "If a branch name conflicts, delete or rename the existing branch",
    ],
    ErrorCategory.TEST_ERROR: [
        "Update default_test_command in config.yaml",
        "Inspect .agentforge/runs/<latest>/test_result.txt",
        "If the command was refused, see .agentforge/runs/<latest>/security_report.json",
    ],
    ErrorCategory.CONFIG_ERROR: [
        "Run `agentforge init` to write a starter config.yaml",
        "Or pass --config /path/to/config.yaml",
        "Verify the YAML parses (`python -c 'import yaml; yaml.safe_load(open(\"config.yaml\"))'`)",
    ],
    ErrorCategory.POLICY_ERROR: [
        "Inspect .agentforge/runs/<latest>/policy_report.json",
        "Adjust the policies block in config.yaml",
    ],
    ErrorCategory.SECURITY_ERROR: [
        "Inspect .agentforge/runs/<latest>/security_report.json",
        "Fix the offending file or update default_test_command",
        "If a secret leaked into a file, rotate it before re-running",
    ],
    ErrorCategory.ARTIFACT_ERROR: [
        "Check disk space and write permissions on .agentforge/runs/",
        "Re-run from a working directory you have write access to",
    ],
    ErrorCategory.UNKNOWN_ERROR: [
        "Re-run with --dry-run to isolate which step is failing",
        "Open an issue with the failure_report.json contents (redact sensitive paths)",
    ],
}


# Categories where retrying with the same config will hit the same error;
# the operator has to do something first.
_NEEDS_USER_ACTION: set[ErrorCategory] = {
    ErrorCategory.AGENT_ERROR,
    ErrorCategory.CONFIG_ERROR,
    ErrorCategory.SECURITY_ERROR,
    ErrorCategory.POLICY_ERROR,
    ErrorCategory.TEST_ERROR,
}


def categorize_message(message: str) -> ErrorCategory:
    """Pattern-classify an aborted-reason string when no exception is available.

    Many soft failures bubble out as ``RunResult.aborted_reason`` strings,
    not as raised exceptions (e.g. the agent CLI returned exit 127, so
    ``CLIAgent.run`` packaged ``AgentUnavailable`` into an ``AgentResponse``
    rather than raising it). This helper recovers the category from the
    message text so the operator gets the right "Suggested fix" block.
    """
    text = (message or "").lower()
    if not text:
        return ErrorCategory.UNKNOWN_ERROR
    # Agent-side failures.
    if any(s in text for s in (
        "not found on path",
        "agent command is empty",
        "empty response",
        "timed out after",
        "planner exit",
        "implementer exit",
        "reviewer exit",
    )):
        return ErrorCategory.AGENT_ERROR
    # Budget.
    if any(s in text for s in (
        "ai call budget exhausted",
        "character budget would be exceeded",
        "review loop budget exhausted",
        "planned ai calls",
        "exceeds total cap",
    )):
        return ErrorCategory.BUDGET_ERROR
    # Git.
    if any(s in text for s in (
        "not a git repo",
        "uncommitted changes",
        "branch ",
        "could not find a base branch",
        "git ",
    )):
        return ErrorCategory.GIT_ERROR
    # Security / refused command.
    if any(s in text for s in (
        "refused",
        "dangerous pattern",
        "secret pattern",
        "blocked by security",
    )):
        return ErrorCategory.SECURITY_ERROR
    # Config.
    if any(s in text for s in ("config.yaml", "configuration")):
        return ErrorCategory.CONFIG_ERROR
    if "human approval declined" in text:
        return ErrorCategory.POLICY_ERROR
    return ErrorCategory.UNKNOWN_ERROR


def categorize_exception(exc: BaseException | None) -> ErrorCategory:
    """Best-effort mapping. Uses class name to avoid circular imports."""
    if exc is None:
        return ErrorCategory.UNKNOWN_ERROR
    name = type(exc).__name__
    if name == "AgentUnavailable":
        return ErrorCategory.AGENT_ERROR
    if name == "BudgetExceeded":
        return ErrorCategory.BUDGET_ERROR
    if name == "GitError":
        return ErrorCategory.GIT_ERROR
    if isinstance(exc, KeyboardInterrupt):
        return ErrorCategory.UNKNOWN_ERROR
    if isinstance(exc, FileNotFoundError):
        return ErrorCategory.CONFIG_ERROR
    if isinstance(exc, (PermissionError, IsADirectoryError)):
        return ErrorCategory.ARTIFACT_ERROR
    if isinstance(exc, OSError):
        return ErrorCategory.ARTIFACT_ERROR
    return ErrorCategory.UNKNOWN_ERROR


@dataclass
class FailureReport:
    status: str
    error_category: str
    message: str
    step_failed: str | None
    safe_to_retry: bool
    suggested_fix: list[str] = field(default_factory=list)
    partial_artifacts_written: list[str] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "error_category": self.error_category,
            "message": self.message,
            "step_failed": self.step_failed,
            "safe_to_retry": self.safe_to_retry,
            "suggested_fix": list(self.suggested_fix),
            "partial_artifacts_written": list(self.partial_artifacts_written),
            "timestamp": self.timestamp,
        }

    def human_summary(self) -> list[str]:
        lines = ["AgentForge stopped safely."]
        lines.append(f"Reason: {self.message}")
        if self.suggested_fix:
            lines.append("Suggested fix:")
            for fix in self.suggested_fix:
                lines.append(f"  - {fix}")
        if not self.safe_to_retry:
            lines.append("(Retrying without changes will hit the same error.)")
        return lines


def build_failure_report(
    *,
    status: RunStatus,
    exception: BaseException | None,
    message: str,
    step_failed: str | None,
    partial_artifacts: list[str],
    error_category: ErrorCategory | None = None,
) -> FailureReport:
    if error_category is not None:
        category = error_category
    elif exception is not None:
        category = categorize_exception(exception)
    else:
        # No exception available — fall back to message-based pattern match.
        category = categorize_message(message)
    return FailureReport(
        status=status.value,
        error_category=category.value,
        message=message,
        step_failed=step_failed,
        safe_to_retry=category not in _NEEDS_USER_ACTION,
        suggested_fix=list(SUGGESTED_FIXES.get(category, SUGGESTED_FIXES[ErrorCategory.UNKNOWN_ERROR])),
        partial_artifacts_written=partial_artifacts,
    )
