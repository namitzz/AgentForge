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


PR_REVIEW_SYSTEM = """\
You are the REVIEW agent for AgentForge, running in PR mode.
You receive: an optional task description, the base + head branch names,
the list of changed files, the merge-base git diff, and (locally
generated) risk + policy reports.

You DO NOT receive the full repository. Reason only from what is shown.

Your job:
- Judge whether the diff is safe to merge into the base branch.
- Flag concrete problems with file + line context when possible.
- Be terse. Do not restate the diff.

You MUST respond with a single JSON object and nothing else.
"""


PR_REVIEW_TEMPLATE = """\
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

# Git diff (base...head)
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


def build_pr_review_prompt(
    *,
    task: str | None,
    base_branch: str,
    head_branch: str,
    changed_files: list[str],
    diff: str,
    risk_summary: str,
    policy_summary: str,
) -> str:
    rendered_files = "\n".join(f"- {p}" for p in changed_files) or "(no files)"
    return PR_REVIEW_TEMPLATE.format(
        system=PR_REVIEW_SYSTEM.strip(),
        task=(task or "").strip() or "(no task description supplied)",
        base_branch=base_branch,
        head_branch=head_branch,
        changed_files=rendered_files,
        risk_summary=risk_summary.strip() or "(no risk report)",
        policy_summary=policy_summary.strip() or "(no policy report)",
        diff=diff.strip() or "(no diff)",
    )
