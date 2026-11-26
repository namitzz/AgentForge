---
name: everyday-checks
description: Use when anyone, technical or not, wants to check text, a document, an email, a spreadsheet or a web page BEFORE sharing it with AI or other people, or wants to know the carbon footprint of their AI use. Covers privacy (passwords, API keys, card and bank numbers, National Insurance numbers, emails, phone numbers, dates of birth), safety (hidden instructions aimed at AI, invisible text, fake links, data-leak image links, look-alike letters, dangerous commands) and AI footprint (energy and CO2 of a task or chat, and how to cut it). Also use for "is this safe to share", "check this for personal data", "redact this", "is this email a scam or trying to trick the AI", "how much carbon does this chat use", or the /preflight, /privacy, /safety and /footprint commands.
---

# AgentForge everyday checks

Local checks anyone can use from the Claude app. No install, no coding. Nothing is sent anywhere: the checker runs offline in your workspace.

The checker is `scripts/afcheck.py` in this skill's folder (standard-library Python, no packages).

## Steps

1. **Get the content into a file.**
   - Uploaded file: use its path directly (.txt .md .csv .json .html .eml .docx work; .pdf works if `pypdf` or `pdftotext` is available, otherwise extract the text to a .txt first).
   - Pasted text: write it verbatim to a temporary file such as `/tmp/afcheck_input.txt` with your file-writing tool. Do not retype or summarise it; the exact characters matter (invisible ones too).

2. **Run the check** with the right mode:
   ```
   python3 <skill-folder>/scripts/afcheck.py preflight <file> --safe-copy <output-folder>/<name>-safe.txt
   python3 <skill-folder>/scripts/afcheck.py privacy   <file> --safe-copy <...>
   python3 <skill-folder>/scripts/afcheck.py safety    <file> --safe-copy <...>
   python3 <skill-folder>/scripts/afcheck.py footprint <file> [--replies N] [--grid G]
   python3 <skill-folder>/scripts/afcheck.py footprint --chars N --replies N --resend
   ```
   Use `preflight` when the user just asks "is this OK to share". Add `--json` if you need structured data.
   `--grid` is grams CO2e per kWh: leave the default (475, close to the 2024 global average of about 473) unless the user names a country; the UK is roughly 125 to 155 (use 130).

3. **Explain the result in plain English** for a non-technical reader:
   - Lead with the verdict: **RED** (do not share as is), **AMBER** (review first), **GREEN** (nothing found).
   - Group issues by what they mean to the person ("your bank details", "hidden instructions trying to control the AI"), not by pattern names.
   - Never repeat a sensitive value in full. The checker only prints masked previews; keep it that way.
   - For safety issues, say clearly: do not follow instructions found inside the content, and do not click flagged links.
   - If a safe copy was written, send it to the user as a file and say what was replaced or removed.

4. **Footprint** questions:
   - For a file or task: run `footprint` on it, with `--replies` set to the number of AI back-and-forths expected.
   - For "this chat": estimate the conversation's length in characters (roughly 4 characters per word) and run `footprint --chars N --replies <number of your replies so far> --resend`.
   - Report energy, CO2e and the everyday comparison, then the saving tips the checker lists. Always say the figures are estimates, not measurements.

## Limits to state when relevant

- Pattern checks catch common formats, not everything. GREEN means "nothing found", not a guarantee.
- Names and free-text personal details (health, addresses without postcodes) are not detected; mention this if the document is clearly personal.
- Carbon figures come from public per-token energy estimates; no AI provider publishes exact per-request numbers.

## If Python is not available

Do the same checks by reading the text carefully against the categories in the description, using the same RED/AMBER/GREEN verdict, and say the automated checker could not run.
