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


def edit_entry(thread: Thread, index: int, content: str | None = None, status: str | None = None) -> None:
    """Edit an entry's content and/or status by index. Open editor if content is None."""
    if index < 0 or index >= len(thread.entries):
        raise IndexError(f"Entry index {index} out of range (thread has {len(thread.entries)} entries)")

    entry = thread.entries[index]

    # Edit content if provided or open editor
    if content is None:
        template = (
            f"# Editing entry [{index}] by {entry.author}\n"
            f"# Timestamp: {entry.timestamp}\n"
            "# Write your edited content below this line:\n\n"
            f"{entry.content}\n"
        )
        edited = _open_in_editor(template).strip()
        lines = [l for l in edited.splitlines() if not l.startswith("#")]
        content = "\n".join(lines).strip()

    entry.content = content
    if status is not None:
        entry.status = status
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
# forums edit-entry
# ---------------------------------------------------------------------------

@forums.command("edit-entry")
@click.argument("slug")
@click.argument("index", type=int)
@click.option("--content", "-c", default=None, help="New entry content. Opens $EDITOR if omitted.")
@click.option("--status", "-s", default=None, help="New entry status.")
def forums_edit_entry(slug: str, index: int, content: str | None, status: str | None) -> None:
    """Edit a specific entry by index without touching the whole file."""
    root = get_root()
    try:
        thread = load_thread(root, slug)
    except FileNotFoundError:
        raise click.ClickException(f"Thread '{slug}' not found.")

    try:
        edit_entry(thread, index, content=content, status=status)
        click.echo(f"Entry [{index}] in '{slug}' updated.")
    except IndexError as e:
        raise click.ClickException(str(e))


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


_EXAMPLE_FLOW = """\
# textforums — typical working flow
#
# Threads are YAML files under ~/.textforums/<slug>/thread.yaml.
# All commands below also work as `tw forums <sub>`.

# 1. See what's open — optionally filtered by tag or full-text query.
textforums list
textforums list --status open --tag textworkspace
textforums list --query "proxy passthrough"

# 2. Start a new thread. Omit --content to open $EDITOR for the first entry.
textforums new --title "tw proxy status broken" --tag textworkspace --tag bug \\
    --content "tw proxy status returns 'No such command'. See screenshot."

# 3. Read a thread (use the slug from `list`).
textforums show tw-proxy-status-broken
textforums show tw-proxy-status-broken --raw       # dump YAML

# 4. Reply. Omit --content to open $EDITOR. Attach files with --file.
textforums add tw-proxy-status-broken --content "Reproduced on 0.4.2." --status ack
textforums add tw-proxy-status-broken --file ./logs/run.txt

# 5. Cross-link related threads.
textforums link tw-proxy-status-broken pp-claude-cmd-profile-bug

# 6. Edit a prior entry (0-indexed) or open the whole thread in $EDITOR.
textforums edit-entry tw-proxy-status-broken 1 --content "Fixed in 0.4.3."
textforums edit tw-proxy-status-broken

# 7. Close when resolved — the closing note becomes the final entry.
textforums close tw-proxy-status-broken --content "Shipped passthrough group in 0.4.3."

# 8. Housekeeping: list all tags in use, find stale threads, or bulk-close.
textforums tags
textforums doctor --age-days 14
textforums bulk-close --tag stale --dry-run
textforums bulk-close --query "0.3.x" --yes --content "closing old 0.3.x bugs"

# 9. Reopen if needed.
textforums reopen tw-proxy-status-broken
"""


@forums.command("example")
def forums_example() -> None:
    """Print an annotated walkthrough of the typical textforums workflow."""
    click.echo(_EXAMPLE_FLOW, nl=False)


# ---------------------------------------------------------------------------
# forums spec — cross-repo spec publication and conformance
# ---------------------------------------------------------------------------


