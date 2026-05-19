"""Helpers for working with diffs."""

from __future__ import annotations

import re
from dataclasses import dataclass


_FILE_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)


@dataclass
class DiffStats:
    files_changed: int
    additions: int
    deletions: int
    file_list: list[str]

    def to_dict(self) -> dict:
        return {
            "files_changed": self.files_changed,
            "additions": self.additions,
            "deletions": self.deletions,
            "file_list": self.file_list,
        }


def parse_diff_stats(diff_text: str) -> DiffStats:
    files = [m.group(2) for m in _FILE_HEADER_RE.finditer(diff_text)]
    additions = 0
    deletions = 0
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return DiffStats(
        files_changed=len(files),
        additions=additions,
        deletions=deletions,
        file_list=files,
    )


def truncate_diff(diff_text: str, max_chars: int) -> str:
    if len(diff_text) <= max_chars:
        return diff_text
    return diff_text[:max_chars] + f"\n\n... [truncated {len(diff_text) - max_chars} chars]"
