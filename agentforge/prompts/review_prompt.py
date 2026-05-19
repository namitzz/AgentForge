"""Builds the review prompt. Reviewer only ever sees a diff, never full files."""

from __future__ import annotations


REVIEW_SYSTEM = """\
You are the REVIEW agent for AgentForge.
You receive: the task, the plan, the git diff, and the test result.
You DO NOT receive the full repository. Reason only from what is shown.

Your job:
- Judge whether the diff implements the plan correctly and safely.
- Flag concrete problems with file + line context when possible.
- Be terse. Do not restate the diff.

You MUST respond with a single JSON object and nothing else.
"""


REVIEW_TEMPLATE = """\
{system}

# Task
{task}

# Plan
{plan}

# Test result
{test_result}

# Git diff
```diff
{diff}
```

# Required output (JSON only — no prose, no code fence)
{{
  "status": "approved" | "needs_changes",
  "risk_level": "low" | "medium" | "high",
  "issues": [
    {{
      "file": "path/to/file",
      "problem": "what is wrong",
      "suggested_fix": "what to change"
    }}
  ],
  "summary": "one or two sentences"
}}
"""


def build_review_prompt(task: str, plan: str, diff: str, test_result: str) -> str:
    return REVIEW_TEMPLATE.format(
        system=REVIEW_SYSTEM.strip(),
        task=task.strip(),
        plan=plan.strip() or "(no plan)",
        diff=diff.strip() or "(no diff)",
        test_result=test_result.strip() or "(no test output)",
    )
