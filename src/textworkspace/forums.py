"""Core data structures, I/O, and CLI for textforums."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml

from textworkspace import __version__

DEFAULT_ROOT = Path.home() / ".textforums"

_THREAD_FILE = "thread.yaml"


# ---------------------------------------------------------------------------
# Root / author resolution
# ---------------------------------------------------------------------------

def get_root() -> Path:
    """Resolve forums root: $TEXTFORUMS_ROOT > config.forums.root > default."""
    env = os.environ.get("TEXTFORUMS_ROOT")
    if env:
        return Path(env)
    try:
        from textworkspace.config import load_config
        cfg = load_config()
        root_str = cfg.forums.get("root")
        if root_str:
            return Path(root_str).expanduser()
    except Exception:
        pass
    return DEFAULT_ROOT


def get_author(override: str | None = None) -> str:
    """Resolve author: override > $TEXTFORUMS_AUTHOR > config.forums.author > $USER."""
    if override:
        return override
    env = os.environ.get("TEXTFORUMS_AUTHOR")
    if env:
        return env
    try:
        from textworkspace.config import load_config
        cfg = load_config()
        author = cfg.forums.get("author")
        if author:
            return author
    except Exception:
        pass
    return os.environ.get("USER", "unknown")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ThreadLink:
    rel: str    # e.g. "blocks", "blocked-by", "relates-to"
    slug: str   # target thread slug
    note: str = ""


@dataclass
class ThreadMeta:
    title: str
    created: str           # ISO 8601
    author: str
    tags: list[str] = field(default_factory=list)
    status: str = "open"
    links: list[ThreadLink] = field(default_factory=list)


@dataclass
class Entry:
    author: str
    timestamp: str         # ISO 8601
    status: str
    content: str
    files: list[str] = field(default_factory=list)  # relative paths


@dataclass
class Thread:
    meta: ThreadMeta
    entries: list[Entry]
    path: Path             # file path on disk


# ---------------------------------------------------------------------------
# Slug
# ---------------------------------------------------------------------------

def slug_from_title(title: str) -> str:
    """Lowercase, replace non-alnum with hyphens, strip edges, truncate to 60 chars."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:60]


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _meta_to_dict(meta: ThreadMeta) -> dict:
    d: dict = {
        "title": meta.title,
        "created": meta.created,
        "author": meta.author,
        "tags": meta.tags,
        "status": meta.status,
    }
    if meta.links:
        d["links"] = [{"rel": lnk.rel, "slug": lnk.slug, "note": lnk.note} for lnk in meta.links]
    return d


def _entry_to_dict(entry: Entry) -> dict:
    return {
        "author": entry.author,
        "timestamp": entry.timestamp,
        "status": entry.status,
        "content": entry.content,
        "files": entry.files,
    }


def _parse_meta(data: dict) -> ThreadMeta:
    raw_links = data.get("links") or []
    links = [
        ThreadLink(rel=lnk["rel"], slug=lnk["slug"], note=lnk.get("note", ""))
        for lnk in raw_links
    ]
    return ThreadMeta(
        title=data["title"],
        created=data["created"],
        author=data["author"],
        tags=data.get("tags") or [],
        status=data.get("status", "open"),
        links=links,
    )


def _parse_entry(data: dict) -> Entry:
    return Entry(
        author=data["author"],
        timestamp=data["timestamp"],
        status=data.get("status", ""),
        content=data.get("content", ""),
        files=data.get("files") or [],
    )


def _thread_to_dict(thread: Thread) -> dict:
    return {
        "meta": _meta_to_dict(thread.meta),
        "entries": [_entry_to_dict(e) for e in thread.entries],
    }


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_thread(root: Path, slug: str) -> Thread:
    """Load a thread from <root>/<slug>/thread.yaml."""
    path = root / slug / _THREAD_FILE
    with path.open() as f:
        raw = yaml.safe_load(f) or {}
    meta = _parse_meta(raw["meta"])
    entries = [_parse_entry(e) for e in (raw.get("entries") or [])]
    return Thread(meta=meta, entries=entries, path=path)


def save_thread(thread: Thread) -> None:
    """Save thread to its path."""
    thread.path.parent.mkdir(parents=True, exist_ok=True)
    with thread.path.open("w") as f:
        yaml.dump(_thread_to_dict(thread), f, default_flow_style=False, allow_unicode=True)


