"""Tests for workspace profiles — WorkspaceConfig validation and WorkspaceManager."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
import yaml

from textworkspace.config import Config, ServersConfig, WorkspaceConfig, _parse_workspace
from textworkspace.workspace import WorkspaceManager, _read_state, _write_state


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_cfg(**ws_kwargs) -> Config:
    defaults = dict(
        name="data",
        profile="work",
        servers=ServersConfig(tags=["data"]),
        description="Data work",
        project="",
        default_session_name="data",
    )
    defaults.update(ws_kwargs)
    ws = WorkspaceConfig(**defaults)
    cfg = Config()
    cfg.workspaces = {ws.name: ws}
    return cfg


@pytest.fixture
def cfg():
    return _make_cfg()


@pytest.fixture
def state_file(tmp_path):
    return tmp_path / "state.yaml"


# ---------------------------------------------------------------------------
# T01: Config validation (R03, R04)
# ---------------------------------------------------------------------------


def test_parse_workspace_tags_and_names_raises():
    with pytest.raises(ValueError, match="mutually exclusive"):
        _parse_workspace("ws", {"profile": "x", "servers": {"tags": ["a"], "names": ["b"]}})


def test_parse_workspace_empty_profile_raises():
    with pytest.raises(ValueError, match="profile is required"):
        _parse_workspace("ws", {"profile": ""})


def test_parse_workspace_missing_profile_raises():
    with pytest.raises(ValueError, match="profile is required"):
        _parse_workspace("ws", {})


def test_parse_workspace_valid_tags():
    ws = _parse_workspace("ws", {"profile": "work", "servers": {"tags": ["data", "bi"]}})
    assert ws.servers.tags == ["data", "bi"]
    assert ws.servers.names == []


def test_parse_workspace_valid_names():
    ws = _parse_workspace("ws", {"profile": "work", "servers": {"names": ["snowflake"]}})
    assert ws.servers.names == ["snowflake"]
    assert ws.servers.tags == []


def test_parse_workspace_optional_fields_default():
    ws = _parse_workspace("ws", {"profile": "work"})
    assert ws.description == ""
    assert ws.project == ""
    assert ws.default_session_name == ""


# ---------------------------------------------------------------------------
# T02/T05: State helpers
# ---------------------------------------------------------------------------


def test_write_and_read_state(tmp_path, monkeypatch):
    sf = tmp_path / "state.yaml"
    monkeypatch.setattr("textworkspace.workspace.STATE_FILE", sf)

    _write_state(active_workspace="data", started_at="2026-04-17T10:00:00Z")
    state = _read_state()
    assert state["active_workspace"] == "data"
    assert state["started_at"] == "2026-04-17T10:00:00Z"


def test_write_state_clears_none_values(tmp_path, monkeypatch):
    sf = tmp_path / "state.yaml"
    monkeypatch.setattr("textworkspace.workspace.STATE_FILE", sf)

    _write_state(active_workspace="data", started_at="2026-04-17T10:00:00Z")
    _write_state(active_workspace=None, started_at=None)
    state = _read_state()
    assert "active_workspace" not in state
    assert "started_at" not in state


def test_read_state_missing_file(tmp_path, monkeypatch):
    sf = tmp_path / "nonexistent.yaml"
    monkeypatch.setattr("textworkspace.workspace.STATE_FILE", sf)
    assert _read_state() == {}


# ---------------------------------------------------------------------------
# T02: WorkspaceManager — unknown name (R01)
# ---------------------------------------------------------------------------


def test_start_unknown_workspace_raises(state_file, monkeypatch):
    monkeypatch.setattr("textworkspace.workspace.STATE_FILE", state_file)
    cfg = Config()
    import click

    with pytest.raises(click.UsageError, match="not found"):
        WorkspaceManager(cfg).start("nonexistent")


def test_stop_unknown_workspace_raises(state_file, monkeypatch):
    monkeypatch.setattr("textworkspace.workspace.STATE_FILE", state_file)
    cfg = Config()
    import click

    with pytest.raises(click.UsageError, match="not found"):
        WorkspaceManager(cfg).stop("nonexistent")


# ---------------------------------------------------------------------------
# T02: Happy path — correct order and CLAUDE_CONFIG_DIR injection (R02, R09)
# ---------------------------------------------------------------------------


def test_start_happy_path_order(tmp_path, cfg, monkeypatch, capsys):
    sf = tmp_path / "state.yaml"
    monkeypatch.setattr("textworkspace.workspace.STATE_FILE", sf)
    project_dir = tmp_path / "data-project"
    project_dir.mkdir()
    cfg.workspaces["data"].project = str(project_dir)

    monkeypatch.setattr("textworkspace.workspace._HAS_TEXTACCOUNTS", True)
    monkeypatch.setattr(
        "textworkspace.workspace._ta_env_for_profile",
        lambda p: {"CLAUDE_CONFIG_DIR": "/tmp/profile/work"},
    )

    call_order: list[str] = []
    captured_envs: list[dict] = []

    def mock_run(args, check=True, env=None, **kw):
        call_order.append(args[0].rsplit("/", 1)[-1])
        if env is not None:
            captured_envs.append(dict(env))
        return MagicMock(returncode=0)

    monkeypatch.setattr("textworkspace.workspace.subprocess.run", mock_run)
    monkeypatch.setattr("textworkspace.workspace.shutil.which", lambda x: f"/usr/bin/{x}")

    WorkspaceManager(cfg).start("data")

    # mcpf called before textsessions
    assert call_order.index("mcpf") < call_order.index("textsessions")

    # CLAUDE_CONFIG_DIR injected into mcpf env
    assert any(e.get("CLAUDE_CONFIG_DIR") == "/tmp/profile/work" for e in captured_envs)

    # State written
    state = yaml.safe_load(sf.read_text())
    assert state["active_workspace"] == "data"
    assert "started_at" in state


def test_start_passes_session_name(tmp_path, cfg, monkeypatch):
    sf = tmp_path / "state.yaml"
    monkeypatch.setattr("textworkspace.workspace.STATE_FILE", sf)
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    cfg.workspaces["data"].project = str(project_dir)

    monkeypatch.setattr("textworkspace.workspace._HAS_TEXTACCOUNTS", False)
    ts_args: list[list[str]] = []

    def mock_run(args, check=True, env=None, **kw):
        if "textsessions" in args[0]:
            ts_args.append(list(args))
        return MagicMock(returncode=0)

    monkeypatch.setattr("textworkspace.workspace.subprocess.run", mock_run)
    monkeypatch.setattr("textworkspace.workspace.shutil.which", lambda x: f"/usr/bin/{x}")

    WorkspaceManager(cfg).start("data", session_name="reporting-orderbook-bug")

    assert any("reporting-orderbook-bug" in " ".join(a) for a in ts_args)


def test_start_profile_override(tmp_path, cfg, monkeypatch):
    sf = tmp_path / "state.yaml"
    monkeypatch.setattr("textworkspace.workspace.STATE_FILE", sf)
    monkeypatch.setattr("textworkspace.workspace._HAS_TEXTACCOUNTS", True)

    called_with: list[str] = []
    monkeypatch.setattr(
        "textworkspace.workspace._ta_env_for_profile",
        lambda p: called_with.append(p) or {"CLAUDE_CONFIG_DIR": "/tmp/other"},
    )
    monkeypatch.setattr("textworkspace.workspace.subprocess.run", lambda *a, **k: MagicMock(returncode=0))
    monkeypatch.setattr("textworkspace.workspace.shutil.which", lambda x: f"/usr/bin/{x}")

    WorkspaceManager(cfg).start("data", profile="personal")

    assert called_with == ["personal"], "should use override profile, not workspace default"


def test_start_default_session_name_used(tmp_path, cfg, monkeypatch):
    sf = tmp_path / "state.yaml"
    monkeypatch.setattr("textworkspace.workspace.STATE_FILE", sf)
    cfg.workspaces["data"].default_session_name = "data-default"
    monkeypatch.setattr("textworkspace.workspace._HAS_TEXTACCOUNTS", False)

    ts_args: list[list[str]] = []

    def mock_run(args, check=True, env=None, **kw):
        if "textsessions" in args[0]:
            ts_args.append(list(args))
        return MagicMock(returncode=0)

    monkeypatch.setattr("textworkspace.workspace.subprocess.run", mock_run)
    monkeypatch.setattr("textworkspace.workspace.shutil.which", lambda x: f"/usr/bin/{x}")

    WorkspaceManager(cfg).start("data")

    assert any("data-default" in " ".join(a) for a in ts_args)


# ---------------------------------------------------------------------------
# T02: Degradation — each tool missing (R05, R06, R07)
# ---------------------------------------------------------------------------


def test_start_no_textaccounts_warns_continues(tmp_path, cfg, monkeypatch, capsys):
    sf = tmp_path / "state.yaml"
    monkeypatch.setattr("textworkspace.workspace.STATE_FILE", sf)
    monkeypatch.setattr("textworkspace.workspace._HAS_TEXTACCOUNTS", False)
    monkeypatch.setattr("textworkspace.workspace.subprocess.run", lambda *a, **k: MagicMock(returncode=0))
    monkeypatch.setattr("textworkspace.workspace.shutil.which", lambda x: f"/usr/bin/{x}")

    WorkspaceManager(cfg).start("data")

    err = capsys.readouterr().err
    assert "[WARN]" in err
    assert "textaccounts" in err
    # State still written
    assert sf.exists()


def test_start_no_mcpf_warns_continues(tmp_path, cfg, monkeypatch, capsys):
    sf = tmp_path / "state.yaml"
    monkeypatch.setattr("textworkspace.workspace.STATE_FILE", sf)
    monkeypatch.setattr("textworkspace.workspace._HAS_TEXTACCOUNTS", False)
    monkeypatch.setattr("textworkspace.workspace.subprocess.run", lambda *a, **k: MagicMock(returncode=0))
    monkeypatch.setattr(
        "textworkspace.workspace.shutil.which",
        lambda x: None if x == "mcpf" else f"/usr/bin/{x}",
    )

    WorkspaceManager(cfg).start("data")

    err = capsys.readouterr().err
    assert "mcpf not found" in err
    assert sf.exists()


def test_start_no_textsessions_warns_continues(tmp_path, cfg, monkeypatch, capsys):
    sf = tmp_path / "state.yaml"
    monkeypatch.setattr("textworkspace.workspace.STATE_FILE", sf)
    monkeypatch.setattr("textworkspace.workspace._HAS_TEXTACCOUNTS", False)
    monkeypatch.setattr("textworkspace.workspace.subprocess.run", lambda *a, **k: MagicMock(returncode=0))
    monkeypatch.setattr(
        "textworkspace.workspace.shutil.which",
        lambda x: None if x == "textsessions" else f"/usr/bin/{x}",
    )

    WorkspaceManager(cfg).start("data")

    err = capsys.readouterr().err
    assert "textsessions not found" in err
    assert sf.exists()


def test_start_missing_project_dir_warns_continues(tmp_path, cfg, monkeypatch, capsys):
    sf = tmp_path / "state.yaml"
    monkeypatch.setattr("textworkspace.workspace.STATE_FILE", sf)
    monkeypatch.setattr("textworkspace.workspace._HAS_TEXTACCOUNTS", False)
    monkeypatch.setattr("textworkspace.workspace.subprocess.run", lambda *a, **k: MagicMock(returncode=0))
    monkeypatch.setattr("textworkspace.workspace.shutil.which", lambda x: f"/usr/bin/{x}")
    cfg.workspaces["data"].project = str(tmp_path / "nonexistent-dir")

    WorkspaceManager(cfg).start("data")

    err = capsys.readouterr().err
    assert "does not exist" in err
    assert sf.exists()


# ---------------------------------------------------------------------------
# T05: stop clears state, does not run profile switch (R11, R12)
# ---------------------------------------------------------------------------


def test_stop_clears_state(tmp_path, cfg, monkeypatch):
    sf = tmp_path / "state.yaml"
    monkeypatch.setattr("textworkspace.workspace.STATE_FILE", sf)
    sf.write_text("active_workspace: data\nstarted_at: '2026-04-17T10:00:00Z'\n")

    monkeypatch.setattr("textworkspace.workspace.subprocess.run", lambda *a, **k: MagicMock(returncode=0))
    monkeypatch.setattr("textworkspace.workspace.shutil.which", lambda x: f"/usr/bin/{x}")

    WorkspaceManager(cfg).stop("data")

    state = _read_state()
    assert "active_workspace" not in state


def test_stop_does_not_call_textaccounts(tmp_path, cfg, monkeypatch):
    sf = tmp_path / "state.yaml"
    monkeypatch.setattr("textworkspace.workspace.STATE_FILE", sf)

    ta_calls: list = []
    monkeypatch.setattr(
        "textworkspace.workspace._ta_env_for_profile",
        lambda p: ta_calls.append(p) or {},
    )
    monkeypatch.setattr("textworkspace.workspace.subprocess.run", lambda *a, **k: MagicMock(returncode=0))
    monkeypatch.setattr("textworkspace.workspace.shutil.which", lambda x: f"/usr/bin/{x}")

    WorkspaceManager(cfg).stop("data")

    assert ta_calls == [], "stop() must not touch profile (R12)"


# ---------------------------------------------------------------------------
# T14: workspaces.status
# ---------------------------------------------------------------------------


def test_status_returns_state_when_active(tmp_path, cfg, monkeypatch):
    sf = tmp_path / "state.yaml"
    monkeypatch.setattr("textworkspace.workspace.STATE_FILE", sf)
    sf.write_text("active_workspace: data\nstarted_at: '2026-04-17T10:00:00Z'\n")

    state = WorkspaceManager(cfg).status()
    assert state is not None
    assert state["active_workspace"] == "data"


def test_status_returns_none_when_no_active(tmp_path, cfg, monkeypatch):
    sf = tmp_path / "state.yaml"
    monkeypatch.setattr("textworkspace.workspace.STATE_FILE", sf)

    assert WorkspaceManager(cfg).status() is None
