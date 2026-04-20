"""Tests for textworkspace.forums."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from textworkspace.forums import (
    Entry,
    Thread,
    ThreadLink,
    ThreadMeta,
    add_entry,
    cli,
    forums,
    get_author,
    get_root,
    list_tags,
    list_threads,
    load_thread,
    save_thread,
    search_threads,
    slug_from_title,
    stale_threads,
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


# ---------------------------------------------------------------------------
# test_list_tags
# ---------------------------------------------------------------------------

def test_list_tags_empty_root(tmp_path):
    """list_tags returns empty list for nonexistent root."""
    result = list_tags(tmp_path / "nonexistent")
    assert result == []


def test_list_tags_no_tags(tmp_path):
    """list_tags returns empty list when threads have no tags."""
    _make_and_save(tmp_path, "thread-a", "open", [])
    _make_and_save(tmp_path, "thread-b", "open", [])
    result = list_tags(tmp_path)
    assert result == []


def test_list_tags_collects_unique_tags(tmp_path):
    """list_tags collects and deduplicates tags from all threads."""
    _make_and_save(tmp_path, "thread-a", "open", ["python", "dev"])
    _make_and_save(tmp_path, "thread-b", "open", ["rust", "dev"])
    _make_and_save(tmp_path, "thread-c", "open", ["python"])
    result = list_tags(tmp_path)
    assert result == ["dev", "python", "rust"]  # sorted


def test_list_tags_sorted(tmp_path):
    """list_tags returns tags in alphabetical order."""
    _make_and_save(tmp_path, "thread-a", "open", ["zebra", "apple", "monkey"])
    result = list_tags(tmp_path)
    assert result == ["apple", "monkey", "zebra"]


# ---------------------------------------------------------------------------
# test_forums_tags command
# ---------------------------------------------------------------------------

def test_forums_tags_shows_tags(tmp_path):
    """forums tags command displays all unique tags."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Python Post", "--tag", "python", "--tag", "dev", "--content", "content"])
    runner.invoke(forums, ["new", "--title", "Rust Post", "--tag", "rust", "--tag", "dev", "--content", "content"])
    result = runner.invoke(forums, ["tags"])
    assert result.exit_code == 0, result.output
    assert "dev" in result.output
    assert "python" in result.output
    assert "rust" in result.output


def test_forums_tags_no_tags(tmp_path):
    """forums tags command shows message when no tags exist."""
    runner = _runner(tmp_path)
    result = runner.invoke(forums, ["tags"])
    assert result.exit_code == 0, result.output
    assert "No tags found" in result.output


def test_forums_tags_sorted_output(tmp_path):
    """forums tags command outputs tags in sorted order."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "A", "--tag", "zebra", "--content", "c"])
    runner.invoke(forums, ["new", "--title", "B", "--tag", "apple", "--content", "c"])
    result = runner.invoke(forums, ["tags"])
    assert result.exit_code == 0, result.output
    # Find positions of each tag in output
    output_lines = result.output.strip().split("\n")
    assert output_lines[0] == "apple"
    assert output_lines[1] == "zebra"


# ---------------------------------------------------------------------------
# ThreadLink — data model
# ---------------------------------------------------------------------------

def test_thread_link_round_trip(tmp_path):
    """ThreadLink survives save/load round-trip."""
    meta = ThreadMeta(
        title="Source Thread",
        created="2026-04-20T10:00:00Z",
        author="alice",
        tags=[],
        status="open",
        links=[
            ThreadLink(rel="blocks", slug="target-thread", note="waiting on fix"),
            ThreadLink(rel="relates-to", slug="another-thread", note=""),
        ],
    )
    thread = Thread(meta=meta, entries=[], path=tmp_path / "source-thread" / "thread.yaml")
    save_thread(thread)

    loaded = load_thread(tmp_path, "source-thread")
    assert len(loaded.meta.links) == 2
    assert loaded.meta.links[0].rel == "blocks"
    assert loaded.meta.links[0].slug == "target-thread"
    assert loaded.meta.links[0].note == "waiting on fix"
    assert loaded.meta.links[1].rel == "relates-to"
    assert loaded.meta.links[1].slug == "another-thread"


def test_thread_no_links_omits_field(tmp_path):
    """Threads with no links serialize without 'links' key."""
    import yaml
    thread = _make_thread(tmp_path, slug="no-links")
    save_thread(thread)
    raw = yaml.safe_load((tmp_path / "no-links" / "thread.yaml").read_text())
    assert "links" not in raw["meta"]


def test_thread_links_empty_on_load_without_field(tmp_path):
    """Threads saved without links field deserialize to empty links list."""
    thread = _make_thread(tmp_path, slug="old-thread")
    save_thread(thread)
    loaded = load_thread(tmp_path, "old-thread")
    assert loaded.meta.links == []


# ---------------------------------------------------------------------------
# forums link CLI
# ---------------------------------------------------------------------------

def test_forums_link_creates_link(tmp_path):
    """forums link adds a link to the source thread."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Source", "--content", "src"])
    runner.invoke(forums, ["new", "--title", "Target", "--content", "tgt"])
    result = runner.invoke(forums, ["link", "source", "target", "--rel", "blocks"])
    assert result.exit_code == 0, result.output
    assert "source --[blocks]--> target" in result.output

    thread = load_thread(tmp_path, "source")
    assert len(thread.meta.links) == 1
    assert thread.meta.links[0].rel == "blocks"
    assert thread.meta.links[0].slug == "target"


