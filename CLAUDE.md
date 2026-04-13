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
  status.py     — unified status display
  shell.py      — fish function generation
tests/
  test_cli.py
```

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