def list_threads(root: Path, status: str | None = None, tag: str | None = None) -> list[Thread]:
    """Return threads under root, optionally filtered by status and/or tag."""
    threads: list[Thread] = []
    if not root.exists():
        return threads
    for slug_dir in sorted(root.iterdir()):
        thread_file = slug_dir / _THREAD_FILE
        if not (slug_dir.is_dir() and thread_file.exists()):
            continue
        try:
            thread = load_thread(root, slug_dir.name)
        except Exception:
            continue
        if status is not None and thread.meta.status != status:
            continue
        if tag is not None and tag not in thread.meta.tags:
            continue
        threads.append(thread)
    return threads


def add_entry(thread: Thread, entry: Entry, files: list[Path] | None = None) -> None:
    """Append entry to thread, copy files to slug subdir if provided, save."""
    if files:
        slug_dir = thread.path.parent
        slug_dir.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        for src in files:
            dest = slug_dir / src.name
            shutil.copy2(src, dest)
            copied.append(src.name)
        entry.files = copied
    thread.entries.append(entry)
    save_thread(thread)


def search_threads(root: Path, query: str, status: str | None = None) -> list[tuple[Thread, list[int]]]:
    """Search threads by title, entry content, and tags. Returns (thread, matching_entry_indices)."""
    query_lower = query.lower()
    results: list[tuple[Thread, list[int]]] = []

    if not root.exists():
        return results

    for slug_dir in sorted(root.iterdir()):
        thread_file = slug_dir / _THREAD_FILE
        if not (slug_dir.is_dir() and thread_file.exists()):
            continue
        try:
            thread = load_thread(root, slug_dir.name)
        except Exception:
            continue

        if status is not None and thread.meta.status != status:
            continue

        # Check if query matches title
        title_match = query_lower in thread.meta.title.lower()

        # Check if query matches any tag
        tag_match = any(query_lower in tag.lower() for tag in thread.meta.tags)

        # Check if query matches any entry content
        matching_entries: list[int] = []
        for i, entry in enumerate(thread.entries):
            if query_lower in entry.content.lower():
                matching_entries.append(i)

        # Include thread if there's any match
        if title_match or tag_match or matching_entries:
            results.append((thread, matching_entries))

    return results


def stale_threads(root: Path, age_days: int = 14) -> list[tuple[str, int]]:
    """Return (slug, days_since_last_activity) for open threads idle for >= age_days days."""
    threads = list_threads(root, status="open")
    now = datetime.now(timezone.utc)
    result: list[tuple[str, int]] = []
    for thread in threads:
        last_ts = thread.meta.created
        if thread.entries:
            last_ts = thread.entries[-1].timestamp
        try:
            last_activity = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            days = (now - last_activity).days
            if days >= age_days:
                result.append((thread.path.parent.name, days))
        except Exception:
            continue
    return result


def list_tags(root: Path) -> list[str]:
    """Return all unique tags from all threads, sorted alphabetically."""
    tags_set: set[str] = set()
    if not root.exists():
        return []

    for slug_dir in root.iterdir():
        thread_file = slug_dir / _THREAD_FILE
        if not (slug_dir.is_dir() and thread_file.exists()):
            continue
        try:
            thread = load_thread(root, slug_dir.name)
            tags_set.update(thread.meta.tags)
        except Exception:
            continue

    return sorted(tags_set)


# ---------------------------------------------------------------------------
# Editor helper
# ---------------------------------------------------------------------------

