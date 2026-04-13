"""Tests for the textworkspace CLI entry point."""

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from textworkspace.cli import main
from textworkspace.combos import (
    COMBOS_DIR,
    export_combo,
    fetch_community_info,
    install_combo,
    search_community,
    update_combo,
    _source_to_url,
)
from textworkspace.config import Config, ToolEntry, config_as_yaml, load_config, save_config


# ---------------------------------------------------------------------------
# CLI smoke tests
# ---------------------------------------------------------------------------

def test_version():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.1" in result.output


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
        "textworkspace.cli.load_sessions",
        lambda: [
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
    monkeypatch.setattr("textworkspace.cli.load_sessions", lambda: [])

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
        "textworkspace.cli.load_sessions",
        lambda: [
            {"id": "1", "title": "a", "state": "active"},
            {"id": "2", "title": "b", "state": "idle"},
        ],
    )
    monkeypatch.setenv("TW_PROFILE", "work")

    runner = CliRunner()
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0
    assert "work" in result.output
    assert "2 total" in result.output


# ---------------------------------------------------------------------------
# Combo sharing — unit tests for combos module
# ---------------------------------------------------------------------------

_STANDALONE_YAML = """\
name: my-stack
author: paulie
description: My test stack
tags: [test, data]
requires:
  - textserve
steps:
  - run: proxy start
    skip_if: proxy.running
  - run: servers start --tag test
"""


def test_source_to_url_gh():
    url = _source_to_url("gh:acme/combos/my-stack")
    assert url == "https://raw.githubusercontent.com/acme/combos/main/my-stack.yaml"


def test_source_to_url_gh_with_yaml_extension():
    url = _source_to_url("gh:acme/combos/my-stack.yaml")
    assert url == "https://raw.githubusercontent.com/acme/combos/main/my-stack.yaml"


def test_source_to_url_gh_missing_name():
    with pytest.raises(ValueError, match="gh:"):
        _source_to_url("gh:acme/combos")


def test_install_combo_local(tmp_path, monkeypatch):
    monkeypatch.setattr("textworkspace.combos.COMBOS_DIR", tmp_path / "combos.d")
    monkeypatch.setattr("textworkspace.combos.CONFIG_DIR", tmp_path)

    name = install_combo("/tmp/fake.yaml", _STANDALONE_YAML)
    assert name == "my-stack"

    dest = tmp_path / "combos.d" / "my-stack.yaml"
    assert dest.exists()

    data = yaml.safe_load(dest.read_text())
    assert data["_source"] == "/tmp/fake.yaml"
    assert data["_modified"] is False
    assert "_installed" in data
    assert "combos" in data
    assert "my-stack" in data["combos"]
    defn = data["combos"]["my-stack"]
    assert len(defn["steps"]) == 2


def test_install_combo_missing_name(tmp_path, monkeypatch):
    monkeypatch.setattr("textworkspace.combos.COMBOS_DIR", tmp_path / "combos.d")
    with pytest.raises(ValueError, match="name"):
        install_combo("source", "steps:\n  - run: foo\n")


def test_install_combo_missing_steps(tmp_path, monkeypatch):
    monkeypatch.setattr("textworkspace.combos.COMBOS_DIR", tmp_path / "combos.d")
    with pytest.raises(ValueError, match="steps"):
        install_combo("source", "name: foo\n")


