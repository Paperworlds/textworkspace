# Report: 202 — WorkspaceManager — start/stop/list/status + env propagation + state.yaml

Date: 2026-04-20T16:32:00Z
Status: DONE

## Summary

Task 202 requested implementing `WorkspaceManager` with `start`, `stop`, `list`, `status` methods, env propagation (`CLAUDE_CONFIG_DIR` injection), and `state.yaml` persistence.

All deliverables were already implemented in a prior session (commit history shows `feat: workspace profiles — tw start/stop, tw workspaces group`). This task verified and validated the existing implementation.

## What Exists

### workspace.py — WorkspaceManager

- **`start(name, session_name, profile)`**: resolves profile via `textaccounts`, injects `CLAUDE_CONFIG_DIR` into env, calls `textserve start` (by tag or name), calls `textsessions new`, writes `state.yaml`. All tools degrade gracefully with `[WARN]` if missing.
- **`stop(name)`**: calls `textserve stop`, clears `state.yaml`. Does NOT touch profile (R12).
- **`list()`**: returns `list[WorkspaceConfig]` from config.
- **`status()`**: reads `state.yaml`, returns dict or None.
- **`_read_state()` / `_write_state()`**: YAML helpers for `~/.config/paperworlds/state.yaml`. `None` values are removed on write (clean state on stop).

### CLI commands (cli.py)

- `tw start <workspace> [session_name] [--profile]`
- `tw stop <workspace>`
- `tw workspaces list`
- `tw workspaces status`
- `tw workspaces add` (interactive)
- `tw workspaces edit`

### Env propagation

`CLAUDE_CONFIG_DIR` is injected into `textserve start` subprocess env when `textaccounts` is available and the resolved profile has that variable. `textsessions new` does not receive the injected env (it reads the profile itself).

## Test Results

- `tests/test_workspace.py`: **29/29 passed**
- Full suite: **306/307 passed** (1 pre-existing failure in `test_cli.py:399` — textserve `--json` flag, unrelated)

## Notes for Next Prompt

- `STATE_FILE` lives at `~/.config/paperworlds/state.yaml` (not `~/.local/state/…`)
- `stop()` intentionally does not revert the profile — profile is session-persistent
- `textserve start/stop` support both `--tag` and positional name modes (mutually exclusive per workspace config)
