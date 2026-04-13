"""textworkspace CLI — meta CLI and package manager for the Paperworlds text- stack."""

from __future__ import annotations

import os
import shutil
import subprocess

import click

from textworkspace import __version__
from textworkspace.bootstrap import (
    BIN_DIR,
    GITHUB_ORG,
    download_binary,
    install_binary,
    latest_version,
)
from textworkspace.config import CONFIG_FILE, ToolEntry, config_as_yaml, load_config, save_config

# ---------------------------------------------------------------------------
# Optional integration imports — degrade gracefully if not installed
# ---------------------------------------------------------------------------

try:
    from textaccounts.api import env_for_profile, list_profiles, switch as _ta_switch

    _HAS_TEXTACCOUNTS = True
except ImportError:
    _HAS_TEXTACCOUNTS = False

    def list_profiles() -> list:  # type: ignore[misc]
        return []

    def env_for_profile(profile: str) -> dict:  # type: ignore[misc]
        raise KeyError(profile)

    def _ta_switch(profile: str) -> None:  # type: ignore[misc]
        pass

try:
    from textsessions.api import list_sessions as _ts_list

    _HAS_TEXTSESSIONS = True
except ImportError:
    _HAS_TEXTSESSIONS = False

    def _ts_list(**kwargs) -> list:  # type: ignore[misc]
        return []


# ---------------------------------------------------------------------------
# CLI root
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(__version__, "--version", "-V", prog_name="textworkspace")
def main() -> None:
    """textworkspace — manage the Paperworlds text- stack."""


# ---------------------------------------------------------------------------
# tw init / doctor
# ---------------------------------------------------------------------------


@main.command()
def init() -> None:
    """Initialise textworkspace config and install dependencies."""
    click.echo("init: not yet implemented")


@main.command()
def doctor() -> None:
    """Check that all required binaries and services are healthy."""
    click.echo("doctor: not yet implemented")


# ---------------------------------------------------------------------------
# tw update / which
# ---------------------------------------------------------------------------

_GO_TOOLS = ("textproxy", "textserve")


@main.command()
@click.argument("tool", required=False)
def update(tool: str | None) -> None:
    """Check for and install newer versions of managed binaries.

    Pass TOOL to update a single Go binary (e.g. textproxy, textserve).
    Omit TOOL to update all known Go tools.
    """
    tools = (tool,) if tool else _GO_TOOLS

    cfg = load_config()
    any_updated = False

    for name in tools:
        click.echo(f"Checking {name} …")
        try:
            latest = latest_version(name)
        except Exception as exc:  # noqa: BLE001
            click.echo(f"  {name}: could not fetch latest version — {exc}", err=True)
            continue

        current = cfg.tools.get(name)
        current_ver = current.version if current else None

        ver_display = current_ver or "(not installed)"
        click.echo(f"  current: {ver_display}  latest: {latest}")

        if current_ver and current_ver.lstrip("v") == latest.lstrip("v"):
            click.echo(f"  {name}: already up to date")
            continue

        click.echo(f"  Downloading {name} {latest} …")
        try:
            download_binary(name, latest)
            symlink = install_binary(name, latest)
        except Exception as exc:  # noqa: BLE001
            click.echo(f"  {name}: install failed — {exc}", err=True)
            continue

        cfg.tools[name] = ToolEntry(
            version=latest.lstrip("v"),
            source="github",
            bin=str(symlink),
        )
        save_config(cfg)

        click.echo(f"  {name}: installed {latest} → {symlink}")
        any_updated = True

    if not any_updated and not tool:
        click.echo("All tools are up to date.")


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


# ---------------------------------------------------------------------------
# tw switch <profile>
# ---------------------------------------------------------------------------


@main.command()
@click.argument("profile", required=False)
def switch(profile: str | None) -> None:
    """Switch the active workspace profile.

    Prints shell eval output to set environment variables.
    Wrap in a fish function:  tw switch work | source
    """
    if not _HAS_TEXTACCOUNTS:
        click.echo(
            "warning: textaccounts is not installed — run: pip install textaccounts",
            err=True,
        )
        raise SystemExit(1)

    if profile is None:
        profiles = list_profiles()
        if not profiles:
            click.echo("No profiles configured.")
        else:
            click.echo("Available profiles:")
            for p in profiles:
                click.echo(f"  {p}")
        return

    try:
        env = env_for_profile(profile)
    except KeyError:
        click.echo(f"switch: unknown profile '{profile}'", err=True)
        raise SystemExit(1)

    # Emit fish-compatible env exports for eval/source
    for key, val in env.items():
        click.echo(f"set -gx {key} {val!r}")

    # Notify the underlying library (may update default, etc.)
    try:
        _ta_switch(profile)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"warning: switch side-effect failed — {exc}", err=True)


# ---------------------------------------------------------------------------
# tw sessions [query]
# ---------------------------------------------------------------------------