def test_install_combo_warns_missing_requires(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("textworkspace.combos.COMBOS_DIR", tmp_path / "combos.d")
    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", cfg_file)

    # No tools configured → textserve will be missing
    install_combo("/tmp/fake.yaml", _STANDALONE_YAML)
    # warning goes to click's err stream; check it didn't raise


def test_export_combo(tmp_path, monkeypatch):
    monkeypatch.setattr("textworkspace.combos.COMBOS_DIR", tmp_path / "combos.d")
    install_combo("/tmp/fake.yaml", _STANDALONE_YAML)

    out = export_combo("my-stack")
    parsed = yaml.safe_load(out)
    assert parsed["name"] == "my-stack"
    assert "steps" in parsed
    assert "_source" not in parsed
    assert "_modified" not in parsed
    assert "_installed" not in parsed


def test_export_combo_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr("textworkspace.combos.COMBOS_DIR", tmp_path / "combos.d")
    (tmp_path / "combos.d").mkdir()
    with pytest.raises(FileNotFoundError):
        export_combo("nonexistent")


def test_update_combo_skips_modified(tmp_path, monkeypatch):
    monkeypatch.setattr("textworkspace.combos.COMBOS_DIR", tmp_path / "combos.d")
    install_combo("/tmp/fake.yaml", _STANDALONE_YAML)

    file_data = {"_source": "/tmp/fake.yaml", "_modified": True}
    result = update_combo("my-stack", file_data)
    assert result == "skipped"


def test_update_combo_local_source(tmp_path, monkeypatch):
    monkeypatch.setattr("textworkspace.combos.COMBOS_DIR", tmp_path / "combos.d")
    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", tmp_path / "config.yaml")

    src = tmp_path / "source.yaml"
    src.write_text(_STANDALONE_YAML)
    install_combo(str(src), _STANDALONE_YAML)

    file_data = {"_source": str(src), "_modified": False}
    result = update_combo("my-stack", file_data)
    assert result == "updated"


def test_update_combo_no_source():
    result = update_combo("foo", {"_modified": False})
    assert result.startswith("error:")


def test_search_community_mocked(monkeypatch, tmp_path):
    import json

    gh_listing = [
        {
            "name": "data-eng.yaml",
            "download_url": "https://raw.githubusercontent.com/paperworlds/textcombos/main/data-eng.yaml",
        }
    ]
    combo_yaml = (
        "name: data-eng\ndescription: Data engineering stack\ntags: [data, airflow]\nsteps:\n  - run: foo\n"
    )

    class _FakeResp:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self._body

        @property
        def text(self):
            return self._body if isinstance(self._body, str) else json.dumps(self._body)

    call_count = {"n": 0}

    def _fake_get(url, **kwargs):
        call_count["n"] += 1
        if "contents" in url:
            return _FakeResp(gh_listing)
        return _FakeResp(combo_yaml)

    import httpx

    monkeypatch.setattr(httpx, "get", _fake_get)

    results = search_community("data")
    assert len(results) == 1
    assert results[0]["name"] == "data-eng"
    assert "airflow" in results[0]["tags"]


def test_search_community_no_match(monkeypatch):
    import json

    gh_listing = [
        {
            "name": "other.yaml",
            "download_url": "https://raw.githubusercontent.com/paperworlds/textcombos/main/other.yaml",
        }
    ]
    combo_yaml = "name: other\ndescription: Something else\ntags: [misc]\nsteps:\n  - run: bar\n"

    class _FakeResp:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self._body

        @property
        def text(self):
            return self._body if isinstance(self._body, str) else json.dumps(self._body)

    import httpx

    monkeypatch.setattr(httpx, "get", lambda url, **kw: _FakeResp(gh_listing if "contents" in url else combo_yaml))

    results = search_community("data")
    assert results == []


def test_fetch_community_info_mocked(monkeypatch):
    combo_yaml = (
        "name: my-stack\nauthor: paulie\ndescription: A stack\ntags: [test]\nsteps:\n  - run: foo\n"
    )

    class _FakeResp:
        def raise_for_status(self):
            pass

        @property
        def text(self):
            return combo_yaml

    import httpx

    monkeypatch.setattr(httpx, "get", lambda url, **kw: _FakeResp())

    data = fetch_community_info("my-stack")
    assert data["name"] == "my-stack"
    assert data["author"] == "paulie"


# ---------------------------------------------------------------------------
# tw combos install / export / update / search — CLI integration
# ---------------------------------------------------------------------------


def test_cli_combos_install_local(tmp_path, monkeypatch):
    monkeypatch.setattr("textworkspace.combos.COMBOS_DIR", tmp_path / "combos.d")
    monkeypatch.setattr("textworkspace.cli.COMBOS_DIR", tmp_path / "combos.d")
    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", tmp_path / "config.yaml")

    src = tmp_path / "my-stack.yaml"
    src.write_text(_STANDALONE_YAML)

    runner = CliRunner()
    result = runner.invoke(main, ["combos", "install", str(src)])
    assert result.exit_code == 0
    assert "installed 'my-stack'" in result.output
    assert (tmp_path / "combos.d" / "my-stack.yaml").exists()


def test_cli_combos_install_missing_file(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["combos", "install", str(tmp_path / "missing.yaml")])
    assert result.exit_code != 0


def test_cli_combos_export(tmp_path, monkeypatch):
    monkeypatch.setattr("textworkspace.combos.COMBOS_DIR", tmp_path / "combos.d")
    monkeypatch.setattr("textworkspace.cli.COMBOS_DIR", tmp_path / "combos.d")
    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", tmp_path / "config.yaml")

    install_combo("/tmp/fake.yaml", _STANDALONE_YAML)

    runner = CliRunner()
    result = runner.invoke(main, ["combos", "export", "my-stack"])
    assert result.exit_code == 0
    parsed = yaml.safe_load(result.output)
    assert parsed["name"] == "my-stack"


def test_cli_combos_export_all(tmp_path, monkeypatch):
    monkeypatch.setattr("textworkspace.combos.COMBOS_DIR", tmp_path / "combos.d")
    monkeypatch.setattr("textworkspace.cli.COMBOS_DIR", tmp_path / "combos.d")
    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", tmp_path / "config.yaml")

    install_combo("/tmp/fake.yaml", _STANDALONE_YAML)

    runner = CliRunner()
    result = runner.invoke(main, ["combos", "export", "--all"])
    assert result.exit_code == 0
    assert "my-stack" in result.output


def test_cli_combos_remove(tmp_path, monkeypatch):
    monkeypatch.setattr("textworkspace.combos.COMBOS_DIR", tmp_path / "combos.d")
    monkeypatch.setattr("textworkspace.cli.COMBOS_DIR", tmp_path / "combos.d")
    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", tmp_path / "config.yaml")

    install_combo("/tmp/fake.yaml", _STANDALONE_YAML)
    assert (tmp_path / "combos.d" / "my-stack.yaml").exists()

    runner = CliRunner()
    result = runner.invoke(main, ["combos", "remove", "my-stack"])
    assert result.exit_code == 0
    assert not (tmp_path / "combos.d" / "my-stack.yaml").exists()


def test_cli_combos_search_mocked(monkeypatch):
    monkeypatch.setattr(
        "textworkspace.cli.search_community",
        lambda q: [{"name": "data-eng", "description": "Data stack", "tags": ["data"], "author": "paulie", "requires": []}],
    )
    runner = CliRunner()
    result = runner.invoke(main, ["combos", "search", "data"])
    assert result.exit_code == 0
    assert "data-eng" in result.output


def test_cli_combos_info_mocked(monkeypatch):
    monkeypatch.setattr(
        "textworkspace.cli.fetch_community_info",
        lambda n: {
            "name": n,
            "author": "paulie",
            "description": "A stack",
            "tags": ["test"],
            "requires": ["textserve"],
            "steps": [{"run": "proxy start"}],
        },
    )
    runner = CliRunner()
    result = runner.invoke(main, ["combos", "info", "my-stack"])
    assert result.exit_code == 0
    assert "my-stack" in result.output
    assert "paulie" in result.output
    assert "textserve" in result.output


# ---------------------------------------------------------------------------
# doctor.py — detect_installed_tools
# ---------------------------------------------------------------------------

from textworkspace.doctor import (
    CheckResult,
    ToolInfo,
    _detect_python_tool,
    detect_installed_tools,
    run_doctor_checks,
    _is_port_responding,
)


def test_detect_python_tool_found(monkeypatch):
    """detect_python_tool returns installed=True when module is importable."""
    import importlib.util as _ilu
    import shutil as _sh

    fake_spec = object()  # truthy non-None
    monkeypatch.setattr(_ilu, "find_spec", lambda name: fake_spec)
    monkeypatch.setattr("importlib.metadata.version", lambda name: "1.2.3")
    # No binary on PATH — falls back to importlib.metadata for version
    monkeypatch.setattr(_sh, "which", lambda name: None)

    info = _detect_python_tool("textaccounts")
    assert info.installed is True
    assert info.importable is True
    assert info.version == "1.2.3"
    assert info.source == "pypi"


def test_detect_python_tool_prefers_binary_version(monkeypatch, tmp_path):
    """detect_python_tool prefers --version output over importlib.metadata."""
    import importlib.util as _ilu
    import shutil as _sh

    fake_spec = object()
    monkeypatch.setattr(_ilu, "find_spec", lambda name: fake_spec)
    monkeypatch.setattr("importlib.metadata.version", lambda name: "0.5.4")

    fake_bin = tmp_path / "textsessions"
    fake_bin.write_text("#!/bin/sh\necho 'textsessions, version 0.6.0'\n")
    fake_bin.chmod(0o755)
    monkeypatch.setattr(_sh, "which", lambda name: str(fake_bin))

    info = _detect_python_tool("textsessions")
    assert info.installed is True
    assert info.version == "0.6.0"  # binary wins over metadata


def test_detect_python_tool_missing(monkeypatch):
    """detect_python_tool returns installed=False when module is not found."""
    import importlib.util as _ilu

    monkeypatch.setattr(_ilu, "find_spec", lambda name: None)
    import shutil as _sh
    monkeypatch.setattr(_sh, "which", lambda name: None)

    info = _detect_python_tool("textaccounts")
    assert info.installed is False
    assert info.importable is False


def test_detect_python_tool_in_path_but_not_importable(monkeypatch, tmp_path):
    """detect_python_tool marks installed=True if binary is on PATH even if not importable."""
    import importlib.util as _ilu
    import shutil as _sh

    monkeypatch.setattr(_ilu, "find_spec", lambda name: None)
    fake_bin = tmp_path / "textaccounts"
    fake_bin.touch()
    monkeypatch.setattr(_sh, "which", lambda name: str(fake_bin))

    info = _detect_python_tool("textaccounts")
    assert info.installed is True
    assert info.importable is False
    assert info.source == "path"


def test_detect_go_tool_in_bin_dir(tmp_path, monkeypatch):
    """detect_installed_tools finds a Go binary in the managed BIN_DIR."""
    import shutil as _sh
    import textworkspace.doctor as _doc

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_binary = bin_dir / "textproxy"
    fake_binary.touch()

    # Patch BIN_DIR in bootstrap and doctor, block PATH lookup
    monkeypatch.setattr("textworkspace.bootstrap.BIN_DIR", bin_dir)
    monkeypatch.setattr(_sh, "which", lambda name: None)
    # Prevent config load from touching real fs
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)

    tools = detect_installed_tools()
    assert tools["textproxy"].installed is True
    assert tools["textproxy"].source == "github"
    assert tools["textproxy"].bin_path == str(fake_binary)