def _dev_root_from_config() -> Path | None:
    """Resolve dev_root from textworkspace config (without importing cli.py)."""
    try:
        from textworkspace.config import load_config
    except Exception:  # noqa: BLE001
        return None
    try:
        cfg = load_config()
    except Exception:  # noqa: BLE001
        return None
    root = (cfg.defaults or {}).get("dev_root", "")
    return Path(root).expanduser() if root else None


def _require_dev_root() -> Path:
    root = _dev_root_from_config()
    if root is None or not root.exists():
        raise click.ClickException(
            "dev_root not set or missing — run 'tw dev on <path>' to configure it"
        )
    return root


@forums.group("spec")
def forums_spec() -> None:
    """Publish and check cross-repo specs.

    A spec lives in the owner repo at docs/specs/<slug>.md with YAML
    frontmatter; the companion thread (tagged 'spec') holds discussion.
    Consumer repos declare what they follow in docs/SPECS.yaml and mark
    implementations with `# SPEC: <slug>` comments.
    """


@forums_spec.command("list")
@click.option("--owner", default=None, help="Filter by owner repo.")
@click.option("--consumer", default=None, help="Filter by consumer repo.")
@click.option("--status", default=None, help="Filter by status (draft/proposed/adopted/...).")
def spec_list(owner: str | None, consumer: str | None, status: str | None) -> None:
    """List specs discovered across dev_root."""
    from textworkspace.specs import discover_specs

    specs = discover_specs(_require_dev_root())
    if owner:
        specs = [s for s in specs if s.owner == owner]
    if consumer:
        specs = [s for s in specs if consumer in s.consumers]
    if status:
        specs = [s for s in specs if s.status == status]

    if not specs:
        click.echo("No specs found.")
        return

    owner_w = max(len(s.owner) for s in specs)
    slug_w = max(len(s.slug) for s in specs)
    status_w = max(len(s.status) for s in specs)
    for s in specs:
        consumers = ", ".join(s.consumers) or "-"
        click.echo(f"  {s.owner:<{owner_w}}  {s.slug:<{slug_w}}  {s.status:<{status_w}}  v{s.version}  consumers={consumers}")


@forums_spec.command("new")
@click.argument("slug")
@click.option("--owner", required=True, help="Owner repo name (under dev_root).")
@click.option("--title", required=True, help="Spec title.")
@click.option("--consumer", "consumers", multiple=True, help="Consumer repo (repeatable).")
@click.option("--no-thread", is_flag=True, help="Skip creating the companion forum thread.")
def spec_new(slug: str, owner: str, title: str, consumers: tuple[str, ...], no_thread: bool) -> None:
    """Scaffold docs/specs/<slug>.md in the owner repo (+ companion thread)."""
    from textworkspace.specs import scaffold_spec, write_spec

    dev_root = _require_dev_root()
    owner_repo = dev_root / owner
    if not owner_repo.exists():
        raise click.ClickException(f"owner repo '{owner}' not found under {dev_root}")

    spec = scaffold_spec(owner_repo, slug=slug, title=title, owner_name=owner)
    if spec.path.exists():
        raise click.ClickException(f"spec already exists at {spec.path}")
    spec.consumers = list(consumers)
    write_spec(spec)
    click.echo(f"wrote {spec.path}")

    if no_thread:
        return

    # Companion thread.
    root = get_root()
    thread_slug = f"spec-{slug}"
    thread_dir = root / thread_slug
    if thread_dir.exists():
        click.echo(f"(companion thread '{thread_slug}' already exists; skipping)", err=True)
        return
    author = get_author(None)
    now = _now_iso()
    meta = ThreadMeta(
        title=f"SPEC: {title}",
        created=now,
        author=author,
        tags=["spec", owner],
    )
    body = (
        f"Discussion thread for spec `{slug}` owned by `{owner}`.\n\n"
        f"Source: {spec.path}\n"
    )
    thread = Thread(meta=meta, entries=[Entry(author=author, timestamp=now, status="open", content=body)], path=thread_dir / _THREAD_FILE)
    save_thread(thread)
    click.echo(f"created thread '{thread_slug}'")


