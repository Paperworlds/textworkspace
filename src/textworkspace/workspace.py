"""Workspace profile manager — join account + servers + project into one unit."""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click
import yaml

STATE_FILE = Path.home() / ".config" / "paperworlds" / "state.yaml"

try:
    from textaccounts.api import env_for_profile as _ta_env_for_profile

    _HAS_TEXTACCOUNTS = True
except ImportError:
    _HAS_TEXTACCOUNTS = False

    def _ta_env_for_profile(profile: str) -> dict:  # type: ignore[misc]
        raise ImportError("textaccounts not installed")


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


def _read_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    with STATE_FILE.open() as f:
        return yaml.safe_load(f) or {}


def _write_state(**kwargs: object) -> None:
    state = _read_state()
    state.update(kwargs)
    state = {k: v for k, v in state.items() if v is not None}
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with STATE_FILE.open("w") as f:
        yaml.dump(state, f, default_flow_style=False)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run_tool(args: list[str], env: Optional[dict] = None, tool_name: str = "") -> None:
    label = tool_name or args[0]
    try:
        subprocess.run(args, check=True, env=env)
    except FileNotFoundError:
        click.echo(f"[WARN] {label} not found — skipping", err=True)
    except subprocess.CalledProcessError as e:
        click.echo(f"[WARN] {label} failed ({e.returncode}) — skipping", err=True)


def _mcpf_args(servers) -> list[str]:
    if servers.tags:
        args = []
        for tag in servers.tags:
            args += ["--tag", tag]
        return args
    return list(servers.names)


# ---------------------------------------------------------------------------
# WorkspaceManager
# ---------------------------------------------------------------------------


class WorkspaceManager:
    def __init__(self, cfg) -> None:
        self._cfg = cfg

    def start(
        self,
        name: str,
        session_name: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> None:
        ws = self._cfg.workspaces.get(name)
        if ws is None:
            raise click.UsageError(f"workspace '{name}' not found — run: tw workspaces list")

        active_profile = profile or ws.profile

        # Step 1: Resolve profile dir for CLAUDE_CONFIG_DIR injection
        profile_dir: Optional[str] = None
        if _HAS_TEXTACCOUNTS:
            try:
                env_vars = _ta_env_for_profile(active_profile)
                raw = env_vars.get("CLAUDE_CONFIG_DIR")
                if raw:
                    profile_dir = str(raw)
            except (KeyError, ValueError, Exception) as e:
                click.echo(f"[WARN] textaccounts: {e} — skipping profile switch", err=True)
        else:
            click.echo("[WARN] textaccounts not installed — skipping profile switch", err=True)

        # Step 2: Build mcpf env with injected CLAUDE_CONFIG_DIR
        mcpf_env = {**os.environ}
        if profile_dir:
            mcpf_env["CLAUDE_CONFIG_DIR"] = profile_dir

        # Step 3: Start servers
        if ws.servers.tags or ws.servers.names:
            mcpf_bin = shutil.which("mcpf")
            if mcpf_bin is None:
                click.echo("[WARN] mcpf not found — skipping server start", err=True)
            else:
                extra = _mcpf_args(ws.servers)
                _run_tool([mcpf_bin, "start"] + extra, env=mcpf_env, tool_name="mcpf")

        # Step 4: Open session
        ts_bin = shutil.which("textsessions")
        if ts_bin is None:
            click.echo("[WARN] textsessions not found — skipping session launch", err=True)
        else:
            session_cmd = [ts_bin, "new"]
            if ws.project:
                project_path = Path(ws.project).expanduser()
                if project_path.exists():
                    session_cmd += ["--project", str(project_path)]
                else:
                    click.echo(
                        f"[WARN] project dir '{ws.project}' does not exist — continuing", err=True
                    )
            sname = session_name or ws.default_session_name
            if sname:
                session_cmd += ["--name", sname]
            _run_tool(session_cmd, tool_name="textsessions")

        # Step 5: Write state
        _write_state(
            active_workspace=name,
            started_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        click.echo(f"workspace '{name}' started")

    def stop(self, name: str) -> None:
        ws = self._cfg.workspaces.get(name)
        if ws is None:
            raise click.UsageError(f"workspace '{name}' not found — run: tw workspaces list")

        # Stop servers (no profile env injection needed for stop)
        if ws.servers.tags or ws.servers.names:
            mcpf_bin = shutil.which("mcpf")
            if mcpf_bin is None:
                click.echo("[WARN] mcpf not found — skipping server stop", err=True)
            else:
                extra = _mcpf_args(ws.servers)
                _run_tool([mcpf_bin, "stop"] + extra, tool_name="mcpf")

        # Clear state — do NOT touch profile (R12)
        _write_state(active_workspace=None, started_at=None)
        click.echo(f"workspace '{name}' stopped")

    def list(self):
        return list(self._cfg.workspaces.values())

    def status(self) -> Optional[dict]:
        state = _read_state()
        if not state.get("active_workspace"):
            return None
        return state
