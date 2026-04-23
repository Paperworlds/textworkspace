"""Tests for textworkspace.specs."""

from __future__ import annotations

from pathlib import Path

import pytest

from textworkspace.specs import (
    Spec,
    check_all,
    check_consumer,
    discover_specs,
    dump_spec,
    find_markers,
    find_spec,
    load_consumer_manifest,
    parse_spec_file,
    scaffold_spec,
    write_spec,
)


def _mkrepo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    return repo


def _write_spec_file(repo: Path, slug: str, frontmatter: str, body: str = "body\n") -> Path:
    path = repo / "docs" / "specs" / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}\n---\n{body}")
    return path


def test_parse_and_dump_roundtrip(tmp_path: Path) -> None:
    repo = _mkrepo(tmp_path, "owner_repo")
    _write_spec_file(repo, "protocol-v1", "slug: protocol-v1\nowner: owner_repo\nstatus: draft\nversion: 0.1.0\n", body="# Proto\n")
    spec = parse_spec_file(repo / "docs" / "specs" / "protocol-v1.md")
    assert spec.slug == "protocol-v1"
    assert spec.owner == "owner_repo"
    assert spec.status == "draft"
    dumped = dump_spec(spec)
    assert dumped.startswith("---\n")
    assert "slug: protocol-v1" in dumped
    assert "# Proto" in dumped


def test_parse_missing_frontmatter_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.md"
    path.write_text("no frontmatter here")
    with pytest.raises(ValueError, match="missing YAML frontmatter"):
        parse_spec_file(path)


def test_parse_missing_required_field_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.md"
    path.write_text("---\nstatus: draft\n---\nbody")
    with pytest.raises(ValueError, match="missing required field"):
        parse_spec_file(path)


def test_parse_unknown_status_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.md"
    path.write_text("---\nslug: x\nowner: y\nstatus: wonky\n---\nbody")
    with pytest.raises(ValueError, match="unknown status"):
        parse_spec_file(path)


def test_discover_walks_dev_root(tmp_path: Path) -> None:
    one = _mkrepo(tmp_path, "one")
    two = _mkrepo(tmp_path, "two")
    _write_spec_file(one, "a", "slug: a\nowner: one\nstatus: draft\n")
    _write_spec_file(two, "b", "slug: b\nowner: two\nstatus: adopted\nadopted_at: 2026-04-24\n")
    specs = discover_specs(tmp_path)
    assert sorted(s.slug for s in specs) == ["a", "b"]


def test_find_spec_by_slug(tmp_path: Path) -> None:
    repo = _mkrepo(tmp_path, "owner")
    _write_spec_file(repo, "x", "slug: x\nowner: owner\n")
    assert find_spec(tmp_path, "x") is not None
    assert find_spec(tmp_path, "missing") is None


def test_find_markers(tmp_path: Path) -> None:
    repo = _mkrepo(tmp_path, "r")
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("# SPEC: proto-v1\nprint('ok')\n")
    (repo / "src" / "b.py").write_text("# spec: other\n")
    (repo / "README.md").write_text("plain file\n")
    (repo / ".venv").mkdir()
    (repo / ".venv" / "ignore.py").write_text("# SPEC: should-be-skipped\n")

    hits = find_markers(repo, "proto-v1")
    assert len(hits) == 1
    path, line, slug = hits[0]
    assert path.name == "a.py"
    assert line == 1
    assert slug == "proto-v1"

    # Ignored dirs don't surface.
    all_hits = find_markers(repo)
    assert all("ignore.py" not in str(p) for p, _, _ in all_hits)


def test_consumer_manifest_round_trip(tmp_path: Path) -> None:
    repo = _mkrepo(tmp_path, "consumer")
    (repo / "docs").mkdir()
    (repo / "docs" / "SPECS.yaml").write_text(
        "follows:\n"
        "  - slug: proto-v1\n"
        "    pinned_version: 1.0.0\n"
        "    implemented_in: [src/proto.py]\n"
    )
    mf = load_consumer_manifest(repo)
    assert mf is not None
    assert mf.repo == "consumer"
    assert len(mf.follows) == 1
    assert mf.follows[0].slug == "proto-v1"
    assert mf.follows[0].pinned_version == "1.0.0"


