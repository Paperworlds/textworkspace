"""Tests for the textworkspace CLI entry point."""

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from textworkspace.cli import main
from textworkspace.config import Config, ToolEntry, config_as_yaml, load_config, save_config


# ---------------------------------------------------------------------------
# CLI smoke tests
# ---------------------------------------------------------------------------

def test_version():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "textworkspace" in result.output


def test_help_shows_all_subcommands():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    expected = ["init", "status", "doctor", "update", "switch", "sessions", "stats", "serve", "config", "which"]
    for cmd in expected:
        assert cmd in result.output, f"subcommand '{cmd}' missing from --help"


# ---------------------------------------------------------------------------
# Config load / save / defaults
# ---------------------------------------------------------------------------

def test_load_config_creates_file_on_first_access(tmp_path, monkeypatch):
    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", tmp_path / "config.yaml")

    cfg = load_config()
    assert (tmp_path / "config.yaml").exists()
    assert isinstance(cfg, Config)
    assert isinstance(cfg.tools, dict)
    assert "profile" in cfg.defaults


def test_save_and_round_trip(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", cfg_file)

    cfg = Config(
        tools={
            "textaccounts": ToolEntry(version="0.3.1", source="pypi"),
            "textserve": ToolEntry(version="0.1.0", source="github", bin="~/.local/share/textworkspace/bin/textserve"),
        },
        defaults={"profile": "work", "proxy_autostart": False},
    )
    save_config(cfg)

    loaded = load_config()
    assert loaded.tools["textaccounts"].version == "0.3.1"
    assert loaded.tools["textaccounts"].source == "pypi"
    assert loaded.tools["textaccounts"].bin is None
    assert loaded.tools["textserve"].bin == "~/.local/share/textworkspace/bin/textserve"
    assert loaded.defaults["profile"] == "work"


def test_config_as_yaml_is_valid_yaml():
    cfg = Config(
        tools={"textaccounts": ToolEntry(version="0.3.1", source="pypi")},
        defaults={"profile": "default", "proxy_autostart": False},
    )
    out = config_as_yaml(cfg)
    parsed = yaml.safe_load(out)
    assert parsed["tools"]["textaccounts"]["version"] == "0.3.1"
    assert parsed["defaults"]["profile"] == "default"


def test_load_config_no_bin_omitted_from_yaml(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", cfg_file)

    cfg = Config(tools={"textaccounts": ToolEntry(version="0.3.1", source="pypi")})
    save_config(cfg)

    raw = yaml.safe_load(cfg_file.read_text())
    assert "bin" not in raw["tools"]["textaccounts"]


# ---------------------------------------------------------------------------
# tw config command
# ---------------------------------------------------------------------------

def test_config_show_prints_yaml(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", cfg_file)

    runner = CliRunner()
    result = runner.invoke(main, ["config"])
    assert result.exit_code == 0
    parsed = yaml.safe_load(result.output)
    assert "defaults" in parsed


def test_config_show_subcommand(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", cfg_file)

    runner = CliRunner()
    result = runner.invoke(main, ["config", "show"])
    assert result.exit_code == 0
    yaml.safe_load(result.output)  # valid YAML


# ---------------------------------------------------------------------------
# tw which command
# ---------------------------------------------------------------------------

def test_which_known_tool(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", cfg_file)

    cfg = Config(tools={"textaccounts": ToolEntry(version="0.3.1", source="pypi")})
    save_config(cfg)

    runner = CliRunner()
    result = runner.invoke(main, ["which", "textaccounts"])
    assert result.exit_code == 0
    assert "0.3.1" in result.output
    assert "pypi" in result.output


def test_which_tool_with_bin(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", cfg_file)

    cfg = Config(tools={
        "textserve": ToolEntry(version="0.1.0", source="github", bin="~/.local/share/textworkspace/bin/textserve")
    })
    save_config(cfg)

    runner = CliRunner()
    result = runner.invoke(main, ["which", "textserve"])
    assert result.exit_code == 0
    assert "github" in result.output
    assert "~/.local/share/textworkspace/bin/textserve" in result.output


def test_which_unknown_tool(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", cfg_file)

    save_config(Config())

    runner = CliRunner()
    result = runner.invoke(main, ["which", "nonexistent"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# tw switch
# ---------------------------------------------------------------------------

def test_switch_warns_when_textaccounts_missing(monkeypatch):
    monkeypatch.setattr("textworkspace.cli._HAS_TEXTACCOUNTS", False)

    runner = CliRunner()
    result = runner.invoke(main, ["switch", "work"])
    assert result.exit_code != 0
    assert "textaccounts" in result.output


def test_switch_lists_profiles_when_no_profile_arg(monkeypatch):
    monkeypatch.setattr("textworkspace.cli._HAS_TEXTACCOUNTS", True)
    monkeypatch.setattr("textworkspace.cli.list_profiles", lambda: ["work", "personal"])

    runner = CliRunner()
    result = runner.invoke(main, ["switch"])
    assert result.exit_code == 0
    assert "work" in result.output
    assert "personal" in result.output


def test_switch_emits_fish_env_exports(monkeypatch):
    monkeypatch.setattr("textworkspace.cli._HAS_TEXTACCOUNTS", True)
    monkeypatch.setattr("textworkspace.cli.list_profiles", lambda: ["work"])
    monkeypatch.setattr(
        "textworkspace.cli.env_for_profile",
        lambda p: {"CLAUDE_CONFIG_DIR": "/home/user/.claude-work"},
    )
    monkeypatch.setattr("textworkspace.cli._ta_switch", lambda p: None)

    runner = CliRunner()
    result = runner.invoke(main, ["switch", "work"])
    assert result.exit_code == 0
    assert "set -gx" in result.output
    assert "CLAUDE_CONFIG_DIR" in result.output


def test_switch_unknown_profile_exits_nonzero(monkeypatch):
    monkeypatch.setattr("textworkspace.cli._HAS_TEXTACCOUNTS", True)
    monkeypatch.setattr("textworkspace.cli.list_profiles", lambda: ["work"])
    monkeypatch.setattr("textworkspace.cli.env_for_profile", lambda p: (_ for _ in ()).throw(KeyError(p)))

    runner = CliRunner()
    result = runner.invoke(main, ["switch", "nonexistent"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# tw sessions
# ---------------------------------------------------------------------------

def test_sessions_warns_when_missing(monkeypatch):
    monkeypatch.setattr("textworkspace.cli._HAS_TEXTSESSIONS", False)
    monkeypatch.setattr("textworkspace.cli.shutil.which", lambda _: None)

    runner = CliRunner()
    result = runner.invoke(main, ["sessions"])
    assert result.exit_code != 0
    assert "textsessions" in result.output


def test_sessions_lists_via_api(monkeypatch):
    monkeypatch.setattr("textworkspace.cli._HAS_TEXTSESSIONS", True)
    monkeypatch.setattr(
        "textworkspace.cli._ts_list",
        lambda query=None, limit=20: [
            {"id": "abc123", "title": "my session", "state": "active"},
            {"id": "def456", "title": "old session", "state": "idle"},
        ],
    )

    runner = CliRunner()
    result = runner.invoke(main, ["sessions"])
    assert result.exit_code == 0
    assert "abc123" in result.output
    assert "my session" in result.output
    assert "active" in result.output


def test_sessions_no_results(monkeypatch):
    monkeypatch.setattr("textworkspace.cli._HAS_TEXTSESSIONS", True)
    monkeypatch.setattr("textworkspace.cli._ts_list", lambda query=None, limit=20: [])

    runner = CliRunner()
    result = runner.invoke(main, ["sessions"])
    assert result.exit_code == 0
    assert "No sessions" in result.output


# ---------------------------------------------------------------------------
# tw stats
# ---------------------------------------------------------------------------

def test_stats_from_http(monkeypatch):
    monkeypatch.setattr(
        "textworkspace.cli._proxy_stats_http",
        lambda port=9880: {"tokens": 14200, "cost": 0.042, "session_count": 3, "active_sessions": 1},
    )

    runner = CliRunner()
    result = runner.invoke(main, ["stats"])
    assert result.exit_code == 0
    assert "14.2k" in result.output
    assert "0.0420" in result.output


def test_stats_falls_back_to_subprocess(monkeypatch):
    def _fail(*a, **kw):
        raise ConnectionError("not running")

    monkeypatch.setattr("textworkspace.cli._proxy_stats_http", _fail)
    monkeypatch.setattr(
        "textworkspace.cli._proxy_stats_subprocess",
        lambda: {"tokens": 5000},
    )

    runner = CliRunner()
    result = runner.invoke(main, ["stats"])
    assert result.exit_code == 0
    assert "5.0k" in result.output


def test_stats_warns_when_proxy_not_running(monkeypatch):
    def _fail_http(*a, **kw):
        raise ConnectionError("no")

    def _fail_proc():
        raise FileNotFoundError("textproxy")

    monkeypatch.setattr("textworkspace.cli._proxy_stats_http", _fail_http)
    monkeypatch.setattr("textworkspace.cli._proxy_stats_subprocess", _fail_proc)

    runner = CliRunner()
    result = runner.invoke(main, ["stats"])
    assert result.exit_code != 0
    assert "textproxy" in result.output


def test_stats_session_filter(monkeypatch):
    monkeypatch.setattr(
        "textworkspace.cli._proxy_stats_http",
        lambda port=9880: {"sessions": {"sess-1": {"tokens": 999}}},
    )

    runner = CliRunner()
    result = runner.invoke(main, ["stats", "--session", "sess-1"])
    assert result.exit_code == 0
    assert "sess-1" in result.output
    assert "999" in result.output


# ---------------------------------------------------------------------------
# tw serve
# ---------------------------------------------------------------------------

def test_serve_warns_when_binary_missing(monkeypatch):
    monkeypatch.setattr("textworkspace.cli.shutil.which", lambda _: None)
    # Also make sure BIN_DIR path doesn't exist
    from textworkspace.bootstrap import BIN_DIR
    monkeypatch.setattr("textworkspace.cli.BIN_DIR", Path("/nonexistent/bin"))

    runner = CliRunner()
    result = runner.invoke(main, ["serve"])
    assert result.exit_code != 0
    assert "textserve" in result.output


def test_serve_list_no_servers(monkeypatch, tmp_path):
    fake_bin = tmp_path / "textserve"
    fake_bin.write_text("#!/bin/sh\necho '[]'\n")
    fake_bin.chmod(0o755)

    monkeypatch.setattr("textworkspace.cli.shutil.which", lambda _: str(fake_bin))

    runner = CliRunner()
    result = runner.invoke(main, ["serve"])
    assert result.exit_code == 0
    assert "No servers running" in result.output


def test_serve_list_with_servers(monkeypatch, tmp_path):
    import json as _json

    servers = [{"name": "airflow", "status": "running", "addr": ":8080"}]
    fake_bin = tmp_path / "textserve"
    fake_bin.write_text(f"#!/bin/sh\necho '{_json.dumps(servers)}'\n")
    fake_bin.chmod(0o755)

    monkeypatch.setattr("textworkspace.cli.shutil.which", lambda _: str(fake_bin))

    runner = CliRunner()
    result = runner.invoke(main, ["serve"])
    assert result.exit_code == 0
    assert "airflow" in result.output
    assert "running" in result.output


# ---------------------------------------------------------------------------
# tw status
# ---------------------------------------------------------------------------

def test_status_shows_all_sections(monkeypatch):
    monkeypatch.setattr("textworkspace.cli._HAS_TEXTACCOUNTS", False)
    monkeypatch.setattr("textworkspace.cli._HAS_TEXTSESSIONS", False)

    def _fail_http(*a, **kw):
        raise ConnectionError

    def _fail_proc():
        raise FileNotFoundError

    monkeypatch.setattr("textworkspace.cli._proxy_stats_http", _fail_http)
    monkeypatch.setattr("textworkspace.cli._proxy_stats_subprocess", _fail_proc)
    monkeypatch.setattr("textworkspace.cli.shutil.which", lambda _: None)
    monkeypatch.setattr("textworkspace.cli.BIN_DIR", Path("/nonexistent/bin"))

    runner = CliRunner()
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0
    assert "profile" in result.output
    assert "proxy" in result.output
    assert "servers" in result.output
    assert "sessions" in result.output


def test_status_with_mocked_integrations(monkeypatch):
    monkeypatch.setattr("textworkspace.cli._HAS_TEXTACCOUNTS", True)
    monkeypatch.setattr("textworkspace.cli._HAS_TEXTSESSIONS", True)
    monkeypatch.setattr("textworkspace.cli.list_profiles", lambda: ["work", "personal"])
    monkeypatch.setattr(
        "textworkspace.cli._proxy_stats_http",
        lambda port=9880: {"tokens": 14200},
    )
    monkeypatch.setattr(
        "textworkspace.cli._ts_list",
        lambda limit=1000: [
            {"id": "1", "title": "a", "state": "active"},
            {"id": "2", "title": "b", "state": "idle"},
        ],
    )
    import os as _os
    monkeypatch.setenv("TW_PROFILE", "work")

    runner = CliRunner()
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0
    assert "work" in result.output
    assert "running" in result.output
    assert "14.2k" in result.output
    assert "2 total" in result.output
