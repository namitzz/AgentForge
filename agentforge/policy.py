"""Policy engine.

Loads governance rules from config.yaml and evaluates them against the set of
files an agent would touch or see. Decisions flow back into the orchestrator
so it can:

  - drop blocked files before they're sent to any agent
  - force review on for sensitive paths even when the classifier wouldn't
  - force tests on for sensitive paths
  - require human approval before continuing a run

Policies are purely declarative. No LLM is involved.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class Policy:
    name: str
    match: list[str] = field(default_factory=list)
    block: list[str] = field(default_factory=list)
    require_review: bool = False
    require_tests: bool = False
    require_human_approval: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Policy":
        return cls(
            name=str(data.get("name") or "unnamed policy"),
            match=list(data.get("match") or []),
            block=list(data.get("block") or []),
            require_review=bool(data.get("require_review", False)),
            require_tests=bool(data.get("require_tests", False)),
            require_human_approval=bool(data.get("require_human_approval", False)),
        )


@dataclass
class PolicyHit:
    policy: str
    path: str
    reason: str   # "match" | "block"


@dataclass
class PolicyReport:
    blocked_files: list[PolicyHit] = field(default_factory=list)
    matched_files: list[PolicyHit] = field(default_factory=list)
    require_review: bool = False
    require_tests: bool = False
    require_human_approval: bool = False
    triggering_policies: list[str] = field(default_factory=list)

    @property
    def blocked_paths(self) -> list[str]:
        return sorted({h.path for h in self.blocked_files})

    def to_dict(self) -> dict:
        return {
            "blocked_files": [
                {"policy": h.policy, "path": h.path, "reason": h.reason}
                for h in self.blocked_files
            ],
            "matched_files": [
                {"policy": h.policy, "path": h.path, "reason": h.reason}
                for h in self.matched_files
            ],
            "require_review": self.require_review,
            "require_tests": self.require_tests,
            "require_human_approval": self.require_human_approval,
            "triggering_policies": self.triggering_policies,
        }

    def human_summary(self) -> list[str]:
        lines: list[str] = ["Policy checks:"]
        if self.blocked_files:
            lines.append(
                f"- Blocked {len(self.blocked_paths)} sensitive file(s): "
                + ", ".join(self.blocked_paths)
            )
        else:
            lines.append("- Blocked sensitive files: none")
        lines.append(f"- Review required: {'yes' if self.require_review else 'no'}")
        lines.append(f"- Tests required: {'yes' if self.require_tests else 'no'}")
        lines.append(
            f"- Human approval required: {'yes' if self.require_human_approval else 'no'}"
        )
        if self.triggering_policies:
            lines.append("- Triggering policies: " + ", ".join(self.triggering_policies))
        return lines


def _match_path(pattern: str, path: str) -> bool:
    """Glob-style match. Supports ``**`` for any-depth, plus normal fnmatch."""
    if pattern == path:
        return True
    if fnmatch.fnmatch(path, pattern):
        return True
    # Treat ``**/x`` as "x at any depth".
    if pattern.startswith("**/") and fnmatch.fnmatch(path, pattern[3:]):
        return True
    if pattern.startswith("**/"):
        suffix = pattern[3:]
        parts = path.split("/")
        for i in range(len(parts)):
            if fnmatch.fnmatch("/".join(parts[i:]), suffix):
                return True
    # Treat ``dir/**`` as "anything under dir/".
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        if path == prefix or path.startswith(prefix + "/"):
            return True
    # Bare filename match.
    if "/" not in pattern and fnmatch.fnmatch(path.split("/")[-1], pattern):
        return True
    return False


class PolicyEngine:
    """Evaluates declarative policies against a set of file paths."""

    def __init__(self, policies: Iterable[Policy] | None = None) -> None:
        self.policies: list[Policy] = list(policies or [])

    @classmethod
    def from_config_list(cls, raw: list[dict[str, Any]] | None) -> "PolicyEngine":
        return cls([Policy.from_dict(d) for d in (raw or [])])

    def evaluate(self, paths: Iterable[str]) -> PolicyReport:
        report = PolicyReport()
        triggered: set[str] = set()

        for policy in self.policies:
            policy_matched_anything = False
            for path in paths:
                for pat in policy.block:
                    if _match_path(pat, path):
                        report.blocked_files.append(
                            PolicyHit(policy=policy.name, path=path, reason="block")
                        )
                        policy_matched_anything = True
                for pat in policy.match:
                    if _match_path(pat, path):
                        report.matched_files.append(
                            PolicyHit(policy=policy.name, path=path, reason="match")
                        )
                        policy_matched_anything = True

            if policy_matched_anything:
                triggered.add(policy.name)
                if policy.require_review:
                    report.require_review = True
                if policy.require_tests:
                    report.require_tests = True
                if policy.require_human_approval:
                    report.require_human_approval = True

        report.triggering_policies = sorted(triggered)
        return report

    def filter_blocked(self, paths: Iterable[str]) -> tuple[list[str], list[PolicyHit]]:
        """Return (kept_paths, blocked_hits). ``block`` patterns are checked across all policies."""
        kept: list[str] = []
        blocked: list[PolicyHit] = []
        for path in paths:
            hit: PolicyHit | None = None
            for policy in self.policies:
                for pat in policy.block:
                    if _match_path(pat, path):
                        hit = PolicyHit(policy=policy.name, path=path, reason="block")
                        break
                if hit:
                    break
            if hit:
                blocked.append(hit)
            else:
                kept.append(path)
        return kept, blocked
