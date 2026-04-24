"""Tests for textworkspace.ideas."""

from __future__ import annotations

from pathlib import Path

from textworkspace.ideas import load_all_ideas, load_ideas_for_repo


def _mkrepo(root: Path, name: str, ideas_yaml: str | None = None, ideas_md: str | None = None) -> Path:
    repo = root / name
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    if ideas_yaml is not None:
        (repo / "docs").mkdir()
        (repo / "docs" / "IDEAS.yaml").write_text(ideas_yaml)
    if ideas_md is not None:
        (repo / "IDEAS.md").write_text(ideas_md)
    return repo


def test_list_form_with_id(tmp_path: Path) -> None:
    _mkrepo(tmp_path, "alpha", ideas_yaml="""
ideas:
  - id: a1
    title: First idea
    status: planned
    priority: 1
    summary: |
      multi line
""")
    ideas = load_ideas_for_repo(tmp_path / "alpha")
    assert len(ideas) == 1
    assert ideas[0].id == "a1"
    assert ideas[0].title == "First idea"
    assert ideas[0].status == "planned"
    assert ideas[0].priority == 1


def test_mapping_form_with_slug_as_key(tmp_path: Path) -> None:
    _mkrepo(tmp_path, "beta", ideas_yaml="""
ideas:
  slug_one:
    title: Slug one
    status: idea
  slug_two:
    title: Slug two
    status: exploring
""")
    ideas = sorted(load_ideas_for_repo(tmp_path / "beta"), key=lambda i: i.id)
    assert [i.id for i in ideas] == ["slug_one", "slug_two"]
    assert ideas[0].status == "idea"


def test_brainstorm_form_with_name(tmp_path: Path) -> None:
    _mkrepo(tmp_path, "gamma", ideas_yaml="""
brainstorm:
  - name: forums-agent
    title: Enforce forums usage
    status: brainstorm
""")
    ideas = load_ideas_for_repo(tmp_path / "gamma")
    assert ideas[0].id == "forums-agent"
    assert ideas[0].status == "brainstorm"


def test_markdown_placeholder(tmp_path: Path) -> None:
    _mkrepo(tmp_path, "delta", ideas_md="# some ideas\n")
    ideas = load_ideas_for_repo(tmp_path / "delta")
    assert len(ideas) == 1
    assert ideas[0].format == "md"
    assert ideas[0].status == "md"


def test_load_all_discovers_sibling_repos(tmp_path: Path) -> None:
    _mkrepo(tmp_path, "one", ideas_yaml="ideas:\n  - id: x\n    title: X\n    status: idea\n")
    _mkrepo(tmp_path, "two", ideas_yaml="ideas:\n  - id: y\n    title: Y\n    status: idea\n")
    (tmp_path / "not_a_repo").mkdir()  # no pyproject -> skipped
    ideas = load_all_ideas(tmp_path)
    assert sorted(i.repo for i in ideas) == ["one", "two"]


def test_parse_error_surfaces_as_entry(tmp_path: Path) -> None:
    _mkrepo(tmp_path, "broken", ideas_yaml="ideas:\n  - bad yaml: : :\n")
    ideas = load_ideas_for_repo(tmp_path / "broken")
    assert len(ideas) == 1
    assert ideas[0].status == "error"


def test_directory_of_per_idea_yaml(tmp_path: Path) -> None:
    repo = _mkrepo(tmp_path, "work-repo")
    (repo / ".files" / "ideas").mkdir(parents=True)
    (repo / ".files" / "ideas" / "refactor-auth.yaml").write_text(
        "title: Refactor auth\nstatus: planned\npriority: 2\nsummary: do the thing\n"
    )
    (repo / ".files" / "ideas" / "bundle-logs.yaml").write_text(
        "title: Bundle logs\nstatus: idea\n"
    )
    ideas = sorted(load_ideas_for_repo(repo), key=lambda i: i.id)
    assert [i.id for i in ideas] == ["bundle-logs", "refactor-auth"]
    assert ideas[1].priority == 2
    assert ideas[1].summary == "do the thing"


def test_directory_and_single_file_coexist(tmp_path: Path) -> None:
    repo = _mkrepo(tmp_path, "mixed",
                   ideas_yaml="ideas:\n  - id: agg\n    title: Aggregate\n    status: idea\n")
    (repo / ".files" / "ideas").mkdir(parents=True)
    (repo / ".files" / "ideas" / "extra.yaml").write_text("title: Extra\nstatus: idea\n")
    ideas = sorted(load_ideas_for_repo(repo), key=lambda i: i.id)
    assert {i.id for i in ideas} == {"agg", "extra"}


def test_directory_of_md_files_placeholders(tmp_path: Path) -> None:
    repo = _mkrepo(tmp_path, "md-repo")
    (repo / ".files" / "ideas").mkdir(parents=True)
    (repo / ".files" / "ideas" / "sketch.md").write_text("# sketch\n")
    ideas = load_ideas_for_repo(repo)
    assert len(ideas) == 1
    assert ideas[0].id == "sketch"
    assert ideas[0].format == "md"
