"""Selects a minimal, relevant context to send to an agent.

Goal: never send the entire repo. Pick the smallest set of files plausibly
relevant to the task while respecting per-file and total character caps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .agents.local_agent import LocalAgent
from .config import Config
from .tools.file_scanner import RepoSummary


# Tokens that are too generic to be useful for scoring.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "in", "on", "for", "with", "of",
    "is", "are", "be", "this", "that", "it", "as", "by", "from", "at",
    "fix", "add", "update", "remove", "make", "use", "we", "i", "you",
    "should", "can", "will", "do", "does", "not", "no", "yes",
}

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if t.lower() not in _STOPWORDS and len(t) > 2}


@dataclass
class BuiltContext:
    repo_summary_text: str
    selected_files: list[tuple[str, str]]   # (rel_path, content)
    selected_paths: list[str]
    total_chars: int
    truncated: bool

    def to_dict(self) -> dict:
        return {
            "selected_paths": self.selected_paths,
            "total_chars": self.total_chars,
            "truncated": self.truncated,
        }


def _score_file(rel_path: str, task_tokens: set[str]) -> int:
    name_tokens = _tokens(rel_path.replace("/", " "))
    overlap = name_tokens & task_tokens
    score = len(overlap) * 10
    # Mild boost for source files near the root.
    depth = rel_path.count("/")
    score += max(0, 3 - depth)
    return score


def summarize_repo(summary: RepoSummary, max_files_in_summary: int = 40) -> str:
    """Produce a compact textual summary suitable for prompt headers."""
    lines: list[str] = []
    lines.append(f"root: {summary.root}")
    lines.append(f"files: {summary.file_count}  bytes: {summary.total_bytes}")
    if summary.languages:
        langs = ", ".join(f"{ext}:{n}" for ext, n in list(summary.languages.items())[:8])
        lines.append(f"by_ext: {langs}")
    if summary.top_dirs:
        lines.append("top_dirs: " + ", ".join(summary.top_dirs[:12]))
    lines.append("")
    lines.append("files (sample):")
    for f in summary.files[:max_files_in_summary]:
        marker = " [risky]" if f.is_risky else ""
        lines.append(f"  - {f.path} ({f.size}B){marker}")
    if summary.file_count > max_files_in_summary:
        lines.append(f"  ... and {summary.file_count - max_files_in_summary} more")
    return "\n".join(lines)


def select_relevant_files(
    summary: RepoSummary,
    task: str,
    config: Config,
    hinted_paths: list[str] | None = None,
) -> list[str]:
    """Return up to ``max_files_sent`` file paths ranked by relevance to ``task``."""
    task_tokens = _tokens(task)
    hinted = set(hinted_paths or [])

    ranked: list[tuple[int, str]] = []
    for f in summary.files:
        base = _score_file(f.path, task_tokens)
        if f.path in hinted:
            base += 100
        if f.is_risky and any(t in task.lower() for t in ("security", "auth", "payment", "secret")):
            base += 5
        ranked.append((base, f.path))

    ranked.sort(key=lambda kv: (-kv[0], kv[1]))
    # Drop zero-score entries unless we have nothing else.
    nonzero = [p for s, p in ranked if s > 0]
    if not nonzero:
        return [p for _, p in ranked[: config.max_files_sent]]
    return nonzero[: config.max_files_sent]


def build_context(
    local: LocalAgent,
    summary: RepoSummary,
    task: str,
    config: Config,
    hinted_paths: list[str] | None = None,
) -> BuiltContext:
    """Pick files and read their contents, respecting all budget caps."""
    selected_paths = select_relevant_files(summary, task, config, hinted_paths)
    selected_files: list[tuple[str, str]] = []
    total = 0
    truncated = False
    for rel in selected_paths:
        content = local.read_file(rel)
        if not content:
            continue
        if total + len(content) > config.max_total_chars:
            remaining = config.max_total_chars - total
            if remaining <= 0:
                truncated = True
                break
            content = content[:remaining] + "\n... [truncated]"
            truncated = True
        selected_files.append((rel, content))
        total += len(content)
        if total >= config.max_total_chars:
            truncated = True
            break

    return BuiltContext(
        repo_summary_text=summarize_repo(summary),
        selected_files=selected_files,
        selected_paths=[p for p, _ in selected_files],
        total_chars=total,
        truncated=truncated,
    )
