"""textworkspace CLI — meta CLI and package manager for the Paperworlds text- stack."""

from __future__ import annotations

import click

from textworkspace import __version__


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


@main.command("config")
@click.argument("key", required=False)
@click.argument("value", required=False)
def config_cmd(key: str | None, value: str | None) -> None:
    """Get or set a config value (key [value])."""
    if key is None:
        click.echo("config: not yet implemented — use 'textworkspace config <key> [value]'")
        return
    if value is None:
        click.echo(f"config get {key}: not yet implemented")
    else:
        click.echo(f"config set {key}={value}: not yet implemented")


@main.command()
@click.argument("binary", required=False)
def which(binary: str | None) -> None:
    """Print the path of a managed binary."""
    if binary is None:
        click.echo("which: specify a binary name")
        return
    click.echo(f"which {binary}: not yet implemented")
