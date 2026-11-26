# HiddenInk

Check anything before you share it with AI. Works in the Claude app with no coding.

| Command | What it does |
|---|---|
| /preflight | One red, amber or green verdict for privacy, hidden tricks and carbon, plus a cleaned safe copy |
| /privacy | Finds passwords, access keys, card and bank numbers, National Insurance and passport numbers, emails, phones and dates of birth, and redacts them |
| /safety | Reveals instructions hidden for AI (invisible Unicode text, white or hidden web text, Word hidden text, encoded text), data-leak image links, disguised web addresses, look-alike letters and harmful commands |
| /footprint | Estimates the energy and CO2 of a document, a task or the current chat, in everyday terms, with tips that cut it |

You can also just ask, for example "is this safe to paste into an AI chat?" with a file attached.

## How it works

The plugin is a set of instructions (a skill) that Claude follows to inspect your content. It adds no extra programs, no outside services and no extra AI calls beyond the chat you are already having.

## Limits

- Rule-based checks catch common formats, not everything. GREEN means nothing was found, not a guarantee. Names and free-text personal details are not reliably detected.
- Carbon figures are estimates from published research (Epoch AI for energy per token, Ember for grid intensity). No AI provider publishes exact per-request energy figures.

## About

Part of the AgentForge project by namitzz. The full AgentForge plugin, with an offline checker script and guardrails for Claude Code, lives in the root of this repository. MIT licensed.
