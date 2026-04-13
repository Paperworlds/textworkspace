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
