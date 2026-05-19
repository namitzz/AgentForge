"""Repo-aware filesystem scanning.

Produces a compact summary of the repo and reads file contents safely,
skipping ignored directories, secret files, and binaries.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from ..config import Config


BINARY_SNIFF_BYTES = 1024


@dataclass
class FileEntry:
    path: str          # POSIX-style relative path
    size: int
    is_risky: bool = False

    def to_dict(self) -> dict:
        return {"path": self.path, "size": self.size, "is_risky": self.is_risky}


@dataclass
class RepoSummary:
    root: str
    file_count: int
    total_bytes: int
    files: list[FileEntry] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)
    top_dirs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "files": [f.to_dict() for f in self.files],
            "languages": self.languages,
            "top_dirs": self.top_dirs,
        }


def _is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            chunk = f.read(BINARY_SNIFF_BYTES)
    except OSError:
        return True
    if b"\x00" in chunk:
        return True
    return False


def _rel_posix(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_ignored_dir(name: str, ignore_dirs: Iterable[str]) -> bool:
    return name in set(ignore_dirs)


def _is_secret_file(name: str, secret_files: Iterable[str]) -> bool:
    return name in set(secret_files)


def _is_risky(rel_path: str, risky_substrings: Iterable[str]) -> bool:
    lowered = rel_path.lower()
    return any(s in lowered for s in risky_substrings)


def scan_repo(root: Path | str, config: Config) -> RepoSummary:
    """Walk the repo and produce a summary. Reads no file contents."""
    root_p = Path(root).resolve()
    ignore = set(config.ignore_dirs)
    text_exts = set(config.text_extensions)
    secret = set(config.secret_files)
    risky = list(config.risky_files)

    files: list[FileEntry] = []
    languages: dict[str, int] = {}
    top_dirs: set[str] = set()
    total_bytes = 0

    for dirpath, dirnames, filenames in os.walk(root_p):
        # Prune ignored directories in-place so os.walk doesn't recurse into them.
        dirnames[:] = [d for d in dirnames if not _is_ignored_dir(d, ignore)]

        for fname in filenames:
            if _is_secret_file(fname, secret):
                continue
            p = Path(dirpath) / fname
            ext = p.suffix.lower()
            if ext and ext not in text_exts:
                # Skip non-text extensions entirely for the summary.
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            rel = _rel_posix(root_p, p)
            top = rel.split("/", 1)[0]
            top_dirs.add(top)
            total_bytes += size
            languages[ext or "<none>"] = languages.get(ext or "<none>", 0) + 1
            files.append(FileEntry(
                path=rel,
                size=size,
                is_risky=_is_risky(rel, risky),
            ))

    files.sort(key=lambda f: f.path)
    return RepoSummary(
        root=str(root_p),
        file_count=len(files),
        total_bytes=total_bytes,
        files=files,
        languages=dict(sorted(languages.items(), key=lambda kv: -kv[1])),
        top_dirs=sorted(top_dirs),
    )


def read_file_capped(path: Path | str, max_chars: int) -> str:
    """Read a text file, truncating to ``max_chars``. Returns '' for binaries."""
    p = Path(path)
    if not p.exists() or not p.is_file():
        return ""
    if _is_binary(p):
        return ""
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) > max_chars:
        return text[:max_chars] + f"\n\n... [truncated {len(text) - max_chars} chars]"
    return text
