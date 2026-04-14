"""Core data structures and I/O for textforums."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

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
class ThreadMeta:
    title: str
    created: str           # ISO 8601
    author: str
    tags: list[str] = field(default_factory=list)
    status: str = "open"


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
    return {
        "title": meta.title,
        "created": meta.created,
        "author": meta.author,
        "tags": meta.tags,
        "status": meta.status,
    }


def _entry_to_dict(entry: Entry) -> dict:
    return {
        "author": entry.author,
        "timestamp": entry.timestamp,
        "status": entry.status,
        "content": entry.content,
        "files": entry.files,
    }


def _parse_meta(data: dict) -> ThreadMeta:
    return ThreadMeta(
        title=data["title"],
        created=data["created"],
        author=data["author"],
        tags=data.get("tags") or [],
        status=data.get("status", "open"),
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