def test_check_consumer_reports_missing_impl_and_marker(tmp_path: Path) -> None:
    owner = _mkrepo(tmp_path, "owner")
    _write_spec_file(owner, "proto-v1", "slug: proto-v1\nowner: owner\nstatus: adopted\nversion: 1.0.0\nadopted_at: 2026-04-24\nconsumers: [consumer]\n")

    consumer = _mkrepo(tmp_path, "consumer")
    (consumer / "docs").mkdir()
    (consumer / "docs" / "SPECS.yaml").write_text(
        "follows:\n"
        "  - slug: proto-v1\n"
        "    pinned_version: 1.0.0\n"
        "    implemented_in: [src/missing.py]\n"
    )
    # No marker, no file.

    specs_by_slug = {s.slug: s for s in discover_specs(tmp_path)}
    findings = check_consumer(tmp_path, consumer, specs_by_slug)
    messages = [f.message for f in findings]
    assert any("implemented_in path missing" in m for m in messages)
    assert any("no '# SPEC: proto-v1' marker" in m for m in messages)


def test_check_consumer_passes_with_marker_and_impl(tmp_path: Path) -> None:
    owner = _mkrepo(tmp_path, "owner")
    _write_spec_file(owner, "proto-v1", "slug: proto-v1\nowner: owner\nstatus: adopted\nversion: 1.0.0\nadopted_at: 2026-04-24\nconsumers: [consumer]\n")

    consumer = _mkrepo(tmp_path, "consumer")
    (consumer / "docs").mkdir()
    (consumer / "docs" / "SPECS.yaml").write_text(
        "follows:\n"
        "  - slug: proto-v1\n"
        "    pinned_version: 1.0.0\n"
        "    implemented_in: [src/proto.py]\n"
    )
    (consumer / "src").mkdir()
    (consumer / "src" / "proto.py").write_text("# SPEC: proto-v1\n")

    specs_by_slug = {s.slug: s for s in discover_specs(tmp_path)}
    findings = check_consumer(tmp_path, consumer, specs_by_slug)
    assert findings == []


def test_check_consumer_flags_drift_on_pinned_version(tmp_path: Path) -> None:
    owner = _mkrepo(tmp_path, "owner")
    _write_spec_file(owner, "proto-v1", "slug: proto-v1\nowner: owner\nstatus: adopted\nversion: 1.2.0\nadopted_at: 2026-04-24\nconsumers: [consumer]\n")

    consumer = _mkrepo(tmp_path, "consumer")
    (consumer / "docs").mkdir()
    (consumer / "docs" / "SPECS.yaml").write_text(
        "follows:\n"
        "  - slug: proto-v1\n"
        "    pinned_version: 1.0.0\n"
        "    implemented_in: [src/proto.py]\n"
    )
    (consumer / "src").mkdir()
    (consumer / "src" / "proto.py").write_text("# SPEC: proto-v1\n")

    specs_by_slug = {s.slug: s for s in discover_specs(tmp_path)}
    findings = check_consumer(tmp_path, consumer, specs_by_slug)
    assert any("pinned_version 1.0.0 != owner's current 1.2.0" in f.message for f in findings)


def test_check_consumer_warns_on_missing_follows_when_spec_lists_consumer(tmp_path: Path) -> None:
    owner = _mkrepo(tmp_path, "owner")
    _write_spec_file(owner, "proto-v1", "slug: proto-v1\nowner: owner\nstatus: adopted\nversion: 1.0.0\nadopted_at: 2026-04-24\nconsumers: [consumer]\n")

    consumer = _mkrepo(tmp_path, "consumer")
    (consumer / "docs").mkdir()
    (consumer / "docs" / "SPECS.yaml").write_text("follows: []\n")

    specs_by_slug = {s.slug: s for s in discover_specs(tmp_path)}
    findings = check_consumer(tmp_path, consumer, specs_by_slug)
    assert any("spec lists this repo as consumer" in f.message for f in findings)


def test_scaffold_and_write(tmp_path: Path) -> None:
    repo = _mkrepo(tmp_path, "owner")
    spec = scaffold_spec(repo, slug="proto-v2", title="Proto v2", owner_name="owner")
    assert spec.slug == "proto-v2"
    assert "# Proto v2" in spec.body
    assert "# SPEC: proto-v2" in spec.body
    write_spec(spec)
    assert spec.path.exists()
    loaded = parse_spec_file(spec.path)
    assert loaded.slug == "proto-v2"


def test_check_all_skips_when_no_consumers(tmp_path: Path) -> None:
    _mkrepo(tmp_path, "lonely")
    assert check_all(tmp_path) == []
