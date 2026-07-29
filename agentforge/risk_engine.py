"""Local risk scoring + workflow recommendation.

Inspects the task text and (optionally) the set of files that would be sent
to an agent. Returns a structured risk report:

  - level: LOW / MEDIUM / HIGH
  - numeric score 0-100
  - human-readable reasons
  - recommended workflow steps
  - whether review / human approval should be required

Purely local. No LLM, no network, no auth. Used by the orchestrator to:

  - avoid overusing AI on trivial tasks (LOW -> skip planning / review)
  - add guardrails on dangerous changes (HIGH -> human approval before merge)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# --- Scoring tables ----------------------------------------------------
# Each entry contributes to the final 0-100 score. Keywords are matched as
# substrings on the lower-cased task text. Path patterns are matched as
# substrings on POSIX-style relative paths.

_HIGH_KEYWORDS: tuple[str, ...] = (
    "auth", "authentication", "authorize", "authn", "authz",
    "login", "logout", "signin", "sign-in", "signup", "sign-up",
    "password", "passwd", "credential", "token", "jwt", "oauth",
    "permission", "role", "rbac", "admin",
    "security", "vulnerab", "exploit", "csrf", "xss", "sql injection",
    "secret", "api key", "private key",
    "env", "environment variable", ".env",
    "payment", "billing", "invoice", "stripe", "charge", "refund",
    "database", "migration", "schema", "alembic",
    "model", "models.py",
    "production", "prod ", "deploy", "deployment", "release",
    "config", "configuration",
)

_MEDIUM_KEYWORDS: tuple[str, ...] = (
    "refactor", "restructure", "rearchitect",
    "endpoint", "api ", "route", "router", "controller",
    "service", "handler", "middleware",
    "component", "page", "view",
    "state", "store", "redux",
    "dependency", "package", "upgrade", "bump",
    "integration", "webhook",
    "performance", "perf ", "optimi",
    "feature", "add ", "implement", "support for",
)

_LOW_KEYWORDS: tuple[str, ...] = (
    "readme", "docs", "documentation", "docstring",
    "comment", "typo", "wording", "copy ", "text ",
    "style", "css", "tailwind", "format", "formatting",
    "rename label", "rename button", "tooltip",
)

_HIGH_PATH_SUBSTRINGS: tuple[str, ...] = (
    "auth/", "/auth.", "security/", "/security.",
    "migrations/", "/migration.", "/schema.", "schema.sql",
    "models/", "/models.py",
    "config/", "/config.",
    ".env", "secrets", "credentials",
    "payment", "billing",
    "database/", "/database.",
    "deploy", "infra",
)

_MEDIUM_PATH_SUBSTRINGS: tuple[str, ...] = (
    "api/", "/api.", "routes/", "/route.",
    "services/", "/service.",
    "components/", "/component.",
    "package.json", "pyproject.toml", "requirements.txt", "go.mod", "Cargo.toml",
    "controllers/", "handlers/", "middleware/",
    "store/", "reducers/",
)

_LOW_PATH_SUBSTRINGS: tuple[str, ...] = (
    "readme", "README", ".md",
    "docs/", "documentation/",
    "/styles/", ".css", ".scss",
    "i18n/", "locales/", "translations/",
)

# Per-match contributions (capped at score 100).
HIGH_KEYWORD_POINTS = 30
HIGH_PATH_POINTS = 25
MEDIUM_KEYWORD_POINTS = 15
MEDIUM_PATH_POINTS = 12
LOW_KEYWORD_REDUCTION = 8
LOW_PATH_REDUCTION = 6

# Risk level cut-offs.
HIGH_THRESHOLD = 70
MEDIUM_THRESHOLD = 40


@dataclass
class RiskReport:
    risk_level: RiskLevel
    score: int
    reasons: list[str] = field(default_factory=list)
    recommended_workflow: list[str] = field(default_factory=list)
    review_required: bool = False
    tests_required: bool = False
    human_approval_required: bool = False
    keyword_matches: dict[str, list[str]] = field(default_factory=dict)
    path_matches: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "risk_level": self.risk_level.value,
            "score": self.score,
            "reasons": list(self.reasons),
            "recommended_workflow": list(self.recommended_workflow),
            "review_required": self.review_required,
            "tests_required": self.tests_required,
            "human_approval_required": self.human_approval_required,
            "keyword_matches": {k: list(v) for k, v in self.keyword_matches.items()},
            "path_matches": {k: list(v) for k, v in self.path_matches.items()},
        }

    def human_summary(self) -> list[str]:
        lines: list[str] = ["Risk assessment:"]
        lines.append(f"- Level: {self.risk_level.value}")
        lines.append(f"- Score: {self.score}/100")
        if self.reasons:
            lines.append("- Reasons:")
            for r in self.reasons:
                lines.append(f"  - {r}")
        else:
            lines.append("- Reasons: none specific (defaulted by score)")
        if self.recommended_workflow:
            lines.append("- Recommended workflow:")
            for step in self.recommended_workflow:
                lines.append(f"  - {step}")
        return lines


def _match_substrings(haystack: str, needles: Iterable[str]) -> list[str]:
    hits: list[str] = []
    for needle in needles:
        if needle and needle in haystack:
            hits.append(needle.strip())
    # Preserve first-seen order without duplicates.
    seen: set[str] = set()
    deduped: list[str] = []
    for h in hits:
        if h not in seen:
            seen.add(h)
            deduped.append(h)
    return deduped


def _path_matches(paths: Iterable[str], substrings: Iterable[str]) -> list[tuple[str, str]]:
    """Returns list of (substring, path) pairs that matched."""
    out: list[tuple[str, str]] = []
    for path in paths or []:
        lowered = path.lower()
        for sub in substrings:
            if sub.lower() in lowered:
                out.append((sub, path))
    return out


def _score_to_level(score: int) -> RiskLevel:
    if score >= HIGH_THRESHOLD:
        return RiskLevel.HIGH
    if score >= MEDIUM_THRESHOLD:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _recommend_workflow(level: RiskLevel) -> tuple[list[str], bool, bool, bool]:
    """Map a level to (workflow steps, review_required, tests_required, human_approval_required)."""
    if level == RiskLevel.HIGH:
        return (
            [
                "Claude planning required",
                "Claude implementation allowed",
                "Tests strongly recommended",
                "Claude diff review required",
                "Human approval required before merge",
            ],
            True,   # review_required
            True,   # tests_required
            True,   # human_approval_required
        )
    if level == RiskLevel.MEDIUM:
        return (
            [
                "Claude planning recommended",
                "Claude implementation allowed",
                "Tests recommended",
                "Claude diff review recommended",
            ],
            True,
            True,
            False,
        )
    # LOW
    return (
        [
            "Planning step can be skipped",
            "Claude implementation allowed",
            "Optional diff review",
            "No human approval gate required",
        ],
        False,
        False,
        False,
    )


class RiskEngine:
    """Local, deterministic risk scoring + workflow recommendation."""

    def assess(
        self,
        task: str,
        selected_paths: Iterable[str] | None = None,
    ) -> RiskReport:
        text = (task or "").lower()
        paths = list(selected_paths or [])

        score = 0
        reasons: list[str] = []
        keyword_hits: dict[str, list[str]] = {"high": [], "medium": [], "low": []}
        path_hits: dict[str, list[str]] = {"high": [], "medium": [], "low": []}

        # --- HIGH ---
        hi_kw = _match_substrings(text, _HIGH_KEYWORDS)
        if hi_kw:
            score += HIGH_KEYWORD_POINTS * min(len(hi_kw), 3)
            keyword_hits["high"] = hi_kw
            reasons.append(f"Task mentions high-risk topics: {', '.join(hi_kw[:5])}")

        hi_paths = _path_matches(paths, _HIGH_PATH_SUBSTRINGS)
        if hi_paths:
            score += HIGH_PATH_POINTS * min(len(hi_paths), 3)
            path_hits["high"] = sorted({p for _, p in hi_paths})
            substrings = sorted({s for s, _ in hi_paths})
            reasons.append(
                f"Selected file paths include sensitive areas: {', '.join(substrings[:5])}"
            )

        # --- MEDIUM ---
        md_kw = _match_substrings(text, _MEDIUM_KEYWORDS)
        if md_kw:
            score += MEDIUM_KEYWORD_POINTS * min(len(md_kw), 3)
            keyword_hits["medium"] = md_kw
            reasons.append(f"Task mentions medium-risk topics: {', '.join(md_kw[:5])}")

        md_paths = _path_matches(paths, _MEDIUM_PATH_SUBSTRINGS)
        if md_paths:
            score += MEDIUM_PATH_POINTS * min(len(md_paths), 3)
            path_hits["medium"] = sorted({p for _, p in md_paths})

        # --- LOW (reduces score) ---
        # If the task itself flagged a HIGH topic, ignore LOW reductions —
        # editing a README on top of an auth change doesn't make it safer.
        any_high_signal = bool(hi_kw or hi_paths)

        lo_kw = _match_substrings(text, _LOW_KEYWORDS)
        if lo_kw:
            keyword_hits["low"] = lo_kw
            if not any_high_signal:
                score -= LOW_KEYWORD_REDUCTION * min(len(lo_kw), 3)
                reasons.append(f"Task looks like a low-risk change: {', '.join(lo_kw[:5])}")

        lo_paths = _path_matches(paths, _LOW_PATH_SUBSTRINGS)
        if lo_paths:
            path_hits["low"] = sorted({p for _, p in lo_paths})
            if not any_high_signal:
                score -= LOW_PATH_REDUCTION * min(len(lo_paths), 3)

        # Empty/very vague task: nudge it into MEDIUM so we don't skip safety.
        if not text.strip():
            score = max(score, MEDIUM_THRESHOLD)
            reasons.append("Task description was empty — defaulting to MEDIUM")

        # Clamp to [0, 100].
        score = max(0, min(100, score))

        level = _score_to_level(score)
        workflow, review_required, tests_required, approval_required = _recommend_workflow(level)

        if not reasons:
            reasons.append("No specific risk signals matched — defaulted by score")

        return RiskReport(
            risk_level=level,
            score=score,
            reasons=reasons,
            recommended_workflow=workflow,
            review_required=review_required,
            tests_required=tests_required,
            human_approval_required=approval_required,
            keyword_matches=keyword_hits,
            path_matches=path_hits,
        )


def assess_risk(task: str, selected_paths: Iterable[str] | None = None) -> RiskReport:
    """Module-level convenience wrapper."""
    return RiskEngine().assess(task, selected_paths)
