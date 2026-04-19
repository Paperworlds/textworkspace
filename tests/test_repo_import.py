"""Tests for repo_import.py and tw repo import CLI command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from textworkspace.repo_import import (
    ImportedRepo,
    _parse_repo_line,
    collect_from_tool,
    deduplicate,
    find_conflicts,
)


# ---------------------------------------------------------------------------
# _parse_repo_line
# ---------------------------------------------------------------------------


def test_parse_valid_line():
    result = _parse_repo_line("REPO foo /projects/foo")
    assert result is not None
    name, path, meta = result
    assert name == "foo"
    assert path == Path("/projects/foo")
    assert meta == {}


def test_parse_line_with_known_meta():
    result = _parse_repo_line("REPO foo /projects/foo profile=work")
    assert result is not None
    name, path, meta = result
    assert meta == {"profile": "work"}


def test_parse_line_unknown_keys_ignored(R03=None):
    """Unknown k=v pairs are accepted and returned — forward-compatible (R03)."""
    result = _parse_repo_line("REPO foo /projects/foo profile=work future_key=whatever")
    assert result is not None
    _, _, meta = result
    assert "future_key" in meta
    assert meta["future_key"] == "whatever"


def test_parse_non_repo_line_returns_none():
    assert _parse_repo_line("STALE something /path") is None
    assert _parse_repo_line("") is None
    assert _parse_repo_line("# comment") is None


def test_parse_malformed_too_short_returns_none():
    assert _parse_repo_line("REPO onlyname") is None


def test_parse_tilde_path_expanded():
    result = _parse_repo_line("REPO foo ~/projects/foo")
    assert result is not None
    _, path, _ = result
    assert not str(path).startswith("~")


# ---------------------------------------------------------------------------
# collect_from_tool
# ---------------------------------------------------------------------------


def _mock_run(stdout: str, returncode: int):
    def _run(args, **kw):
        m = MagicMock()
        m.stdout = stdout
        m.returncode = returncode
        return m
    return _run


def test_collect_parses_repo_lines():
    output = "REPO foo /projects/foo profile=work\nREPO bar /projects/bar\n"
    with patch("subprocess.run", _mock_run(output, 0)):
        repos, code = collect_from_tool("/usr/bin/textsessions", "textsessions")
    assert code == 0
    assert len(repos) == 2
    assert repos[0].name == "foo"
    assert repos[1].name == "bar"


def test_collect_skips_non_repo_lines():
    output = "some noise\nREPO foo /projects/foo\nmore noise\n"
    with patch("subprocess.run", _mock_run(output, 0)):
        repos, code = collect_from_tool("/usr/bin/textsessions", "textsessions")
    assert len(repos) == 1


def test_collect_returns_exit_code():
    with patch("subprocess.run", _mock_run("", 2)):
        repos, code = collect_from_tool("/usr/bin/textsessions", "textsessions")
    assert code == 2
    assert repos == []


# ---------------------------------------------------------------------------
# deduplicate
# ---------------------------------------------------------------------------


def test_deduplicate_collapses_same_path():
    repos = [
        ImportedRepo(name="foo", path=Path("/projects/foo")),
        ImportedRepo(name="foo-alias", path=Path("/projects/foo")),
    ]
    result = deduplicate(repos)
    assert len(result) == 1
    assert result[0].name == "foo"


def test_deduplicate_keeps_different_paths():
    repos = [
        ImportedRepo(name="foo", path=Path("/projects/foo")),
        ImportedRepo(name="bar", path=Path("/projects/bar")),
    ]
    result = deduplicate(repos)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# find_conflicts
# ---------------------------------------------------------------------------


def _existing_repos(**kwargs):
    """Build a simple existing repos dict for conflict detection."""
    result = {}
    for name, path in kwargs.items():
        m = MagicMock()
        m.path = path
        result[name] = m
    return result


def test_conflict_same_name_different_path():
    incoming = [ImportedRepo(name="foo", path=Path("/new/path"))]
    existing = _existing_repos(foo="/old/path")
    conflicts = find_conflicts(incoming, existing)
    assert len(conflicts) == 1
    assert conflicts[0].kind == "name"


def test_conflict_same_path_different_name():
    incoming = [ImportedRepo(name="bar", path=Path("/projects/foo"))]
    existing = _existing_repos(foo="/projects/foo")
    conflicts = find_conflicts(incoming, existing)
    assert len(conflicts) == 1
    assert conflicts[0].kind == "path"


def test_no_conflict_clean_import():
    incoming = [ImportedRepo(name="newrepo", path=Path("/projects/new"))]
    existing = _existing_repos(foo="/projects/foo")
    conflicts = find_conflicts(incoming, existing)
    assert conflicts == []


# ---------------------------------------------------------------------------
# tw repo import CLI — integration tests
# ---------------------------------------------------------------------------


def test_exit_2_silent_skip(tmp_path, monkeypatch):
    """Tool exit code 2 is skipped silently (R12)."""
    from textworkspace.cli import main
    from textworkspace.doctor import ToolInfo

    mock_tools = {
        "textsessions": ToolInfo(
            name="textsessions", installed=True, bin_path="/usr/bin/textsessions"
        )
    }
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr("textworkspace.combos.COMBOS_FILE", tmp_path / "combos.yaml")
    monkeypatch.setattr("textworkspace.combos.COMBOS_DIR", tmp_path / "combos.d")

    with patch("textworkspace.doctor.detect_installed_tools", return_value=mock_tools), \
         patch("subprocess.run", _mock_run("", 2)):
        result = CliRunner().invoke(main, ["repo", "import", "textsessions"])

    assert result.exit_code == 0
    assert "WARN" not in result.output


def test_nonzero_non2_prints_warn(tmp_path, monkeypatch):
    """Non-zero, non-2 exit code prints [WARN] and continues (R13)."""
    from textworkspace.cli import main
    from textworkspace.doctor import ToolInfo

    mock_tools = {
        "textsessions": ToolInfo(
            name="textsessions", installed=True, bin_path="/usr/bin/textsessions"
        )
    }
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr("textworkspace.combos.COMBOS_FILE", tmp_path / "combos.yaml")
    monkeypatch.setattr("textworkspace.combos.COMBOS_DIR", tmp_path / "combos.d")

    with patch("textworkspace.doctor.detect_installed_tools", return_value=mock_tools), \
         patch("subprocess.run", _mock_run("", 1)):
        result = CliRunner().invoke(main, ["repo", "import", "textsessions"])

    assert "WARN" in result.output


def test_missing_path_imports_with_warn(tmp_path, monkeypatch):
    """Repos with non-existent paths are still imported, with a [WARN] (R14)."""
    from textworkspace.cli import main
    from textworkspace.doctor import ToolInfo

    mock_tools = {
        "textsessions": ToolInfo(
            name="textsessions", installed=True, bin_path="/usr/bin/textsessions"
        )
    }
    output = "REPO ghost /does/not/exist profile=work\n"
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr("textworkspace.combos.COMBOS_FILE", tmp_path / "combos.yaml")
    monkeypatch.setattr("textworkspace.combos.COMBOS_DIR", tmp_path / "combos.d")

    with patch("textworkspace.doctor.detect_installed_tools", return_value=mock_tools), \
         patch("subprocess.run", _mock_run(output, 0)):
        result = CliRunner().invoke(main, ["repo", "import", "textsessions"])

    assert "WARN" in result.output
    assert "ghost" in result.output


# ---------------------------------------------------------------------------
# tw workspaces add pick-lists
# ---------------------------------------------------------------------------


def test_pick_list_number_resolves_to_item():
    """Typing a valid number returns the corresponding item."""
    import textworkspace.cli as _cli_mod
    from textworkspace.cli import _prompt_pick_list
    with patch.object(_cli_mod.click, "prompt", return_value="2"), \
         patch.object(_cli_mod.click, "echo"):
        result = _prompt_pick_list(["alpha", "beta", "gamma"], "Pick one")
    assert result == "beta"


def test_pick_list_freetext_accepted():
    """Typing free text instead of a number returns it as-is."""
    import textworkspace.cli as _cli_mod
    from textworkspace.cli import _prompt_pick_list
    with patch.object(_cli_mod.click, "prompt", return_value="my-custom-profile"), \
         patch.object(_cli_mod.click, "echo"):
        result = _prompt_pick_list(["alpha", "beta"], "Pick one")
    assert result == "my-custom-profile"


def test_pick_list_empty_falls_back_to_prompt():
    """Empty items list falls back to a plain click.prompt (R17)."""
    import textworkspace.cli as _cli_mod
    from textworkspace.cli import _prompt_pick_list
    with patch.object(_cli_mod.click, "prompt", return_value="fallback") as mock_prompt, \
         patch.object(_cli_mod.click, "echo"):
        result = _prompt_pick_list([], "Pick one")
    assert result == "fallback"
    mock_prompt.assert_called_once()


def test_pick_list_out_of_range_treated_as_freetext():
    """Out-of-range number is treated as free text."""
    import textworkspace.cli as _cli_mod
    from textworkspace.cli import _prompt_pick_list
    with patch.object(_cli_mod.click, "prompt", return_value="99"), \
         patch.object(_cli_mod.click, "echo"):
        result = _prompt_pick_list(["alpha", "beta"], "Pick one")
    assert result == "99"