@main.command()
@click.argument("query", required=False)
@click.option("--limit", "-n", default=20, show_default=True, help="Max sessions to show.")
def sessions(query: str | None, limit: int) -> None:
    """List or search recent textsessions.

    Falls back to launching the textsessions TUI if the Python API is
    unavailable.  Pass QUERY to filter by session title or ID.
    """
    if _HAS_TEXTSESSIONS:
        try:
            items = _ts_list(query=query, limit=limit)
        except Exception as exc:  # noqa: BLE001
            click.echo(f"sessions: error querying textsessions — {exc}", err=True)
            raise SystemExit(1)

        if not items:
            click.echo("No sessions found.")
            return

        for item in items:
            if isinstance(item, dict):
                sid = item.get("id", "?")
                title = item.get("title", item.get("name", "untitled"))
                state = item.get("state", item.get("status", ""))
            else:
                sid = getattr(item, "id", "?")
                title = getattr(item, "title", getattr(item, "name", "untitled"))
                state = getattr(item, "state", getattr(item, "status", ""))
            status_tag = f"  [{state}]" if state else ""
            click.echo(f"  {sid}  {title}{status_tag}")
        return

    # Fallback: try launching textsessions as a subprocess TUI
    tui = shutil.which("textsessions")
    if tui:
        args = [tui]
        if query:
            args += [query]
        try:
            subprocess.run(args, check=False)
        except OSError as exc:
            click.echo(f"sessions: failed to launch textsessions — {exc}", err=True)
            raise SystemExit(1)
    else:
        click.echo(
            "warning: textsessions is not installed — run: pip install textsessions",
            err=True,
        )
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# tw stats [--session ID]
# ---------------------------------------------------------------------------

_TEXTPROXY_DEFAULT_PORT = 9880


def _proxy_stats_http(port: int = _TEXTPROXY_DEFAULT_PORT) -> dict:
    """Query textproxy HTTP API; raises on any error."""
    import httpx  # local import — optional dep

    url = f"http://localhost:{port}/stats"
    resp = httpx.get(url, timeout=3)
    resp.raise_for_status()
    return resp.json()


