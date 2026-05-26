"""Red-team review prompt.

A strict, adversarial flavour of the diff reviewer. Asks the agent to assume
the worst and report findings in a richer schema (severity, why_it_matters,
missing_tests, merge_recommendation).

Used by ``agentforge redteam``. Output is parsed by ``parse_redteam_response``
which never raises — on malformed JSON the verdict falls back to
``status: needs_manual_review`` so a human can read the raw output.
"""

from __future__ import annotations

import json
import re
from typing import Any


REDTEAM_SYSTEM = """\
You are the RED TEAM review agent for AgentForge.

You receive: an optional task description, base + head branch names, the
list of changed files, local risk + policy + security summaries, and the
git diff. You DO NOT receive the full repository. Reason only from what
is shown.

Your job:
- Assume the change is wrong until proven safe.
- Hunt for failure modes the implementer might have missed.
- Be specific. Quote file paths and line context when possible.
- Be terse. Do not restate the diff.

Categories to inspect (look for each — and report what is OK as well):

  1.  authentication bypass
  2.  token / session issues
  3.  password reset abuse
  4.  user enumeration
  5.  missing authorization checks
  6.  missing input validation
  7.  unsafe database changes
  8.  migration risks
  9.  secrets exposure
  10. unsafe logging (passwords, tokens, PII)
  11. destructive shell or git commands
  12. missing tests
  13. regression risk in unrelated code paths
  14. overbroad changes (more touched than the task implies)
  15. mismatch between the stated task and the diff

You MUST respond with a single JSON object and nothing else.
"""


REDTEAM_TEMPLATE = """\
{system}

# Task (optional)
{task}

# Branch
- base: {base_branch}
- head: {head_branch}

# Changed files
{changed_files}

# Risk report (local)
{risk_summary}

# Policy report (local)
{policy_summary}

# Security report (local)
{security_summary}

# Git diff
```diff
{diff}
```

# Required output (JSON only - no prose, no code fence)
{{
  "status": "approved" | "needs_changes",
  "risk_level": "low" | "medium" | "high",
  "findings": [
    {{
      "severity": "low" | "medium" | "high" | "critical",
      "file": "path/to/file",
      "issue": "what is wrong",
      "why_it_matters": "concrete consequence if shipped",
      "suggested_fix": "what to change"
    }}
  ],
  "missing_tests": [
    "Plain-English description of a test case that should exist but does not."
  ],
  "merge_recommendation": "do_not_merge" | "merge_with_caution" | "merge_ready",
  "summary": "one or two sentences"
}}
"""


def build_redteam_prompt(
    *,
    task: str | None,
    base_branch: str,
    head_branch: str,
    changed_files: list[str],
    diff: str,
    risk_summary: str,
    policy_summary: str,
    security_summary: str,
) -> str:
    rendered_files = "\n".join(f"- {p}" for p in changed_files) or "(no files)"
    return REDTEAM_TEMPLATE.format(
        system=REDTEAM_SYSTEM.strip(),
        task=(task or "").strip() or "(no task description supplied)",
        base_branch=base_branch,
        head_branch=head_branch,
        changed_files=rendered_files,
        risk_summary=(risk_summary or "").strip() or "(no risk report)",
        policy_summary=(policy_summary or "").strip() or "(no policy report)",
        security_summary=(security_summary or "").strip() or "(no security report)",
        diff=(diff or "").strip() or "(no diff)",
    )


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

REQUIRED_KEYS: tuple[str, ...] = (
    "status",
    "risk_level",
    "findings",
    "missing_tests",
    "merge_recommendation",
    "summary",
)

_VALID_STATUS = {"approved", "needs_changes"}
_VALID_RISK = {"low", "medium", "high"}
_VALID_REC = {"do_not_merge", "merge_with_caution", "merge_ready"}


def _needs_manual_review(message: str, raw_output: str = "") -> dict[str, Any]:
    """Build a safety-conservative fallback verdict."""
    out: dict[str, Any] = {
        "status": "needs_manual_review",
        "risk_level": "high",
        "findings": [],
        "missing_tests": [],
        "merge_recommendation": "do_not_merge",
        "summary": message,
    }
    if raw_output:
        out["raw_output"] = raw_output[:4000]
    return out


def _normalize_findings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for f in value:
        if not isinstance(f, dict):
            continue
        out.append({
            "severity":       str(f.get("severity", "medium")),
            "file":           str(f.get("file", "")),
            "issue":          str(f.get("issue", "")),
            "why_it_matters": str(f.get("why_it_matters", "")),
            "suggested_fix":  str(f.get("suggested_fix", "")),
        })
    return out


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if isinstance(v, (str, int, float))]


def parse_redteam_response(text: str) -> dict[str, Any]:
    """Parse the reviewer's JSON. Never raises.

    On invalid JSON or missing required keys, returns a safety-conservative
    ``needs_manual_review`` verdict with the raw output preserved so a human
    can read it.
    """
    if not text or not text.strip():
        return _needs_manual_review("Reviewer returned an empty response.")

    cleaned = text.strip()
    # Strip ```json ... ``` or ``` ... ``` wrappers.
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    parsed: dict[str, Any] | None = None
    try:
        candidate = json.loads(cleaned)
        if isinstance(candidate, dict):
            parsed = candidate
    except json.JSONDecodeError:
        # Try to extract the first JSON object embedded in prose.
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                candidate = json.loads(match.group(0))
                if isinstance(candidate, dict):
                    parsed = candidate
            except json.JSONDecodeError:
                parsed = None

    if parsed is None:
        return _needs_manual_review(
            "Reviewer returned non-JSON output.",
            raw_output=text,
        )

    # Validate + normalise. Missing keys downgrade us to manual review,
    # except for trivially-missable ones like findings / missing_tests
    # which default to empty.
    missing = [k for k in REQUIRED_KEYS if k not in parsed]
    if missing:
        # Only count "structural" misses as fatal. Allow the reviewer to
        # omit findings/missing_tests by treating them as empty.
        fatal = [k for k in missing if k not in ("findings", "missing_tests")]
        if fatal:
            return _needs_manual_review(
                f"Reviewer response missing required keys: {', '.join(fatal)}.",
                raw_output=text,
            )

    status = str(parsed.get("status", "")).lower()
    if status not in _VALID_STATUS:
        return _needs_manual_review(
            f"Reviewer returned unrecognised status: {status!r}.",
            raw_output=text,
        )

    risk_level = str(parsed.get("risk_level", "")).lower()
    if risk_level not in _VALID_RISK:
        # Don't fail hard for a slightly-off risk_level; coerce to high.
        risk_level = "high"

    recommendation = str(parsed.get("merge_recommendation", "")).lower()
    if recommendation not in _VALID_REC:
        # Conservative default if missing or unknown.
        recommendation = "merge_with_caution" if status == "approved" else "do_not_merge"

    return {
        "status":               status,
        "risk_level":           risk_level,
        "findings":             _normalize_findings(parsed.get("findings", [])),
        "missing_tests":        _normalize_string_list(parsed.get("missing_tests", [])),
        "merge_recommendation": recommendation,
        "summary":              str(parsed.get("summary", "")).strip() or "(no summary)",
    }
