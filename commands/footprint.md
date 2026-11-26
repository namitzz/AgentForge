---
description: Estimate the energy and carbon of an AI task, a document or this chat, with tips that cut it.
argument-hint: [attach a file, describe a task, or say "this chat"]
---

The user wants the AI footprint of:

**$ARGUMENTS**

Use the `everyday-checks` skill in `footprint` mode. For a file, run it on the file with `--replies` set to the expected number of AI replies. For "this chat" (or nothing given), estimate this conversation's length in characters and run `footprint --chars N --replies <your replies so far> --resend`. If they mention a country, set `--grid` (UK roughly 200). Report energy, CO2e, the everyday comparison and the saving tips, and say clearly these are estimates.
