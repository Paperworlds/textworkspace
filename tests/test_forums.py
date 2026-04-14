"""Tests for textworkspace.forums."""

from __future__ import annotations

from pathlib import Path

import pytest

from textworkspace.forums import (
    Entry,
    Thread,
    ThreadMeta,
    add_entry,
    get_author,
    get_root,
    list_threads,
    load_thread,
    save_thread,
    slug_from_title,
    DEFAULT_ROOT,
)


# ---------------------------------------------------------------------------
# slug_from_title
# ---------------------------------------------------------------------------

def test_slug_from_title_basic():
    assert slug_from_title("Hello World") == "hello-world"


def test_slug_from_title_spaces_and_punctuation():
    assert slug_from_title("  My Great Post!  ") == "my-great-post"


def test_slug_from_title_unicode():
    # non-ascii chars become hyphens
    result = slug_from_title("Café au lait")
    assert result == "caf-au-lait"


def test_slug_from_title_multiple_separators():
    assert slug_from_title("one---two   three") == "one-two-three"


def test_slug_from_title_truncates_to_60():
    long_title = "a" * 80
    assert len(slug_from_title(long_title)) == 60


def test_slug_from_title_strips_leading_trailing_hyphens():
    assert not slug_from_title("!hello!").startswith("-")
    assert not slug_from_title("!hello!").endswith("-")


# ---------------------------------------------------------------------------
# save / load round-trip
# ---------------------------------------------------------------------------

def _make_thread(root: Path, slug: str = "test-thread") -> Thread:
    meta = ThreadMeta(
        title="Test Thread",
        created="2026-04-14T10:00:00Z",
        author="alice",
        tags=["python", "testing"],
        status="open",
    )
    entry = Entry(
        author="alice",
        timestamp="2026-04-14T10:01:00Z",
        status="initial",
        content="Hello, world!",
        files=[],
    )
    path = root / slug / "thread.yaml"
    return Thread(meta=meta, entries=[entry], path=path)


def test_save_and_load_round_trip(tmp_path):
    thread = _make_thread(tmp_path)
    save_thread(thread)

    loaded = load_thread(tmp_path, "test-thread")
    assert loaded.meta.title == thread.meta.title
    assert loaded.meta.author == thread.meta.author
    assert loaded.meta.tags == thread.meta.tags
    assert loaded.meta.status == thread.meta.status
    assert len(loaded.entries) == 1
    assert loaded.entries[0].content == "Hello, world!"
    assert loaded.entries[0].author == "alice"


# ---------------------------------------------------------------------------
# add_entry
# ---------------------------------------------------------------------------

def test_add_entry_appends(tmp_path):
    thread = _make_thread(tmp_path)
    save_thread(thread)

    new_entry = Entry(
        author="bob",
        timestamp="2026-04-14T11:00:00Z",
        status="reply",
        content="Nice post!",
        files=[],
    )
    add_entry(thread, new_entry)

    loaded = load_thread(tmp_path, "test-thread")
    assert len(loaded.entries) == 2
    assert loaded.entries[-1].author == "bob"
    assert loaded.entries[-1].content == "Nice post!"


def test_add_entry_copies_files(tmp_path):
    thread = _make_thread(tmp_path)
    save_thread(thread)

    # Create a temp file to attach
    src_file = tmp_path / "attachment.txt"
    src_file.write_text("data")

    entry = Entry(
        author="carol",
        timestamp="2026-04-14T12:00:00Z",
        status="note",
        content="See attachment",
        files=[],
    )
    add_entry(thread, entry, files=[src_file])

    # File should be copied into the slug dir
    assert (tmp_path / "test-thread" / "attachment.txt").exists()
    assert thread.entries[-1].files == ["attachment.txt"]


# ---------------------------------------------------------------------------
# list_threads — status filter
# ---------------------------------------------------------------------------

def _make_and_save(root: Path, slug: str, status: str, tags: list[str]) -> Thread:
    meta = ThreadMeta(
        title=slug.replace("-", " ").title(),
        created="2026-04-14T00:00:00Z",
        author="x",
        tags=tags,
        status=status,
    )
    thread = Thread(meta=meta, entries=[], path=root / slug / "thread.yaml")
    save_thread(thread)
    return thread


def test_list_threads_filters_by_status(tmp_path):
    _make_and_save(tmp_path, "open-thread", "open", [])
    _make_and_save(tmp_path, "closed-thread", "closed", [])

    open_threads = list_threads(tmp_path, status="open")
    assert len(open_threads) == 1
    assert open_threads[0].meta.status == "open"


def test_list_threads_no_filter_returns_all(tmp_path):
    _make_and_save(tmp_path, "alpha", "open", [])
    _make_and_save(tmp_path, "beta", "closed", [])

    all_threads = list_threads(tmp_path)
    assert len(all_threads) == 2


# ---------------------------------------------------------------------------
# list_threads — tag filter
# ---------------------------------------------------------------------------

def test_list_threads_filters_by_tag(tmp_path):
    _make_and_save(tmp_path, "python-post", "open", ["python", "dev"])
    _make_and_save(tmp_path, "rust-post", "open", ["rust"])

    python_threads = list_threads(tmp_path, tag="python")
    assert len(python_threads) == 1
    assert "python" in python_threads[0].meta.tags


def test_list_threads_empty_root(tmp_path):
    result = list_threads(tmp_path / "nonexistent")
    assert result == []


# ---------------------------------------------------------------------------
# get_root env override
# ---------------------------------------------------------------------------

def test_get_root_env_override(tmp_path, monkeypatch):
    custom = str(tmp_path / "custom-root")
    monkeypatch.setenv("TEXTFORUMS_ROOT", custom)
    assert get_root() == Path(custom)


def test_get_root_default_without_env(monkeypatch):
    monkeypatch.delenv("TEXTFORUMS_ROOT", raising=False)
    # With no env var and a fresh config (no forums.root set),
    # the result should be the default.  We patch load_config to return empty.
    from textworkspace import config as cfg_mod
    from textworkspace.config import Config
    monkeypatch.setattr(cfg_mod, "load_config", lambda: Config())
    assert get_root() == DEFAULT_ROOT


# ---------------------------------------------------------------------------
# get_author resolution
# ---------------------------------------------------------------------------

def test_get_author_override_wins(monkeypatch):
    monkeypatch.setenv("TEXTFORUMS_AUTHOR", "env-author")
    assert get_author("explicit") == "explicit"


def test_get_author_env_over_config(monkeypatch):
    monkeypatch.setenv("TEXTFORUMS_AUTHOR", "env-author")
    assert get_author() == "env-author"


def test_get_author_config_fallback(monkeypatch):
    monkeypatch.delenv("TEXTFORUMS_AUTHOR", raising=False)
    from textworkspace import config as cfg_mod
    from textworkspace.config import Config
    monkeypatch.setattr(cfg_mod, "load_config", lambda: Config(forums={"author": "cfg-author"}))
    assert get_author() == "cfg-author"


def test_get_author_user_env_last_resort(monkeypatch):
    monkeypatch.delenv("TEXTFORUMS_AUTHOR", raising=False)
    monkeypatch.setenv("USER", "system-user")
    from textworkspace import config as cfg_mod
    from textworkspace.config import Config
    monkeypatch.setattr(cfg_mod, "load_config", lambda: Config())
    assert get_author() == "system-user"
