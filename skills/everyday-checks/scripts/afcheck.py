#!/usr/bin/env python3
"""AgentForge everyday checks: privacy, safety, footprint, preflight.

Standalone, standard-library only, so it runs anywhere Python 3.9+ runs
(including the Claude app's own workspace) with nothing to install.

    python3 afcheck.py privacy   FILE|-  [--safe-copy OUT] [--json]
    python3 afcheck.py safety    FILE|-  [--safe-copy OUT] [--json]
    python3 afcheck.py footprint FILE|-  [--chars N] [--replies N] [--grid G] [--json]
    python3 afcheck.py preflight FILE|-  [--safe-copy OUT] [--json]

FILE can be .txt .md .csv .json .html .eml .docx (and .pdf when pypdf or
pdftotext is available). Use - to read from stdin.

Nothing leaves the machine: no network, no AI calls. Matched sensitive
values are never printed in full, only masked previews.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import re
import shutil
import subprocess
import sys
import unicodedata
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

VERSION = "0.3.0"

HIGH, MEDIUM, LOW = "high", "medium", "low"
_SEV_ORDER = {HIGH: 0, MEDIUM: 1, LOW: 2}


# ---------------------------------------------------------------- reading --

def read_input(src: str) -> str:
    if src == "-":
        return sys.stdin.read()
    p = Path(src)
    if not p.exists():
        raise SystemExit(f"File not found: {src}")
    suffix = p.suffix.lower()
    if suffix == ".docx":
        return _read_docx(p)
    if suffix == ".pdf":
        return _read_pdf(p)
    data = p.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _read_docx(p: Path) -> str:
    with zipfile.ZipFile(p) as z:
        parts = [n for n in z.namelist()
                 if re.match(r"word/(document|header\d*|footer\d*|footnotes|comments)\.xml$", n)]
        out = []
        for name in parts:
            xml = z.read(name).decode("utf-8", errors="replace")
            xml = re.sub(r"</w:p>", "\n", xml)
            xml = re.sub(r"<w:tab/>", "\t", xml)
            # Keep hidden-text markers visible to the safety scan.
            xml = re.sub(r"<w:vanish/>", " [[HIDDEN_TEXT_FORMAT]] ", xml)
            out.append(html.unescape(re.sub(r"<[^>]+>", "", xml)))
    return "\n".join(out)


def _read_pdf(p: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
    except ImportError:
        pass
    if shutil.which("pdftotext"):
        res = subprocess.run(["pdftotext", "-layout", str(p), "-"],
                             capture_output=True, text=True)
        if res.returncode == 0:
            return res.stdout
    raise SystemExit("Cannot read PDF here (no pypdf or pdftotext). "
                     "Extract the text to a .txt file first, then re-run.")


# ---------------------------------------------------------------- findings --

@dataclass
class Finding:
    check: str          # privacy | safety
    kind: str           # e.g. card_number
    label: str          # human label
    severity: str
    line: int
    preview: str        # masked / short, never the full secret
    advice: str = ""


def _line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


def _mask(value: str, keep: int = 2) -> str:
    v = value.strip()
    if len(v) <= keep * 2 + 2:
        return "*" * len(v)
    return f"{v[:keep]}{'*' * min(len(v) - keep * 2, 12)}{v[-keep:]}"


# ----------------------------------------------------------------- privacy --

SECRET_PATTERNS = [
    ("aws_key", "AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", "GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("anthropic_key", "Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai_key", "OpenAI API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}")),
    ("jwt", "Login token (JWT)", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("private_key", "Private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("slack_token", "Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("google_key", "Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("stripe_key", "Stripe secret key", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}")),
]

PASSWORD_RE = re.compile(
    r"(?i)\b(pass(?:word|wd|code)?|pwd|pin|api[_ -]?key|secret|token)\s*(?:is|=|:)\s*[\"']?([^\s\"',;]{4,})")
_PLACEHOLDERS = ("your", "example", "changeme", "placeholder", "xxxx", "****", "<", "replace", "todo", "none", "n/a", "here")

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?<![\w+])(?:\+44\s?7\d{3}|\b07\d{3}|\+\d{1,3}[\s-]?\(?\d{2,4}\)?)[\s-]?\d{3}[\s-]?\d{3,4}\b")
CARD_RE = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,3})?\b")
NINO_RE = re.compile(r"\b(?!BG|GB|NK|KN|TN|NT|ZZ)[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z]\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b")
SSN_RE = re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")
SORT_CODE_RE = re.compile(r"(?i)\bsort\s*code\b[^\d\n]{0,15}(\d{2}[- ]?\d{2}[- ]?\d{2})")
ACCOUNT_RE = re.compile(r"(?i)\b(?:account\s*(?:no|number|num)?|acc(?:t)?\s*no)\b[^\d\n]{0,15}(\d{8})\b")
POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s+\d[A-Z]{2}\b")
DOB_RE = re.compile(r"(?i)\b(?:d\.?o\.?b\.?|date of birth|born(?: on)?)\b[^\n\d]{0,12}(\d{1,2}[/.\- ]\d{1,2}[/.\- ]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})")
PASSPORT_RE = re.compile(r"(?i)\bpassport\s*(?:no|number|#)?\b[^\w\n]{0,6}([A-Z0-9]{8,9})\b")
IPV4_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


_CARD_WORDS = re.compile(r"(?i)\b(card|visa|mastercard|master card|amex|american express|credit|debit|cvv|expiry|exp)\b")


def _card_brand_ok(d: str) -> bool:
    n = len(d)
    if d[0] == "4":
        return n in (13, 16, 19)
    if d[:2] in ("34", "37"):
        return n == 15
    if 51 <= int(d[:2]) <= 55 or 2221 <= int(d[:4]) <= 2720:
        return n == 16
    if d.startswith(("6011", "65")) or 644 <= int(d[:3]) <= 649:
        return n in (16, 19)
    return False


def _looks_like_card(text: str, m: re.Match) -> bool:
    raw = m.group()
    digits = re.sub(r"\D", "", raw)
    if not (13 <= len(digits) <= 19 and _card_brand_ok(digits) and _luhn_ok(digits) and len(set(digits)) > 1):
        return False
    grouped = bool(re.fullmatch(r"\d{4}([ -])\d{4}\1\d{4}\1\d{1,7}|\d{4}([ -])\d{6}\2\d{5}", raw))
    nearby = _CARD_WORDS.search(text[max(0, m.start() - 40):m.start()])
    return grouped or bool(nearby)


def _iban_ok(raw: str) -> bool:
    s = raw.replace(" ", "")
    if not 15 <= len(s) <= 34:
        return False
    s = s[4:] + s[:4]
    num = "".join(str(int(c, 36)) for c in s)
    return int(num) % 97 == 1


@dataclass
class _Hit:
    start: int
    end: int
    kind: str
    label: str
    severity: str
    advice: str


def _privacy_hits(text: str) -> list[_Hit]:
    hits: list[_Hit] = []

    def add(m, kind, label, sev, advice, group=0):
        hits.append(_Hit(m.start(group), m.end(group), kind, label, sev, advice))

    for kind, label, rx in SECRET_PATTERNS:
        for m in rx.finditer(text):
            add(m, kind, label, HIGH, "Revoke/rotate it if it was ever shared. Never paste keys into AI chats.")
    for m in PASSWORD_RE.finditer(text):
        val = m.group(2)
        if any(p in val.lower() for p in _PLACEHOLDERS):
            continue
        add(m, "password", f"Possible {m.group(1).lower()} value", HIGH,
            "Remove it before sharing; change it if it was already shared.", group=2)
    for m in CARD_RE.finditer(text):
        if _looks_like_card(text, m):
            add(m, "card_number", "Payment card number", HIGH, "Never share full card numbers.")
    for m in IBAN_RE.finditer(text):
        if _iban_ok(m.group()):
            add(m, "iban", "Bank account (IBAN)", HIGH, "Remove bank details before sharing.")
    for m in SORT_CODE_RE.finditer(text):
        add(m, "sort_code", "UK sort code", MEDIUM, "Remove bank details before sharing.", group=1)
    for m in ACCOUNT_RE.finditer(text):
        add(m, "account_number", "Bank account number", HIGH, "Remove bank details before sharing.", group=1)
    for m in NINO_RE.finditer(text):
        add(m, "ni_number", "UK National Insurance number", HIGH, "ID numbers enable identity fraud; remove them.")
    for m in SSN_RE.finditer(text):
        add(m, "ssn", "US Social Security number", HIGH, "ID numbers enable identity fraud; remove them.")
    for m in PASSPORT_RE.finditer(text):
        add(m, "passport", "Passport number", HIGH, "ID numbers enable identity fraud; remove them.", group=1)
    for m in DOB_RE.finditer(text):
        add(m, "date_of_birth", "Date of birth", MEDIUM, "Combined with a name this identifies a person.", group=1)
    for m in EMAIL_RE.finditer(text):
        add(m, "email", "Email address", MEDIUM, "Remove other people's emails unless needed.")
    for m in PHONE_RE.finditer(text):
        if len(re.sub(r"\D", "", m.group())) >= 10:
            add(m, "phone", "Phone number", MEDIUM, "Remove other people's numbers unless needed.")
    for m in POSTCODE_RE.finditer(text):
        add(m, "postcode", "UK postcode (address)", LOW, "Addresses identify people; keep only if needed.")
    for m in IPV4_RE.finditer(text):
        before = text[max(0, m.start() - 12):m.start()].lower()
        if not m.group().startswith(("0.", "127.", "255.")) and not re.search(r"(version|ver\.?|v)\s*$", before):
            add(m, "ip_address", "IP address", LOW, "Can reveal location or internal systems.")

    # Resolve overlaps: keep the most severe, then the longest.
    hits.sort(key=lambda h: (h.start, _SEV_ORDER[h.severity], -(h.end - h.start)))
    kept: list[_Hit] = []
    for h in hits:
        if kept and h.start < kept[-1].end:
            prev = kept[-1]
            if (_SEV_ORDER[h.severity], -(h.end - h.start)) < (_SEV_ORDER[prev.severity], -(prev.end - prev.start)):
                kept[-1] = h
            continue
        kept.append(h)
    return kept


def check_privacy(text: str) -> tuple[list[Finding], str]:
    hits = _privacy_hits(text)
    findings = [Finding("privacy", h.kind, h.label, h.severity, _line_of(text, h.start),
                        _mask(text[h.start:h.end]), h.advice) for h in hits]
    # Redacted copy with consistent placeholders.
    counters: dict[str, int] = {}
    seen: dict[tuple[str, str], str] = {}
    out, pos = [], 0
    for h in hits:
        val = text[h.start:h.end]
        key = (h.kind, val)
        if key not in seen:
            counters[h.kind] = counters.get(h.kind, 0) + 1
            seen[key] = f"[{h.kind.upper()}_{counters[h.kind]}]"
        out.append(text[pos:h.start])
        out.append(seen[key])
        pos = h.end
    out.append(text[pos:])
    return findings, "".join(out)


# ------------------------------------------------------------------ safety --

INJECTION_PHRASES = (
    "ignore previous instructions", "ignore all previous instructions", "ignore the above",
    "ignore all prior", "disregard previous instructions", "disregard prior instructions",
    "disregard the above", "forget your instructions", "forget all previous",
    "new instructions:", "override your instructions", "your new task is",
    "reveal your system prompt", "reveal the system prompt", "print your system prompt",
    "you are now", "you are dan", "do anything now", "developer mode",
    "do not tell the user", "don't tell the user", "without telling the user",
    "do not mention this", "keep this secret from",
    "send the conversation", "send this conversation", "forward this email",
    "forward all emails", "send secrets", "reveal secrets", "exfiltrate",
    "disable safety", "bypass safety", "disable security", "jailbreak",
    "as an ai assistant, you must", "when summarizing this", "when summarising this",
    "if you are an ai", "if you are a language model", "ai assistants reading this",
    "note to ai", "instructions for ai", "hidden instructions",
)

ROLE_SPOOF_RE = re.compile(r"(?im)^\s*(?:\[?\s*(?:system|assistant)\s*\]?\s*:|<\|?(?:system|im_start)\|?>|###\s*(?:system|instruction))")

ZERO_WIDTH = {"​": "zero-width space", "‌": "zero-width non-joiner",
              "‍": "zero-width joiner", "⁠": "word joiner",
              "﻿": "zero-width no-break space", "᠎": "mongolian vowel separator"}
BIDI = {chr(c) for c in list(range(0x202A, 0x202F)) + list(range(0x2066, 0x206A))}

HIDDEN_CSS_RE = re.compile(
    r"(?is)<([a-z]+)[^>]*style\s*=\s*[\"'][^\"']*(?:display\s*:\s*none|visibility\s*:\s*hidden|"
    r"font-size\s*:\s*0(?:px|pt|em)?\s*[;\"']|opacity\s*:\s*0(?:\.0+)?\s*[;\"']|"
    r"color\s*:\s*(?:#fff(?:fff)?|white|rgba?\(\s*255\s*,\s*255\s*,\s*255))[^\"']*[\"'][^>]*>(.*?)</\1>")
HTML_COMMENT_RE = re.compile(r"(?s)<!--(.*?)-->")
MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)\)")
URL_RE = re.compile(r"https?://[^\s)\"'<>]+")
BASE64_RE = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{120,}={0,2}(?![A-Za-z0-9+/])")
SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "goo.gl", "is.gd", "ow.ly", "rebrand.ly", "cutt.ly", "shorturl.at")
DANGEROUS_CMD_RE = re.compile(
    r"(?i)\brm\s+-[rf]{1,2}\s+[/~*]|\bformat\s+[a-z]:|\bdel\s+/[sq]\b|"
    r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:ba)?sh\b|powershell[^\n]*(?:-enc(?:odedcommand)?|iex|downloadstring)|"
    r"\bmkfs\b|:\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}")


def _script_of(ch: str) -> str | None:
    if not ch.isalpha():
        return None
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return None
    for s in ("LATIN", "CYRILLIC", "GREEK"):
        if name.startswith(s):
            return s
    return "OTHER"


def _contains_injection(s: str) -> str | None:
    low = re.sub(r"\s+", " ", s.lower())
    for p in INJECTION_PHRASES:
        if p in low:
            return p
    return None


def check_safety(text: str) -> tuple[list[Finding], str]:
    f: list[Finding] = []

    # 1. Hidden "tag" characters: invisible text that AI models can read.
    tag_runs = re.finditer(r"[\U000E0000-\U000E007F]+", text)
    for m in tag_runs:
        hidden = "".join(chr(ord(c) - 0xE0000) for c in m.group() if 0xE0020 <= ord(c) <= 0xE007E)
        f.append(Finding("safety", "invisible_tag_text", "Invisible hidden message (Unicode tag characters)",
                         HIGH, _line_of(text, m.start()), f'decodes to: "{hidden[:80]}"',
                         "Text a human cannot see but an AI can read. Treat the document as hostile."))

    # 2. Zero-width and direction-override characters.
    zw = [(i, c) for i, c in enumerate(text) if c in ZERO_WIDTH]
    if zw:
        f.append(Finding("safety", "zero_width", f"{len(zw)} invisible zero-width character(s)",
                         MEDIUM if len(zw) > 3 else LOW, _line_of(text, zw[0][0]),
                         ", ".join(sorted({ZERO_WIDTH[c] for _, c in zw})),
                         "Can hide or split words to slip past filters."))
    bd = [i for i, c in enumerate(text) if c in BIDI]
    if bd:
        f.append(Finding("safety", "bidi_override", f"{len(bd)} text-direction override character(s)",
                         HIGH, _line_of(text, bd[0]), "U+202E style reversal",
                         "Makes text or file names display differently from what they really say."))

    # 3. Prompt-injection phrases in visible text.
    for ln_no, ln in enumerate(text.split("\n"), start=1):
        hit = _contains_injection(ln)
        if hit:
            start = ln.lower().find(hit)
            snippet = re.sub(r"<[^>]+>", "", ln[start:start + 80]).strip()
            f.append(Finding("safety", "injection_phrase", "Instruction aimed at an AI", HIGH,
                             ln_no, f'"{snippet}"',
                             "Someone is trying to steer the AI that reads this. Do not follow it."))
    for m in ROLE_SPOOF_RE.finditer(text):
        f.append(Finding("safety", "role_spoof", "Fake system/assistant message marker", MEDIUM,
                         _line_of(text, m.start()), f'"{m.group().strip()[:40]}"',
                         "Text pretending to be from the AI system itself."))

    # 4. Hidden HTML / white text / comments.
    for m in HIDDEN_CSS_RE.finditer(text):
        inner = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if inner:
            sev = HIGH if _contains_injection(inner) else MEDIUM
            f.append(Finding("safety", "hidden_html", "Hidden or invisible web text", sev,
                             _line_of(text, m.start()), f'"{inner[:70]}"',
                             "Content styled to be invisible to people but read by AI."))
    for m in HTML_COMMENT_RE.finditer(text):
        body = m.group(1).strip()
        if body and _contains_injection(body):
            f.append(Finding("safety", "hidden_comment", "Instruction hidden in an HTML comment", HIGH,
                             _line_of(text, m.start()), f'"{body[:70]}"', "Hidden instructions for AI."))
    if "[[HIDDEN_TEXT_FORMAT]]" in text:
        f.append(Finding("safety", "hidden_word_text", "Hidden-formatted text in Word document", MEDIUM,
                         _line_of(text, text.find("[[HIDDEN_TEXT_FORMAT]]")), "w:vanish",
                         "Text formatted as hidden in Word. Check what it says."))

    # 5. Data-leak links (images that would send data to a server when shown).
    for m in MD_IMAGE_RE.finditer(text):
        url = m.group(1)
        if "?" in url and len(url.split("?", 1)[1]) > 20 or "{" in url:
            f.append(Finding("safety", "exfil_image", "Image link that could leak data", HIGH,
                             _line_of(text, m.start()), url[:80],
                             "A classic trick to make an AI send chat contents to an outside server."))
    for m in URL_RE.finditer(text):
        url = m.group()
        host = re.sub(r"^https?://", "", url).split("/")[0].lower()
        why = None
        if "@" in host:
            why = "uses '@' to disguise the real website"
        elif re.fullmatch(r"[\d.:]+", host):
            why = "points to a raw IP address"
        elif "xn--" in host:
            why = "uses look-alike (punycode) characters"
        elif host.split(":")[0] in SHORTENERS:
            why = "is a link shortener hiding the destination"
        if why:
            f.append(Finding("safety", "suspicious_link", f"Suspicious link: {why}", MEDIUM,
                             _line_of(text, m.start()), url[:80], "Check where it really goes before clicking."))

    # 6. Look-alike letters mixed into one word (e.g. Cyrillic 'а' in 'pаypal').
    for m in re.finditer(r"\b\w{3,}\b", text):
        scripts = {_script_of(c) for c in m.group()} - {None}
        if "LATIN" in scripts and scripts & {"CYRILLIC", "GREEK"}:
            f.append(Finding("safety", "homoglyph", "Word mixing look-alike alphabets", MEDIUM,
                             _line_of(text, m.start()), f'"{m.group()}"',
                             "Often used in phishing to fake brand names."))

    # 7. Encoded blobs hiding instructions.
    for m in BASE64_RE.finditer(text):
        try:
            decoded = base64.b64decode(m.group() + "=" * (-len(m.group()) % 4)).decode("utf-8", "ignore")
        except Exception:
            continue
        hit = _contains_injection(decoded)
        if hit:
            f.append(Finding("safety", "encoded_instruction", "Instruction hidden in encoded (base64) text",
                             HIGH, _line_of(text, m.start()), f'decodes to include "{hit}"',
                             "Deliberately disguised instructions. Treat as hostile."))

    # 8. Dangerous commands someone might ask you (or an AI) to run.
    for m in DANGEROUS_CMD_RE.finditer(text):
        f.append(Finding("safety", "dangerous_command", "Dangerous computer command", HIGH,
                         _line_of(text, m.start()), f'"{m.group()[:60]}"',
                         "Do not run this. It can delete files or install malware."))

    # Cleaned copy: strip invisible/tag/bidi characters and hidden HTML comments.
    cleaned = re.sub(r"[\U000E0000-\U000E007F]", "", text)
    cleaned = "".join(c for c in cleaned if c not in ZERO_WIDTH and c not in BIDI)
    cleaned = HTML_COMMENT_RE.sub("", cleaned)
    cleaned = HIDDEN_CSS_RE.sub("", cleaned)
    cleaned = cleaned.replace(" [[HIDDEN_TEXT_FORMAT]] ", "")
    cleaned = MD_IMAGE_RE.sub(lambda m: "[REMOVED_DATA_LEAK_LINK]"
                              if ("?" in m.group(1) or "{" in m.group(1)) else m.group(), cleaned)
    for p in sorted(INJECTION_PHRASES, key=len, reverse=True):
        cleaned = re.sub(re.escape(p), "[REMOVED_AI_INSTRUCTION]", cleaned, flags=re.I)
    cleaned = DANGEROUS_CMD_RE.sub("[REMOVED_DANGEROUS_COMMAND]", cleaned)
    return f, cleaned


# --------------------------------------------------------------- footprint --
# Same model as agentforge/carbon.py. Estimates, not measurements.

WH_PER_1K_IN = 0.25
WH_PER_1K_OUT = 0.6
CHARS_PER_TOKEN = 4.0
OUT_TOKENS_PER_REPLY = 500
PHONE_CHARGE_WH = 15.0     # typical smartphone full charge
LED_BULB_HOUR_WH = 10.0    # 10 W LED bulb for one hour


def footprint(chars: int, replies: int, grid: float, resend: bool) -> dict:
    """Energy and CO2e for an AI task.

    If ``resend`` is true the text is re-read on every reply, as happens
    when a long document stays in a chat across several messages.
    """
    in_tokens = chars / CHARS_PER_TOKEN
    total_in = in_tokens * (replies if resend else 1)
    total_out = OUT_TOKENS_PER_REPLY * replies

    def wh(tin, tout):
        return tin / 1000 * WH_PER_1K_IN + tout / 1000 * WH_PER_1K_OUT

    base_wh = wh(total_in, total_out)
    scenarios = []
    if in_tokens > 2_000:
        # Share only the relevant ~quarter of a long document.
        trimmed = wh(total_in * 0.25, total_out)
        scenarios.append(("Share only the relevant section (about a quarter)", trimmed))
    if replies > 1 and resend:
        # One well-specified request instead of many follow-ups.
        one_shot = wh(in_tokens, OUT_TOKENS_PER_REPLY * max(1, replies // 2))
        scenarios.append(("Ask for everything in one clear message, then start a fresh chat", one_shot))
    co2 = lambda w: w / 1000 * grid  # noqa: E731
    return {
        "input_tokens": round(in_tokens),
        "replies": replies,
        "energy_wh": round(base_wh, 3),
        "co2e_g": round(co2(base_wh), 3),
        "phone_charges": round(base_wh / PHONE_CHARGE_WH, 3),
        "led_bulb_minutes": round(base_wh / LED_BULB_HOUR_WH * 60, 1),
        "savings": [
            {"tip": tip, "energy_wh": round(w, 3), "co2e_g": round(co2(w), 3),
             "saved_pct": round(100 * (1 - w / base_wh)) if base_wh else 0}
            for tip, w in scenarios
        ],
        "assumptions": {
            "wh_per_1k_input_tokens": WH_PER_1K_IN, "wh_per_1k_output_tokens": WH_PER_1K_OUT,
            "output_tokens_per_reply": OUT_TOKENS_PER_REPLY, "chars_per_token": CHARS_PER_TOKEN,
            "grid_intensity_g_per_kwh": grid,
        },
        "note": "Estimate from public per-token energy figures; not measured. Smaller AI models "
                "generally use less energy per reply, but exact ratios are not published.",
    }


# ------------------------------------------------------------------ output --

def verdict(findings: list[Finding]) -> str:
    sev = {x.severity for x in findings}
    if HIGH in sev:
        return "RED"
    if MEDIUM in sev:
        return "AMBER"
    return "GREEN"


VERDICT_TEXT = {
    "RED": "Do not share this with AI (or anyone) as it is.",
    "AMBER": "Review the flagged items before sharing.",
    "GREEN": "No problems found by these checks.",
}


def _fmt_g(g: float) -> str:
    return f"{g / 1000:.2f} kg" if g >= 1000 else (f"{g:.1f} g" if g >= 1 else f"{g:.2f} g")


def render_findings(title: str, findings: list[Finding]) -> list[str]:
    lines = [f"## {title}: {len(findings)} issue(s)"]
    if not findings:
        lines.append("- Nothing found.")
        return lines
    for x in sorted(findings, key=lambda x: (_SEV_ORDER[x.severity], x.line)):
        lines.append(f"- **{x.severity.upper()}** line {x.line}: {x.label} ({x.preview})")
        if x.advice:
            lines.append(f"  - {x.advice}")
    return lines


def _phone(x: float) -> str:
    return f"{x:.1f} phone charges" if x >= 1 else f"{x * 100:.0f}% of a phone charge"


def render_footprint(fp: dict) -> list[str]:
    lines = ["## AI footprint (estimate)",
             f"- About {fp['input_tokens']:,} tokens in, {fp['replies']} AI repl{'y' if fp['replies'] == 1 else 'ies'}",
             f"- Energy: ~{fp['energy_wh']:.2f} Wh, carbon: ~{_fmt_g(fp['co2e_g'])} CO2e",
             f"- That is about {_phone(fp['phone_charges'])}, "
             f"or a 10 W LED bulb for {fp['led_bulb_minutes']:.0f} min"]
    for s in fp["savings"]:
        lines.append(f"- Save ~{s['saved_pct']}%: {s['tip']} (~{_fmt_g(s['co2e_g'])} CO2e)")
    lines.append(f"- _{fp['note']}_")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="afcheck", description=__doc__.split("\n\n")[0])
    ap.add_argument("--version", action="version", version=f"afcheck {VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("privacy", "safety", "footprint", "preflight"):
        sp = sub.add_parser(name)
        sp.add_argument("src", nargs="?", default="-", help="file path or - for stdin")
        sp.add_argument("--json", action="store_true")
        sp.add_argument("--safe-copy", help="write a cleaned/redacted copy here")
        sp.add_argument("--chars", type=int, help="footprint: size in characters instead of a file")
        sp.add_argument("--replies", type=int, default=1, help="footprint: expected AI replies")
        sp.add_argument("--grid", type=float, default=400.0, help="grid g CO2e per kWh (UK ~150-250)")
        sp.add_argument("--resend", action="store_true",
                        help="footprint: the text stays in the chat and is re-read every reply")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

    text = "" if (a.cmd == "footprint" and a.chars is not None) else read_input(a.src)
    result: dict = {"command": a.cmd, "version": VERSION}
    out: list[str] = []
    findings: list[Finding] = []
    safe_text = text

    if a.cmd in ("privacy", "preflight"):
        pf, safe_text = check_privacy(safe_text)
        findings += pf
        result["privacy"] = [asdict(x) for x in pf]
    if a.cmd in ("safety", "preflight"):
        sf, safe_text = check_safety(safe_text)
        findings += sf
        result["safety"] = [asdict(x) for x in sf]
    if a.cmd in ("footprint", "preflight"):
        chars = a.chars if a.chars is not None else len(text)
        result["footprint"] = footprint(chars, max(1, a.replies), a.grid, a.resend or a.replies > 1)

    if a.cmd != "footprint":
        v = verdict(findings)
        result["verdict"] = v
        out.append(f"# Verdict: {v}. {VERDICT_TEXT[v]}")
        if a.cmd in ("privacy", "preflight"):
            out += [""] + render_findings("Privacy", [x for x in findings if x.check == "privacy"])
        if a.cmd in ("safety", "preflight"):
            out += [""] + render_findings("Safety", [x for x in findings if x.check == "safety"])
        if a.safe_copy:
            Path(a.safe_copy).write_text(safe_text, encoding="utf-8")
            result["safe_copy"] = a.safe_copy
            out += ["", f"Safe copy written to {a.safe_copy} (sensitive items replaced, hidden text removed)."]
    if "footprint" in result:
        out += [""] + render_footprint(result["footprint"])

    print(json.dumps(result, indent=2, ensure_ascii=False) if a.json else "\n".join(out).strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
