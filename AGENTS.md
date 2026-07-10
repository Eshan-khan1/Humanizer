# Agent instructions (Humanizer)

## Keep code in sync (required)

GitHub `main` is the single source of truth. Local machines, cloud agents, and every checkout must stay aligned.

### At the start of every task

1. Run `bash scripts/pull-github.sh` (or `git fetch origin && git pull --rebase origin main` on `main`).
2. Confirm you are on the intended branch and up to date with `origin/main`.

### During and after every task

1. Commit meaningful changes with a clear message.
2. Push to GitHub: `git push -u origin HEAD`.
3. Before finishing, run `bash scripts/sync-github.sh` so any remaining edits are committed and pushed.

### Rules

- Never leave work only on the VM or only on a local disk — always push to GitHub.
- If you pull and see new commits from another machine, integrate them before pushing.
- Prefer working on `main` for small fixes; use `cursor/<description>-bc1d` branches for larger changes, then merge via PR.
- Do not commit secrets, `.venv/`, logs, or `.cursor/debug*.log`.

### Quick commands

| Goal | Command |
|------|---------|
| Get latest from GitHub | `bash scripts/pull-github.sh` |
| Push local/cloud changes | `bash scripts/sync-github.sh` |
| Full bidirectional sync | `bash scripts/sync-all.sh` |
