"""Export decided textforum threads as textmap-ingestable markdown.

textmap's `textmap ingest <dir>` walks a directory of `.md` files with YAML
frontmatter. Each file becomes a node: node id derived from filename, type
and description from frontmatter. We emit one `decision-<slug>.md` file per
thread whose status is "decided", with edges for supersede chains, repo
context, and spec references.

Decoupling: forums doesn't import textmap; textmap doesn't import forums.
textmap's existing ingestor is the contract between them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from textworkspace.forums import Thread, list_threads


DEFAULT_EXPORT_DIR = Path.home() / ".cache" / "paperworlds" / "textmap-decisions"


@dataclass
class ExportedFile:
    path: Path
    slug: str          # forum slug (without decision- prefix)
    node_id: str       # decision-<slug> (the textmap id)
    superseded: bool


def _node_id(slug: str) -> str:
    return f"decision-{slug}"


def _build_supersede_index(threads: list[Thread]) -> dict[str, list[str]]:
    """slug → list of slugs that this thread replaces (i.e. inbound 'superseded-by').

    Forum convention: the OLD thread carries `superseded-by → new`.
    Textmap convention: the NEW node `replaces` the old. So we invert the
    adjacency: for every OLD → NEW superseded-by link, index under NEW.
    """
    replaces: dict[str, list[str]] = {}
    slugs = {t.path.parent.name for t in threads}
    for old in threads:
        old_slug = old.path.parent.name
        for lnk in old.meta.links:
            if lnk.rel != "superseded-by":
                continue
            # Only emit edges between decisions we actually export.
            if lnk.slug not in slugs:
                continue
            replaces.setdefault(lnk.slug, []).append(old_slug)
    return replaces


def _is_superseded(thread: Thread) -> bool:
    return any(lnk.rel == "superseded-by" for lnk in thread.meta.links)


def _frontmatter(
    thread: Thread,
    replaces_slugs: list[str],
) -> dict:
    meta = thread.meta
    d = meta.decision
    # 'active' unless this thread has been superseded by a newer one.
    status = "deprecated" if _is_superseded(thread) else "active"

    connections: list[dict] = []
    # New node replaces old nodes (only emitted on the NEW file).
    for old in replaces_slugs:
        connections.append({"to": _node_id(old), "relation": "replaces"})
    # Decision applies_to the repos listed in context.repos.
    for repo in meta.context.repos:
        connections.append({"to": repo, "relation": "applies_to"})
    # Decision implements the spec it discusses (if any).
    if meta.context.spec:
        connections.append({"to": meta.context.spec, "relation": "implements"})

    labels = sorted({*meta.context.repos, *meta.tags})

    fm = {
        "type": "decision",
        "description": (d.summary if d else meta.title).strip(),
        "status": status,
    }
    if labels:
        fm["labels"] = labels
    if connections:
        fm["connections"] = connections
    return fm


def _body(thread: Thread) -> str:
    """Human-readable body: decision block + thread title + entry log (compact)."""
    lines: list[str] = []
    meta = thread.meta
    d = meta.decision

    lines.append(f"# {meta.title}")
    lines.append("")
    if d:
        lines.append(f"**Decision:** {d.summary}")
        lines.append("")
        lines.append(f"_Decided {d.decided_at} by {d.decided_by}._")
        lines.append("")
    if meta.context.repos:
        lines.append(f"**Repos:** {', '.join(meta.context.repos)}")
    if meta.context.spec:
        lines.append(f"**Spec:** {meta.context.spec}")
    if meta.context.repos or meta.context.spec:
        lines.append("")

    if thread.entries:
        lines.append("## Discussion")
        lines.append("")
        for e in thread.entries:
            lines.append(f"### {e.author} — {e.timestamp}")
            if e.status:
                lines.append(f"_status: {e.status}_")
            lines.append("")
            lines.append(e.content.rstrip())
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_file(thread: Thread, replaces_slugs: list[str]) -> str:
    """Produce the full markdown (frontmatter + body) for one thread."""
    fm = _frontmatter(thread, replaces_slugs)
    fm_yaml = yaml.safe_dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False).rstrip()
    return f"---\n{fm_yaml}\n---\n\n{_body(thread)}"


def decided_threads(root: Path) -> list[Thread]:
    return list_threads(root, status="decided")


def export_all(threads: Iterable[Thread], out_dir: Path) -> list[ExportedFile]:
    """Write one markdown file per decided thread. Full rewrite (idempotent).

    Returns the list of files written, in the order they were processed.
    Pre-existing files in out_dir with a `decision-` prefix that don't
    correspond to a current decided thread are removed — a rerun reflects
    the current forum state exactly.
    """
    threads = list(threads)
    out_dir.mkdir(parents=True, exist_ok=True)

    replaces_index = _build_supersede_index(threads)
    written: list[ExportedFile] = []
    kept_names: set[str] = set()

    for thread in threads:
        slug = thread.path.parent.name
        node = _node_id(slug)
        file_path = out_dir / f"{node}.md"
        replaces_slugs = replaces_index.get(slug, [])
        file_path.write_text(render_file(thread, replaces_slugs))
        kept_names.add(file_path.name)
        written.append(ExportedFile(
            path=file_path,
            slug=slug,
            node_id=node,
            superseded=_is_superseded(thread),
        ))

    # Clean up stale exports (thread re-opened, deleted, etc.).
    for existing in out_dir.iterdir():
        if not existing.is_file():
            continue
        if not existing.name.startswith("decision-"):
            continue
        if existing.name not in kept_names:
            existing.unlink()

    return written
