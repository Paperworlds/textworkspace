"""Tests for textworkspace.textmap_export."""

from __future__ import annotations

from pathlib import Path

import yaml

from textworkspace.forums import (
    Decision,
    Entry,
    Thread,
    ThreadContext,
    ThreadLink,
    ThreadMeta,
    save_thread,
)
from textworkspace.textmap_export import (
    _build_supersede_index,
    decided_threads,
    export_all,
    render_file,
)


def _decided(
    root: Path,
    slug: str,
    *,
    summary: str = "pick A",
    repos: list[str] | None = None,
    spec: str = "",
    tags: list[str] | None = None,
    links: list[ThreadLink] | None = None,
) -> Thread:
    meta = ThreadMeta(
        title=slug.replace("-", " ").title(),
        created="2026-04-20T00:00:00Z",
        author="paolo",
        tags=tags or [],
        status="decided",
        links=links or [],
        context=ThreadContext(repos=repos or [], spec=spec),
        decision=Decision(summary=summary, decided_at="2026-04-24", decided_by="paolo"),
    )
    t = Thread(
        meta=meta,
        entries=[Entry(author="paolo", timestamp="2026-04-20T00:00:00Z",
                       status="decided", content=f"Decision: {summary}")],
        path=root / slug / "thread.yaml",
    )
    save_thread(t)
    return t


def _open_thread(root: Path, slug: str) -> Thread:
    meta = ThreadMeta(title=slug, created="2026-04-20T00:00:00Z", author="p",
                      status="open")
    t = Thread(meta=meta, entries=[], path=root / slug / "thread.yaml")
    save_thread(t)
    return t


def test_decided_threads_only(tmp_path):
    _decided(tmp_path, "a")
    _open_thread(tmp_path, "still-open")
    result = decided_threads(tmp_path)
    assert {t.path.parent.name for t in result} == {"a"}


def test_render_basic_frontmatter(tmp_path):
    t = _decided(tmp_path, "pick-wire", summary="Use protobuf.",
                 repos=["textgame-io", "textworld"], tags=["protocol"])
    md = render_file(t, replaces_slugs=[])
    # Split frontmatter
    assert md.startswith("---\n")
    _, fm_text, body = md.split("---\n", 2)
    fm = yaml.safe_load(fm_text)

    assert fm["type"] == "decision"
    assert fm["description"] == "Use protobuf."
    assert fm["status"] == "active"
    # labels are union of repos + tags, sorted
    assert fm["labels"] == sorted(["textgame-io", "textworld", "protocol"])
    # applies_to edges for each repo
    targets = [(c["to"], c["relation"]) for c in fm["connections"]]
    assert ("textgame-io", "applies_to") in targets
    assert ("textworld", "applies_to") in targets
    # body contains decision summary
    assert "Use protobuf." in body


def test_render_with_spec_emits_implements(tmp_path):
    t = _decided(tmp_path, "envelope", summary="Envelope v2.", spec="protocol-envelope-v2")
    md = render_file(t, replaces_slugs=[])
    fm = yaml.safe_load(md.split("---\n", 2)[1])
    targets = [(c["to"], c["relation"]) for c in fm["connections"]]
    assert ("protocol-envelope-v2", "implements") in targets


def test_supersede_index_inverts_direction(tmp_path):
    # Forum convention: OLD thread has `superseded-by: new`.
    # Textmap convention: NEW `replaces` OLD.
    _decided(tmp_path, "old", links=[ThreadLink(rel="superseded-by", slug="new")])
    _decided(tmp_path, "new")
    idx = _build_supersede_index(decided_threads(tmp_path))
    assert idx == {"new": ["old"]}


def test_render_superseded_marked_deprecated(tmp_path):
    _decided(tmp_path, "old", links=[ThreadLink(rel="superseded-by", slug="new")])
    new = _decided(tmp_path, "new")
    # Pull the old thread back from disk so we test the round-trip path.
    threads = decided_threads(tmp_path)
    old = next(t for t in threads if t.path.parent.name == "old")

    old_md = render_file(old, replaces_slugs=[])
    old_fm = yaml.safe_load(old_md.split("---\n", 2)[1])
    assert old_fm["status"] == "deprecated"

    # new replaces old
    new_md = render_file(new, replaces_slugs=["old"])
    new_fm = yaml.safe_load(new_md.split("---\n", 2)[1])
    targets = [(c["to"], c["relation"]) for c in new_fm["connections"]]
    assert ("decision-old", "replaces") in targets
    assert new_fm["status"] == "active"


def test_export_all_writes_files_and_cleans_stale(tmp_path):
    out = tmp_path / "out"
    # Pre-seed a stale decision file that doesn't match any current thread.
    out.mkdir()
    (out / "decision-ghost.md").write_text("---\ntype: decision\n---\n")
    # Also an unrelated file — should be kept.
    (out / "README.md").write_text("hi")

    _decided(tmp_path, "real", summary="Go.")
    threads = decided_threads(tmp_path)
    written = export_all(threads, out)

    assert len(written) == 1
    assert written[0].node_id == "decision-real"
    assert (out / "decision-real.md").exists()
    # Stale removed
    assert not (out / "decision-ghost.md").exists()
    # Non-decision file untouched
    assert (out / "README.md").exists()


def test_export_idempotent(tmp_path):
    out = tmp_path / "out"
    _decided(tmp_path, "a", summary="Use A.")
    threads = decided_threads(tmp_path)
    first = export_all(threads, out)
    content_a = first[0].path.read_text()
    # Re-run: same bytes.
    second = export_all(threads, out)
    assert second[0].path.read_text() == content_a
