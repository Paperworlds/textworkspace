---
id: '001'
title: Config integration and dataclasses
repo: textworkspace
model: sonnet
budget_usd: 1.50
phase: phase-1
---

# 001 — Config integration and dataclasses

## Goal

Add forums config support and define the core data structures.

## Steps

1. **config.py** — Add `forums: dict` field to the `Config` dataclass with default `{}`. Parse/serialize it in `load_config`/`save_config`. Keys: `root` (str, default `~/.textforums`), `author` (str, optional).

2. **forums.py** — Create `src/textworkspace/forums.py` with:
   - Constants: `DEFAULT_ROOT = Path.home() / ".textforums"`
   - `get_root() -> Path` — resolve from `$TEXTFORUMS_ROOT` env > `config.forums.root` > default
   - `get_author(override: str | None) -> str` — resolve from override > `$TEXTFORUMS_AUTHOR` env > config > `$USER`
   - Dataclasses:
     ```python
     @dataclass
     class ThreadMeta:
         title: str
         created: str           # ISO 8601
         author: str
         tags: list[str]
         status: str            # freeform, default "open"

     @dataclass
     class Entry:
         author: str
         timestamp: str         # ISO 8601
         status: str            # freeform
         content: str
         files: list[str]       # relative paths

     @dataclass
     class Thread:
         meta: ThreadMeta
         entries: list[Entry]
         path: Path             # file path on disk
     ```
   - `slug_from_title(title: str) -> str` — lowercase, replace non-alnum with hyphens, strip edges, truncate to 60 chars
   - `load_thread(root: Path, slug: str) -> Thread`
   - `save_thread(thread: Thread) -> None`
   - `list_threads(root: Path, status: str | None, tag: str | None) -> list[Thread]`
   - `add_entry(thread: Thread, entry: Entry, files: list[Path] | None) -> None` — append entry, copy files to `{slug}/` subdir if provided, save

3. **Tests** — Add `tests/test_forums.py`:
   - `test_slug_from_title` — various inputs (spaces, unicode, long strings)
   - `test_save_and_load_round_trip` — create Thread, save, load, compare
   - `test_add_entry_appends` — create thread, add entry, verify it's last
   - `test_list_threads_filters_by_status` — multiple threads, filter
   - `test_list_threads_filters_by_tag`
   - `test_get_root_env_override` — monkeypatch env, verify
   - `test_get_author_resolution` — test the priority chain

## Commit message
feat(forums): add config integration and core data layer