def test_forums_link_default_rel_is_relates_to(tmp_path):
    """forums link defaults --rel to 'relates-to'."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Alpha", "--content", "a"])
    runner.invoke(forums, ["new", "--title", "Beta", "--content", "b"])
    runner.invoke(forums, ["link", "alpha", "beta"])

    thread = load_thread(tmp_path, "alpha")
    assert thread.meta.links[0].rel == "relates-to"


def test_forums_link_with_note(tmp_path):
    """forums link stores an optional note."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "A", "--content", "a"])
    runner.invoke(forums, ["new", "--title", "B", "--content", "b"])
    runner.invoke(forums, ["link", "a", "b", "--rel", "blocks", "--note", "PR #42"])

    thread = load_thread(tmp_path, "a")
    assert thread.meta.links[0].note == "PR #42"


def test_forums_link_duplicate_rejected(tmp_path):
    """forums link rejects a duplicate (same rel + target) link."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "A", "--content", "a"])
    runner.invoke(forums, ["new", "--title", "B", "--content", "b"])
    runner.invoke(forums, ["link", "a", "b", "--rel", "blocks"])
    result = runner.invoke(forums, ["link", "a", "b", "--rel", "blocks"])
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_forums_link_warns_missing_target(tmp_path):
    """forums link warns (stderr) when target thread doesn't exist."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Source", "--content", "src"])
    result = runner.invoke(forums, ["link", "source", "nonexistent", "--rel", "relates-to"], catch_exceptions=False)
    assert result.exit_code == 0
    # Check that warning appears in mix_stderr output
    assert "nonexistent" in result.output


def test_forums_link_source_not_found(tmp_path):
    """forums link fails when source thread doesn't exist."""
    runner = _runner(tmp_path)
    result = runner.invoke(forums, ["link", "no-such-thread", "other", "--rel", "blocks"])
    assert result.exit_code != 0
    assert "not found" in result.output


# ---------------------------------------------------------------------------
# forums unlink CLI
# ---------------------------------------------------------------------------

def test_forums_unlink_removes_link(tmp_path):
    """forums unlink removes a specific link."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "A", "--content", "a"])
    runner.invoke(forums, ["new", "--title", "B", "--content", "b"])
    runner.invoke(forums, ["link", "a", "b", "--rel", "blocks"])
    result = runner.invoke(forums, ["unlink", "a", "b", "--rel", "blocks"])
    assert result.exit_code == 0, result.output
    assert "Removed 1 link" in result.output

    thread = load_thread(tmp_path, "a")
    assert thread.meta.links == []


def test_forums_unlink_all_rels_to_target(tmp_path):
    """forums unlink without --rel removes all links to target."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "A", "--content", "a"])
    runner.invoke(forums, ["new", "--title", "B", "--content", "b"])
    runner.invoke(forums, ["link", "a", "b", "--rel", "blocks"])
    runner.invoke(forums, ["link", "a", "b", "--rel", "relates-to"])
    result = runner.invoke(forums, ["unlink", "a", "b"])
    assert result.exit_code == 0, result.output
    assert "Removed 2 link" in result.output

    thread = load_thread(tmp_path, "a")
    assert thread.meta.links == []


