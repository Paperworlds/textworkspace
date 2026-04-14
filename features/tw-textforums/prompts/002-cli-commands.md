---
id: '002'
title: CLI commands
repo: textworkspace
model: sonnet
budget_usd: 1.50
phase: phase-1
depends_on: ['001']
---

# 002 — CLI commands

## Goal

Add all textforums CLI commands as a Click group in `forums.py`.

## Depends on
001-config-and-dataclasses

## Steps

1. **Click group in forums.py** — Add at the bottom of `forums.py`:
   ```python
   @click.group()
   @click.version_option(...)
   def forums(): ...
   
   def cli():
       """Standalone entry point for `textforums` binary."""
       forums(standalone_mode=True)
   ```

2. **Commands** — Implement each:

   - `forums list [--status S] [--tag T]` — table output: slug, status, title, entries count, age
   - `forums new --title "..." [--tag T ...] [--author A] [--content "..."]` — create thread file, optional first entry. If no `--content`, open `$EDITOR` with template. Print slug on success.
   - `forums show <slug> [--raw]` — pretty-print meta + entries. `--raw` dumps YAML.
   - `forums add <slug> --content "..." [--author A] [--status S] [--file PATH ...]` — append one entry. If no `--content`, open `$EDITOR`. `--file` copies into `{slug}/` subdir.
   - `forums close <slug> [--content "..."]` — set `meta.status = "resolved"`, optionally append closing entry.
   - `forums edit <slug>` — open thread YAML in `$EDITOR`.
   - `forums reopen <slug>` — set `meta.status = "open"`.

3. **Register entry points**:
   - `pyproject.toml`: add `textforums = "textworkspace.forums:cli"` to `[project.scripts]`
   - `cli.py`: add `from textworkspace.forums import forums as forums_group` and `main.add_command(forums_group, "forums")`

4. **Tests** — Add CLI tests to `tests/test_forums.py`:
   - `test_forums_new_creates_file` — invoke via CliRunner
   - `test_forums_list_shows_thread`
   - `test_forums_show_displays_entries`
   - `test_forums_add_appends_entry`
   - `test_forums_close_sets_resolved`
   - `test_forums_reopen`
   - `test_forums_edit_opens_editor` — mock $EDITOR
   - `test_standalone_entry_point` — invoke `cli()` directly
   - `test_tw_forums_subcommand` — invoke via `tw forums list`

## Commit message
feat(forums): add CLI commands and entry points
