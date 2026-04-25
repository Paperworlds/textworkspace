"""Tests for `tw run` thin wrapper."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from textworkspace.cli import main


VALID_WITH_INPUTS = """\
slug: pb-x
owner: ownerA
status: draft
version: 0.1.0
persona: pr-reviewer
inputs:
  - name: pr_number
    type: int
    required: true
  - name: repo
    type: string
    required: true
  - name: extra
    type: string
    required: false
steps:
  - id: a
    kind: run
    run: ls
"""


def _repos_with_pb(tmp_path: Path, content: str) -> dict[str, Path]:
    repo = tmp_path / "ownerA"
    (repo / "docs/specs/playbooks").mkdir(parents=True)
    (repo / "docs/specs/playbooks" / "x.yaml").write_text(content)
    return {"ownerA": repo}


def test_run_unknown_slug(tmp_path):
    repos = _repos_with_pb(tmp_path, VALID_WITH_INPUTS)
    with patch("textworkspace.cli._playbook_repos", return_value=repos):
        result = CliRunner().invoke(main, ["run", "missing"])
    assert result.exit_code != 0
    assert "not found" in result.output


def test_run_missing_required_input(tmp_path):
    repos = _repos_with_pb(tmp_path, VALID_WITH_INPUTS)
    with patch("textworkspace.cli._playbook_repos", return_value=repos):
        result = CliRunner().invoke(main, ["run", "pb-x", "--dry-run"])
    assert result.exit_code == 2
    assert "missing required input" in result.output


def test_run_unknown_input_rejected(tmp_path):
    repos = _repos_with_pb(tmp_path, VALID_WITH_INPUTS)
    with patch("textworkspace.cli._playbook_repos", return_value=repos):
        result = CliRunner().invoke(main, [
            "run", "pb-x", "-i", "pr_number=1", "-i", "repo=x/y",
            "-i", "made_up=oops", "--dry-run",
        ])
    assert result.exit_code == 2
    assert "unknown input" in result.output


def test_run_invalid_input_format(tmp_path):
    repos = _repos_with_pb(tmp_path, VALID_WITH_INPUTS)
    with patch("textworkspace.cli._playbook_repos", return_value=repos):
        result = CliRunner().invoke(main, [
            "run", "pb-x", "-i", "no_equals_sign", "--dry-run",
        ])
    assert result.exit_code == 2
    assert "invalid --input" in result.output


def test_run_dry_run_prints_command(tmp_path):
    repos = _repos_with_pb(tmp_path, VALID_WITH_INPUTS)
    with patch("textworkspace.cli._playbook_repos", return_value=repos):
        result = CliRunner().invoke(main, [
            "run", "pb-x", "-i", "pr_number=1", "-i", "repo=x/y", "--dry-run",
        ])
    assert result.exit_code == 0
    assert "playbook run pb-x" in result.output
    assert "pr_number=1" in result.output
    assert "repo=x/y" in result.output
    assert "(dry-run" in result.output


def test_run_invokes_pp_when_installed(tmp_path):
    repos = _repos_with_pb(tmp_path, VALID_WITH_INPUTS)
    fake_tool = MagicMock(installed=True, bin_path="/fake/textprompts")
    fake_result = MagicMock(returncode=0)

    with (
        patch("textworkspace.cli._playbook_repos", return_value=repos),
        patch("textworkspace.doctor.detect_installed_tools",
              return_value={"textprompts": fake_tool}),
        patch("textworkspace.cli.subprocess.run", return_value=fake_result) as run_mock,
    ):
        result = CliRunner().invoke(main, [
            "run", "pb-x", "-i", "pr_number=1", "-i", "repo=x/y",
        ])
    assert result.exit_code == 0
    args = run_mock.call_args[0][0]
    assert args[0] == "/fake/textprompts"
    assert args[1:4] == ["playbook", "run", "pb-x"]
    assert "pr_number=1" in args
    assert "repo=x/y" in args


def test_run_surfaces_unsupported_verb(tmp_path):
    """When pp returns exit 2 (verb not implemented), surface the contract message."""
    repos = _repos_with_pb(tmp_path, VALID_WITH_INPUTS)
    fake_tool = MagicMock(installed=True, bin_path="/fake/textprompts")
    fake_result = MagicMock(returncode=2)

    with (
        patch("textworkspace.cli._playbook_repos", return_value=repos),
        patch("textworkspace.doctor.detect_installed_tools",
              return_value={"textprompts": fake_tool}),
        patch("textworkspace.cli.subprocess.run", return_value=fake_result),
    ):
        result = CliRunner().invoke(main, [
            "run", "pb-x", "-i", "pr_number=1", "-i", "repo=x/y",
        ])
    assert result.exit_code == 2
    assert "not yet supported" in result.output


def test_run_no_textprompts_installed(tmp_path):
    repos = _repos_with_pb(tmp_path, VALID_WITH_INPUTS)
    with (
        patch("textworkspace.cli._playbook_repos", return_value=repos),
        patch("textworkspace.doctor.detect_installed_tools", return_value={}),
        patch("textworkspace.cli.subprocess.run") as run_mock,
    ):
        run_mock.side_effect = AssertionError("subprocess.run must not be called when no tool installed")
        result = CliRunner().invoke(main, [
            "run", "pb-x", "-i", "pr_number=1", "-i", "repo=x/y",
        ])
    assert result.exit_code == 127
    assert "not installed" in result.output