def test_forums_unlink_no_match_fails(tmp_path):
    """forums unlink fails when no matching link exists."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "A", "--content", "a"])
    result = runner.invoke(forums, ["unlink", "a", "nonexistent"])
    assert result.exit_code != 0
    assert "No matching link" in result.output


# ---------------------------------------------------------------------------
# forums show — links display
# ---------------------------------------------------------------------------

def test_forums_show_displays_links(tmp_path):
    """forums show renders links section."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Source", "--content", "src"])
    runner.invoke(forums, ["new", "--title", "Target", "--content", "tgt"])
    runner.invoke(forums, ["link", "source", "target", "--rel", "blocks", "--note", "see #99"])
    result = runner.invoke(forums, ["show", "source"])
    assert result.exit_code == 0, result.output
    assert "Links:" in result.output
    assert "blocks" in result.output
    assert "target" in result.output
    assert "see #99" in result.output


def test_forums_show_no_links_omits_section(tmp_path):
    """forums show omits Links section when thread has no links."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Solo", "--content", "alone"])
    result = runner.invoke(forums, ["show", "solo"])
    assert result.exit_code == 0, result.output
    assert "Links:" not in result.output


# ---------------------------------------------------------------------------
# forums list — link count column
# ---------------------------------------------------------------------------

def test_forums_list_shows_link_count(tmp_path):
    """forums list includes a LINKS column."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "A", "--content", "a"])
    runner.invoke(forums, ["new", "--title", "B", "--content", "b"])
    runner.invoke(forums, ["link", "a", "b", "--rel", "blocks"])
    result = runner.invoke(forums, ["list"])
    assert result.exit_code == 0, result.output
    assert "LINKS" in result.output


# ---------------------------------------------------------------------------
# forums bulk-close
# ---------------------------------------------------------------------------

def test_forums_bulk_close_closes_matching_threads(tmp_path):
    """forums bulk-close closes all matching threads."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Thread One", "--tag", "bug", "--content", "open"])
    runner.invoke(forums, ["new", "--title", "Thread Two", "--tag", "bug", "--content", "open"])
    runner.invoke(forums, ["new", "--title", "Thread Three", "--tag", "feature", "--content", "open"])

    result = runner.invoke(forums, ["bulk-close", "--tag", "bug", "--force"])
    assert result.exit_code == 0, result.output
    assert "Closed 2 thread(s)." in result.output

    # Verify threads are closed
    thread_one = load_thread(tmp_path, "thread-one")
    thread_two = load_thread(tmp_path, "thread-two")
    thread_three = load_thread(tmp_path, "thread-three")
    assert thread_one.meta.status == "resolved"
    assert thread_two.meta.status == "resolved"
    assert thread_three.meta.status == "open"  # not closed


def test_forums_bulk_close_with_status_filter(tmp_path):
    """forums bulk-close filters by status."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Open Thread", "--content", "open"])
    runner.invoke(forums, ["new", "--title", "Closed Thread", "--content", "will close"])
    runner.invoke(forums, ["close", "closed-thread"])

    result = runner.invoke(forums, ["bulk-close", "--status", "open", "--force"])
    assert result.exit_code == 0, result.output
    assert "Closed 1 thread(s)." in result.output

    open_thread = load_thread(tmp_path, "open-thread")
    closed_thread = load_thread(tmp_path, "closed-thread")
    assert open_thread.meta.status == "resolved"
    assert closed_thread.meta.status == "resolved"


