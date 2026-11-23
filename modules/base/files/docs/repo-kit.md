# Repo kit

This repository was initialized with **repo-kit**. Keep standards docs under `docs/` and Cursor assets under `.cursor/`.

Step-by-step ops guidance: `.cursor/rules/step-by-step.mdc` and `docs/step-by-step-guidance.md`.

Session handoff lives under `.repo-kit/chat/` (see `.cursor/skills/chat-context/`). Installed layout version is in `.repo-kit/version`.

Crypto security review notes live under gitignored `.repo-kit/findings/` (see
`.cursor/skills/crypto-security-review/`).

Personal-data check: `/scrub-personal-data` or `.repo-kit/scripts/scrub-personal-data.sh` (numbered report; `--fix 1,3` replaces selected hits; `--help` lists detectors). Needs only `python3`. List your own usernames and hostnames in gitignored `.repo-kit/personal-tokens.txt`.

To upgrade an older install (legacy root `.chat/` layout), run `migrate.sh` from the repo-kit source tree against this project.

Do not rely on symlinks back to the kit — copied files are the project source of truth after init.