def _open_in_editor(initial_text: str) -> str:
    """Open $EDITOR with initial_text and return the edited content."""
    editor = os.environ.get("EDITOR", "vi")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(initial_text)
        tmp = f.name
    try:
        subprocess.run([editor, tmp], check=True)
        return Path(tmp).read_text()
    finally:
        Path(tmp).unlink(missing_ok=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(__version__, "--version", "-V", prog_name="textforums")
def forums() -> None:
    """Manage textforums threads."""


def cli() -> None:
    """Standalone entry point for the `textforums` binary."""
    forums(standalone_mode=True)


# ---------------------------------------------------------------------------
# forums list
# ---------------------------------------------------------------------------

@forums.command("list")
@click.option("--status", "-s", default=None, help="Filter by status (open/resolved).")
@click.option("--tag", "-t", default=None, help="Filter by tag.")
def forums_list(status: str | None, tag: str | None) -> None:
    """List threads as a table."""
    root = get_root()
    threads = list_threads(root, status=status, tag=tag)
    if not threads:
        click.echo("No threads found.")
        return

    # Table header
    header = f"{'SLUG':<35} {'STATUS':<10} {'ENTRIES':>7}  {'LINKS':>5}  {'AGE':<12}  TITLE"
    click.echo(header)
    click.echo("-" * len(header))

    now = datetime.now(timezone.utc)
    for t in threads:
        slug = t.path.parent.name
        try:
            created = datetime.fromisoformat(t.meta.created.replace("Z", "+00:00"))
            delta = now - created
            days = delta.days
            age = f"{days}d" if days > 0 else f"{delta.seconds // 3600}h"
        except Exception:
            age = "?"
        link_count = len(t.meta.links)
        click.echo(f"{slug:<35} {t.meta.status:<10} {len(t.entries):>7}  {link_count:>5}  {age:<12}  {t.meta.title}")


# ---------------------------------------------------------------------------
# forums new
# ---------------------------------------------------------------------------

@forums.command("new")
@click.option("--title", "-T", required=True, help="Thread title.")
@click.option("--tag", "-t", "tags", multiple=True, help="Tag (repeatable).")
@click.option("--author", "-a", default=None, help="Author name.")
@click.option("--content", "-c", default=None, help="First entry content. Opens $EDITOR if omitted.")
def forums_new(title: str, tags: tuple[str, ...], author: str | None, content: str | None) -> None:
    """Create a new thread, optionally with a first entry."""
    root = get_root()
    slug = slug_from_title(title)
    thread_dir = root / slug
    if thread_dir.exists():
        raise click.ClickException(f"Thread '{slug}' already exists.")

    author = get_author(author)
    now = _now_iso()
    meta = ThreadMeta(title=title, created=now, author=author, tags=list(tags))
    thread = Thread(meta=meta, entries=[], path=thread_dir / _THREAD_FILE)

    if content is None:
        existing_tags = list_tags(root)
        tag_suggestions = f"# Available tags: {', '.join(existing_tags)}\n" if existing_tags else "# No tags yet.\n"
        template = (
            f"# New entry for: {title}\n"
            f"# Author: {author}\n"
            f"{tag_suggestions}"
            "# Write your entry below this line:\n\n"
        )
        content = _open_in_editor(template).strip()
        # Strip comment lines
        lines = [l for l in content.splitlines() if not l.startswith("#")]
        content = "\n".join(lines).strip()

    if content:
        entry = Entry(author=author, timestamp=now, status="open", content=content)
        thread.entries.append(entry)

    save_thread(thread)
    click.echo(slug)


# ---------------------------------------------------------------------------
# forums show
# ---------------------------------------------------------------------------

@forums.command("show")
@click.argument("slug")
@click.option("--raw", is_flag=True, default=False, help="Dump raw YAML.")
def forums_show(slug: str, raw: bool) -> None:
    """Display a thread's metadata and entries."""
    root = get_root()
    try:
        thread = load_thread(root, slug)
    except FileNotFoundError:
        raise click.ClickException(f"Thread '{slug}' not found.")

    if raw:
        click.echo(yaml.dump(_thread_to_dict(thread), default_flow_style=False, allow_unicode=True))
        return

    m = thread.meta
    click.echo(f"Title:   {m.title}")
    click.echo(f"Slug:    {slug}")
    click.echo(f"Status:  {m.status}")
    click.echo(f"Author:  {m.author}")
    click.echo(f"Created: {m.created}")
    if m.tags:
        click.echo(f"Tags:    {', '.join(m.tags)}")
    if m.links:
        click.echo("Links:")
        for lnk in m.links:
            note_str = f"  ({lnk.note})" if lnk.note else ""
            click.echo(f"  {lnk.rel} → {lnk.slug}{note_str}")
    click.echo(f"\n{len(thread.entries)} entr{'y' if len(thread.entries) == 1 else 'ies'}:")
    for i, e in enumerate(thread.entries, 1):
        click.echo(f"\n--- [{i}] {e.author} @ {e.timestamp} ---")
        if e.status:
            click.echo(f"Status: {e.status}")
        click.echo(e.content)
        if e.files:
            click.echo(f"Files: {', '.join(e.files)}")


# ---------------------------------------------------------------------------
# forums add
# ---------------------------------------------------------------------------

@forums.command("add")
@click.argument("slug")
@click.option("--content", "-c", default=None, help="Entry content. Opens $EDITOR if omitted.")
@click.option("--author", "-a", default=None, help="Author name.")
@click.option("--status", "-s", default="", help="Entry status tag.")
@click.option("--file", "-f", "file_paths", multiple=True, type=click.Path(exists=True, path_type=Path), help="File to attach (repeatable).")
def forums_add(slug: str, content: str | None, author: str | None, status: str, file_paths: tuple[Path, ...]) -> None:
    """Append an entry to a thread."""
    root = get_root()
    try:
        thread = load_thread(root, slug)
    except FileNotFoundError:
        raise click.ClickException(f"Thread '{slug}' not found.")

    author = get_author(author)

    if content is None:
        existing_tags = list_tags(root)
        tag_suggestions = f"# Available tags: {', '.join(existing_tags)}\n" if existing_tags else "# No tags yet.\n"
        template = (
            f"# Adding entry to: {slug}\n"
            f"# Author: {author}\n"
            f"{tag_suggestions}"
            "# Write your entry below this line:\n\n"
        )
        content = _open_in_editor(template).strip()
        lines = [l for l in content.splitlines() if not l.startswith("#")]
        content = "\n".join(lines).strip()

    entry = Entry(author=author, timestamp=_now_iso(), status=status, content=content)
    add_entry(thread, entry, files=list(file_paths) if file_paths else None)
    click.echo(f"Entry added to '{slug}'.")


# ---------------------------------------------------------------------------
# forums close
# ---------------------------------------------------------------------------

@forums.command("close")
@click.argument("slug")
@click.option("--content", "-c", default=None, help="Optional closing entry content.")
@click.option("--author", "-a", default=None, help="Author name.")
def forums_close(slug: str, content: str | None, author: str | None) -> None:
    """Set a thread's status to 'resolved'."""
    root = get_root()
    try:
        thread = load_thread(root, slug)
    except FileNotFoundError:
        raise click.ClickException(f"Thread '{slug}' not found.")

    thread.meta.status = "resolved"
    if content:
        author = get_author(author)
        entry = Entry(author=author, timestamp=_now_iso(), status="resolved", content=content)
        thread.entries.append(entry)
    save_thread(thread)
    click.echo(f"Thread '{slug}' closed.")


# ---------------------------------------------------------------------------
# forums bulk-close
# ---------------------------------------------------------------------------

@forums.command("bulk-close")
@click.option("--status", "-s", default=None, help="Filter by status (open/resolved).")
@click.option("--tag", "-t", default=None, help="Filter by tag.")
@click.option("--content", "-c", default=None, help="Optional closing entry content for each thread.")
@click.option("--force", "-f", is_flag=True, default=False, help="Skip confirmation prompt.")
@click.option("--author", "-a", default=None, help="Author name for closing entry.")
def forums_bulk_close(status: str | None, tag: str | None, content: str | None, force: bool, author: str | None) -> None:
    """Close all threads matching filters in bulk."""
    root = get_root()
    threads = list_threads(root, status=status, tag=tag)

    if not threads:
        click.echo("No threads matching filters.")
        return

    # Show what will be closed
    click.echo(f"Found {len(threads)} thread(s) to close:")
    for t in threads:
        slug = t.path.parent.name
        click.echo(f"  - {slug}: {t.meta.title}")

    # Ask for confirmation
    if not force:
        if not click.confirm("Close these threads?"):
            click.echo("Aborted.")
            return

    # Close each thread
    author_name = get_author(author)
    closed = 0
    for t in threads:
        t.meta.status = "resolved"
        if content:
            entry = Entry(author=author_name, timestamp=_now_iso(), status="resolved", content=content)
            t.entries.append(entry)
        save_thread(t)
        closed += 1

    click.echo(f"Closed {closed} thread(s).")


# ---------------------------------------------------------------------------
# forums edit
# ---------------------------------------------------------------------------

@forums.command("edit")
@click.argument("slug")
def forums_edit(slug: str) -> None:
    """Open the thread YAML in $EDITOR."""
    root = get_root()
    thread_file = root / slug / _THREAD_FILE
    if not thread_file.exists():
        raise click.ClickException(f"Thread '{slug}' not found.")
    editor = os.environ.get("EDITOR", "vi")
    subprocess.run([editor, str(thread_file)], check=True)


# ---------------------------------------------------------------------------
# forums reopen
# ---------------------------------------------------------------------------

@forums.command("reopen")
@click.argument("slug")
def forums_reopen(slug: str) -> None:
    """Set a thread's status back to 'open'."""
    root = get_root()
    try:
        thread = load_thread(root, slug)
    except FileNotFoundError:
        raise click.ClickException(f"Thread '{slug}' not found.")

    thread.meta.status = "open"
    save_thread(thread)
    click.echo(f"Thread '{slug}' reopened.")


# ---------------------------------------------------------------------------
# forums search
# ---------------------------------------------------------------------------

@forums.command("search")
@click.argument("query")
@click.option("--status", "-s", default=None, help="Filter by status (open/resolved).")
def forums_search(query: str, status: str | None) -> None:
    """Search threads by title, content, and tags."""
    root = get_root()
    results = search_threads(root, query, status=status)

    if not results:
        click.echo("No matches found.")
        return

    # Table header
    header = f"{'SLUG':<35} {'MATCH TYPE':<20}  TITLE"
    click.echo(header)
    click.echo("-" * len(header))

    for thread, matching_entries in results:
        slug = thread.path.parent.name
        match_types: list[str] = []

        # Determine what matched
        query_lower = query.lower()
        if query_lower in thread.meta.title.lower():
            match_types.append("title")
        if any(query_lower in tag.lower() for tag in thread.meta.tags):
            match_types.append(f"tag:{','.join(t for t in thread.meta.tags if query_lower in t.lower())}")
        if matching_entries:
            match_types.append(f"entries({len(matching_entries)})")

        match_str = ", ".join(match_types)
        click.echo(f"{slug:<35} {match_str:<20}  {thread.meta.title}")


# ---------------------------------------------------------------------------
# forums tags
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# forums link
# ---------------------------------------------------------------------------

VALID_RELS = ("blocks", "blocked-by", "relates-to")


@forums.command("link")
@click.argument("slug")
@click.argument("target")
@click.option("--rel", "-r", default="relates-to",
              help=f"Relationship type. Common: {', '.join(VALID_RELS)}.")
@click.option("--note", "-n", default="", help="Optional note about the relationship.")
def forums_link(slug: str, target: str, rel: str, note: str) -> None:
    """Add a link from SLUG to TARGET (e.g. blocks, relates-to)."""
    root = get_root()
    try:
        thread = load_thread(root, slug)
    except FileNotFoundError:
        raise click.ClickException(f"Thread '{slug}' not found.")

    # Warn if target doesn't exist, but don't block (target may not exist yet)
    if not (root / target / _THREAD_FILE).exists():
        click.echo(f"Warning: target thread '{target}' does not exist.", err=True)

    # Check for duplicate
    for lnk in thread.meta.links:
        if lnk.rel == rel and lnk.slug == target:
            raise click.ClickException(f"Link '{rel} → {target}' already exists on '{slug}'.")

    thread.meta.links.append(ThreadLink(rel=rel, slug=target, note=note))
    save_thread(thread)
    click.echo(f"Linked: {slug} --[{rel}]--> {target}")


# ---------------------------------------------------------------------------
# forums unlink
# ---------------------------------------------------------------------------

@forums.command("unlink")
@click.argument("slug")
@click.argument("target")
@click.option("--rel", "-r", default=None,
              help="Relationship type to remove. Omit to remove all links to TARGET.")
def forums_unlink(slug: str, target: str, rel: str | None) -> None:
    """Remove a link from SLUG to TARGET."""
    root = get_root()
    try:
        thread = load_thread(root, slug)
    except FileNotFoundError:
        raise click.ClickException(f"Thread '{slug}' not found.")

    before = len(thread.meta.links)
    thread.meta.links = [
        lnk for lnk in thread.meta.links
        if not (lnk.slug == target and (rel is None or lnk.rel == rel))
    ]
    removed = before - len(thread.meta.links)
    if removed == 0:
        raise click.ClickException(f"No matching link to '{target}' found on '{slug}'.")

    save_thread(thread)
    click.echo(f"Removed {removed} link(s) from '{slug}' to '{target}'.")


# ---------------------------------------------------------------------------
# forums tags
# ---------------------------------------------------------------------------

@forums.command("tags")
def forums_tags() -> None:
    """List all existing tags."""
    root = get_root()
    tags = list_tags(root)
    if not tags:
        click.echo("No tags found.")
        return

    for tag in tags:
        click.echo(tag)


# ---------------------------------------------------------------------------
# forums doctor
# ---------------------------------------------------------------------------

@forums.command("doctor")
@click.option("--age-days", default=14, show_default=True, help="Flag threads idle for longer than N days.")
def forums_doctor(age_days: int) -> None:
    """Output machine-readable stale-thread diagnostics.

    Prints one line per stale open thread:

        STALE <slug> <days>d

    Consumed by 'tw doctor' to surface long-running open threads.
    """
    root = get_root()
    for slug, days in stale_threads(root, age_days=age_days):
        click.echo(f"STALE {slug} {days}d")