def _proxy_stats_subprocess() -> dict:
    """Fall back to `textproxy stats --json` subprocess."""
    import json

    result = subprocess.run(
        ["textproxy", "stats", "--json"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "textproxy stats failed")
    return json.loads(result.stdout)


def _fmt_tokens(n: int | float | None) -> str:
    if n is None:
        return "?"
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


@main.command()
@click.option("--session", "session_id", default=None, help="Filter stats for a specific session ID.")
@click.option("--port", default=_TEXTPROXY_DEFAULT_PORT, show_default=True, help="textproxy HTTP port.")
def stats(session_id: str | None, port: int) -> None:
    """Show token usage and stats from the textproxy.

    Queries the HTTP API first; falls back to `textproxy stats --json`.
    """
    data: dict | None = None

    try:
        data = _proxy_stats_http(port)
    except Exception:  # noqa: BLE001
        try:
            data = _proxy_stats_subprocess()
        except FileNotFoundError:
            click.echo("warning: textproxy is not running and not in PATH", err=True)
            raise SystemExit(1)
        except Exception as exc:  # noqa: BLE001
            click.echo(f"stats: could not reach textproxy — {exc}", err=True)
            raise SystemExit(1)

    if data is None:
        click.echo("stats: no data returned", err=True)
        raise SystemExit(1)

    if session_id:
        sessions_data = data.get("sessions", {})
        session = sessions_data.get(session_id)
        if session is None:
            click.echo(f"stats: session '{session_id}' not found", err=True)
            raise SystemExit(1)
        click.echo(f"  session  {session_id}")
        _print_stats_flat(session)
    else:
        _print_stats_flat(data)


def _print_stats_flat(data: dict) -> None:
    tokens = data.get("tokens", data.get("total_tokens"))
    cost = data.get("cost", data.get("total_cost"))
    sessions_count = data.get("session_count", data.get("sessions_total"))
    active = data.get("active_sessions", data.get("active"))

    lines = []
    if tokens is not None:
        lines.append(f"  tokens   {_fmt_tokens(tokens)}")
    if cost is not None:
        lines.append(f"  cost     ${cost:.4f}")
    if sessions_count is not None:
        active_part = f" · {active} active" if active is not None else ""
        lines.append(f"  sessions {sessions_count}{active_part}")
    if not lines:
        import json

        click.echo(json.dumps(data, indent=2))
        return
    click.echo("\n".join(lines))


# ---------------------------------------------------------------------------
# tw serve [name] [--tag TAG]
# ---------------------------------------------------------------------------


@main.command()
@click.argument("name", required=False)
@click.option("--tag", default=None, help="Filter or start servers by tag.")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def serve(name: str | None, tag: str | None, as_json: bool) -> None:
    """Start or inspect textserve servers.

    With no arguments, lists running servers.
    Pass NAME to start or inspect a specific server.
    """
    binary = shutil.which("textserve")
    if binary is None and (BIN_DIR / "textserve").exists():
        binary = str(BIN_DIR / "textserve")

    if binary is None:
        click.echo(
            "warning: textserve binary not found — run: tw update textserve",
            err=True,
        )
        raise SystemExit(1)

    if name is None and tag is None:
        # List running servers
        cmd = [binary, "list", "--json"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            click.echo(f"serve: {result.stderr.strip() or 'textserve list failed'}", err=True)
            raise SystemExit(result.returncode)

        if as_json:
            click.echo(result.stdout, nl=False)
            return

        try:
            import json

            servers = json.loads(result.stdout) if result.stdout.strip() else []
        except Exception:  # noqa: BLE001
            click.echo(result.stdout, nl=False)
            return

        if not isinstance(servers, list):
            servers = [servers]

        if not servers:
            click.echo("No servers running.")
            return

        for srv in servers:
            s_name = srv.get("name", "?")
            s_status = srv.get("status", "?")
            s_addr = srv.get("addr", srv.get("address", ""))
            addr_part = f"  {s_addr}" if s_addr else ""
            click.echo(f"  {s_name}  {s_status}{addr_part}")
        return

    # Start / inspect a named server
    cmd = [binary]
    if name:
        cmd += ["start", name]
    if tag:
        cmd += ["--tag", tag]
    if as_json:
        cmd += ["--json"]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        click.echo(result.stdout, nl=False)
    if result.stderr:
        click.echo(result.stderr, nl=False, err=True)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


# ---------------------------------------------------------------------------
# tw status — unified view
# ---------------------------------------------------------------------------


@main.command()
def status() -> None:
    """Show unified status of all stack components.

    Combines profile, proxy, servers, and sessions into one compact view.
    """
    rows: list[tuple[str, str]] = [
        ("profile", _status_profile()),
        ("proxy", _status_proxy()),
        ("servers", _status_servers()),
        ("sessions", _status_sessions()),
    ]

    label_width = max(len(r[0]) for r in rows)
    for label, value in rows:
        click.echo(f"  {label:<{label_width}}  {value}")


def _status_profile() -> str:
    if not _HAS_TEXTACCOUNTS:
        return "(textaccounts not installed)"
    try:
        profiles = list_profiles()
        active = os.environ.get("TW_PROFILE", profiles[0] if profiles else "default")
        env = os.environ.get("CLAUDE_CONFIG_DIR", "")
        env_part = f" (CLAUDE_CONFIG_DIR={env})" if env else ""
        return f"{active}{env_part}"
    except Exception as exc:  # noqa: BLE001
        return f"(error: {exc})"


def _status_proxy() -> str:
    port = _TEXTPROXY_DEFAULT_PORT
    try:
        data = _proxy_stats_http(port)
        tokens = data.get("tokens", data.get("total_tokens"))
        token_part = f" · {_fmt_tokens(tokens)} tokens this session" if tokens is not None else ""
        return f"running :{port}{token_part}"
    except Exception:  # noqa: BLE001
        pass

    try:
        data = _proxy_stats_subprocess()
        tokens = data.get("tokens", data.get("total_tokens"))
        token_part = f" · {_fmt_tokens(tokens)} tokens this session" if tokens is not None else ""
        return f"running{token_part}"
    except FileNotFoundError:
        return "not installed"
    except Exception:  # noqa: BLE001
        return "not running"


def _status_servers() -> str:
    binary = shutil.which("textserve")
    if binary is None and (BIN_DIR / "textserve").exists():
        binary = str(BIN_DIR / "textserve")
    if binary is None:
        return "(textserve not installed)"

    try:
        result = subprocess.run(
            [binary, "list", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return f"(error: {result.stderr.strip()})"

        import json

        servers = json.loads(result.stdout) if result.stdout.strip() else []
        if not isinstance(servers, list):
            servers = [servers]

        total = len(servers)
        running = sum(1 for s in servers if s.get("status") == "running")
        names = ", ".join(s.get("name", "?") for s in servers if s.get("status") == "running")
        name_part = f" ({names})" if names else ""
        return f"{running}/{total} running{name_part}"
    except Exception as exc:  # noqa: BLE001
        return f"(error: {exc})"


def _status_sessions() -> str:
    if not _HAS_TEXTSESSIONS:
        return "(textsessions not installed)"
    try:
        items = _ts_list(limit=1000)
        total = len(items)
        active = sum(
            1 for i in items
            if (i.get("state") if isinstance(i, dict) else getattr(i, "state", None))
            in ("active", "running")
        )
        active_part = f" · {active} active" if active else ""
        return f"{total} total{active_part}"
    except Exception as exc:  # noqa: BLE001
        return f"(error: {exc})"


# ---------------------------------------------------------------------------
# tw config group
# ---------------------------------------------------------------------------


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
    load_config()
    editor = os.environ.get("EDITOR", "vi")
    subprocess.run([editor, str(CONFIG_FILE)], check=False)