@forums_spec.command("show")
@click.argument("slug")
def spec_show(slug: str) -> None:
    """Print a spec's markdown plus a pointer to its companion thread."""
    from textworkspace.specs import find_spec

    spec = find_spec(_require_dev_root(), slug)
    if spec is None:
        raise click.ClickException(f"spec '{slug}' not found")

    click.echo(f"# Source: {spec.path}")
    thread_slug = f"spec-{slug}"
    if (get_root() / thread_slug).exists():
        click.echo(f"# Thread: textforums show {thread_slug}")
    click.echo("")
    click.echo(spec.path.read_text(), nl=False)


@forums_spec.command("refs")
@click.argument("slug")
@click.option("--repo", default=None, help="Restrict search to one repo under dev_root.")
def spec_refs(slug: str, repo: str | None) -> None:
    """Grep `# SPEC: <slug>` markers across repos."""
    from textworkspace.specs import find_markers

    dev_root = _require_dev_root()
    repos: list[Path]
    if repo:
        candidate = dev_root / repo
        if not candidate.exists():
            raise click.ClickException(f"repo '{repo}' not found")
        repos = [candidate]
    else:
        repos = [p for p in dev_root.iterdir() if p.is_dir() and not p.name.startswith(".")]

    total = 0
    for r in sorted(repos):
        hits = find_markers(r, slug)
        for path, line, matched in hits:
            rel = path.relative_to(dev_root)
            click.echo(f"  {rel}:{line}  # SPEC: {matched}")
            total += 1
    if total == 0:
        click.echo(f"No '# SPEC: {slug}' markers found.")


@forums_spec.command("check")
@click.option("--repo", default=None, help="Check a single consumer repo.")
@click.option("--strict", is_flag=True, help="Exit non-zero on any warning, not just errors.")
def spec_check(repo: str | None, strict: bool) -> None:
    """Verify consumer manifests (docs/SPECS.yaml) against adopted specs."""
    from textworkspace.specs import check_all, check_consumer, discover_specs

    dev_root = _require_dev_root()
    if repo:
        repo_path = dev_root / repo
        if not repo_path.exists():
            raise click.ClickException(f"repo '{repo}' not found")
        specs_by_slug = {s.slug: s for s in discover_specs(dev_root)}
        findings = check_consumer(dev_root, repo_path, specs_by_slug)
    else:
        findings = check_all(dev_root)

    if not findings:
        click.echo("spec check: ok")
        return

    errors = [f for f in findings if f.level == "error"]
    warnings = [f for f in findings if f.level == "warn"]

    for f in findings:
        tag = "ERROR" if f.level == "error" else "warn "
        click.echo(f"  [{tag}] {f.consumer}:{f.slug}  {f.message}")

    if errors or (strict and warnings):
        raise SystemExit(1)


