"""repo_import — parse REPO lines from tools and import into config."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ImportedRepo:
    name: str
    path: Path
    meta: dict[str, str] = field(default_factory=dict)
    source_tool: str = ""


@dataclass
class ImportConflict:
    kind: str  # "name" or "path"
    incoming: ImportedRepo
    existing_name: str  # for kind="name": the clashing existing name
    existing_path: Path  # for kind="path": the clashing existing path


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _parse_repo_line(line: str) -> Optional[tuple[str, Path, dict[str, str]]]:
    """Parse a single REPO line.

    Format: REPO <name> <path> [key=value ...]

    Returns (name, path, metadata) or None if the line is not a REPO line.
    Unknown k=v pairs are accepted and returned in metadata (R03).
    """
    if not line.startswith("REPO "):
        return None
    parts = line.split()
    if len(parts) < 3:
        return None
    _, name, raw_path, *rest = parts
    path = Path(raw_path).expanduser()
    meta: dict[str, str] = {}
    for pair in rest:
        if "=" in pair:
            k, _, v = pair.partition("=")
            meta[k] = v
    return name, path, meta


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def collect_from_tool(bin_path: str, tool_name: str) -> tuple[list[ImportedRepo], int]:
    """Run `<tool> repos`, parse output. Returns (repos, exit_code)."""
    try:
        result = subprocess.run(
            [bin_path, "repos"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return [], 1
    except subprocess.TimeoutExpired:
        return [], 1

    repos: list[ImportedRepo] = []
    for line in result.stdout.splitlines():
        parsed = _parse_repo_line(line)
        if parsed is None:
            continue
        name, path, meta = parsed
        repos.append(ImportedRepo(name=name, path=path, meta=meta, source_tool=tool_name))
    return repos, result.returncode


def collect_from_all(tools: dict) -> list[ImportedRepo]:
    """Collect REPO entries from every installed tool, merging results."""
    all_repos: list[ImportedRepo] = []
    for tool_name, tool_info in tools.items():
        if not tool_info.installed or not tool_info.bin_path:
            continue
        repos, code = collect_from_tool(tool_info.bin_path, tool_name)
        if code == 2:
            continue  # tool does not support repos — skip silently (R12)
        if code != 0:
            import click
            click.echo(f"[WARN] {tool_name} repos failed (exit {code}) — skipping", err=True)
            continue  # (R13)
        all_repos.extend(repos)
    return all_repos


# ---------------------------------------------------------------------------
# Deduplication and conflict detection
# ---------------------------------------------------------------------------


def deduplicate(repos: list[ImportedRepo]) -> list[ImportedRepo]:
    """Collapse entries with identical resolved paths (keep first seen)."""
    seen: dict[str, ImportedRepo] = {}
    result: list[ImportedRepo] = []
    for repo in repos:
        key = str(repo.path)
        if key not in seen:
            seen[key] = repo
            result.append(repo)
    return result


def find_conflicts(
    incoming: list[ImportedRepo],
    existing_repos: dict,
) -> list[ImportConflict]:
    """Detect name and path conflicts between incoming and existing repos."""
    conflicts: list[ImportConflict] = []
    existing_by_path = {str(Path(r.path).expanduser()): name for name, r in existing_repos.items()}
    for repo in incoming:
        path_key = str(repo.path)
        if repo.name in existing_repos:
            existing_entry = existing_repos[repo.name]
            existing_path = Path(existing_entry.path).expanduser()
            if str(existing_path) != path_key:
                conflicts.append(ImportConflict(
                    kind="name",
                    incoming=repo,
                    existing_name=repo.name,
                    existing_path=existing_path,
                ))
        elif path_key in existing_by_path:
            conflicts.append(ImportConflict(
                kind="path",
                incoming=repo,
                existing_name=existing_by_path[path_key],
                existing_path=repo.path,
            ))
    return conflicts
