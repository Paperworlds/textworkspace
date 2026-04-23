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


# Locations we probe, relative to each repo root. First hit wins.
_CANDIDATE_PATHS: tuple[str, ...] = (
    "docs/IDEAS.yaml",
    "docs/IDEAS.yml",
    "IDEAS.yaml",
    "IDEAS.yml",
    "docs/IDEAS.md",
    "IDEAS.md",
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

    @property
    def format(self) -> str:
        return self.path.suffix.lstrip(".")


def discover_repos(dev_root: Path) -> list[Path]:
    """Return sibling repo directories under dev_root that look like repos."""
    if not dev_root.exists():
        return []
    out: list[Path] = []
    for child in sorted(dev_root.iterdir()):
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
    return Idea(repo=repo_name, path=path, id=idea_id, title=title, status=status, priority=priority, summary=summary)


def load_ideas_for_repo(repo: Path) -> list[Idea]:
    path = _find_ideas_file(repo)
    if path is None:
        return []

    if path.suffix == ".md":
        # Opaque: surface a single placeholder entry pointing at the file.
        return [Idea(
            repo=repo.name,
            path=path,
            id="(markdown)",
            title=f"{path.name} — use `tw ideas show {repo.name}` to read",
            status="md",
            summary="",
        )]

    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception as exc:  # noqa: BLE001
        return [Idea(
            repo=repo.name, path=path, id="(error)",
            title=f"failed to parse: {exc}", status="error",
        )]

    return [_item_to_idea(repo.name, path, hint, item) for hint, item in _extract_items(data)]


def load_all_ideas(dev_root: Path) -> list[Idea]:
    out: list[Idea] = []
    for repo in discover_repos(dev_root):
        out.extend(load_ideas_for_repo(repo))
    return out