def test_detect_go_tool_not_found(tmp_path, monkeypatch):
    """detect_installed_tools returns installed=False when binary absent."""
    import shutil as _sh

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    monkeypatch.setattr("textworkspace.bootstrap.BIN_DIR", bin_dir)
    monkeypatch.setattr(_sh, "which", lambda name: None)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)

    tools = detect_installed_tools()
    assert tools["textproxy"].installed is False
    assert tools["textserve"].installed is False


def test_is_port_responding_false():
    """_is_port_responding returns False for a port nothing listens on."""
    assert _is_port_responding(19999, timeout=0.1) is False


# ---------------------------------------------------------------------------
# doctor.py — run_doctor_checks
# ---------------------------------------------------------------------------


def _make_mock_tools(*, textaccounts=True, textsessions=True, textproxy=True, textserve=False):
    tools = {}
    for name, installed in [
        ("textaccounts", textaccounts),
        ("textsessions", textsessions),
        ("textproxy", textproxy),
        ("textserve", textserve),
    ]:
        tools[name] = ToolInfo(
            name=name,
            installed=installed,
            version="0.1.0" if installed else None,
            source="pypi" if name in ("textaccounts", "textsessions") else "github",
        )
    return tools


def test_doctor_checks_all_tools_ok(tmp_path, monkeypatch):
    """run_doctor_checks marks all tools ok when installed."""
    import textworkspace.doctor as _doc

    monkeypatch.setattr(_doc, "detect_installed_tools", lambda: _make_mock_tools())
    monkeypatch.setattr(_doc, "_is_port_responding", lambda port, **kw: True)
    monkeypatch.setattr(_doc, "_FISH_FUNCTIONS_DIR", tmp_path)

    # Fish function files present
    for fn in ["tw", "xtw", "ta", "xta"]:
        (tmp_path / f"{fn}.fish").touch()

    # Config
    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", cfg_file)
    monkeypatch.setattr("textworkspace.combos.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.combos.COMBOS_FILE", tmp_path / "combos.yaml")
    monkeypatch.setattr("textworkspace.combos.COMBOS_DIR", tmp_path / "combos.d")

    # Registry
    registry = tmp_path / "registry.yaml"
    registry.touch()
    monkeypatch.setattr(
        Path, "home", staticmethod(lambda: tmp_path),
    )

    results = run_doctor_checks()

    tool_results = {r.label: r for r in results}
    assert tool_results["textaccounts"].status == "ok"
    assert tool_results["textsessions"].status == "ok"
    assert tool_results["textproxy"].status == "ok"