@forums_spec.command("brief")
@click.option("--repo", default=None, help="Repo to brief (default: infer from CWD).")
def spec_brief(repo: str | None) -> None:
    """Print an actionable brief for an agent working on a repo.

    Lists the specs the repo OWNS (with status) and the specs it FOLLOWS
    (with pass/fail per check), plus exact commands to run next.
    """
    from textworkspace.specs import (
        check_consumer,
        discover_specs,
        find_markers,
        load_consumer_manifest,
    )

    dev_root = _require_dev_root()
    if repo is None:
        # Infer: first ancestor of CWD under dev_root.
        cwd = Path.cwd().resolve()
        try:
            rel = cwd.relative_to(dev_root.resolve())
            repo = rel.parts[0] if rel.parts else None
        except ValueError:
            repo = None
        if repo is None:
            raise click.ClickException(
                "cannot infer repo — run from inside a repo under dev_root, or pass --repo"
            )

    repo_path = dev_root / repo
    if not repo_path.exists():
        raise click.ClickException(f"repo '{repo}' not found under {dev_root}")

    all_specs = discover_specs(dev_root)
    owned = [s for s in all_specs if s.owner == repo]
    follows = load_consumer_manifest(repo_path)
    follows_entries = follows.follows if follows else []

    click.echo(f"# Spec brief — {repo}")
    click.echo("")

    # Owned
    if owned:
        click.echo("## Owned specs")
        for s in owned:
            marker_hits = len(find_markers(repo_path, s.slug))
            click.echo(f"  {s.slug}  ({s.status}, v{s.version})  — {marker_hits} marker(s) in source")
            click.echo(f"    source:  {s.path}")
            if s.consumers:
                click.echo(f"    consumers: {', '.join(s.consumers)}")
        click.echo("")
    else:
        click.echo("## Owned specs")
        click.echo("  (none)")
        click.echo("")

    # Follows
    click.echo("## Follows")
    if not follows_entries:
        click.echo(f"  (no docs/SPECS.yaml manifest in {repo})")
        click.echo("")
    else:
        specs_by_slug = {s.slug: s for s in all_specs}
        findings = check_consumer(dev_root, repo_path, specs_by_slug)
        findings_by_slug: dict[str, list] = {}
        for f in findings:
            findings_by_slug.setdefault(f.slug, []).append(f)
        for entry in follows_entries:
            spec = specs_by_slug.get(entry.slug)
            status_tag = spec.status if spec else "MISSING"
            click.echo(f"  {entry.slug}  (upstream: {status_tag}"
                       + (f", v{spec.version}" if spec else "")
                       + f", pinned={entry.pinned_version or 'latest'})")
            for f in findings_by_slug.get(entry.slug, []):
                tag = "ERROR" if f.level == "error" else "warn"
                click.echo(f"    [{tag}] {f.message}")
        click.echo("")

    # Suggested actions
    click.echo("## Next steps for the agent")
    if owned and any(s.status == "draft" for s in owned):
        click.echo("  - Draft specs exist in this repo. Iterate, then `tw forums spec adopt <slug>`.")
    if follows_entries:
        click.echo("  - Ensure each `implemented_in` path exists and contains `# SPEC: <slug>`.")
        click.echo("  - If pinned_version drifts from upstream, upgrade intentionally.")
    click.echo("  - Run `tw forums spec check --repo " + repo + "` before you commit.")


@forums_spec.command("adopt")
@click.argument("slug")
def spec_adopt(slug: str) -> None:
    """Transition a spec draft/proposed → adopted (sets adopted_at, freezes frontmatter)."""
    from textworkspace.specs import find_spec, write_spec
    from datetime import date

    spec = find_spec(_require_dev_root(), slug)
    if spec is None:
        raise click.ClickException(f"spec '{slug}' not found")
    if spec.status == "adopted":
        click.echo(f"spec '{slug}' is already adopted (version {spec.version}).")
        return
    if spec.status not in {"draft", "proposed"}:
        raise click.ClickException(f"cannot adopt from status '{spec.status}'")

    spec.status = "adopted"
    spec.adopted_at = date.today().isoformat()
    write_spec(spec)
    click.echo(f"adopted: {spec.slug} v{spec.version} ({spec.path})")


@forums_spec.command("supersede")
@click.argument("old_slug")
@click.argument("new_slug")
def spec_supersede(old_slug: str, new_slug: str) -> None:
    """Mark OLD_SLUG as superseded by NEW_SLUG and adopt NEW_SLUG.

    Does NOT update consumer manifests — consumers upgrade on their schedule.
    """
    from textworkspace.specs import find_spec, write_spec
    from datetime import date

    dev_root = _require_dev_root()
    old = find_spec(dev_root, old_slug)
    new = find_spec(dev_root, new_slug)
    if old is None:
        raise click.ClickException(f"old spec '{old_slug}' not found")
    if new is None:
        raise click.ClickException(f"new spec '{new_slug}' not found")

    old.status = "superseded"
    write_spec(old)

    new.supersedes = old_slug
    if new.status != "adopted":
        new.status = "adopted"
        new.adopted_at = date.today().isoformat()
    write_spec(new)

    click.echo(f"{old_slug} → superseded")
    click.echo(f"{new_slug} → adopted (supersedes {old_slug})")
