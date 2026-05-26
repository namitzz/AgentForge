"""Merge readiness scoring.

Reads the existing run artifacts under ``.agentforge/runs/<id>/`` and turns
them into a single 0-100 score plus a human-readable verdict so a developer
can make a fast merge / don't-merge decision.

Inputs (all optional — missing or placeholder files are handled gracefully):
  - task.json            (run manifest; checks dry_run)
  - risk_report.json     (risk_level, human_approval_required)
  - policy_report.json   (require_review, require_tests, require_human_approval)
  - security_report.json (blocked_files, prompt_injection_warnings, safe_to_continue)
  - budget.json          (stopped_early)
  - review.json          (status: approved / needs_changes)
  - test_result.txt      (exit_code parsed; "(no test command configured)" counts as not run)
  - failure_report.json  (status: failed -> blocker)

Score levels:
  - 90-100  READY
  - 70-89   READY_WITH_CAUTION
  - 40-69   NEEDS_WORK
  -  0-39   DO_NOT_MERGE

Hard cap: regardless of arithmetic, the score cannot enter READY (>= 90)
if any of these conditions holds:
  - tests failed
  - review status == needs_changes
  - security says safe_to_continue == false
  - failure_report.json exists with status == failed
  - human approval is required but not recorded

No LLM is called. No network. Pure local file reads.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LEVEL_READY               = "READY"
LEVEL_READY_WITH_CAUTION  = "READY_WITH_CAUTION"
LEVEL_NEEDS_WORK          = "NEEDS_WORK"
LEVEL_DO_NOT_MERGE        = "DO_NOT_MERGE"

# Score cut-offs.
_THRESHOLD_READY              = 90
_THRESHOLD_READY_WITH_CAUTION = 70
_THRESHOLD_NEEDS_WORK         = 40

# Deductions (positive numbers — applied via subtraction).
_DEDUCT_FAILURE                = 35
_DEDUCT_NOT_SAFE_TO_CONTINUE   = 30
_DEDUCT_SECRETS_BLOCKED        = 25
_DEDUCT_TESTS_FAILED           = 25
_DEDUCT_TESTS_DID_NOT_RUN      = 15
_DEDUCT_NEEDS_CHANGES          = 20
_DEDUCT_RISK_HIGH              = 15
_DEDUCT_RISK_MEDIUM            =  8
_DEDUCT_APPROVAL_REQUIRED      = 15
_DEDUCT_POLICY_REVIEW_MISSING  = 10
_DEDUCT_POLICY_TESTS_MISSING   = 10
_DEDUCT_BUDGET_STOPPED_EARLY   =  5
_DEDUCT_INJECTION_WARNINGS     =  5


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class MergeReadinessResult:
    score: int
    level: str
    summary: str
    passed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    recommendation: str = ""
    deductions: list[tuple[str, int]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "level": self.level,
            "summary": self.summary,
            "passed": list(self.passed),
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "recommendation": self.recommendation,
            "deductions": [
                {"reason": reason, "points": pts}
                for reason, pts in self.deductions
            ],
        }

    def human_summary(self) -> list[str]:
        lines: list[str] = ["Merge readiness:"]
        lines.append(f"- Score: {self.score}/100")
        lines.append(f"- Level: {self.level}")
        lines.append(f"- Recommendation: {self.recommendation}")
        lines.append("")
        if self.passed:
            lines.append("Passed:")
            for item in self.passed:
                lines.append(f"  - {item}")
            lines.append("")
        if self.warnings:
            lines.append("Warnings:")
            for item in self.warnings:
                lines.append(f"  - {item}")
            lines.append("")
        if self.blockers:
            lines.append("Blockers:")
            for item in self.blockers:
                lines.append(f"  - {item}")
        return lines


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class MergeReadinessEngine:
    """Reads a single run directory and computes a merge readiness verdict."""

    def __init__(self, run_dir: Path | str) -> None:
        self.run_dir = Path(run_dir)
        if not self.run_dir.is_dir():
            raise NotADirectoryError(f"not a run directory: {self.run_dir}")
        self._json = self._load_json_artifacts()
        self._test_text = self._load_test_text()

    # --- artifact loading --------------------------------------------------
    _JSON_NAMES: tuple[str, ...] = (
        "task.json",
        "risk_report.json",
        "policy_report.json",
        "security_report.json",
        "budget.json",
        "review.json",
        "failure_report.json",
    )

    def _load_json_artifacts(self) -> dict[str, dict[str, Any] | None]:
        out: dict[str, dict[str, Any] | None] = {}
        for name in self._JSON_NAMES:
            p = self.run_dir / name
            if not p.exists() or not p.is_file():
                out[name] = None
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                out[name] = None
                continue
            # Placeholder artifacts ({"placeholder": true, ...}) are
            # treated as "this file was not really produced".
            if isinstance(data, dict) and data.get("placeholder"):
                out[name] = None
            else:
                out[name] = data
        return out

    def _load_test_text(self) -> str | None:
        p = self.run_dir / "test_result.txt"
        if not p.exists() or not p.is_file():
            return None
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            return None
        if not text.strip() or text.startswith("(placeholder"):
            return None
        return text

    # --- signal probes -----------------------------------------------------
    @property
    def _failure(self) -> dict | None:
        return self._json.get("failure_report.json")

    @property
    def _security(self) -> dict | None:
        return self._json.get("security_report.json")

    @property
    def _policy(self) -> dict | None:
        return self._json.get("policy_report.json")

    @property
    def _risk(self) -> dict | None:
        return self._json.get("risk_report.json")

    @property
    def _review(self) -> dict | None:
        return self._json.get("review.json")

    @property
    def _budget(self) -> dict | None:
        return self._json.get("budget.json")

    @property
    def _task(self) -> dict | None:
        return self._json.get("task.json")

    def _dry_run(self) -> bool:
        return bool((self._task or {}).get("dry_run"))

    def _test_outcome(self) -> str:
        """Returns 'passed', 'failed', or 'not_run'."""
        text = self._test_text
        if text is None:
            return "not_run"
        if "no test command configured" in text:
            return "not_run"
        m = re.search(r"exit_code:\s*(-?\d+)", text)
        if m is None:
            # Old or non-standard format — be conservative.
            return "not_run"
        try:
            code = int(m.group(1))
        except ValueError:
            return "not_run"
        return "passed" if code == 0 else "failed"

    def _approval_required(self) -> bool:
        if (self._policy or {}).get("require_human_approval"):
            return True
        if (self._risk or {}).get("human_approval_required"):
            return True
        return False

    # --- scoring -----------------------------------------------------------
    def calculate(self) -> MergeReadinessResult:
        score = 100
        passed: list[str] = []
        warnings: list[str] = []
        blockers: list[str] = []
        deductions: list[tuple[str, int]] = []
        never_ready = False

        def deduct(reason: str, points: int) -> None:
            nonlocal score
            score -= points
            deductions.append((reason, points))

        # --- failure_report.json ---
        if self._failure and self._failure.get("status") == "failed":
            deduct("Run failed (failure_report.json present)", _DEDUCT_FAILURE)
            blockers.append(
                f"Run failed: {self._failure.get('message') or 'see failure_report.json'}"
            )
            never_ready = True

        # --- security ---
        security = self._security
        if security is not None:
            if security.get("safe_to_continue") is False:
                deduct("Security says safe_to_continue=false", _DEDUCT_NOT_SAFE_TO_CONTINUE)
                blockers.append(
                    "Security check refused to continue (see security_report.json)"
                )
                never_ready = True

            blocked = security.get("blocked_files") or []
            if blocked:
                deduct(f"{len(blocked)} secret file(s) blocked", _DEDUCT_SECRETS_BLOCKED)
                warnings.append(
                    f"{len(blocked)} secret-bearing file(s) were dropped from context"
                )
            else:
                passed.append("No secret files were sent")

            inj = security.get("prompt_injection_warnings") or []
            if inj:
                deduct(f"{len(inj)} prompt-injection warning(s)", _DEDUCT_INJECTION_WARNINGS)
                warnings.append(
                    f"{len(inj)} prompt-injection warning(s) in selected files"
                )
        else:
            warnings.append("Security report missing")

        # --- tests ---
        outcome = self._test_outcome()
        policy = self._policy or {}
        if outcome == "failed":
            deduct("Tests failed", _DEDUCT_TESTS_FAILED)
            blockers.append("Tests failed")
            never_ready = True
        elif outcome == "not_run":
            deduct("Tests did not run", _DEDUCT_TESTS_DID_NOT_RUN)
            if policy.get("require_tests"):
                deduct("Policy requires tests but they did not run", _DEDUCT_POLICY_TESTS_MISSING)
                blockers.append("Policy requires tests, but tests did not run")
            else:
                warnings.append("Tests did not run")
        else:  # passed
            passed.append("Tests passed")

        # --- review ---
        review = self._review
        if review is not None:
            status = (review.get("status") or "").lower()
            if status == "needs_changes":
                deduct("Reviewer requested changes", _DEDUCT_NEEDS_CHANGES)
                blockers.append("Reviewer requested changes")
                never_ready = True
            elif status == "approved":
                passed.append("Diff review completed and approved")
            else:
                warnings.append(f"Review status is '{status or 'unknown'}'")
        else:
            if policy.get("require_review"):
                deduct(
                    "Policy requires review but it did not run",
                    _DEDUCT_POLICY_REVIEW_MISSING,
                )
                warnings.append("Policy requires review, but no review was recorded")
            # Else: review wasn't required — silent.

        # --- risk ---
        risk = self._risk
        if risk is not None:
            level = (risk.get("risk_level") or "").upper()
            if level == "HIGH":
                deduct("HIGH risk task", _DEDUCT_RISK_HIGH)
                warnings.append("Task classified as HIGH risk")
            elif level == "MEDIUM":
                deduct("MEDIUM risk task", _DEDUCT_RISK_MEDIUM)
                warnings.append("Task classified as MEDIUM risk")
            passed.append("Risk report generated")
        else:
            warnings.append("Risk report missing")

        # --- policy ---
        if policy:
            passed.append("Policy checks completed")
        else:
            warnings.append("Policy report missing")

        # --- human approval ---
        # MVP: we don't yet have an "approval recorded" artifact. If approval
        # is required by either policy or risk, treat it as outstanding.
        if self._approval_required():
            deduct("Human approval required", _DEDUCT_APPROVAL_REQUIRED)
            warnings.append("Human approval required before merge")
            never_ready = True

        # --- budget stopped early ---
        if (self._budget or {}).get("stopped_early"):
            deduct("Run stopped early", _DEDUCT_BUDGET_STOPPED_EARLY)
            reason = (self._budget or {}).get("stop_reason") or "(no reason recorded)"
            warnings.append(f"Run stopped early ({reason})")

        # --- dry-run note (not a deduction; an explainer) ---
        if self._dry_run():
            warnings.append(
                "This was a --dry-run preview; tests / review / edits did not actually execute"
            )

        # --- clamp + decide level ---
        score = max(0, min(100, score))

        # Hard cap: never-READY conditions force score below the READY band.
        if never_ready and score >= _THRESHOLD_READY:
            score = _THRESHOLD_READY - 1  # 89

        level = _level_for(score)
        summary = _summary_for(level, blockers, warnings, security, risk, policy)
        recommendation = _recommendation_for(level, blockers, warnings)

        return MergeReadinessResult(
            score=score,
            level=level,
            summary=summary,
            passed=passed,
            warnings=warnings,
            blockers=blockers,
            recommendation=recommendation,
            deductions=deductions,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _level_for(score: int) -> str:
    if score >= _THRESHOLD_READY:
        return LEVEL_READY
    if score >= _THRESHOLD_READY_WITH_CAUTION:
        return LEVEL_READY_WITH_CAUTION
    if score >= _THRESHOLD_NEEDS_WORK:
        return LEVEL_NEEDS_WORK
    return LEVEL_DO_NOT_MERGE


def _summary_for(
    level: str,
    blockers: list[str],
    warnings: list[str],
    security: dict | None,
    risk: dict | None,
    policy: dict | None,
) -> str:
    if level == LEVEL_READY:
        return "All core gates passed. Safe to merge."

    auth_touched = bool(
        policy
        and any(
            "auth" in (h.get("path") or "").lower()
            for h in (policy.get("matched_files") or [])
        )
    )
    risk_level = (risk or {}).get("risk_level", "")

    if level == LEVEL_READY_WITH_CAUTION:
        if auth_touched:
            return (
                "The change passed core checks but requires human approval "
                "because it touches auth-related files."
            )
        if risk_level == "HIGH":
            return "Core checks passed but this is a HIGH risk task — review carefully."
        return "Core checks passed, but the run has warnings worth reviewing."

    if level == LEVEL_NEEDS_WORK:
        return (
            "Several issues need attention before merging: "
            + "; ".join(blockers or warnings[:2] or ["see warnings/blockers"])
        )

    # DO_NOT_MERGE
    return (
        "Critical issues prevent merge: "
        + "; ".join(blockers or ["see blockers"])
    )


def _recommendation_for(level: str, blockers: list[str], warnings: list[str]) -> str:
    if level == LEVEL_READY:
        return "Ready to merge."
    if level == LEVEL_READY_WITH_CAUTION:
        # Pick the most actionable warning/blocker for the headline.
        for source in (blockers, warnings):
            for item in source:
                low = item.lower()
                if "approval" in low:
                    return "Do not merge until human approval is recorded."
                if "test" in low and ("not run" in low or "failed" in low):
                    return "Do not merge until tests pass."
        return "Inspect warnings before merging."
    if level == LEVEL_NEEDS_WORK:
        return "Address the listed blockers and re-run."
    return "Do not merge. Investigate failures before retrying."


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

def calculate_for_run(run_dir: Path | str) -> MergeReadinessResult:
    """Compute readiness for a run directory."""
    return MergeReadinessEngine(run_dir).calculate()


MERGE_READINESS_ARTIFACT_NAME: str = "merge_readiness.json"