def test_doctor_checks_missing_required_tool(tmp_path, monkeypatch):
    """run_doctor_checks marks textaccounts as fail when not installed."""
    import textworkspace.doctor as _doc

    missing_tools = _make_mock_tools(textaccounts=False, textproxy=False, textserve=False)
    monkeypatch.setattr(_doc, "detect_installed_tools", lambda: missing_tools)
    monkeypatch.setattr(_doc, "_is_port_responding", lambda port, **kw: False)
    monkeypatch.setattr(_doc, "_FISH_FUNCTIONS_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr("textworkspace.combos.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.combos.COMBOS_FILE", tmp_path / "combos.yaml")
    monkeypatch.setattr("textworkspace.combos.COMBOS_DIR", tmp_path / "combos.d")

    results = run_doctor_checks()
    tool_results = {r.label: r for r in results}

    assert tool_results["textaccounts"].status == "fail"
    assert tool_results["textproxy"].status == "warn"  # optional tool
    assert tool_results["textserve"].status == "warn"  # optional tool


def test_doctor_checks_missing_config(tmp_path, monkeypatch):
    """run_doctor_checks warns when config.yaml is absent."""
    import textworkspace.doctor as _doc

    monkeypatch.setattr(_doc, "detect_installed_tools", lambda: _make_mock_tools())
    monkeypatch.setattr(_doc, "_is_port_responding", lambda port, **kw: False)
    monkeypatch.setattr(_doc, "_FISH_FUNCTIONS_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", tmp_path / "nonexistent.yaml")
    monkeypatch.setattr("textworkspace.combos.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.combos.COMBOS_FILE", tmp_path / "combos.yaml")
    monkeypatch.setattr("textworkspace.combos.COMBOS_DIR", tmp_path / "combos.d")

    results = run_doctor_checks()
    tool_results = {r.label: r for r in results}
    assert tool_results["config"].status == "warn"
    assert "tw init" in (tool_results["config"].fix or "")


def test_doctor_checks_fish_present(tmp_path, monkeypatch):
    """run_doctor_checks shows ok when tw.fish is installed."""
    import textworkspace.doctor as _doc

    monkeypatch.setattr(_doc, "detect_installed_tools", lambda: _make_mock_tools())
    monkeypatch.setattr(_doc, "_is_port_responding", lambda port, **kw: False)
    monkeypatch.setattr(_doc, "_FISH_FUNCTIONS_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr("textworkspace.combos.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.combos.COMBOS_FILE", tmp_path / "combos.yaml")
    monkeypatch.setattr("textworkspace.combos.COMBOS_DIR", tmp_path / "combos.d")

    (tmp_path / "tw.fish").touch()

    results = run_doctor_checks()
    fish_result = next(r for r in results if r.label == "fish")
    assert fish_result.status == "ok"
    assert "tw" in fish_result.detail


def test_doctor_proxy_responding(tmp_path, monkeypatch):
    """run_doctor_checks shows proxy ok when port is responding."""
    import textworkspace.doctor as _doc

    monkeypatch.setattr(_doc, "detect_installed_tools", lambda: _make_mock_tools())
    monkeypatch.setattr(_doc, "_is_port_responding", lambda port, **kw: True)
    monkeypatch.setattr(_doc, "_FISH_FUNCTIONS_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr("textworkspace.combos.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.combos.COMBOS_FILE", tmp_path / "combos.yaml")
    monkeypatch.setattr("textworkspace.combos.COMBOS_DIR", tmp_path / "combos.d")

    results = run_doctor_checks()
    proxy = next(r for r in results if r.label == "proxy")
    assert proxy.status == "ok"
    assert "responding" in proxy.detail


# ---------------------------------------------------------------------------
# tw init — CLI integration
# ---------------------------------------------------------------------------


def test_init_creates_config_and_combos(tmp_path, monkeypatch):
    """tw init creates config.yaml and combos.yaml when both are absent."""
    import textworkspace.doctor as _doc

    cfg_file = tmp_path / "config.yaml"
    combos_file = tmp_path / "combos.yaml"

    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", cfg_file)
    monkeypatch.setattr("textworkspace.combos.COMBOS_FILE", combos_file)
    monkeypatch.setattr("textworkspace.cli.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.cli.CONFIG_FILE", cfg_file)
    monkeypatch.setattr("textworkspace.cli.COMBOS_FILE", combos_file)

    # No tools installed, decline all downloads
    monkeypatch.setattr(_doc, "detect_installed_tools", lambda: _make_mock_tools(
        textaccounts=False, textsessions=False, textproxy=False, textserve=False,
    ))

    runner = CliRunner()
    result = runner.invoke(main, ["init"], input="n\nn\nn\n")
    assert result.exit_code == 0
    assert cfg_file.exists()
    assert combos_file.exists()
    assert "Done" in result.output


def test_init_registers_detected_python_tools(tmp_path, monkeypatch):
    """tw init writes detected Python tools to config."""
    import textworkspace.doctor as _doc

    cfg_file = tmp_path / "config.yaml"
    combos_file = tmp_path / "combos.yaml"

    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", cfg_file)
    monkeypatch.setattr("textworkspace.combos.COMBOS_FILE", combos_file)
    monkeypatch.setattr("textworkspace.cli.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.cli.CONFIG_FILE", cfg_file)
    monkeypatch.setattr("textworkspace.cli.COMBOS_FILE", combos_file)

    detected = _make_mock_tools(textproxy=False, textserve=False)
    detected["textaccounts"].version = "0.3.1"
    detected["textsessions"].version = "0.5.0"
    monkeypatch.setattr(_doc, "detect_installed_tools", lambda: detected)

    runner = CliRunner()
    result = runner.invoke(main, ["init"], input="n\nn\nn\n")
    assert result.exit_code == 0

    cfg = load_config()
    assert "textaccounts" in cfg.tools
    assert cfg.tools["textaccounts"].version == "0.3.1"
    assert "textsessions" in cfg.tools
    assert cfg.tools["textsessions"].version == "0.5.0"


def test_init_combos_file_already_exists(tmp_path, monkeypatch):
    """tw init doesn't overwrite existing combos.yaml."""
    import textworkspace.doctor as _doc

    cfg_file = tmp_path / "config.yaml"
    combos_file = tmp_path / "combos.yaml"
    combos_file.write_text("# existing\n")

    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", cfg_file)
    monkeypatch.setattr("textworkspace.combos.COMBOS_FILE", combos_file)
    monkeypatch.setattr("textworkspace.cli.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.cli.CONFIG_FILE", cfg_file)
    monkeypatch.setattr("textworkspace.cli.COMBOS_FILE", combos_file)

    monkeypatch.setattr(_doc, "detect_installed_tools", lambda: _make_mock_tools(
        textaccounts=False, textsessions=False, textproxy=False, textserve=False,
    ))

    runner = CliRunner()
    result = runner.invoke(main, ["init"], input="n\nn\nn\n")
    assert result.exit_code == 0
    assert combos_file.read_text() == "# existing\n"
    assert "exists" in result.output


def test_doctor_cli_output_format(tmp_path, monkeypatch):
    """tw doctor prints aligned columns with status labels."""
    import textworkspace.doctor as _doc

    monkeypatch.setattr(_doc, "run_doctor_checks", lambda: [
        CheckResult(label="textaccounts", detail="0.3.1 via pypi", status="ok"),
        CheckResult(label="textproxy", detail="not installed", status="warn", fix="tw update textproxy"),
    ])

    runner = CliRunner()
    result = runner.invoke(main, ["doctor"])
    assert result.exit_code == 0
    assert "textaccounts" in result.output
    assert "0.3.1 via pypi" in result.output
    assert "ok" in result.output
    assert "warn" in result.output
    assert "tw update textproxy" in result.output