def test_forums_bulk_close_with_content(tmp_path):
    """forums bulk-close adds closing entry with content."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Issue A", "--tag", "bug", "--content", "open"])
    runner.invoke(forums, ["new", "--title", "Issue B", "--tag", "bug", "--content", "open"])

    result = runner.invoke(forums, ["bulk-close", "--tag", "bug", "--content", "bulk resolved", "--force"])
    assert result.exit_code == 0, result.output
    assert "Closed 2 thread(s)." in result.output

    thread_a = load_thread(tmp_path, "issue-a")
    thread_b = load_thread(tmp_path, "issue-b")
    # Each thread should have an extra entry
    assert len(thread_a.entries) == 2
    assert len(thread_b.entries) == 2
    # Last entry should be the closing note
    assert thread_a.entries[-1].content == "bulk resolved"
    assert thread_b.entries[-1].content == "bulk resolved"
    assert thread_a.entries[-1].status == "resolved"
    assert thread_b.entries[-1].status == "resolved"


def test_forums_bulk_close_no_matches(tmp_path):
    """forums bulk-close shows message when no threads match."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Some Thread", "--tag", "dev", "--content", "open"])

    result = runner.invoke(forums, ["bulk-close", "--tag", "nonexistent", "--force"])
    assert result.exit_code == 0, result.output
    assert "No threads matching filters" in result.output


def test_forums_bulk_close_requires_confirmation(tmp_path):
    """forums bulk-close asks for confirmation (can be skipped with --force)."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Thread", "--tag", "bug", "--content", "open"])

    # Without --force, sends 'n' to reject confirmation
    result = runner.invoke(forums, ["bulk-close", "--tag", "bug"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Aborted" in result.output

    # Thread should still be open
    thread = load_thread(tmp_path, "thread")
    assert thread.meta.status == "open"


def test_forums_bulk_close_confirm_closes_threads(tmp_path):
    """forums bulk-close closes threads when user confirms."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Thread", "--tag", "bug", "--content", "open"])

    # Send 'y' to confirm
    result = runner.invoke(forums, ["bulk-close", "--tag", "bug"], input="y\n")
    assert result.exit_code == 0, result.output
    assert "Closed 1 thread(s)." in result.output

    # Thread should be closed
    thread = load_thread(tmp_path, "thread")
    assert thread.meta.status == "resolved"


def test_forums_bulk_close_lists_matching_threads(tmp_path):
    """forums bulk-close shows what will be closed before asking for confirmation."""
    runner = _runner(tmp_path)
    runner.invoke(forums, ["new", "--title", "Bug One", "--tag", "bug", "--content", "first"])
    runner.invoke(forums, ["new", "--title", "Bug Two", "--tag", "bug", "--content", "second"])

    result = runner.invoke(forums, ["bulk-close", "--tag", "bug", "--force"])
    assert result.exit_code == 0, result.output
    assert "Found 2 thread(s) to close:" in result.output
    assert "bug-one" in result.output
    assert "bug-two" in result.output
    assert "Bug One" in result.output
    assert "Bug Two" in result.output


# ---------------------------------------------------------------------------
# stale_threads
# ---------------------------------------------------------------------------

def _make_thread_with_timestamps(root: Path, slug: str, created: str, last_entry_ts: str | None = None) -> Thread:
    """Create a thread with specific timestamps for staleness testing."""
    meta = ThreadMeta(
        title=slug.replace("-", " ").title(),
        created=created,
        author="x",
        tags=[],
        status="open",
    )
    entries = []
    if last_entry_ts:
        entries.append(Entry(author="x", timestamp=last_entry_ts, status="", content="reply"))
    thread = Thread(meta=meta, entries=entries, path=root / slug / "thread.yaml")
    save_thread(thread)
    return thread


def test_stale_threads_returns_old_open_threads(tmp_path):
    """stale_threads returns open threads idle for >= age_days days."""
    _make_thread_with_timestamps(tmp_path, "old-thread", "2020-01-01T00:00:00Z")
    result = stale_threads(tmp_path, age_days=14)
    assert len(result) == 1
    slug, days = result[0]
    assert slug == "old-thread"
    assert days > 365  # much older than 14 days


