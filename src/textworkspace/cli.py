"""textworkspace CLI — meta CLI and package manager for the Paperworlds text- stack."""

from __future__ import annotations

import os
import subprocess
import tempfile

import click

from textworkspace import __version__
from textworkspace.config import CONFIG_FILE, config_as_yaml, load_config, save_config


@click.group()
@click.version_option(__version__, "--version", "-V", prog_name="textworkspace")
def main() -> None:
    """textworkspace — manage the Paperworlds text- stack."""


@main.command()
def init() -> None:
    """Initialise textworkspace config and install dependencies."""
    click.echo("init: not yet implemented")


@main.command()
def status() -> None:
    """Show unified status of all stack components."""
    click.echo("status: not yet implemented")


@main.command()
def doctor() -> None:
    """Check that all required binaries and services are healthy."""
    click.echo("doctor: not yet implemented")


@main.command()
def update() -> None:
    """Update all managed binaries and packages to latest versions."""
    click.echo("update: not yet implemented")


@main.command()
def switch() -> None:
    """Switch the active workspace profile."""
    click.echo("switch: not yet implemented")


@main.command()
def sessions() -> None:
    """Launch or attach to a textsessions TUI."""
    click.echo("sessions: not yet implemented")


@main.command()
def stats() -> None:
    """Show aggregate stats across sessions and accounts."""
    click.echo("stats: not yet implemented")


@main.command()
def serve() -> None:
    """Start a local workspace HTTP API server."""
    click.echo("serve: not yet implemented")


@main.group("config", invoke_without_command=True)
@click.pass_context
def config_cmd(ctx: click.Context) -> None:
    """Show or edit the config file."""
    if ctx.invoked_subcommand is None:
        cfg = load_config()
        click.echo(config_as_yaml(cfg), nl=False)


@config_cmd.command("show")
def config_show() -> None:
    """Print the current config as YAML."""
    cfg = load_config()
    click.echo(config_as_yaml(cfg), nl=False)


@config_cmd.command("edit")
def config_edit() -> None:
    """Open the config file in $EDITOR."""
    # Ensure the file exists before opening
    load_config()
    editor = os.environ.get("EDITOR", "vi")
    subprocess.run([editor, str(CONFIG_FILE)], check=False)


@main.command()
@click.argument("tool")
def which(tool: str) -> None:
    """Show version, source, and install path of a managed tool."""
    cfg = load_config()
    entry = cfg.tools.get(tool)
    if entry is None:
        click.echo(f"{tool}: not found in config", err=True)
        raise SystemExit(1)
    lines = [f"tool:    {tool}", f"version: {entry.version or '(unknown)'}", f"source:  {entry.source}"]
    if entry.bin:
        lines.append(f"bin:     {entry.bin}")
    click.echo("\n".join(lines))
