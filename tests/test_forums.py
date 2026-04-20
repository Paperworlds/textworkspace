"""Tests for textworkspace.forums."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from textworkspace.forums import (
    Entry,
    Thread,
    ThreadMeta,
    add_entry,
    cli,
    forums,
    get_author,
    get_root,
    list_threads,
    load_thread,
    save_thread,
    search_threads,
    slug_from_title,
    DEFAULT_ROOT,
)
from textworkspace.cli import main


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


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _runner(tmp_path: Path) -> CliRunner:
    return CliRunner(env={"TEXTFORUMS_ROOT": str(tmp_path), "TEXTFORUMS_AUTHOR": "tester"})


# ---------------------------------------------------------------------------
# test_forums_new_creates_file
# ---------------------------------------------------------------------------

def test_forums_new_creates_file(tmp_path):
    runner = _runner(tmp_path)
    result = runner.invoke(forums, ["new", "--title", "My First Thread", "--content", "Hello!"])
    assert result.exit_code == 0, result.output
    slug = result.output.strip()
    thread_file = tmp_path / slug / "thread.yaml"
    assert thread_file.exists()
    thread = load_thread(tmp_path, slug)
    assert thread.meta.title == "My First Thread"
    assert len(thread.entries) == 1
    assert thread.entries[0].content == "Hello!"


# ---------------------------------------------------------------------------
# test_forums_list_shows_thread
# ---------------------------------------------------------------------------

def test_forums_list_shows_thread(tmp_path):
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Visible Thread", "--content", "content"])
    result = runner.invoke(forums, ["list"])
    assert result.exit_code == 0, result.output
    assert "visible-thread" in result.output
    assert "open" in result.output


# ---------------------------------------------------------------------------
# test_forums_show_displays_entries
# ---------------------------------------------------------------------------

def test_forums_show_displays_entries(tmp_path):
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Show Me", "--content", "Entry content here"])
    result = runner.invoke(forums, ["show", "show-me"])
    assert result.exit_code == 0, result.output
    assert "Show Me" in result.output
    assert "Entry content here" in result.output


def test_forums_show_raw(tmp_path):
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Raw Thread", "--content", "raw content"])
    result = runner.invoke(forums, ["show", "raw-thread", "--raw"])
    assert result.exit_code == 0, result.output
    assert "meta:" in result.output
    assert "entries:" in result.output


# ---------------------------------------------------------------------------
# test_forums_add_appends_entry
# ---------------------------------------------------------------------------

def test_forums_add_appends_entry(tmp_path):
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Add Test", "--content", "original"])
    result = runner.invoke(forums, ["add", "add-test", "--content", "appended entry"])
    assert result.exit_code == 0, result.output
    thread = load_thread(tmp_path, "add-test")
    assert len(thread.entries) == 2
    assert thread.entries[-1].content == "appended entry"


def test_forums_add_with_file(tmp_path):
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "File Test", "--content", "initial"])
    attachment = tmp_path / "note.txt"
    attachment.write_text("attached")
    result = runner.invoke(forums, ["add", "file-test", "--content", "with file", "--file", str(attachment)])
    assert result.exit_code == 0, result.output
    thread = load_thread(tmp_path, "file-test")
    assert "note.txt" in thread.entries[-1].files


# ---------------------------------------------------------------------------
# test_forums_close_sets_resolved
# ---------------------------------------------------------------------------

def test_forums_close_sets_resolved(tmp_path):
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Close Me", "--content", "open"])
    result = runner.invoke(forums, ["close", "close-me"])
    assert result.exit_code == 0, result.output
    thread = load_thread(tmp_path, "close-me")
    assert thread.meta.status == "resolved"


def test_forums_close_with_content_appends_entry(tmp_path):
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Close With Note", "--content", "open"])
    runner.invoke(forums, ["close", "close-with-note", "--content", "closing note"])
    thread = load_thread(tmp_path, "close-with-note")
    assert thread.meta.status == "resolved"
    assert thread.entries[-1].content == "closing note"


# ---------------------------------------------------------------------------
# test_forums_reopen
# ---------------------------------------------------------------------------

def test_forums_reopen(tmp_path):
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Reopen Me", "--content", "open"])
    runner.invoke(forums, ["close", "reopen-me"])
    result = runner.invoke(forums, ["reopen", "reopen-me"])
    assert result.exit_code == 0, result.output
    thread = load_thread(tmp_path, "reopen-me")
    assert thread.meta.status == "open"


# ---------------------------------------------------------------------------
# test_forums_edit_opens_editor
# ---------------------------------------------------------------------------

def test_forums_edit_opens_editor(tmp_path):
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Edit Me", "--content", "before edit"])
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = None
        result = runner.invoke(forums, ["edit", "edit-me"], env={"TEXTFORUMS_ROOT": str(tmp_path), "EDITOR": "nano"})
    assert result.exit_code == 0, result.output
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[0] == "nano"
    assert "thread.yaml" in args[1]


# ---------------------------------------------------------------------------
# test_standalone_entry_point
# ---------------------------------------------------------------------------

def test_standalone_entry_point(tmp_path, monkeypatch):
    """cli() delegates to the forums group in standalone mode."""
    monkeypatch.setenv("TEXTFORUMS_ROOT", str(tmp_path))
    monkeypatch.setenv("TEXTFORUMS_AUTHOR", "tester")
    import sys
    monkeypatch.setattr(sys, "argv", ["textforums", "list"])
    with pytest.raises(SystemExit) as exc_info:
        cli()
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# test_tw_forums_subcommand
# ---------------------------------------------------------------------------

def test_tw_forums_subcommand(tmp_path):
    runner = CliRunner(env={"TEXTFORUMS_ROOT": str(tmp_path), "TEXTFORUMS_AUTHOR": "tester"})
    result = runner.invoke(main, ["forums", "list"])
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# test_search_threads — by title
# ---------------------------------------------------------------------------

def test_search_threads_by_title(tmp_path):
    """Search finds threads by title."""
    _make_and_save(tmp_path, "python-post", "open", [])
    _make_and_save(tmp_path, "rust-post", "open", [])

    results = search_threads(tmp_path, "python")
    assert len(results) == 1
    thread, _ = results[0]
    assert "python" in thread.meta.title.lower()


def test_search_threads_case_insensitive(tmp_path):
    """Search is case-insensitive."""
    _make_and_save(tmp_path, "test-thread", "open", [])

    results_lower = search_threads(tmp_path, "test")
    results_upper = search_threads(tmp_path, "TEST")
    assert len(results_lower) == 1
    assert len(results_upper) == 1


# ---------------------------------------------------------------------------
# test_search_threads — by content
# ---------------------------------------------------------------------------

def test_search_threads_by_content(tmp_path):
    """Search finds threads by entry content."""
    meta = ThreadMeta(
        title="General Discussion",
        created="2026-04-14T00:00:00Z",
        author="x",
        tags=[],
        status="open",
    )
    entry1 = Entry(author="alice", timestamp="2026-04-14T00:00:00Z", status="", content="discussing algorithms")
    entry2 = Entry(author="bob", timestamp="2026-04-14T01:00:00Z", status="", content="algorithms are cool")
    thread = Thread(meta=meta, entries=[entry1, entry2], path=tmp_path / "general" / "thread.yaml")
    save_thread(thread)

    results = search_threads(tmp_path, "algorithms")
    assert len(results) == 1
    thread_result, matching_entries = results[0]
    assert len(matching_entries) == 2
    assert 0 in matching_entries
    assert 1 in matching_entries


# ---------------------------------------------------------------------------
# test_search_threads — by tag
# ---------------------------------------------------------------------------

def test_search_threads_by_tag(tmp_path):
    """Search finds threads by tag."""
    _make_and_save(tmp_path, "python-post", "open", ["python", "dev"])
    _make_and_save(tmp_path, "rust-post", "open", ["rust"])

    results = search_threads(tmp_path, "python")
    assert len(results) == 1
    thread, _ = results[0]
    assert "python" in thread.meta.tags


def test_search_threads_partial_tag_match(tmp_path):
    """Search matches partial tag text."""
    _make_and_save(tmp_path, "thread-a", "open", ["debugging"])
    _make_and_save(tmp_path, "thread-b", "open", ["logging"])

    results = search_threads(tmp_path, "debug")
    assert len(results) == 1
    thread, _ = results[0]
    assert "debug" in thread.meta.tags[0].lower()


# ---------------------------------------------------------------------------
# test_search_threads — status filter
# ---------------------------------------------------------------------------

def test_search_threads_with_status_filter(tmp_path):
    """Search respects status filter."""
    meta1 = ThreadMeta(
        title="Open Issue",
        created="2026-04-14T00:00:00Z",
        author="x",
        tags=[],
        status="open",
    )
    entry1 = Entry(author="alice", timestamp="2026-04-14T00:00:00Z", status="", content="bug report")
    thread1 = Thread(meta=meta1, entries=[entry1], path=tmp_path / "open-issue" / "thread.yaml")
    save_thread(thread1)

    meta2 = ThreadMeta(
        title="Closed Issue",
        created="2026-04-14T00:00:00Z",
        author="x",
        tags=[],
        status="resolved",
    )
    entry2 = Entry(author="bob", timestamp="2026-04-14T00:00:00Z", status="", content="bug report fixed")
    thread2 = Thread(meta=meta2, entries=[entry2], path=tmp_path / "closed-issue" / "thread.yaml")
    save_thread(thread2)

    all_results = search_threads(tmp_path, "bug")
    assert len(all_results) == 2

    open_results = search_threads(tmp_path, "bug", status="open")
    assert len(open_results) == 1
    assert open_results[0][0].meta.status == "open"


# ---------------------------------------------------------------------------
# test_forums_search CLI
# ---------------------------------------------------------------------------

def test_forums_search_by_title_cli(tmp_path):
    """CLI search finds threads by title."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Python Tutorial", "--content", "content"])
    runner.invoke(forums, ["new", "--title", "Rust Guide", "--content", "content"])
    result = runner.invoke(forums, ["search", "python"])
    assert result.exit_code == 0, result.output
    assert "python-tutorial" in result.output
    assert "title" in result.output.lower()


def test_forums_search_no_results_cli(tmp_path):
    """CLI search shows 'No matches found' when no results."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Some Thread", "--content", "content"])
    result = runner.invoke(forums, ["search", "nonexistent"])
    assert result.exit_code == 0, result.output
    assert "No matches found" in result.output


def test_forums_search_with_status_filter_cli(tmp_path):
    """CLI search respects --status filter."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Bug Report", "--content", "found a bug"])
    runner.invoke(forums, ["close", "bug-report"])
    result = runner.invoke(forums, ["search", "bug", "--status", "open"])
    assert result.exit_code == 0, result.output
    assert "No matches found" in result.output
