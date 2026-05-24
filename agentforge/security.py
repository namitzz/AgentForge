"""Security scanners.

Four local, deterministic checks that run before any agent is invoked:

  - **High-confidence secret scan.** Vendor-prefix credential patterns
    (AWS, GitHub, OpenAI, Anthropic, JWT, PEM private keys, SSH, Slack,
    Google). On match the file is **dropped** from the context. The matched
    value is never logged.

  - **Env-marker scan.** Lower-confidence indicators like ``API_KEY=...``,
    ``PASSWORD=...``, ``TOKEN=...``. On match the file is **kept but
    flagged** as suspicious — false positives in docs / examples are common,
    so dropping would hurt UX. Operators inspect ``security_report.json``.

  - **Prompt-injection scan.** Known phrases that try to subvert the agent.
    Warn-only. Phrases land in ``prompt_injection_warnings``. The agent
    prompts already include explicit guidance to ignore embedded
    instructions.

  - **Command safety check.** Pattern-match the configured
    ``default_test_command`` (and any other shell strings) against a list
    of obviously destructive patterns. Refused commands stop the test
    step with exit 126 and a clear stderr.

Everything here is local. No network, no LLM, no third-party services.

Output schema for ``SecurityReport.to_dict()`` (matches the project spec):

    {
      "blocked_files": ["src/utils/keys.py"],
      "suspicious_files": ["docs/notes.md"],
      "prompt_injection_warnings": [
        {"file": "docs/notes.md", "phrase": "ignore previous instructions"}
      ],
      "command_risk": "low" | "high",
      "command_blocked": false,
      "reasons": ["..."],
      "safe_to_continue": true
    }
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable


# --- High-confidence secret value patterns --------------------------------

# Anchored on a known vendor prefix. On match we DROP the file from
# context.
SECRET_VALUE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key",    re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws_session_token", re.compile(r"\bASIA[0-9A-Z]{16}\b")),
    ("github_token",      re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("openai_key",        re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("anthropic_key",     re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("jwt_token",         re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("pem_private_key",   re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("ssh_private_key",   re.compile(r"-----BEGIN OPENSSH PRIVATE KEY-----")),
    ("slack_token",       re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("google_api_key",    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
]


# --- Env-style marker patterns (warn-only) --------------------------------

# Pattern: known marker name + assignment + at least 8 chars of value-like
# characters. We don't drop the file because docs and examples commonly
# include placeholders. The file is added to ``suspicious_files`` and the
# operator decides.
_VALUE = r"[A-Za-z0-9_\-/+=.~]{8,}"
ENV_MARKER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("API_KEY",           re.compile(rf"\bAPI[_-]?KEY\s*[=:]\s*[\"']?({_VALUE})")),
    ("SECRET",            re.compile(rf"\bSECRET\s*[=:]\s*[\"']?({_VALUE})")),
    ("PASSWORD",          re.compile(rf"\bPASSWORD\s*[=:]\s*[\"']?({_VALUE})")),
    ("TOKEN",             re.compile(rf"\bTOKEN\s*[=:]\s*[\"']?({_VALUE})")),
    ("AWS_ACCESS_KEY_ID", re.compile(rf"\bAWS_ACCESS_KEY_ID\s*[=:]\s*[\"']?({_VALUE})")),
    ("AWS_SECRET_ACCESS_KEY", re.compile(rf"\bAWS_SECRET_ACCESS_KEY\s*[=:]\s*[\"']?({_VALUE})")),
    ("OPENAI_API_KEY",    re.compile(rf"\bOPENAI_API_KEY\s*[=:]\s*[\"']?({_VALUE})")),
    ("ANTHROPIC_API_KEY", re.compile(rf"\bANTHROPIC_API_KEY\s*[=:]\s*[\"']?({_VALUE})")),
    ("PRIVATE_KEY",       re.compile(r"\bPRIVATE\s+KEY\b")),
]

# Obvious placeholders that we *don't* want to flag.
_PLACEHOLDER_VALUES: tuple[str, ...] = (
    "your_key_here", "your-key-here", "your_api_key", "your-api-key",
    "replace_me", "replace-me", "changeme", "change-me",
    "xxxxxxxx", "yyyyyyyy", "<your_key>", "<api_key>",
    "todo", "example", "placeholder",
)


# --- Prompt-injection phrases ---------------------------------------------

INJECTION_PHRASES: tuple[str, ...] = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "disregard previous instructions",
    "disregard prior instructions",
    "send secrets",
    "send all secrets",
    "reveal secrets",
    "reveal the secrets",
    "exfiltrate",
    "disable safety",
    "disable security",
    "bypass safety",
    "reveal your system prompt",
    "reveal the system prompt",
    "you are now",
    "you are dan",
    "do anything now",
    "run rm -rf",
    "delete everything",
    "upload this code",
    "print environment variables",
    "dump environment variables",
)


# --- Dangerous shell-command patterns -------------------------------------

DANGEROUS_COMMAND_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("rm_rf_root",         re.compile(r"\brm\s+(-[rRfF]+\s+)*(/+|/\*|--no-preserve-root)")),
    ("rm_rf_home",         re.compile(r"\brm\s+(-[rRfF]+\s+)*\$HOME\b")),
    ("rm_rf_star",         re.compile(r"\brm\s+(-[rRfF]+\s+)*[\"']?\*[\"']?\s*$")),
    ("mkfs",               re.compile(r"\bmkfs(\.[a-z0-9]+)?\b")),
    ("dd_to_device",       re.compile(r"\bdd\b[^|]*\bof=/dev/")),
    ("device_redirect",    re.compile(r">\s*/dev/(sd[a-z]|nvme|hd[a-z]|disk)")),
    ("fork_bomb",          re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:")),
    ("chmod_777_root",     re.compile(r"\bchmod\s+-R\s+(0?)777\s+/")),
    ("curl_pipe_sh",       re.compile(r"\b(curl|wget)\b[^|]*\|\s*(ba)?sh\b")),
    ("windows_format",     re.compile(r"\bformat\s+[A-Za-z]:", re.IGNORECASE)),
    ("windows_del_c",      re.compile(r"\bdel\s+(/[a-zA-Z]\s+)*[A-Za-z]:\\?", re.IGNORECASE)),
    ("windows_del_s",      re.compile(r"\bdel\s+/[sS]\b", re.IGNORECASE)),
    ("windows_rmdir_s",    re.compile(r"\brmdir\s+/[sS]\b", re.IGNORECASE)),
    ("shutdown",           re.compile(r"\b(shutdown|halt|poweroff|reboot)\b(?:\s+(-[a-zA-Z]+|now))?")),
    ("git_push_force",     re.compile(r"\bgit\s+push\s+(?:[^-]*\s+)?(?:--force\b|-f\b)")),
    ("git_reset_hard",     re.compile(r"\bgit\s+reset\s+(?:[^-]*\s+)?--hard\b")),
    ("git_clean_fd",       re.compile(r"\bgit\s+clean\s+-[a-zA-Z]*[fF][a-zA-Z]*d?[a-zA-Z]*\b")),
]


# --- Result types ----------------------------------------------------------

@dataclass
class SecretHit:
    path: str
    pattern: str

    def to_dict(self) -> dict:
        return {"file": self.path, "pattern": self.pattern}


@dataclass
class MarkerHit:
    path: str
    marker: str

    def to_dict(self) -> dict:
        return {"file": self.path, "marker": self.marker}


@dataclass
class InjectionHit:
    path: str
    phrase: str

    def to_dict(self) -> dict:
        return {"file": self.path, "phrase": self.phrase}


@dataclass
class CommandSafety:
    command: str
    safe: bool
    reasons: list[str] = field(default_factory=list)

    @property
    def risk(self) -> str:
        return "low" if self.safe else "high"

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "risk": self.risk,
            "reasons": list(self.reasons),
        }


@dataclass
class SecurityReport:
    secret_hits: list[SecretHit] = field(default_factory=list)
    marker_hits: list[MarkerHit] = field(default_factory=list)
    injection_hits: list[InjectionHit] = field(default_factory=list)
    command_safety: CommandSafety | None = None
    files_scanned: int = 0

    # --- derived views ------------------------------------------------
    @property
    def blocked_files(self) -> list[str]:
        return sorted({h.path for h in self.secret_hits})

    @property
    def suspicious_files(self) -> list[str]:
        return sorted({h.path for h in self.marker_hits}
                      | {h.path for h in self.injection_hits})

    @property
    def command_risk(self) -> str:
        if self.command_safety is None:
            return "low"
        return self.command_safety.risk

    @property
    def command_blocked(self) -> bool:
        return bool(self.command_safety and not self.command_safety.safe)

    @property
    def reasons(self) -> list[str]:
        out: list[str] = []
        if self.blocked_files:
            patterns = sorted({h.pattern for h in self.secret_hits})
            out.append(
                f"Dropped {len(self.blocked_files)} file(s) containing "
                f"secret patterns: {', '.join(patterns)}"
            )
        if self.marker_hits:
            markers = sorted({h.marker for h in self.marker_hits})
            out.append(
                f"Found {len(self.marker_hits)} env-style secret marker(s) "
                f"({', '.join(markers)}) — kept but flagged for review"
            )
        if self.injection_hits:
            phrases = sorted({h.phrase for h in self.injection_hits})
            shown = ", ".join(phrases[:3]) + ("..." if len(phrases) > 3 else "")
            out.append(
                f"Detected {len(self.injection_hits)} prompt-injection "
                f"phrase(s): {shown}"
            )
        if self.command_blocked:
            assert self.command_safety is not None
            out.append(
                f"Refused dangerous test command "
                f"({self.command_safety.command!r}): "
                f"{', '.join(self.command_safety.reasons)}"
            )
        return out

    @property
    def safe_to_continue(self) -> bool:
        # Blocking secrets and warning on injections are both recoverable —
        # they don't stop the run. The only hard stop is a refused command.
        return not self.command_blocked

    # --- serialisers --------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "blocked_files": self.blocked_files,
            "suspicious_files": self.suspicious_files,
            "prompt_injection_warnings": [h.to_dict() for h in self.injection_hits],
            "secret_marker_warnings": [h.to_dict() for h in self.marker_hits],
            "command_risk": self.command_risk,
            "command_blocked": self.command_blocked,
            "command_safety": (
                self.command_safety.to_dict() if self.command_safety else None
            ),
            "files_scanned": self.files_scanned,
            "reasons": self.reasons,
            "safe_to_continue": self.safe_to_continue,
        }

    def human_summary(self) -> list[str]:
        lines: list[str] = ["Security checks:"]
        if self.blocked_files:
            lines.append("- Blocked secret files: " + ", ".join(self.blocked_files))
        else:
            lines.append("- Blocked secret files: none")
        lines.append(
            f"- Prompt-injection warnings: {len(self.injection_hits)}"
        )
        for hit in self.injection_hits:
            lines.append(f"    - {hit.path}: \"{hit.phrase}\"")
        if self.marker_hits:
            markers = sorted({h.marker for h in self.marker_hits})
            lines.append(
                f"- Suspicious env-style markers: {len(self.marker_hits)} "
                f"({', '.join(markers)})"
            )
        lines.append(f"- Command risk: {self.command_risk}")
        if self.command_blocked and self.command_safety is not None:
            lines.append(
                f"  - REFUSED: {self.command_safety.command} "
                f"({', '.join(self.command_safety.reasons)})"
            )
        lines.append(f"- Safe to continue: {'yes' if self.safe_to_continue else 'no'}")
        return lines


# --- Scanners --------------------------------------------------------------

def scan_for_secret_values(text: str) -> list[str]:
    """Return the names of high-confidence credential patterns that matched."""
    if not text:
        return []
    hits: list[str] = []
    seen: set[str] = set()
    for name, regex in SECRET_VALUE_PATTERNS:
        if regex.search(text) and name not in seen:
            hits.append(name)
            seen.add(name)
    return hits


def scan_for_secret_markers(text: str) -> list[str]:
    """Return env-style marker names whose values look real (not placeholders)."""
    if not text:
        return []
    hits: list[str] = []
    seen: set[str] = set()
    for name, regex in ENV_MARKER_PATTERNS:
        match = regex.search(text)
        if match and name not in seen:
            # If a value group exists, exclude obvious placeholders.
            try:
                value = (match.group(1) or "").lower()
            except (IndexError, AttributeError):
                value = ""
            if value and any(value.startswith(ph) for ph in _PLACEHOLDER_VALUES):
                continue
            hits.append(name)
            seen.add(name)
    return hits


def scan_for_injection(text: str) -> list[str]:
    """Return the lowercase phrases that matched."""
    if not text:
        return []
    lowered = text.lower()
    return [phrase for phrase in INJECTION_PHRASES if phrase in lowered]


def is_dangerous_command(command: str) -> CommandSafety:
    """Pattern-check a shell command. Empty / whitespace = safe (no-op)."""
    cmd = (command or "").strip()
    if not cmd:
        return CommandSafety(command="", safe=True)
    reasons: list[str] = []
    for name, regex in DANGEROUS_COMMAND_PATTERNS:
        if regex.search(cmd):
            reasons.append(name)
    return CommandSafety(command=cmd, safe=not reasons, reasons=reasons)


def scan_files(files: Iterable[tuple[str, str]]) -> SecurityReport:
    """Run secret + marker + injection scans over ``(path, content)`` pairs."""
    report = SecurityReport()
    for path, content in files:
        report.files_scanned += 1
        for pattern_name in scan_for_secret_values(content):
            report.secret_hits.append(SecretHit(path=path, pattern=pattern_name))
        for marker_name in scan_for_secret_markers(content):
            report.marker_hits.append(MarkerHit(path=path, marker=marker_name))
        for phrase in scan_for_injection(content):
            report.injection_hits.append(InjectionHit(path=path, phrase=phrase))
    return report


def files_with_secrets(report: SecurityReport) -> set[str]:
    """Files we will DROP from the context (high-confidence secret matches)."""
    return {h.path for h in report.secret_hits}


# --- Back-compat shim ------------------------------------------------------

# Older callers may import this name. Keep working but treat as the union
# of high-confidence + env-marker scans for breadth.
def scan_for_secrets(text: str) -> list[str]:
    return scan_for_secret_values(text) + scan_for_secret_markers(text)
