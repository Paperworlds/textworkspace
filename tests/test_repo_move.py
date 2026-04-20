"""Tests for tw repo move and tw doctor stale-path aggregation."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from click.testing import CliRunner

from textworkspace.cli import main
from textworkspace.config import Config, RepoEntry, save_config
from textworkspace.doctor import CheckResult, run_doctor_checks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_config(config_dir: Path, repos: dict) -> None:
    data = {"repos": {name: {"path": str(entry["path"]), "label": "", "profile": ""}
                      for name, entry in repos.items()}}
    (config_dir / "config.yaml").write_text(yaml.dump(data))


# ---------------------------------------------------------------------------
# tw repo move — argument validation
# ---------------------------------------------------------------------------

def test_R01_unknown_name(config_dir):
    _write_config(config_dir, {})
    runner = CliRunner()
    result = runner.invoke(main, ["repo", "move", "nonexistent", "/some/path"])
    assert result.exit_code != 0
    assert "nonexistent" in result.output


# ---------------------------------------------------------------------------
# tw repo move — smart folder detection
# ---------------------------------------------------------------------------

def test_R02_already_moved(config_dir, tmp_path):
    """New path exists, old path does not — skip physical move, update refs."""
    old = tmp_path / "old-repo"
    new = tmp_path / "new-repo"
    new.mkdir()  # already moved

    _write_config(config_dir, {"myrepo": {"path": str(old)}})

    runner = CliRunner()
    with pytest.MonkeyPatch().context() as m:
        m.setattr("textworkspace.doctor.detect_installed_tools", lambda: {})
        result = runner.invoke(main, ["repo", "move", "myrepo", str(new)])

    assert result.exit_code == 0
    assert "already at" in result.output
    # config updated
    loaded = yaml.safe_load((config_dir / "config.yaml").read_text())
    assert loaded["repos"]["myrepo"]["path"] == str(new.resolve())


def test_R03_confirm_move(config_dir, tmp_path):
    """Old path exists, new does not — user confirms → dir renamed."""
    old = tmp_path / "old-repo"
    old.mkdir()
    new = tmp_path / "new-repo"

    _write_config(config_dir, {"myrepo": {"path": str(old)}})

    runner = CliRunner()
    with pytest.MonkeyPatch().context() as m:
        m.setattr("textworkspace.doctor.detect_installed_tools", lambda: {})
        result = runner.invoke(main, ["repo", "move", "myrepo", str(new)], input="y\n")

    assert result.exit_code == 0
    assert new.exists()
    assert not old.exists()


def test_R03_deny_move(config_dir, tmp_path):
    """Old path exists, new does not — user declines → abort, no changes."""
    old = tmp_path / "old-repo"
    old.mkdir()
    new = tmp_path / "new-repo"

    _write_config(config_dir, {"myrepo": {"path": str(old)}})

    runner = CliRunner()
    with pytest.MonkeyPatch().context() as m:
        m.setattr("textworkspace.doctor.detect_installed_tools", lambda: {})
        result = runner.invoke(main, ["repo", "move", "myrepo", str(new)], input="n\n")

    assert result.exit_code != 0
    assert old.exists()
    assert not new.exists()


def test_R04_both_exist(config_dir, tmp_path):
    """Both paths exist — abort with ambiguity warning."""
    old = tmp_path / "old-repo"
    new = tmp_path / "new-repo"
    old.mkdir()
    new.mkdir()

    _write_config(config_dir, {"myrepo": {"path": str(old)}})

    runner = CliRunner()
    with pytest.MonkeyPatch().context() as m:
        m.setattr("textworkspace.doctor.detect_installed_tools", lambda: {})
        result = runner.invoke(main, ["repo", "move", "myrepo", str(new)])

    assert result.exit_code != 0
    assert "ambiguous" in result.output.lower() or "exist" in result.output.lower()


def test_R05_neither_exists(config_dir, tmp_path):
    """Neither path exists — warns, updates config anyway."""
    old = tmp_path / "old-repo"
    new = tmp_path / "new-repo"

    _write_config(config_dir, {"myrepo": {"path": str(old)}})

    runner = CliRunner()
    with pytest.MonkeyPatch().context() as m:
        m.setattr("textworkspace.doctor.detect_installed_tools", lambda: {})
        result = runner.invoke(main, ["repo", "move", "myrepo", str(new)])

    assert result.exit_code == 0
    assert "WARN" in result.output
    loaded = yaml.safe_load((config_dir / "config.yaml").read_text())
    assert loaded["repos"]["myrepo"]["path"] == str(new.resolve())


# ---------------------------------------------------------------------------
# tw repo move — tool orchestration
# ---------------------------------------------------------------------------

from textworkspace.doctor import ToolInfo


def _make_tool_info(bin_path: str) -> ToolInfo:
    return ToolInfo(name="faketool", installed=True, bin_path=bin_path)


def test_R09_tool_called_and_output_shown(config_dir, tmp_path, monkeypatch):
    """Tool repo move exits 0 → MOVED line printed."""
    new = tmp_path / "new-repo"
    new.mkdir()
    old = tmp_path / "old-repo"
    _write_config(config_dir, {"myrepo": {"path": str(old)}})

    fake_run_calls = []

    def fake_run(cmd, **kwargs):
        fake_run_calls.append(cmd)
        m = MagicMock()
        m.returncode = 0
        m.stdout = "MOVED myrepo /old → /new"
        m.stderr = ""
        return m

    monkeypatch.setattr("textworkspace.cli.subprocess.run", fake_run)
    monkeypatch.setattr(
        "textworkspace.doctor.detect_installed_tools",
        lambda: {"faketool": _make_tool_info("/usr/local/bin/faketool")},
    )

    runner = CliRunner()
    result = runner.invoke(main, ["repo", "move", "myrepo", str(new)])

    assert result.exit_code == 0
    assert "MOVED myrepo" in result.output
    repo_move_calls = [c for c in fake_run_calls if "repo" in c]
    assert any("move" in c for c in repo_move_calls)


def test_R10_exit2_skipped_silently(config_dir, tmp_path, monkeypatch):
    """Tool repo move exits 2 → no output for that tool."""
    new = tmp_path / "new-repo"
    new.mkdir()
    old = tmp_path / "old-repo"
    _write_config(config_dir, {"myrepo": {"path": str(old)}})

    def fake_run(cmd, **kwargs):
        m = MagicMock()
        m.returncode = 2
        m.stdout = ""
        m.stderr = ""
        return m

    monkeypatch.setattr("textworkspace.cli.subprocess.run", fake_run)
    monkeypatch.setattr(
        "textworkspace.doctor.detect_installed_tools",
        lambda: {"faketool": _make_tool_info("/usr/local/bin/faketool")},
    )

    runner = CliRunner()
    result = runner.invoke(main, ["repo", "move", "myrepo", str(new)])

    assert result.exit_code == 0
    assert "faketool" not in result.output


def test_R11_nonzero_exit_warns(config_dir, tmp_path, monkeypatch):
    """Tool repo move exits 1 → [WARN] printed."""
    new = tmp_path / "new-repo"
    new.mkdir()
    old = tmp_path / "old-repo"
    _write_config(config_dir, {"myrepo": {"path": str(old)}})

    def fake_run(cmd, **kwargs):
        m = MagicMock()
        m.returncode = 1
        m.stdout = ""
        m.stderr = "something went wrong"
        return m

    monkeypatch.setattr("textworkspace.cli.subprocess.run", fake_run)
    monkeypatch.setattr(
        "textworkspace.doctor.detect_installed_tools",
        lambda: {"faketool": _make_tool_info("/usr/local/bin/faketool")},
    )

    runner = CliRunner()
    result = runner.invoke(main, ["repo", "move", "myrepo", str(new)])

    assert result.exit_code == 0
    assert "WARN" in result.output
    assert "something went wrong" in result.output


# ---------------------------------------------------------------------------
# tw doctor — stale-path aggregation (R13, R14)
# ---------------------------------------------------------------------------

def test_R13_doctor_stale_aggregation(config_dir, monkeypatch):
    """Tool doctor outputs STALE line → CheckResult added with warn status."""
    def fake_run(cmd, **kwargs):
        if "doctor" in cmd:
            m = MagicMock()
            m.returncode = 1
            m.stdout = "STALE myrepo /old/path/myrepo\n"
            return m
        m = MagicMock()
        m.returncode = 0
        m.stdout = ""
        return m

    monkeypatch.setattr("textworkspace.doctor.subprocess.run", fake_run)
    monkeypatch.setattr(
        "textworkspace.doctor.detect_installed_tools",
        lambda: {"faketool": _make_tool_info("/usr/local/bin/faketool")},
    )

    results = run_doctor_checks()
    stale = [r for r in results if "stale" in r.detail.lower()]
    assert len(stale) == 1
    assert stale[0].status == "warn"
    assert "myrepo" in stale[0].label
    assert "/old/path/myrepo" in stale[0].detail
    assert "tw repo move myrepo" in (stale[0].fix or "")


def test_R14_doctor_timeout_skipped(config_dir, monkeypatch):
    """Tool doctor times out → no stale CheckResult added."""
    def fake_run(cmd, **kwargs):
        if "doctor" in cmd:
            raise subprocess.TimeoutExpired(cmd, 5)
        m = MagicMock()
        m.returncode = 0
        m.stdout = ""
        return m

    monkeypatch.setattr("textworkspace.doctor.subprocess.run", fake_run)
    monkeypatch.setattr(
        "textworkspace.doctor.detect_installed_tools",
        lambda: {"faketool": _make_tool_info("/usr/local/bin/faketool")},
    )

    results = run_doctor_checks()
    stale = [r for r in results if "stale" in r.detail.lower()]
    assert len(stale) == 0
