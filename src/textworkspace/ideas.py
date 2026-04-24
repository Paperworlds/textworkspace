"""Aggregate IDEAS.{yaml,md} files from sibling repos under dev_root.

Each repo can ship an ideas backlog. We support three YAML shapes out of the
box and surface Markdown backlogs as opaque pointers.

Canonical shape (recommended for new repos):

    ideas:
      - id: some-slug
        title: Short title
        status: idea | exploring | planned | parked | done
        priority: 1          # optional
        summary: |           # optional, free-form prose
          Multi-line description.

Also accepted:

    ideas:                   # mapping form (textread)
      some-slug:
        title: ...
        status: ...

    brainstorm:              # any top-level list-of-dicts (textworkspace)
      - name: some-slug
        title: ...
        status: ...
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml


# Single-file locations we probe, relative to each repo root. First hit wins.
_CANDIDATE_PATHS: tuple[str, ...] = (
    "docs/IDEAS.yaml",
    "docs/IDEAS.yml",
    "IDEAS.yaml",
    "IDEAS.yml",
    "docs/IDEAS.md",
    "IDEAS.md",
)

# Directory locations we probe for repos that keep many small idea files
# (common in work repos that can't adopt a root-level IDEAS.yaml). Every
# *.yaml / *.yml / *.md inside becomes an idea source.
_CANDIDATE_DIRS: tuple[str, ...] = (
    ".files/ideas",
    "docs/ideas",
)


@dataclass
class Idea:
    repo: str
    path: Path
    id: str
    title: str
    status: str
    priority: int | None = None
    summary: str = ""
    # Raw source dict — preserved so `ideas show` can surface custom fields
    # (open_questions, mapping, etc.) that the structured shape drops.
    raw: dict | None = None

    @property
    def format(self) -> str:
        return self.path.suffix.lstrip(".")


def discover_repos(source: Path | dict[str, Path]) -> list[Path]:
    """Return repo directories that look like repos.

    Accepts either a dev_root Path (scanned by marker file) or a repo
    dict[name→path] (used directly).
    """
    if isinstance(source, dict):
        return [p for p in source.values() if p.exists()]
    if not source.exists():
        return []
    out: list[Path] = []
    for child in sorted(source.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        # Heuristic: repos have either a pyproject.toml, package.json, go.mod, or Cargo.toml
        if any((child / marker).exists() for marker in ("pyproject.toml", "go.mod", "package.json", "Cargo.toml")):
            out.append(child)
    return out


def _find_ideas_file(repo: Path) -> Path | None:
    for rel in _CANDIDATE_PATHS:
        p = repo / rel
        if p.exists():
            return p
    return None


def _extract_items(data: Any) -> Iterable[tuple[str | None, dict]]:
    """Yield (id_hint, item_dict) pairs from a parsed IDEAS.yaml body.

    Walks the top-level and returns whichever key first holds a list or dict
    of dicts. This covers `ideas:`, `brainstorm:`, `backlog:`, etc.
    """
    if not isinstance(data, dict):
        return
    for _key, value in data.items():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    yield None, item
            return
        if isinstance(value, dict) and all(isinstance(v, dict) for v in value.values() if v is not None):
            for k, item in value.items():
                if isinstance(item, dict):
                    yield str(k), item
            return


def _item_to_idea(repo_name: str, path: Path, id_hint: str | None, item: dict) -> Idea:
    idea_id = id_hint or str(item.get("id") or item.get("name") or item.get("slug") or item.get("title", "?"))
    title = str(item.get("title") or idea_id)
    status = str(item.get("status") or "idea")
    priority = item.get("priority")
    if not isinstance(priority, int):
        priority = None
    summary_val = item.get("summary") or item.get("description") or ""
    summary = str(summary_val).strip()
    return Idea(
        repo=repo_name, path=path, id=idea_id, title=title,
        status=status, priority=priority, summary=summary,
        raw=dict(item),
    )


def _load_single_file(repo_name: str, path: Path, *, single_idea: bool = False) -> list[Idea]:
    """Load ideas from one file.

    If *single_idea* is True, the entire file is treated as one idea — nested
    lists-of-dicts (e.g. `textmap_references:`) are kept as raw fields instead
    of being mis-detected as idea entries. This is the mode used for per-file
    YAML in `.files/ideas/<name>.yaml`.
    """
    if path.suffix == ".md":
        return [Idea(
            repo=repo_name,
            path=path,
            id=path.stem,
            title=f"{path.name} — use `tw ideas show {repo_name} {path.stem}` to read",
            status="md",
            summary="",
        )]
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception as exc:  # noqa: BLE001
        return [Idea(
            repo=repo_name, path=path, id="(error)",
            title=f"failed to parse {path.name}: {exc}", status="error",
        )]

    if single_idea:
        # Per-file YAML pattern. Don't descend into top-level lists; they're
        # fields of this idea (mappings, references, open_questions, etc.).
        if isinstance(data, dict):
            return [_item_to_idea(repo_name, path, path.stem, data)]
        return []

    items = list(_extract_items(data))
    if items:
        return [_item_to_idea(repo_name, path, hint, item) for hint, item in items]
    if isinstance(data, dict) and (data.get("title") or data.get("id") or data.get("slug")):
        return [_item_to_idea(repo_name, path, path.stem, data)]
    return []


def load_ideas_for_repo(repo: Path) -> list[Idea]:
    out: list[Idea] = []

    # 1. Single aggregate file (IDEAS.yaml / IDEAS.md).
    agg = _find_ideas_file(repo)
    if agg is not None:
        out.extend(_load_single_file(repo.name, agg))

    # 2. Directory of per-idea files (.files/ideas/*.yaml etc.). These are
    # always single-idea files — treat the whole file as the idea, even if
    # it contains a nested list-of-dicts (e.g. textmap_references). This
    # prevents a nested field from masquerading as a list of ideas.
    for rel in _CANDIDATE_DIRS:
        d = repo / rel
        if not d.is_dir():
            continue
        for child in sorted(d.iterdir()):
            if not child.is_file():
                continue
            if child.suffix not in {".yaml", ".yml", ".md"}:
                continue
            out.extend(_load_single_file(repo.name, child, single_idea=True))

    return out


def load_all_ideas(source: Path | dict[str, Path]) -> list[Idea]:
    out: list[Idea] = []
    for repo in discover_repos(source):
        out.extend(load_ideas_for_repo(repo))
    return out


def append_thread_backlink(idea: Idea, thread_slug: str) -> bool:
    """Append *thread_slug* to the idea entry's `threads:` list in its source file.

    Returns True if the file was updated, False if the slug was already there
    or the file shape couldn't be matched safely. YAML comments are lost on
    rewrite — that's the cost of keeping this mechanical.

    Per the idea-expander spec (SPEC: idea-expander), consumers MUST write
    the thread slug back so `tw ideas threads <repo> <id>` can locate it.
    """
    if idea.path.suffix in {".md", ""}:
        return False

    raw = yaml.safe_load(idea.path.read_text()) or {}
    if not isinstance(raw, dict):
        return False

    # Case A: the whole file is the idea (per-file YAML in .files/ideas/).
    # Detected by: no recognised container key matches AND the file's top
    # level looks like a single idea (title/id/slug present).
    if _looks_like_single_idea(raw):
        threads = list(raw.get("threads") or [])
        if thread_slug in threads:
            return False
        threads.append(thread_slug)
        raw["threads"] = threads
        idea.path.write_text(yaml.safe_dump(raw, default_flow_style=False, allow_unicode=True, sort_keys=False))
        return True

    # Case B: aggregate file with a container (ideas:, brainstorm:, etc.).
    for key, value in raw.items():
        if isinstance(value, list):
            for item in value:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("id") or item.get("name") or item.get("slug") or item.get("title", ""))
                if item_id == idea.id:
                    threads = list(item.get("threads") or [])
                    if thread_slug in threads:
                        return False
                    threads.append(thread_slug)
                    item["threads"] = threads
                    idea.path.write_text(yaml.safe_dump(raw, default_flow_style=False, allow_unicode=True, sort_keys=False))
                    return True
            return False
        if isinstance(value, dict) and all(isinstance(v, dict) for v in value.values() if v is not None):
            item = value.get(idea.id)
            if isinstance(item, dict):
                threads = list(item.get("threads") or [])
                if thread_slug in threads:
                    return False
                threads.append(thread_slug)
                item["threads"] = threads
                idea.path.write_text(yaml.safe_dump(raw, default_flow_style=False, allow_unicode=True, sort_keys=False))
                return True
            return False
    return False


def _looks_like_single_idea(data: dict) -> bool:
    return bool(data.get("title") or data.get("id") or data.get("slug"))