def test_stale_threads_excludes_recent_threads(tmp_path):
    """stale_threads ignores threads active within age_days days."""
    from datetime import datetime, timezone, timedelta
    recent_ts = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _make_thread_with_timestamps(tmp_path, "recent-thread", recent_ts)
    result = stale_threads(tmp_path, age_days=14)
    assert result == []


def test_stale_threads_excludes_resolved_threads(tmp_path):
    """stale_threads ignores resolved threads even if old."""
    meta = ThreadMeta(
        title="Old Resolved",
        created="2020-01-01T00:00:00Z",
        author="x",
        tags=[],
        status="resolved",
    )
    thread = Thread(meta=meta, entries=[], path=tmp_path / "old-resolved" / "thread.yaml")
    save_thread(thread)
    result = stale_threads(tmp_path, age_days=14)
    assert result == []


def test_stale_threads_uses_last_entry_timestamp(tmp_path):
    """stale_threads computes staleness from last entry, not created date."""
    from datetime import datetime, timezone, timedelta
    # Thread created long ago but last entry is recent
    recent_ts = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _make_thread_with_timestamps(tmp_path, "recent-reply", "2020-01-01T00:00:00Z", last_entry_ts=recent_ts)
    result = stale_threads(tmp_path, age_days=14)
    assert result == []


def test_stale_threads_empty_root(tmp_path):
    """stale_threads returns empty list for nonexistent root."""
    result = stale_threads(tmp_path / "nonexistent", age_days=14)
    assert result == []


# ---------------------------------------------------------------------------
# forums doctor CLI
# ---------------------------------------------------------------------------

def test_forums_doctor_outputs_stale_lines(tmp_path):
    """forums doctor outputs STALE <slug> <days>d for stale open threads."""
    runner = _runner(tmp_path)
    # Create an old thread
    meta = ThreadMeta(
        title="Old Bug",
        created="2020-06-01T00:00:00Z",
        author="tester",
        tags=[],
        status="open",
    )
    thread = Thread(meta=meta, entries=[], path=tmp_path / "old-bug" / "thread.yaml")
    save_thread(thread)

    result = runner.invoke(forums, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "STALE old-bug" in result.output
    assert "d" in result.output  # age in days


def test_forums_doctor_no_stale_threads_silent(tmp_path):
    """forums doctor produces no output when no threads are stale."""
    from datetime import datetime, timezone, timedelta
    runner = _runner(tmp_path)
    recent_ts = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = ThreadMeta(
        title="Fresh Thread",
        created=recent_ts,
        author="tester",
        tags=[],
        status="open",
    )
    thread = Thread(meta=meta, entries=[], path=tmp_path / "fresh-thread" / "thread.yaml")
    save_thread(thread)

    result = runner.invoke(forums, ["doctor"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == ""


def test_forums_doctor_age_days_option(tmp_path):
    """forums doctor --age-days controls the staleness threshold."""
    from datetime import datetime, timezone, timedelta
    runner = _runner(tmp_path)
    # Thread 5 days old
    ts = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = ThreadMeta(
        title="Mid Age",
        created=ts,
        author="tester",
        tags=[],
        status="open",
    )
    thread = Thread(meta=meta, entries=[], path=tmp_path / "mid-age" / "thread.yaml")
    save_thread(thread)

    # Not stale with default 14-day threshold
    result = runner.invoke(forums, ["doctor"])
    assert result.exit_code == 0
    assert "STALE" not in result.output

    # Stale with 3-day threshold
    result = runner.invoke(forums, ["doctor", "--age-days", "3"])
    assert result.exit_code == 0
    assert "STALE mid-age" in result.output


def test_forums_doctor_ignores_resolved_threads(tmp_path):
    """forums doctor does not flag resolved threads even if old."""
    runner = _runner(tmp_path)
    meta = ThreadMeta(
        title="Old Resolved",
        created="2020-01-01T00:00:00Z",
        author="tester",
        tags=[],
        status="resolved",
    )
    thread = Thread(meta=meta, entries=[], path=tmp_path / "old-resolved" / "thread.yaml")
    save_thread(thread)

    result = runner.invoke(forums, ["doctor"])
    assert result.exit_code == 0
    assert "STALE" not in result.output
