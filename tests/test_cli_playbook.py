"""Tests for `tw playbook list/show` CLI."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from textworkspace.cli import main


VALID = """\
slug: pb-x
owner: ownerA
status: draft
version: 0.1.0
persona: pr-reviewer
description: short summary
steps:
  - id: s1
    kind: run
    run: ls
"""


def _make_repos(tmp_path: Path, *names: str) -> dict[str, Path]:
    repos: dict[str, Path] = {}
    for name in names:
        repo = tmp_path / name
        (repo / "docs/specs/playbooks").mkdir(parents=True)
        repos[name] = repo
    return repos


def _drop_playbook(repo: Path, fname: str, content: str) -> None:
    (repo / "docs/specs/playbooks" / fname).write_text(content)


def test_list_no_repos(tmp_path):
    with patch("textworkspace.cli._playbook_repos", return_value=None):
        result = CliRunner().invoke(main, ["playbook", "list"])
    assert result.exit_code != 0
    assert "no repos found" in result.output


def test_list_empty(tmp_path):
    repos = _make_repos(tmp_path, "owner")
    with patch("textworkspace.cli._playbook_repos", return_value=repos):
        result = CliRunner().invoke(main, ["playbook", "list"])
    assert result.exit_code == 0
    assert "No playbooks found" in result.output


def test_list_renders_row(tmp_path):
    repos = _make_repos(tmp_path, "ownerA")
    _drop_playbook(repos["ownerA"], "x.yaml", VALID)

    with patch("textworkspace.cli._playbook_repos", return_value=repos):
        result = CliRunner().invoke(main, ["playbook", "list"])
    assert result.exit_code == 0
    assert "pb-x" in result.output
    assert "ownerA" in result.output
    assert "draft" in result.output
    assert "0.1.0" in result.output
    assert "pr-reviewer" in result.output


def test_list_filter_owner(tmp_path):
    repos = _make_repos(tmp_path, "ownerA", "ownerB")
    _drop_playbook(repos["ownerA"], "a.yaml", VALID)
    _drop_playbook(repos["ownerB"], "b.yaml", VALID.replace("slug: pb-x", "slug: pb-y").replace("owner: ownerA", "owner: ownerB"))

    with patch("textworkspace.cli._playbook_repos", return_value=repos):
        result = CliRunner().invoke(main, ["playbook", "list", "--owner", "ownerA"])
    assert "pb-x" in result.output
    assert "pb-y" not in result.output


def test_list_filter_status(tmp_path):
    repos = _make_repos(tmp_path, "ownerA")
    _drop_playbook(repos["ownerA"], "draft.yaml", VALID)
    _drop_playbook(
        repos["ownerA"],
        "adopted.yaml",
        VALID.replace("slug: pb-x", "slug: pb-z").replace("status: draft", "status: adopted"),
    )

    with patch("textworkspace.cli._playbook_repos", return_value=repos):
        result = CliRunner().invoke(main, ["playbook", "list", "--status", "adopted"])
    assert "pb-z" in result.output
    assert "pb-x" not in result.output


def test_list_errors_flag_surfaces_parse_failures(tmp_path):
    repos = _make_repos(tmp_path, "ownerA")
    _drop_playbook(repos["ownerA"], "good.yaml", VALID)
    _drop_playbook(repos["ownerA"], "bad.yaml", "this: is\n  bad: -indent")

    with patch("textworkspace.cli._playbook_repos", return_value=repos):
        result = CliRunner().invoke(main, ["playbook", "list", "--errors"])
    assert "pb-x" in result.output
    assert "bad.yaml" in result.output
    assert "parse error" in result.output


def test_show_renders_full_summary(tmp_path):
    repos = _make_repos(tmp_path, "ownerA")
    _drop_playbook(repos["ownerA"], "x.yaml", VALID)

    with patch("textworkspace.cli._playbook_repos", return_value=repos):
        result = CliRunner().invoke(main, ["playbook", "show", "pb-x"])
    assert result.exit_code == 0
    out = result.output
    assert "# pb-x" in out
    assert "owner:    ownerA" in out
    assert "status:   draft" in out
    assert "persona:  pr-reviewer" in out
    assert "short summary" in out
    assert "steps (1)" in out
    assert "s1 (run)" in out


def test_show_unknown_slug(tmp_path):
    repos = _make_repos(tmp_path, "ownerA")
    with patch("textworkspace.cli._playbook_repos", return_value=repos):
        result = CliRunner().invoke(main, ["playbook", "show", "nope"])
    assert result.exit_code != 0
    assert "not found" in result.output
