"""Deterministic task classifier with weighted feature scoring.

Replaces brittle ``substring in text`` matching with:

  - **Word-boundary, stem-aware feature matching.** Single-word features get
    common English suffix variants (``fix`` matches ``fix / fixes / fixed /
    fixing``) anchored on word boundaries (``\bfix\b…``). Multi-word phrases
    match literally with flexible whitespace.
  - **Per-type weighted signals** (strong / medium / weak). A "strong"
    feature like ``fix bug`` or ``refactor`` carries more weight than a
    "medium" feature like ``bug`` alone.
  - **Multi-intent detection.** Secondary intents (>= half the top score,
    above an absolute floor) are surfaced on the returned ``Classification``
    so the orchestrator can act on them without re-running the classifier.
  - **Deterministic tie-breaking** by safety-conservative priority order
    (SECURITY > BUG_FIX > REFACTOR > TESTS > DOCS > FEATURE).
  - **Calibrated confidence** from top-score magnitude + margin to the
    runner-up + presence of a strong-feature match.

No LLM is involved. All work is local, deterministic, and explainable —
``keywords_matched`` lists every feature label that fired, and
``secondary_intents`` shows what else was detected.

Why this is safer than substring-first matching:

  - ``test`` no longer matches ``biggest`` (word boundaries).
  - ``api`` no longer matches ``rapid`` (word boundaries).
  - ``auth`` no longer accidentally matches every word containing the letters
    a-u-t-h; we list each variant explicitly (``auth``, ``authn``, ``authz``,
    ``authentication``, ``authorization``).
  - A weak hit like ``new`` no longer outranks a strong hit like
    ``refactor`` — scoring decides, not iteration order.
  - Ambiguous prompts get lower confidence so downstream consumers can
    decide whether to ask a human, not because of a coincidental hit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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
class Routing:
    planner: str | None
    implementer: str | None
    reviewer: str | None
    require_review: bool


@dataclass
class Classification:
    task_type: TaskType
    confidence: float
    keywords_matched: list[str]
    routing: "Routing"
    secondary_intents: list[TaskType] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "task_type": self.task_type.value,
            "confidence": self.confidence,
            "keywords_matched": list(self.keywords_matched),
            "secondary_intents": [t.value for t in self.secondary_intents],
            "routing": {
                "planner": self.routing.planner,
                "implementer": self.routing.implementer,
                "reviewer": self.routing.reviewer,
                "require_review": self.routing.require_review,
            },
        }


# ---------------------------------------------------------------------------
# Scoring constants
# ---------------------------------------------------------------------------

WEIGHT_STRONG: float = 3.0
WEIGHT_MEDIUM: float = 1.5
WEIGHT_WEAK:   float = 0.5

# Confidence calibration.
_CONFIDENCE_BASE = 0.2
_CONFIDENCE_PER_POINT = 1.0 / 6.0     # full credit at top_score >= 4.8
_CONFIDENCE_AMBIGUOUS_PENALTY = 0.15  # subtracted when top - runner-up < 0.5
_CONFIDENCE_STRONG_FLOOR = 0.5        # if a strong feature fired, never below
_CONFIDENCE_CAP = 0.95
_CONFIDENCE_ANY_MATCH_FLOOR = 0.30    # if anything matched, never below

# Multi-intent reporting.
_SECONDARY_RATIO = 0.5                # >= half the top score …
_SECONDARY_FLOOR = 1.5                # … but also above an absolute floor

# Deterministic tie-break priority (safety-conservative first).
_TIE_BREAK_ORDER: tuple[TaskType, ...] = (
    TaskType.SECURITY,
    TaskType.BUG_FIX,
    TaskType.REFACTOR,
    TaskType.TESTS,
    TaskType.DOCS,
    TaskType.FEATURE,
)
_TIE_BREAK_INDEX = {tt: i for i, tt in enumerate(_TIE_BREAK_ORDER)}


# ---------------------------------------------------------------------------
# Feature compilation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Feature:
    pattern: re.Pattern[str]
    label: str
    weight: float


def _compile(text: str) -> re.Pattern[str]:
    """Build a regex for a feature. Single words get common English suffix
    variants (s, es, ed, ing). Phrases match literally with flexible
    whitespace. All matches are case-insensitive and word-bounded."""
    if " " in text:
        # Multi-word phrase. Escape, then allow \s+ between tokens.
        escaped = re.escape(text).replace(r"\ ", r"\s+")
        return re.compile(rf"\b{escaped}\b", re.IGNORECASE)
    return re.compile(
        rf"\b{re.escape(text)}(?:s|es|ed|ing)?\b",
        re.IGNORECASE,
    )


def _features(
    *,
    strong: tuple[str, ...] = (),
    medium: tuple[str, ...] = (),
    weak: tuple[str, ...] = (),
) -> list[_Feature]:
    out: list[_Feature] = []
    for s in strong:
        out.append(_Feature(_compile(s), s, WEIGHT_STRONG))
    for m in medium:
        out.append(_Feature(_compile(m), m, WEIGHT_MEDIUM))
    for w in weak:
        out.append(_Feature(_compile(w), w, WEIGHT_WEAK))
    return out


# ---------------------------------------------------------------------------
# Feature tables (compiled once at module load)
# ---------------------------------------------------------------------------
#
# Curated. Each list is short on purpose — false positives are worse than
# false negatives at the classifier layer because the orchestrator can
# fall back to UNKNOWN safely (full pipeline + review required).

_FEATURES: dict[TaskType, list[_Feature]] = {
    TaskType.SECURITY: _features(
        strong=(
            # Concrete vulnerability classes / safety-critical phrases.
            "security vulnerability", "auth bypass", "auth flaw",
            "sql injection", "csrf", "xss", "privilege escalation",
            "rce", "ssrf", "credential leak", "secret leak",
            # Bug-fixes on the auth surface count as security-flavoured.
            "fix login", "fix logout", "fix authentication", "fix auth",
            "fix password", "fix token", "fix permission",
            "broken login", "broken auth", "broken authentication",
        ),
        medium=(
            "auth", "authn", "authz",
            "authentication", "authorization", "authorize",
            "login", "logout", "signin", "sign-in",
            "password", "passwd", "credential",
            "token", "jwt", "oauth",
            "permission", "role", "admin", "rbac",
            "secret", "vulnerability", "vulnerabilities", "exploit",
        ),
        weak=("session", "cookie"),
    ),
    TaskType.BUG_FIX: _features(
        strong=(
            "fix bug", "fix the bug", "fix a bug",
            "off-by-one", "off by one", "regression",
            "stack trace", "null pointer", "race condition",
            "memory leak", "infinite loop",
        ),
        medium=(
            "bug", "fix", "broken", "crash",
            "incorrect", "fail", "error", "exception",
        ),
        weak=("issue", "problem", "wrong"),
    ),
    TaskType.REFACTOR: _features(
        strong=(
            "refactor", "restructure", "rearchitect",
            "rename module", "extract method", "split module",
            "merge module", "consolidate module",
        ),
        medium=(
            "rename", "cleanup", "simplify", "rewrite", "reorganize",
        ),
        weak=("clean", "tidy", "factor"),
    ),
    TaskType.TESTS: _features(
        strong=(
            "add tests", "add test", "write tests", "write test",
            "unit tests", "integration tests", "test coverage",
            "missing tests", "more tests", "improve test coverage",
        ),
        medium=("test", "spec", "pytest", "coverage"),
        weak=("assertion", "mock", "fixture"),
    ),
    TaskType.DOCS: _features(
        strong=(
            "update readme", "update the readme",
            "write docs", "write documentation", "improve docs",
            "add docstring", "add docstrings",
            "fix typo", "fix typos", "fix the typo",
        ),
        medium=(
            "readme", "documentation", "docstring", "doc",
            "comment", "typo",
        ),
        weak=("wording", "copy"),
    ),
    TaskType.FEATURE: _features(
        strong=(
            "add feature", "implement feature", "new feature",
            "build the", "build a",
        ),
        medium=(
            "add", "implement", "introduce", "create", "support",
            "endpoint", "feature",
        ),
        weak=("new",),
    ),
}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_type(
    text: str,
    features: list[_Feature],
) -> tuple[float, list[str], bool]:
    """Score a task type against ``text``.

    Returns (score, matched_labels, has_strong_match).
    """
    score = 0.0
    matched: list[str] = []
    has_strong = False
    for feat in features:
        if feat.pattern.search(text):
            score += feat.weight
            matched.append(feat.label)
            if feat.weight == WEIGHT_STRONG:
                has_strong = True
    return score, matched, has_strong


def _calibrate(
    top_score: float,
    runner_up_score: float,
    has_strong: bool,
) -> float:
    """Confidence from top score, margin, and strong-feature presence."""
    base = _CONFIDENCE_BASE + top_score * _CONFIDENCE_PER_POINT
    margin = top_score - runner_up_score
    if margin < 0.5:
        base -= _CONFIDENCE_AMBIGUOUS_PENALTY
    if has_strong:
        base = max(base, _CONFIDENCE_STRONG_FLOOR)
    return round(max(_CONFIDENCE_ANY_MATCH_FLOOR, min(_CONFIDENCE_CAP, base)), 2)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def _route_for(
    task_type: TaskType,
    defaults: tuple[str, str, str],
) -> Routing:
    """Map a task type to an agent routing decision.

    Notable change vs. the old classifier: for ``DOCS`` we now route the
    write-work to ``implementer_default`` instead of ``planner_default``.
    Conceptual fix — the *implementer* slot is "the agent that produces
    changes", and docs are still changes. Users who want a specific agent
    handling prose should set ``agents.implementer`` accordingly.
    """
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
            implementer=implementer_default,
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


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def classify(
    task: str,
    defaults: tuple[str, str, str] = ("claude", "codex", "claude"),
) -> Classification:
    """Classify a task description into its most likely intent.

    Deterministic. No LLM. Same input → same output. The returned
    ``Classification`` exposes:
      - ``task_type`` — the primary intent
      - ``confidence`` — calibrated 0.0–0.95 (1.0 reserved for future use)
      - ``keywords_matched`` — every feature label that fired for the primary
      - ``secondary_intents`` — other intents with non-trivial signal
      - ``routing`` — agent assignments per the routing table
    """
    text = (task or "").strip().lower()
    if not text:
        return Classification(
            task_type=TaskType.UNKNOWN,
            confidence=0.0,
            keywords_matched=[],
            routing=_route_for(TaskType.UNKNOWN, defaults),
            secondary_intents=[],
        )

    # Score every type.
    scored: list[tuple[TaskType, float, list[str], bool]] = []
    for tt, feats in _FEATURES.items():
        score, matched, has_strong = _score_type(text, feats)
        if score > 0:
            scored.append((tt, score, matched, has_strong))

    if not scored:
        return Classification(
            task_type=TaskType.UNKNOWN,
            confidence=0.2,
            keywords_matched=[],
            routing=_route_for(TaskType.UNKNOWN, defaults),
            secondary_intents=[],
        )

    # Sort: score desc, then tie-break priority (so SECURITY beats a
    # numerically-tied FEATURE).
    scored.sort(key=lambda r: (-r[1], _TIE_BREAK_INDEX.get(r[0], 999)))

    top_type, top_score, top_matched, top_has_strong = scored[0]
    runner_up_score = scored[1][1] if len(scored) > 1 else 0.0

    # Multi-intent: keep any other type that's both above the absolute floor
    # AND at least half the top score.
    threshold = max(_SECONDARY_FLOOR, top_score * _SECONDARY_RATIO)
    secondary = [t for t, s, _m, _hs in scored[1:] if s >= threshold]

    confidence = _calibrate(
        top_score=top_score,
        runner_up_score=runner_up_score,
        has_strong=top_has_strong,
    )

    return Classification(
        task_type=top_type,
        confidence=confidence,
        keywords_matched=top_matched,
        routing=_route_for(top_type, defaults),
        secondary_intents=secondary,
    )
