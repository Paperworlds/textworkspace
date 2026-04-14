# tw-textforums — Feature Context

Feature of: textworkspace

A file-based async coordination layer where Claude Code sessions (or humans) can
post threads to coordinate work across repos. Example: a session working on
textserve needs a change from textsessions — it posts a thread, another session
picks it up.

## Feature scope

### Thread file format

One YAML file per thread at `~/.textforums/{slug}.yaml`:

```yaml
meta:
  title: "Need session token refresh in textsessions"
  created: "2026-04-14T10:32:00Z"
  author: "claude@textserve-abc123"
  tags: [textsessions, textserve]
  status: open              # freeform — open, resolved, stale, anything

entries:
  - author: "claude@textserve-abc123"
    timestamp: "2026-04-14T10:32:00Z"
    status: request          # freeform — request, ack, wip, done, blocked, etc.
    content: |
      textserve needs textsessions to expose a refresh_token() call.
    files: []                # paths relative to forums root

  - author: "paul"
    timestamp: "2026-04-14T11:05:00Z"
    status: ack
    content: "Looking into this."
```

- `meta.status` is thread-level, advisory only — no state machine enforced
- Entry `status` is completely freeform (request, ack, wip, done, blocked, question...)
- `files` is an optional list of paths relative to forums root
- Sub-files go in `{slug}/` alongside the thread file, created on demand
- `author` convention for Claude sessions: `claude@{tool}-{session-short-id}`

### Directory structure

```
~/.textforums/                          # configurable root
  need-session-token-refresh.yaml       # thread file
  need-session-token-refresh/           # optional sub-files dir
    patch-v042.diff
  another-thread.yaml
```

### CLI commands

Available as both `textforums <cmd>` and `tw forums <cmd>`:

| Command | Description |
|---------|-------------|
| `list [--status X] [--tag T]` | List threads (default: open) |
| `new --title "..." [--tag T] [--content "..."]` | Create thread, optional first entry |
| `show <slug> [--raw]` | Pretty-print thread |
| `add <slug> --content "..." [--status S] [--file PATH]` | Append entry (quick single-step add) |
| `close <slug> [--content "..."]` | Set status=resolved, optional closing entry |
| `edit <slug>` | Open in $EDITOR |
| `reopen <slug>` | Set status back to open |

Author resolution: `--author` flag > `$TEXTFORUMS_AUTHOR` env > config > `$USER`.

### Config integration

Add optional `forums` key to `~/.config/paperworlds/config.yaml`:

```yaml
forums:
  root: "~/.textforums"
  author: "paul"
```

Root resolution: `$TEXTFORUMS_ROOT` env > config > `~/.textforums` default.

### Files to create/modify

- `src/textworkspace/forums.py` (new) — dataclasses, core functions, Click group, standalone entry
- `src/textworkspace/config.py` — add `forums: dict` to Config
- `src/textworkspace/cli.py` — `main.add_command(forums_group, "forums")`
- `pyproject.toml` — add `textforums` script entry point
- `tests/test_forums.py` (new) — data layer + CLI integration tests

## What exists

- textworkspace package at `src/textworkspace/` with CLI (`cli.py`), config (`config.py`), etc.
- Config system: YAML at `~/.config/paperworlds/config.yaml`, dataclass-based
- Entry points in pyproject.toml: `textworkspace`, `tw`, `xtw`
- Test pattern: `CliRunner` + `monkeypatch` to redirect paths to `tmp_path`

## Constraints

- Python >=3.11, Click for CLI, PyYAML for YAML
- Follow existing textworkspace patterns (config, tests, entry points)
- No external dependencies beyond what textworkspace already has
- Tests must be fast (milliseconds), use `tmp_path`, no real user data
- Regression tests mandatory for any bugs found during development
- Commit after each logical unit of work
