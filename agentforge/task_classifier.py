"""Lightweight, deterministic task classification.

No LLM used — pattern match the user's task description into a category that
drives agent routing. Cheap and good-enough for the MVP.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TaskType(str, Enum):
    BUG_FIX = "bug_fix"
    REFACTOR = "refactor"
    FEATURE = "feature"
    TESTS = "tests"
    DOCS = "docs"
    SECURITY = "security"
    UNKNOWN = "unknown"


@dataclass
class Classification:
    task_type: TaskType
    confidence: float            # 0.0 - 1.0, rough heuristic
    keywords_matched: list[str]
    routing: "Routing"

    def to_dict(self) -> dict:
        return {
            "task_type": self.task_type.value,
            "confidence": self.confidence,
            "keywords_matched": self.keywords_matched,
            "routing": {
                "planner": self.routing.planner,
                "implementer": self.routing.implementer,
                "reviewer": self.routing.reviewer,
                "require_review": self.routing.require_review,
            },
        }


@dataclass
class Routing:
    planner: str | None
    implementer: str | None
    reviewer: str | None
    require_review: bool


# Keyword sets in priority order. First strong match wins.
_KEYWORDS: list[tuple[TaskType, list[str]]] = [
    (TaskType.SECURITY, ["security", "vulnerab", "auth ", "authn", "authz", "xss", "csrf", "sql injection", "secret", "credential"]),
    (TaskType.REFACTOR, ["refactor", "restructure", "clean up", "cleanup", "rearchitect", "rename module"]),
    (TaskType.BUG_FIX, ["bug", "fix ", "broken", "error", "crash", "regression", "issue ", "fails", "failing", "incorrect"]),
    (TaskType.TESTS,   ["test", "unit test", "pytest", "coverage", "spec ", "specs"]),
    (TaskType.DOCS,    ["doc", "docs", "readme", "comment", "documentation", "docstring"]),
    (TaskType.FEATURE, ["add ", "implement", "feature", "support for", "new "]),
]


def _route_for(task_type: TaskType, defaults: tuple[str, str, str]) -> Routing:
    """Map a task type to an agent routing decision."""
    planner_default, implementer_default, reviewer_default = defaults
    if task_type in (TaskType.REFACTOR, TaskType.SECURITY, TaskType.UNKNOWN):
        return Routing(
            planner=planner_default,
            implementer=implementer_default,
            reviewer=reviewer_default,
            require_review=True,
        )
    if task_type == TaskType.BUG_FIX:
        return Routing(
            planner=None,
            implementer=implementer_default,
            reviewer=reviewer_default,
            require_review=False,
        )
    if task_type == TaskType.TESTS:
        return Routing(
            planner=None,
            implementer=implementer_default,
            reviewer=None,
            require_review=False,
        )
    if task_type == TaskType.DOCS:
        return Routing(
            planner=None,
            implementer=planner_default,
            reviewer=None,
            require_review=False,
        )
    # FEATURE
    return Routing(
        planner=planner_default,
        implementer=implementer_default,
        reviewer=reviewer_default,
        require_review=True,
    )


def classify(task: str, defaults: tuple[str, str, str] = ("claude", "codex", "claude")) -> Classification:
    """Classify a task and produce an agent routing plan."""
    text = (task or "").lower()
    if not text.strip():
        routing = _route_for(TaskType.UNKNOWN, defaults)
        return Classification(TaskType.UNKNOWN, 0.0, [], routing)

    for task_type, keywords in _KEYWORDS:
        hits = [k for k in keywords if k in text]
        if hits:
            confidence = min(1.0, 0.4 + 0.2 * len(hits))
            return Classification(task_type, confidence, hits, _route_for(task_type, defaults))

    return Classification(TaskType.UNKNOWN, 0.2, [], _route_for(TaskType.UNKNOWN, defaults))
