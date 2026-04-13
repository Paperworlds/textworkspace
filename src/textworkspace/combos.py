"""Combo loading and execution engine."""

from __future__ import annotations

import os
import shlex
import socket
import subprocess
from pathlib import Path
from typing import Any

import click
import yaml

from textworkspace.config import CONFIG_DIR

COMBOS_FILE = CONFIG_DIR / "combos.yaml"
COMBOS_DIR = CONFIG_DIR / "combos.d"

_TEXTPROXY_PORT = 9880

# ---------------------------------------------------------------------------
# Default combos written by tw init
# ---------------------------------------------------------------------------

DEFAULT_COMBOS_YAML = """\
# textworkspace combos — user-defined workflow recipes
# Add your own combos here, or in ~/.config/paperworlds/combos.d/<name>.yaml
combos:
  up:
    description: Start proxy and default servers
    builtin: true
    steps:
      - run: proxy start
        skip_if: proxy.running
      - run: servers start --tag default

  down:
    description: Stop all servers and proxy
    builtin: true
    steps:
      - run: servers stop --all
      - run: proxy stop
        skip_if: proxy.stopped

  reset:
    description: Switch profile and restart proxy and servers
    builtin: true
    args: [profile]
    steps:
      - run: accounts switch {profile}
      - run: proxy restart
      - run: servers restart --tag default
"""

# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_combos() -> dict[str, dict[str, Any]]:
    """Load combos: combos.d/*.yaml < combos.yaml (user wins).

    Emits a warning on name collision.
    """
    result: dict[str, dict[str, Any]] = {}

    if COMBOS_DIR.exists():
        for path in sorted(COMBOS_DIR.glob("*.yaml")):
            _merge(result, _load_file(path), label=path.name)

    if COMBOS_FILE.exists():
        _merge(result, _load_file(COMBOS_FILE), label="combos.yaml")

    return result


def _load_file(path: Path) -> dict[str, dict[str, Any]]:
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    raw = data.get("combos", {})
    return raw if isinstance(raw, dict) else {}


def _merge(
    target: dict[str, dict],
    incoming: dict[str, dict],
    label: str,
) -> None:
    for name, defn in incoming.items():
        if name in target:
            click.echo(
                f"warning: combo '{name}' from {label} overrides an earlier definition",
                err=True,
            )
        target[name] = defn


# ---------------------------------------------------------------------------
# Condition evaluator
# ---------------------------------------------------------------------------


def evaluate_condition(condition: str) -> bool:
    """Return True if *condition* holds.

    Supported vocabulary:
      proxy.running          — textproxy is accepting connections
      proxy.stopped          — textproxy is not reachable
      servers.running        — at least one textserve server is running
      servers.none_running   — no textserve servers are running
      accounts.active <name> — TW_PROFILE env var equals <name>
    """
    parts = condition.strip().split(None, 1)
    key = parts[0]
    arg = parts[1] if len(parts) > 1 else None

    if key == "proxy.running":
        return _is_proxy_running()
    if key == "proxy.stopped":
        return not _is_proxy_running()
    if key == "servers.running":
        return _are_servers_running()
    if key == "servers.none_running":
        return not _are_servers_running()
    if key == "accounts.active":
        return _is_account_active(arg or "")

    click.echo(f"warning: unknown condition '{condition}' — treating as False", err=True)
    return False


def _is_proxy_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", _TEXTPROXY_PORT), timeout=1):
            return True
    except OSError:
        return False


def _are_servers_running() -> bool:
    import shutil

    binary = shutil.which("textserve")
    if binary is None:
        return False
    try:
        import json as _json

        result = subprocess.run(
            [binary, "list", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False
        servers = _json.loads(result.stdout) if result.stdout.strip() else []
        if not isinstance(servers, list):
            servers = [servers]
        return any(s.get("status") == "running" for s in servers)
    except Exception:  # noqa: BLE001
        return False


def _is_account_active(name: str) -> bool:
    return os.environ.get("TW_PROFILE", "") == name


# ---------------------------------------------------------------------------
# Step executor
# ---------------------------------------------------------------------------


def _interpolate(template: str, args_map: dict[str, str]) -> str:
    """Replace {argname} placeholders with values from args_map."""
    for key, val in args_map.items():
        template = template.replace(f"{{{key}}}", val)
    return template


def run_combo(
    name: str,
    defn: dict[str, Any],
    args_map: dict[str, str],
    *,
    dry_run: bool = False,
    continue_on_error: bool = False,
) -> int:
    """Execute combo *name*.  Returns 0 on success, non-zero on first failure."""
    steps = defn.get("steps", [])
    if not steps:
        click.echo(f"combo '{name}': no steps defined")
        return 0

    if dry_run:
        click.echo(f"[dry-run] combo: {name}")

    failed = 0
    for i, step in enumerate(steps, 1):
        run_str = _interpolate(step.get("run", ""), args_map)
        skip_if = step.get("skip_if")
        only_if = step.get("only_if")

        skip = False
        reason = ""

        if skip_if:
            if evaluate_condition(skip_if):
                skip = True
                reason = f"skip_if '{skip_if}' is true"

        if not skip and only_if:
            if not evaluate_condition(only_if):
                skip = True
                reason = f"only_if '{only_if}' is false"

        if dry_run:
            status = "SKIP" if skip else "RUN"
            note = f"  ({reason})" if reason else ""
            click.echo(f"  step {i}: {run_str}  [{status}]{note}")
            continue

        if skip:
            click.echo(f"  step {i}: {run_str}  [skipped — {reason}]")
            continue

        click.echo(f"  step {i}: {run_str}")
        proc = subprocess.run(["textworkspace"] + shlex.split(run_str))
        if proc.returncode != 0:
            click.echo(f"  step {i}: failed (exit {proc.returncode})", err=True)
            failed += 1
            if not continue_on_error:
                return proc.returncode

    return 1 if (failed and continue_on_error) else 0
