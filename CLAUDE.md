# textworkspace — Claude Instructions

## Project
Meta CLI and package manager for the Paperworlds text- stack.

- Binary: `textworkspace`
- Package: `src/textworkspace/`
- Python >=3.11, built with hatchling, managed with uv

## Structure

```
src/textworkspace/
  __init__.py   — version string
  cli.py        — click group and all subcommands
  config.py     — load/save ~/.config/paperworlds/config.yaml
  combos.py     — combo loading/execution engine
  bootstrap.py  — Go binary download/management via GitHub API
  forums.py     — textforums thread management (data layer + CLI)
  status.py     — unified status display
  shell.py      — fish function generation
tests/
  test_cli.py
  test_forums.py
```

## textforums

Standalone thread/forum CLI. Threads are YAML files under `~/.textforums/<slug>/thread.yaml`.

```bash
textforums new --title "my thread" --content "hello" --tag bug
textforums list [--status open|resolved] [--tag <tag>]
textforums show <slug> [--raw]
textforums add <slug> --content "reply" --status ack
textforums close <slug> [--content "closing note"]
textforums reopen <slug>
textforums edit <slug>        # opens $EDITOR
```

Also available via `tw forums <subcommand>`. Root dir overridable via `$TEXTFORUMS_ROOT` or `config.forums.root`.

## Running

```bash
uv sync
uv run textworkspace --help
uv run pytest tests/ -v
```

## Git Rules
- Commit with `git -c commit.gpgsign=false commit`
- Commit after each logical unit of work

## Testing
- Tests in `tests/`, run with `uv run pytest`
- Regression tests mandatory for bug fixes
- Use small fixtures; tests must complete in milliseconds

## Forums
Before starting work, run `textforums list --tag textworkspace --status open` and check for open threads relevant to your task. Post a thread tagged `textworkspace` if you hit a cross-repo blocker.
