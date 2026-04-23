"""Tests for the combo loading and execution engine."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from textworkspace.cli import main
from textworkspace.combos import (
    _interpolate,
    _is_account_active,
    _is_proxy_running,
    _are_servers_running,
    evaluate_condition,
    load_combos,
    resolve_options,
    run_combo,
    COMBOS_FILE,
    COMBOS_DIR,
    DEFAULT_COMBOS_YAML,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_combos(tmp_path: Path, data: dict, filename: str = "combos.yaml") -> Path:
    path = tmp_path / filename
    path.write_text(yaml.dump({"combos": data}))
    return path


def _patch_combos(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("textworkspace.combos.COMBOS_FILE", tmp_path / "combos.yaml")
    monkeypatch.setattr("textworkspace.combos.COMBOS_DIR", tmp_path / "combos.d")
    monkeypatch.setattr("textworkspace.cli.COMBOS_FILE", tmp_path / "combos.yaml")


# ---------------------------------------------------------------------------
# Combo loader
# ---------------------------------------------------------------------------

class TestLoadCombos:
    def test_empty_when_no_files(self, tmp_path, monkeypatch):
        _patch_combos(monkeypatch, tmp_path)
        assert load_combos() == {}

    def test_loads_from_combos_yaml(self, tmp_path, monkeypatch):
        _patch_combos(monkeypatch, tmp_path)
        _write_combos(tmp_path, {"foo": {"description": "do foo", "steps": [{"run": "serve"}]}})
        combos = load_combos()
        assert "foo" in combos
        assert combos["foo"]["description"] == "do foo"

    def test_loads_from_combos_d(self, tmp_path, monkeypatch):
        _patch_combos(monkeypatch, tmp_path)
        d = tmp_path / "combos.d"
        d.mkdir()
        _write_combos(d, {"bar": {"description": "do bar", "steps": []}}, filename="extra.yaml")
        combos = load_combos()
        assert "bar" in combos

    def test_user_yaml_overrides_combos_d(self, tmp_path, monkeypatch):
        _patch_combos(monkeypatch, tmp_path)
        d = tmp_path / "combos.d"
        d.mkdir()
        _write_combos(d, {"shared": {"description": "from d", "steps": []}}, filename="a.yaml")
        _write_combos(tmp_path, {"shared": {"description": "from user", "steps": []}})
        combos = load_combos()
        assert combos["shared"]["description"] == "from user"

    def test_collision_within_combos_d_warns(self, tmp_path, monkeypatch, capsys):
        _patch_combos(monkeypatch, tmp_path)
        d = tmp_path / "combos.d"
        d.mkdir()
        _write_combos(d, {"clash": {"description": "first", "steps": []}}, filename="a.yaml")
        _write_combos(d, {"clash": {"description": "second", "steps": []}}, filename="b.yaml")
        load_combos()
        captured = capsys.readouterr()
        assert "warning" in captured.err
        assert "clash" in captured.err

    def test_malformed_combos_key_ignored(self, tmp_path, monkeypatch):
        _patch_combos(monkeypatch, tmp_path)
        path = tmp_path / "combos.yaml"
        path.write_text("combos: [a, b, c]\n")  # list instead of dict
        combos = load_combos()
        assert combos == {}

    def test_multiple_combos_d_files_sorted(self, tmp_path, monkeypatch):
        _patch_combos(monkeypatch, tmp_path)
        d = tmp_path / "combos.d"
        d.mkdir()
        _write_combos(d, {"z": {"steps": []}}, filename="z.yaml")
        _write_combos(d, {"a": {"steps": []}}, filename="a.yaml")
        combos = load_combos()
        assert "a" in combos and "z" in combos


# ---------------------------------------------------------------------------
# Condition evaluator
# ---------------------------------------------------------------------------

class TestConditions:
    def test_proxy_running_true(self, monkeypatch):
        monkeypatch.setattr("textworkspace.combos._is_proxy_running", lambda: True)
        assert evaluate_condition("proxy.running") is True

    def test_proxy_running_false(self, monkeypatch):
        monkeypatch.setattr("textworkspace.combos._is_proxy_running", lambda: False)
        assert evaluate_condition("proxy.running") is False

    def test_proxy_stopped_is_inverse(self, monkeypatch):
        monkeypatch.setattr("textworkspace.combos._is_proxy_running", lambda: False)
        assert evaluate_condition("proxy.stopped") is True

    def test_servers_running_true(self, monkeypatch):
        monkeypatch.setattr("textworkspace.combos._are_servers_running", lambda: True)
        assert evaluate_condition("servers.running") is True

    def test_servers_none_running_is_inverse(self, monkeypatch):
        monkeypatch.setattr("textworkspace.combos._are_servers_running", lambda: True)
        assert evaluate_condition("servers.none_running") is False

    def test_accounts_active_match(self, monkeypatch):
        monkeypatch.setenv("TW_PROFILE", "work")
        assert evaluate_condition("accounts.active work") is True

    def test_accounts_active_no_match(self, monkeypatch):
        monkeypatch.setenv("TW_PROFILE", "personal")
        assert evaluate_condition("accounts.active work") is False

    def test_accounts_active_no_env(self, monkeypatch):
        monkeypatch.delenv("TW_PROFILE", raising=False)
        assert evaluate_condition("accounts.active work") is False

    def test_unknown_condition_returns_false(self, capsys):
        result = evaluate_condition("bogus.condition")
        assert result is False
        assert "unknown condition" in capsys.readouterr().err

    def test_is_proxy_running_connects(self):
        """_is_proxy_running returns False when port not open (no server in test env)."""
        # We just test it doesn't crash; it will return False in the test env
        result = _is_proxy_running()
        assert isinstance(result, bool)

    def test_is_account_active(self, monkeypatch):
        monkeypatch.setenv("TW_PROFILE", "work")
        assert _is_account_active("work") is True
        assert _is_account_active("other") is False

    def test_are_servers_running_no_binary(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _: None)
        assert _are_servers_running() is False


# ---------------------------------------------------------------------------
# Interpolation
# ---------------------------------------------------------------------------

class TestInterpolate:
    def test_replaces_placeholder(self):
        assert _interpolate("switch {profile}", {"profile": "work"}) == "switch work"

    def test_multiple_placeholders(self):
        assert _interpolate("{a} {b}", {"a": "x", "b": "y"}) == "x y"

    def test_no_placeholders(self):
        assert _interpolate("serve list", {}) == "serve list"

    def test_missing_key_left_as_is(self):
        assert _interpolate("{missing}", {}) == "{missing}"


# ---------------------------------------------------------------------------
# Step executor
# ---------------------------------------------------------------------------

class TestRunCombo:
    def _defn(self, steps):
        return {"description": "test", "steps": steps}

    def test_no_steps_returns_zero(self):
        rc = run_combo("empty", self._defn([]), {})
        assert rc == 0

    def test_runs_step(self, monkeypatch):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return MagicMock(returncode=0)

        monkeypatch.setattr("textworkspace.combos.subprocess.run", fake_run)
        rc = run_combo("x", self._defn([{"run": "serve"}]), {})
        assert rc == 0
        assert calls == [["textworkspace", "serve"]]

    def test_stops_on_failure(self, monkeypatch):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return MagicMock(returncode=1)

        monkeypatch.setattr("textworkspace.combos.subprocess.run", fake_run)
        rc = run_combo("x", self._defn([{"run": "serve"}, {"run": "stats"}]), {})
        assert rc != 0
        assert len(calls) == 1  # stopped after first failure

    def test_continue_on_error_runs_all_steps(self, monkeypatch):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return MagicMock(returncode=1)

        monkeypatch.setattr("textworkspace.combos.subprocess.run", fake_run)
        rc = run_combo(
            "x",
            self._defn([{"run": "serve"}, {"run": "stats"}]),
            {},
            continue_on_error=True,
        )
        assert rc != 0
        assert len(calls) == 2

    def test_skip_if_true_skips_step(self, monkeypatch):
        calls = []
        monkeypatch.setattr("textworkspace.combos.evaluate_condition", lambda c, **kw: True)

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return MagicMock(returncode=0)

        monkeypatch.setattr("textworkspace.combos.subprocess.run", fake_run)
        rc = run_combo("x", self._defn([{"run": "serve", "skip_if": "proxy.running"}]), {})
        assert rc == 0
        assert calls == []  # skipped

    def test_only_if_false_skips_step(self, monkeypatch):
        calls = []
        monkeypatch.setattr("textworkspace.combos.evaluate_condition", lambda c, **kw: False)

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return MagicMock(returncode=0)

        monkeypatch.setattr("textworkspace.combos.subprocess.run", fake_run)
        rc = run_combo("x", self._defn([{"run": "serve", "only_if": "proxy.running"}]), {})
        assert rc == 0
        assert calls == []  # skipped

    def test_arg_interpolation(self, monkeypatch):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return MagicMock(returncode=0)

        monkeypatch.setattr("textworkspace.combos.subprocess.run", fake_run)
        rc = run_combo("x", self._defn([{"run": "switch {profile}"}]), {"profile": "work"})
        assert rc == 0
        assert calls == [["textworkspace", "switch", "work"]]


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------

class TestDryRun:
    def _defn(self, steps):
        return {"description": "test", "steps": steps}

    def test_dry_run_prints_without_executing(self, monkeypatch):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return MagicMock(returncode=0)

        monkeypatch.setattr("textworkspace.combos.subprocess.run", fake_run)
        run_combo("x", self._defn([{"run": "serve"}, {"run": "stats"}]), {}, dry_run=True)
        assert calls == []  # nothing executed

    def test_dry_run_shows_run_label(self, monkeypatch, capsys):
        monkeypatch.setattr("textworkspace.combos.subprocess.run", lambda *a, **k: MagicMock(returncode=0))
        run_combo("x", self._defn([{"run": "serve"}]), {}, dry_run=True)
        out = capsys.readouterr().out
        assert "[RUN]" in out
        assert "serve" in out

    def test_dry_run_shows_skip_label(self, monkeypatch, capsys):
        monkeypatch.setattr("textworkspace.combos.evaluate_condition", lambda c, **kw: True)
        monkeypatch.setattr("textworkspace.combos.subprocess.run", lambda *a, **k: MagicMock(returncode=0))
        run_combo("x", self._defn([{"run": "serve", "skip_if": "proxy.running"}]), {}, dry_run=True)
        out = capsys.readouterr().out
        assert "[SKIP]" in out

    def test_dry_run_via_cli(self, tmp_path, monkeypatch):
        """tw --dry-run <combo> prints steps without executing."""
        _patch_combos(monkeypatch, tmp_path)
        _write_combos(tmp_path, {
            "mycombo": {
                "description": "test combo",
                "steps": [{"run": "serve"}, {"run": "stats"}],
            }
        })
        # Prevent real process execution
        monkeypatch.setattr("textworkspace.combos.subprocess.run", lambda *a, **k: MagicMock(returncode=0))

        runner = CliRunner()
        result = runner.invoke(main, ["--dry-run", "mycombo"])
        assert result.exit_code == 0
        assert "[dry-run]" in result.output
        assert "serve" in result.output
        assert "stats" in result.output


# ---------------------------------------------------------------------------
# tw combos list / init
# ---------------------------------------------------------------------------

class TestCombosListCommand:
    def test_combos_list_no_combos(self, tmp_path, monkeypatch):
        _patch_combos(monkeypatch, tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, ["combos", "list"])
        assert result.exit_code == 0
        assert "No combos" in result.output

    def test_combos_list_shows_combos(self, tmp_path, monkeypatch):
        _patch_combos(monkeypatch, tmp_path)
        _write_combos(tmp_path, {
            "foo": {"description": "do foo", "steps": []},
            "bar": {"description": "do bar", "steps": []},
        })
        runner = CliRunner()
        result = runner.invoke(main, ["combos", "list"])
        assert result.exit_code == 0
        assert "foo" in result.output
        assert "do foo" in result.output
        assert "bar" in result.output

    def test_combos_list_shows_builtin_tag(self, tmp_path, monkeypatch):
        _patch_combos(monkeypatch, tmp_path)
        _write_combos(tmp_path, {
            "up": {"description": "start stack", "builtin": True, "steps": []},
        })
        runner = CliRunner()
        result = runner.invoke(main, ["combos", "list"])
        assert "[builtin]" in result.output


class TestInitCreatesComboYaml:
    def test_init_creates_combos_yaml(self, tmp_path, monkeypatch):
        import textworkspace.doctor as _doc
        from textworkspace.doctor import ToolInfo

        monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
        monkeypatch.setattr("textworkspace.config.CONFIG_FILE", tmp_path / "config.yaml")
        monkeypatch.setattr("textworkspace.cli.CONFIG_DIR", tmp_path)
        monkeypatch.setattr("textworkspace.cli.CONFIG_FILE", tmp_path / "config.yaml")
        monkeypatch.setattr("textworkspace.cli.COMBOS_FILE", tmp_path / "combos.yaml")
        monkeypatch.setattr("textworkspace.combos.COMBOS_FILE", tmp_path / "combos.yaml")
        # No tools installed; decline Go binary downloads
        monkeypatch.setattr(_doc, "detect_installed_tools", lambda: {
            n: ToolInfo(name=n) for n in ("textaccounts", "textsessions", "textproxy", "textserve")
        })

        runner = CliRunner()
        result = runner.invoke(main, ["init"], input="n\nn\nn\n")
        assert result.exit_code == 0
        combos_path = tmp_path / "combos.yaml"
        assert combos_path.exists()
        data = yaml.safe_load(combos_path.read_text())
        assert "combos" in data
        assert "reset" in data["combos"]
        assert "go" in data["combos"]
        # up/down were promoted to top-level `tw up`/`tw down` (see cli.py)
        assert "up" not in data["combos"]
        assert "down" not in data["combos"]

    def test_init_does_not_overwrite_existing_combos(self, tmp_path, monkeypatch):
        monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
        monkeypatch.setattr("textworkspace.config.CONFIG_FILE", tmp_path / "config.yaml")
        monkeypatch.setattr("textworkspace.cli.CONFIG_DIR", tmp_path)
        monkeypatch.setattr("textworkspace.cli.CONFIG_FILE", tmp_path / "config.yaml")
        monkeypatch.setattr("textworkspace.cli.COMBOS_FILE", tmp_path / "combos.yaml")

        existing = tmp_path / "combos.yaml"
        existing.write_text("# my custom combos\ncombos: {}\n")
        original_content = existing.read_text()

        runner = CliRunner()
        runner.invoke(main, ["init"])
        assert existing.read_text() == original_content


# ---------------------------------------------------------------------------
# Dynamic combo dispatch
# ---------------------------------------------------------------------------

class TestDynamicComboDispatch:
    def test_combo_runs_via_tw_command(self, tmp_path, monkeypatch):
        _patch_combos(monkeypatch, tmp_path)
        _write_combos(tmp_path, {
            "hello": {"description": "say hi", "steps": [{"run": "serve"}]},
        })
        calls = []
        monkeypatch.setattr("textworkspace.combos.subprocess.run", lambda cmd, **k: (calls.append(cmd), MagicMock(returncode=0))[1])

        runner = CliRunner()
        result = runner.invoke(main, ["hello"])
        assert result.exit_code == 0
        assert ["textworkspace", "serve"] in calls

    def test_unknown_command_shows_error(self, tmp_path, monkeypatch):
        _patch_combos(monkeypatch, tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, ["nonexistent_combo_xyz"])
        assert result.exit_code != 0

    def test_combo_appears_in_help(self, tmp_path, monkeypatch):
        _patch_combos(monkeypatch, tmp_path)
        _write_combos(tmp_path, {
            "myworkflow": {"description": "my workflow", "steps": []},
        })
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert "myworkflow" in result.output


# ---------------------------------------------------------------------------
# shell: steps (external commands)
# ---------------------------------------------------------------------------

class TestShellSteps:
    def _defn(self, steps):
        return {"description": "test", "steps": steps}

    def test_shell_step_runs_directly(self, monkeypatch):
        """shell: steps should not prepend 'textworkspace'."""
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return MagicMock(returncode=0)

        monkeypatch.setattr("textworkspace.combos.subprocess.run", fake_run)
        rc = run_combo("x", self._defn([{"shell": "textsessions new -r myrepo"}]), {})
        assert rc == 0
        assert calls == [["textsessions", "new", "-r", "myrepo"]]

    def test_run_step_prepends_textworkspace(self, monkeypatch):
        """run: steps should still prepend 'textworkspace'."""
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return MagicMock(returncode=0)

        monkeypatch.setattr("textworkspace.combos.subprocess.run", fake_run)
        rc = run_combo("x", self._defn([{"run": "switch work"}]), {})
        assert rc == 0
        assert calls == [["textworkspace", "switch", "work"]]

    def test_mixed_run_and_shell_steps(self, monkeypatch):
        """Combo with both run: and shell: steps."""
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return MagicMock(returncode=0)

        monkeypatch.setattr("textworkspace.combos.subprocess.run", fake_run)
        steps = [
            {"run": "switch work"},
            {"shell": "textsessions new -r repo"},
        ]
        rc = run_combo("x", self._defn(steps), {})
        assert rc == 0
        assert calls[0][0] == "textworkspace"  # run: step
        assert calls[1][0] == "textsessions"   # shell: step


# ---------------------------------------------------------------------------
# Options resolution and conditions
# ---------------------------------------------------------------------------

class TestOptions:
    def test_options_defaults_from_defn(self):
        defn = {"options": {"servers": True, "tmux": False}}
        opts = resolve_options("test", defn)
        assert opts == {"servers": True, "tmux": False}

    def test_options_config_override(self, tmp_path, monkeypatch):
        """Config-level combos.<name>.<key> overrides combo defaults."""
        from textworkspace.config import Config, save_config

        config_dir = tmp_path / ".config" / "paperworlds"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr("textworkspace.config.CONFIG_DIR", config_dir)
        monkeypatch.setattr("textworkspace.config.CONFIG_FILE", config_dir / "config.yaml")

        # Save config with combo override
        cfg = Config()
        cfg.defaults["combos"] = {"go": {"tmux": True}}
        save_config(cfg)

        defn = {"options": {"servers": True, "tmux": False}}
        opts = resolve_options("go", defn)
        assert opts["tmux"] is True  # overridden by config
        assert opts["servers"] is True  # kept default

    def test_options_cli_override_wins(self, monkeypatch):
        """CLI flags override both defaults and config."""
        defn = {"options": {"servers": True, "tmux": False}}
        opts = resolve_options("go", defn, cli_overrides={"servers": False})
        assert opts["servers"] is False

    def test_evaluate_options_condition_true(self):
        assert evaluate_condition("options.servers", options={"servers": True}) is True

    def test_evaluate_options_condition_false(self):
        assert evaluate_condition("options.tmux", options={"tmux": False}) is False

    def test_evaluate_options_string_false(self):
        assert evaluate_condition("options.name", options={"name": ""}) is False

    def test_evaluate_options_string_true(self):
        assert evaluate_condition("options.name", options={"name": "mysession"}) is True

    def test_evaluate_options_missing_key(self):
        assert evaluate_condition("options.missing", options={}) is False

    def test_options_skip_step_via_only_if(self, monkeypatch):
        """Steps with only_if: options.X should be skipped when option is false."""
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return MagicMock(returncode=0)

        monkeypatch.setattr("textworkspace.combos.subprocess.run", fake_run)
        defn = {
            "description": "test",
            "options": {"tmux": False},
            "steps": [
                {"run": "switch work"},
                {"shell": "tmux new-window", "only_if": "options.tmux"},
            ],
        }
        rc = run_combo("x", defn, {}, options={"tmux": False})
        assert rc == 0
        assert len(calls) == 1  # only the switch step ran
        assert calls[0][0] == "textworkspace"

    def test_options_interpolated_in_commands(self, monkeypatch):
        """Option values should be available for {interpolation} in step commands."""
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return MagicMock(returncode=0)

        monkeypatch.setattr("textworkspace.combos.subprocess.run", fake_run)
        defn = {
            "description": "test",
            "options": {"name": "mysession"},
            "steps": [{"shell": "textsessions new -n {name}"}],
        }
        rc = run_combo("x", defn, {}, options={"name": "mysession"})
        assert rc == 0
        assert calls == [["textsessions", "new", "-n", "mysession"]]


# ---------------------------------------------------------------------------
# Default combos include "go"
# ---------------------------------------------------------------------------

class TestDefaultCombos:
    def test_go_combo_in_defaults(self):
        """The 'go' combo should be defined in DEFAULT_COMBOS_YAML."""
        data = yaml.safe_load(DEFAULT_COMBOS_YAML)
        assert "go" in data["combos"]
        go = data["combos"]["go"]
        assert "profile" in go["args"]
        assert "repo" in go["args"]
        assert "options" in go
        # Should have both run: and shell: steps
        step_types = set()
        for step in go["steps"]:
            if "shell" in step:
                step_types.add("shell")
            if "run" in step:
                step_types.add("run")
        assert step_types == {"run", "shell"}
