# Repo kit

This repository was initialized with **repo-kit**. Keep standards docs under `docs/` and Cursor assets under `.cursor/`.

Session handoff lives under `.repo-kit/chat/` (see `.cursor/skills/chat-context/`). Installed layout version is in `.repo-kit/version`.

Crypto security review notes live under gitignored `.repo-kit/findings/` (see
`.cursor/skills/crypto-security-review/`).

To upgrade an older install (legacy root `.chat/` layout), run `migrate.sh` from the repo-kit source tree against this project.

Do not rely on symlinks back to the kit — copied files are the project source of truth after init.
