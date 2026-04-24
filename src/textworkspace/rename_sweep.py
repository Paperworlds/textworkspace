"""Identity renames across textworkspace-managed state.

Complement to `tw repo move` (which handles folder-path changes). `tw repo
rename` handles *name* changes — the repo's identity across config,
forum threads, idea tags, and decision exports.

Out of scope (user/tool-owned, not textworkspace-owned):
- the source repo's own pyproject.toml / spec frontmatter / filesystem name
- git remote URL and GitHub repo rename
- textmap graph.yaml content (re-run `tw forums decisions ingest` after)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from textworkspace.config import Config


@dataclass
class RenameChange:
    """One planned edit. Rendered in the dry-run preview."""
    kind: str          # e.g. "config.repos", "thread.context.repos", "thread.tag"
    path: str          # file path (or "config") for display
    detail: str        # human-readable "old thing → new thing"


@dataclass
class RenamePlan:
    old: str
    new: str
    config_change: RenameChange | None = None
    thread_changes: list[tuple[Path, list[RenameChange]]] = field(default_factory=list)
    decision_export_dir: Path | None = None   # cleared on apply so re-export picks up new name

    @property
    def total_changes(self) -> int:
        total = 1 if self.config_change else 0
        total += sum(len(changes) for _, changes in self.thread_changes)
        return total


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _plan_config(cfg: Config, old: str, new: str) -> RenameChange | None:
    if old not in (cfg.repos or {}):
        return None
    return RenameChange(
        kind="config.repos",
        path="config.yaml",
        detail=f"repos.{old} → repos.{new}",
    )


def _apply_config(cfg: Config, old: str, new: str) -> None:
    entry = cfg.repos.pop(old)
    cfg.repos[new] = entry


# ---------------------------------------------------------------------------
# Forum threads
# ---------------------------------------------------------------------------


def _idea_tag_pattern(old: str) -> re.Pattern:
    # Tags we rewrite: `idea:<old>/<anything>`. Everything else left alone.
    return re.compile(rf"^idea:{re.escape(old)}/(.+)$")


def _plan_thread(thread_path: Path, old: str, new: str) -> list[RenameChange]:
    """Scan one thread.yaml for changes. Returns empty list if nothing applies."""
    try:
        raw = yaml.safe_load(thread_path.read_text()) or {}
    except Exception:  # noqa: BLE001
        return []
    meta = raw.get("meta") or {}
    changes: list[RenameChange] = []

    # context.repos membership
    ctx = meta.get("context") or {}
    repos = ctx.get("repos") or []
    if isinstance(repos, list) and old in repos:
        changes.append(RenameChange(
            kind="thread.context.repos",
            path=str(thread_path),
            detail=f"context.repos: {old} → {new}",
        ))

    # idea tags
    tag_re = _idea_tag_pattern(old)
    tags = meta.get("tags") or []
    if isinstance(tags, list):
        for t in tags:
            if isinstance(t, str) and tag_re.match(t):
                changes.append(RenameChange(
                    kind="thread.tag",
                    path=str(thread_path),
                    detail=f"tag {t} → idea:{new}/{tag_re.match(t).group(1)}",
                ))

    return changes


def _scan_threads(forums_root: Path, old: str, new: str) -> list[tuple[Path, list[RenameChange]]]:
    out: list[tuple[Path, list[RenameChange]]] = []
    if not forums_root.exists():
        return out
    for slug_dir in sorted(forums_root.iterdir()):
        if not slug_dir.is_dir() or slug_dir.name.startswith("."):
            continue
        thread_file = slug_dir / "thread.yaml"
        if not thread_file.exists():
            continue
        changes = _plan_thread(thread_file, old, new)
        if changes:
            out.append((thread_file, changes))
    return out


def _apply_thread(thread_path: Path, old: str, new: str) -> None:
    """Re-read, rewrite in place. Preserves everything not matched."""
    raw = yaml.safe_load(thread_path.read_text()) or {}
    meta = raw.get("meta") or {}

    ctx = meta.get("context") or {}
    repos = ctx.get("repos") or []
    if isinstance(repos, list) and old in repos:
        meta["context"]["repos"] = [new if r == old else r for r in repos]

    tag_re = _idea_tag_pattern(old)
    tags = meta.get("tags") or []
    if isinstance(tags, list):
        new_tags: list[str] = []
        for t in tags:
            if isinstance(t, str):
                m = tag_re.match(t)
                if m:
                    new_tags.append(f"idea:{new}/{m.group(1)}")
                    continue
            new_tags.append(t)
        meta["tags"] = new_tags

    thread_path.write_text(
        yaml.safe_dump(raw, default_flow_style=False, allow_unicode=True, sort_keys=False)
    )


# ---------------------------------------------------------------------------
# Plan / apply
# ---------------------------------------------------------------------------


def plan_rename(
    cfg: Config,
    forums_root: Path,
    old: str,
    new: str,
    *,
    decision_export_dir: Path | None = None,
) -> RenamePlan:
    """Scan for changes without writing. Safe to call for dry-run."""
    if old == new:
        raise ValueError("old and new must differ")

    plan = RenamePlan(old=old, new=new)
    plan.config_change = _plan_config(cfg, old, new)
    plan.thread_changes = _scan_threads(forums_root, old, new)

    # If exports exist, nuke the cached .md files on apply so a subsequent
    # `tw forums decisions ingest` emits fresh ones with the new name.
    if decision_export_dir is not None and decision_export_dir.exists():
        plan.decision_export_dir = decision_export_dir

    return plan


def apply_plan(plan: RenamePlan, cfg: Config, forums_root: Path) -> None:
    """Apply a plan in-place. Caller is responsible for saving cfg to disk."""
    if plan.config_change is not None:
        _apply_config(cfg, plan.old, plan.new)

    for thread_path, _changes in plan.thread_changes:
        _apply_thread(thread_path, plan.old, plan.new)

    # Clear export dir so re-ingest repopulates it with the new name.
    if plan.decision_export_dir is not None and plan.decision_export_dir.exists():
        for existing in plan.decision_export_dir.iterdir():
            if existing.is_file() and existing.name.startswith("decision-"):
                existing.unlink()


def format_plan(plan: RenamePlan) -> str:
    """Multiline rendering for the CLI's dry-run / confirm preview."""
    lines: list[str] = [f"# Rename plan: {plan.old} → {plan.new}", ""]
    if plan.config_change is None and not plan.thread_changes and plan.decision_export_dir is None:
        lines.append("  (nothing to do — is the old name correct and registered?)")
        return "\n".join(lines)

    if plan.config_change:
        lines.append(f"## config.yaml")
        lines.append(f"  - {plan.config_change.detail}")
        lines.append("")

    if plan.thread_changes:
        lines.append(f"## forum threads ({len(plan.thread_changes)} file(s), {sum(len(c) for _, c in plan.thread_changes)} change(s))")
        for thread_path, changes in plan.thread_changes:
            lines.append(f"  {thread_path.parent.name}:")
            for c in changes:
                lines.append(f"    - {c.detail}")
        lines.append("")

    if plan.decision_export_dir is not None:
        lines.append(f"## decision export cache")
        lines.append(f"  - clear {plan.decision_export_dir} (re-run `tw forums decisions ingest` after)")
        lines.append("")

    lines.append("Out of scope — handle manually or in the source repo:")
    lines.append("  - filesystem folder rename (use `tw repo move` after if the path also changes)")
    lines.append("  - pyproject.toml, spec frontmatter, README in the renamed repo")
    lines.append("  - git remote URL + GitHub repo rename")
    lines.append("  - textmap graph.yaml content (re-run `tw forums decisions ingest`)")
    return "\n".join(lines)
