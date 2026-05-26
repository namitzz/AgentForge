# Demo media placeholder

AgentForge intentionally ships no binary media in the repository so clones stay small. This file marks the spots where you should drop demo visuals before tagging a release.

## Terminal screenshot

A single still of the colored CLI output (the Risk + Policy + Security + Agent decision panels stacked) is the highest-impact asset. Anyone scrolling the README can see "this is real" in one glance.

- **Suggested path:** `docs/images/agentforge-cli.png`
- **Width:** 1200–1600 px works well on GitHub
- **Reference from README** (in the *Quick demo* section):
  ```markdown
  ![AgentForge CLI](docs/images/agentforge-cli.png)
  ```

## 60-second GIF

A short screen recording of the full demo loop. Keep it under 60 seconds and under 2 MB.

Suggested script:

1. `agentforge init`
2. `agentforge solve "Add password reset validation to the login flow" --dry-run`
3. `agentforge readiness`
4. `agentforge redteam --dry-run`
5. `ls .agentforge/runs/<latest>/`

Recording tools (pick one):

- **asciinema + agg** — best for crisp text, small files
  ```bash
  asciinema rec demo.cast
  agg demo.cast docs/images/agentforge-demo.gif
  ```
- **terminalizer** — yaml-configurable, easy to re-record
- **OBS Studio** — full-screen capture, trim in any video editor, then convert to GIF

- **Suggested path:** `docs/images/agentforge-demo.gif`
- **Reference from README**:
  ```markdown
  ![AgentForge demo](docs/images/agentforge-demo.gif)
  ```

## README image link

Once the file is in place, edit the **Quick demo** section in `README.md` to embed it. Keep both the still and the GIF — readers on metered connections often disable autoplay GIFs.

## Why not commit a placeholder image?

Binary assets bloat clones and complicate licensing. The release checklist (`docs/release-checklist.md`) treats recording the demo GIF as a separate, explicit step.
