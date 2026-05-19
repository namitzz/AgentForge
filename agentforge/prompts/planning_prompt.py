"""Builds the planner prompt."""

from __future__ import annotations


PLANNING_SYSTEM = """\
You are the PLANNING agent for AgentForge.
You do not edit code. You produce a tight, actionable implementation plan.
Be concise. Prefer bullet lists. Avoid restating the task.
"""

PLANNING_TEMPLATE = """\
{system}

# Task
{task}

# Task type (classifier hint)
{task_type}

# Repo summary
{repo_summary}

# Relevant files (paths only)
{relevant_files}

# Output format (Markdown)
Produce a plan with these sections, in order:

## Task understanding
A 2-3 sentence restatement of the goal.

## Relevant files
Bulleted list of files you would touch and why.

## Risks
Bulleted list. Mark each as low / medium / high.

## Implementation steps
Numbered, minimal, ordered steps. Each step should be one concrete change.

## Test strategy
How we verify success. Mention specific test files or commands.

## Reviewer needed?
Yes/No and one sentence why.
"""


def build_planning_prompt(
    task: str,
    task_type: str,
    repo_summary: str,
    relevant_files: list[str],
) -> str:
    return PLANNING_TEMPLATE.format(
        system=PLANNING_SYSTEM.strip(),
        task=task.strip(),
        task_type=task_type,
        repo_summary=repo_summary.strip() or "(no summary)",
        relevant_files="\n".join(f"- {p}" for p in relevant_files) or "(none identified)",
    )
