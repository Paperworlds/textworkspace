"""textworkspace CLI — meta CLI and package manager for the Paperworlds text- stack."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import click

from textworkspace import __version__
from textworkspace.bootstrap import (
    BIN_DIR,
    GITHUB_ORG,
    download_binary,
    install_binary,
    latest_version,
)
from textworkspace.combos import (
    COMBOS_DIR,
    COMBOS_FILE,
    DEFAULT_COMBOS_YAML,
    export_combo,
    fetch_community_info,
    install_combo,
    list_installed_combos,
    load_combos,
    resolve_options,
    run_combo,
    search_community,
    update_combo,
    _fetch_url,
    _source_to_url,
)
from textworkspace.config import CONFIG_DIR, CONFIG_FILE, ToolEntry, config_as_yaml, load_config, save_config
from textworkspace.forums import forums as forums_group

# ---------------------------------------------------------------------------
# Optional integration imports — degrade gracefully if not installed
# ---------------------------------------------------------------------------

try:
    from textaccounts.api import env_for_profile, list_profiles

    _HAS_TEXTACCOUNTS = True
except ImportError:
    _HAS_TEXTACCOUNTS = False

    def list_profiles() -> list:  # type: ignore[misc]
        return []

    def env_for_profile(profile: str) -> dict:  # type: ignore[misc]
        raise KeyError(profile)

try:
    from textsessions.sessions import STATE_DIR as _TS_STATE_DIR, filter_sessions as _ts_filter

    _HAS_TEXTSESSIONS = True

    def load_sessions() -> list[dict]:
        """Read all sessions from textsessions YAML index files."""
        import yaml

        sessions: list[dict] = []
        for f in _TS_STATE_DIR.glob("*.yaml"):
            if f.name.startswith("_"):
                continue
            with f.open() as fh:
                data = yaml.safe_load(fh) or {}
            for sid, info in data.items():
                if isinstance(info, dict):
                    info["id"] = sid
                    sessions.append(info)
        return sessions

    def filter_sessions(sessions: list, query: str | None = None) -> list:
        if not query:
            return sessions
        return _ts_filter(sessions, query=query)

except ImportError:
    _HAS_TEXTSESSIONS = False

    def load_sessions() -> list:  # type: ignore[misc]
        return []

    def filter_sessions(sessions: list, **kwargs) -> list:  # type: ignore[misc]
        return []


# ---------------------------------------------------------------------------
# CLI root — ComboGroup dispatches unknown commands to combo definitions
# ---------------------------------------------------------------------------


class _ComboGroup(click.Group):
    """click.Group that falls back to user-defined combos for unknown commands."""

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        cmd = super().get_command(ctx, cmd_name)
        if cmd is not None:
            return cmd
        try:
            combos = load_combos()
        except Exception:  # noqa: BLE001
            return None
        defn = combos.get(cmd_name)
        if defn is None:
            return None
        return _make_combo_command(cmd_name, defn)

    def list_commands(self, ctx: click.Context) -> list[str]:
        base = super().list_commands(ctx)
        try:
            combo_names = list(load_combos().keys())
        except Exception:  # noqa: BLE001
            combo_names = []
        return sorted(set(base) | set(combo_names))


def _make_combo_command(name: str, defn: dict[str, Any]) -> click.Command:
    """Build a click.Command that runs a combo.

    If the combo defines ``options:``, each boolean option becomes a
    ``--<key>/--no-<key>`` CLI flag, and string options become ``--<key> VALUE``.
    """
    combo_options = defn.get("options", {})

    # Build the command function
    @click.command(name=name, help=defn.get("description", f"Run the '{name}' combo."))
    @click.argument("args", nargs=-1)
    @click.option("--continue", "continue_on_error", is_flag=True, help="Continue on step failure.")
    @click.pass_context
    def _cmd(ctx: click.Context, args: tuple[str, ...], continue_on_error: bool, **opt_kwargs: Any) -> None:
        dry_run = (ctx.obj or {}).get("dry_run", False)
        arg_names: list[str] = defn.get("args", [])
        args_map = {arg_names[i]: args[i] for i in range(min(len(arg_names), len(args)))}

        # Build CLI overrides — only include options explicitly passed by user
        cli_overrides = {}
        for key, val in opt_kwargs.items():
            if val is not None:
                cli_overrides[key] = val

        options = resolve_options(name, defn, cli_overrides)
        rc = run_combo(name, defn, args_map, dry_run=dry_run, continue_on_error=continue_on_error, options=options)
        if rc != 0:
            raise SystemExit(rc)

    # Attach option flags dynamically based on combo options: block
    for key, default_val in combo_options.items():
        if isinstance(default_val, bool):
            _cmd = click.option(
                f"--{key}/--no-{key}",
                default=None,
                help=f"Toggle {key} (default: {default_val}).",
            )(_cmd)
        else:
            _cmd = click.option(
                f"--{key}",
                default=None,
                help=f"Set {key} (default: {default_val!r}).",
            )(_cmd)

    return _cmd


@click.group(cls=_ComboGroup)
@click.version_option(__version__, "--version", "-V", prog_name="textworkspace")
@click.option("--dry-run", is_flag=True, default=False, help="Print planned steps without executing.")
@click.pass_context
def main(ctx: click.Context, dry_run: bool) -> None:
    """textworkspace — manage the Paperworlds text- stack."""
    ctx.ensure_object(dict)
    ctx.obj["dry_run"] = dry_run


# ---------------------------------------------------------------------------
# tw init / doctor
# ---------------------------------------------------------------------------


@main.command()
def init() -> None:
    """Guided first-run setup — detect tools, bootstrap binaries, write config."""
    from textworkspace.doctor import detect_installed_tools

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    click.echo("textworkspace init")
    click.echo(f"  config dir: {CONFIG_DIR}")
    click.echo()

    # Detect already-installed tools
    click.echo("Detecting installed tools…")
    tools = detect_installed_tools()
    for name, info in tools.items():
        if info.installed:
            ver = f" {info.version}" if info.version else ""
            click.echo(f"  {name}{ver}  (already installed via {info.source})")
        else:
            click.echo(f"  {name}  not found")
    click.echo()

    # Load or create config
    cfg = load_config()

    # Walk through tools in dependency order
    _init_textaccounts(cfg, tools)
    click.echo()
    _init_textproxy(cfg, tools)
    click.echo()
    _init_textsessions(cfg, tools)
    click.echo()
    _init_textserve(cfg, tools)
    click.echo()

    # Write config
    save_config(cfg)
    click.echo(f"  wrote config → {CONFIG_FILE}")

    # Write default combos.yaml if absent
    if not COMBOS_FILE.exists():
        COMBOS_FILE.write_text(DEFAULT_COMBOS_YAML)
        click.echo(f"  wrote combos → {COMBOS_FILE}")
    else:
        click.echo(f"  combos → {COMBOS_FILE} (exists)")

    click.echo()

    # Offer to install fish shell functions
    _init_fish_functions()

    click.echo()
    click.echo("Done. Run `tw doctor` to check your setup.")


def _init_textaccounts(cfg: Any, tools: dict) -> None:
    info = tools.get("textaccounts")
    click.echo("textaccounts  (account profiles)")
    if info and info.installed:
        click.echo(f"  already installed ({info.version or '?'})")
        cfg.tools["textaccounts"] = ToolEntry(
            version=info.version or "",
            source=info.source or "pypi",
            bin=info.bin_path,
        )
    else:
        click.echo("  not installed — install with: pip install textaccounts")


def _init_textproxy(cfg: Any, tools: dict) -> None:
    info = tools.get("textproxy")
    click.echo("textproxy  (AI API proxy, optional)")
    if info and info.installed:
        click.echo(f"  already installed ({info.version or '?'})")
        cfg.tools["textproxy"] = ToolEntry(
            version=info.version or "",
            source=info.source or "github",
            bin=info.bin_path,
        )
    elif click.confirm("  Download textproxy binary from GitHub?", default=False):
        _bootstrap_go_tool("textproxy", cfg)
    else:
        click.echo("  skipped")


def _init_textsessions(cfg: Any, tools: dict) -> None:
    info = tools.get("textsessions")
    click.echo("textsessions  (session manager)")
    if info and info.installed:
        click.echo(f"  already installed ({info.version or '?'})")
        cfg.tools["textsessions"] = ToolEntry(
            version=info.version or "",
            source=info.source or "pypi",
            bin=info.bin_path,
        )
    else:
        click.echo("  not installed — install with: pip install textsessions")


def _init_textserve(cfg: Any, tools: dict) -> None:
    info = tools.get("textserve")
    click.echo("textserve  (server manager, optional)")
    if info and info.installed:
        click.echo(f"  already installed ({info.version or '?'})")
        cfg.tools["textserve"] = ToolEntry(
            version=info.version or "",
            source=info.source or "github",
            bin=info.bin_path,
        )
    elif click.confirm("  Download textserve binary from GitHub?", default=False):
        _bootstrap_go_tool("textserve", cfg)
    else:
        click.echo("  skipped")


def _init_fish_functions() -> None:
    """Offer to install fish shell wrapper functions."""
    from textworkspace.shell import generate_fish

    fish_dir = Path.home() / ".config" / "fish" / "functions"
    fish_tw_file = fish_dir / "tw.fish"

    click.echo("fish shell wrapper  (optional, for tw switch env propagation)")

    # Check if fish is available
    try:
        subprocess.run(["fish", "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        click.echo("  fish not found — skipped")
        return

    # Check if functions dir exists
    if not fish_dir.exists():
        if not click.confirm(f"  Create {fish_dir}?", default=False):
            click.echo("  skipped")
            return
        fish_dir.mkdir(parents=True, exist_ok=True)

    # Check if already installed
    if fish_tw_file.exists():
        click.echo(f"  already installed → {fish_tw_file}")
        return

    # Offer to install
    if click.confirm("  Install fish functions?", default=True):
        fish_tw_file.write_text(generate_fish() + "\n")
        click.echo(f"  installed → {fish_tw_file}")
    else:
        click.echo("  skipped")


def _bootstrap_go_tool(name: str, cfg: Any) -> None:
    try:
        click.echo(f"  fetching latest version of {name}…")
        latest = latest_version(name)
        click.echo(f"  downloading {name} {latest}…")
        download_binary(name, latest)
        symlink = install_binary(name, latest)
        cfg.tools[name] = ToolEntry(version=latest.lstrip("v"), source="github", bin=str(symlink))
        click.echo(f"  installed {name} {latest} → {symlink}")
    except Exception as exc:  # noqa: BLE001
        click.echo(f"  failed to install {name}: {exc}", err=True)


@main.command()
def doctor() -> None:
    """Full diagnostic — checks tools, config, combos, fish functions, proxy, servers."""
    from textworkspace.doctor import run_doctor_checks

    results = run_doctor_checks()

    label_w = max(len(r.label) for r in results)
    detail_w = max(len(r.detail) for r in results)

    _icon = {"ok": "ok", "warn": "warn", "fail": "FAIL"}
    for r in results:
        icon = _icon.get(r.status, r.status)
        fix_part = f"  →  {r.fix}" if r.fix else ""
        click.echo(f"  {r.label:<{label_w}}  {r.detail:<{detail_w}}  {icon}{fix_part}")


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
# tw aliases — show available short aliases for installed tools
# ---------------------------------------------------------------------------

# Known aliases: short name -> full binary name
_TOOL_ALIASES: dict[str, list[str]] = {
    "textworkspace": ["tw", "xtw"],
    "textsessions": ["ts"],
    "textaccounts": ["ta"],
    "paperagents": ["pp"],
}

# Tools eligible for `tw shell install --all` completion generation.
# Each entry: (binary_name, click_env_prefix, aliases)
# textworkspace/tw/xtw excluded — handled by existing shell wrapper install.
_COMPLETABLE_TOOLS: list[tuple[str, str, list[str]]] = [
    ("textforums", "TEXTFORUMS", []),
    ("textaccounts", "TEXTACCOUNTS", ["ta"]),
    ("textsessions", "TEXTSESSIONS", ["ts"]),
    ("paperagents", "PAPERAGENTS", ["pp"]),
]


@main.command()
def aliases() -> None:
    """Show available short aliases for installed tools.

    Lists which binaries have short aliases (e.g. tw -> textworkspace)
    and whether each alias is currently available on PATH.
    """
    for full_name, short_names in sorted(_TOOL_ALIASES.items()):
        full_bin = shutil.which(full_name)
        if not full_bin:
            continue
        for alias in short_names:
            alias_bin = shutil.which(alias)
            if alias_bin:
                click.echo(f"  {alias:15s} -> {full_name:20s} ({alias_bin})")
            else:
                click.echo(f"  {alias:15s} -> {full_name:20s} (not installed)")


# ---------------------------------------------------------------------------
# tw dev — developer mode
# ---------------------------------------------------------------------------

# Python tools that can be installed from local repos.
# Order matters: dependencies must come first.
# deps maps tool -> list of other _PYTHON_TOOLS it needs injected via --with-editable.
_PYTHON_TOOLS = ("textaccounts", "textsessions", "textworkspace")
_PYTHON_TOOL_DEPS: dict[str, list[str]] = {
    "textaccounts": [],
    "textsessions": ["textaccounts"],
    "textworkspace": [],
}


@main.group(invoke_without_command=True)
@click.pass_context
def dev(ctx: click.Context) -> None:
    """Developer mode — install tools from local repo checkouts.

    Requires `defaults.dev_root` in config, pointing to the directory
    containing tool repos (e.g. ~/projects/personal/paperworlds).

    \b
    tw dev on        — enable dev mode, install tools editable
    tw dev off       — switch back to user mode (PyPI)
    tw dev reinstall — re-run editable installs after version bumps
    tw dev           — show current mode
    """
    if ctx.invoked_subcommand is not None:
        return
    cfg = load_config()
    mode = cfg.defaults.get("mode", "user")
    dev_root = cfg.defaults.get("dev_root", "")
    click.echo(f"mode: {mode}")
    if dev_root:
        click.echo(f"dev_root: {dev_root}")
    if mode == "developer":
        for name in _PYTHON_TOOLS:
            repo_path = _dev_repo_path(cfg, name)
            if repo_path and Path(repo_path).exists():
                click.echo(f"  {name}: {repo_path}")
            elif repo_path:
                click.echo(f"  {name}: {repo_path} (missing)")
            else:
                click.echo(f"  {name}: not found in dev_root")


def _dev_repo_path(cfg: Any, tool_name: str) -> str | None:
    """Resolve a tool's repo path from dev_root."""
    dev_root = cfg.defaults.get("dev_root", "")
    if not dev_root:
        return None
    candidate = Path(dev_root).expanduser() / tool_name
    return str(candidate)


@dev.command("on")
@click.argument("dev_root", required=False)
def dev_on(dev_root: str | None) -> None:
    """Enable developer mode and install Python tools as editable.

    Optionally pass DEV_ROOT to set the base path where tool repos live.
    If not passed, uses the existing dev_root from config.
    """
    cfg = load_config()

    if dev_root:
        dev_root = str(Path(dev_root).expanduser().resolve())
        cfg.defaults["dev_root"] = dev_root
    elif not cfg.defaults.get("dev_root"):
        click.echo("No dev_root configured. Pass the path to your tool repos:")
        click.echo("  tw dev on /path/to/paperworlds")
        raise SystemExit(1)

    cfg.defaults["mode"] = "developer"
    resolved_root = Path(cfg.defaults["dev_root"])

    if not resolved_root.exists():
        click.echo(f"dev_root does not exist: {resolved_root}", err=True)
        raise SystemExit(1)

    installed = []
    for name in _PYTHON_TOOLS:
        repo_path = resolved_root / name
        if not repo_path.exists():
            click.echo(f"  {name}: {repo_path} not found, skipping")
            continue

        cmd = ["uv", "tool", "install", "-e", str(repo_path), "--force"]
        # Inject local editable deps so tools share the dev versions
        for dep in _PYTHON_TOOL_DEPS.get(name, []):
            dep_path = resolved_root / dep
            if dep_path.exists():
                cmd.extend(["--with-editable", str(dep_path)])

        deps_label = _PYTHON_TOOL_DEPS.get(name, [])
        extra = f" (with {', '.join(deps_label)})" if deps_label else ""
        click.echo(f"  {name}: installing editable from {repo_path}{extra}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            click.echo(f"  {name}: ok")
            installed.append(name)
            cfg.tools[name] = ToolEntry(version="", source="dev", bin=shutil.which(name))
        else:
            click.echo(f"  {name}: failed — {result.stderr.strip()}", err=True)

    save_config(cfg)
    click.echo(f"\nDeveloper mode enabled. {len(installed)}/{len(_PYTHON_TOOLS)} tool(s) installed.")


@dev.command("off")
def dev_off() -> None:
    """Disable developer mode — reinstall tools from PyPI."""
    cfg = load_config()
    cfg.defaults["mode"] = "user"

    for name in _PYTHON_TOOLS:
        click.echo(f"  {name}: reinstalling from PyPI")
        # Install with extras for tools that have optional deps on other tools
        pkg = f"{name}[accounts]" if name == "textsessions" else name
        result = subprocess.run(
            ["uv", "tool", "install", pkg, "--force"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            click.echo(f"  {name}: ok")
            cfg.tools[name] = ToolEntry(version="", source="pypi", bin=shutil.which(name))
        else:
            click.echo(f"  {name}: failed — {result.stderr.strip()}", err=True)

    save_config(cfg)
    click.echo("\nUser mode restored. dev_root preserved (run `tw dev on` to re-enable).")


@dev.command("reinstall")
def dev_reinstall() -> None:
    """Re-install all dev tools (useful after pyproject.toml version bumps)."""
    cfg = load_config()
    if cfg.defaults.get("mode") != "developer":
        click.echo("Not in developer mode. Run `tw dev on` first.")
        raise SystemExit(1)

    resolved_root = Path(cfg.defaults.get("dev_root", ""))
    for name in _PYTHON_TOOLS:
        repo_path = _dev_repo_path(cfg, name)
        if not repo_path or not Path(repo_path).exists():
            click.echo(f"  {name}: skipping (not found)")
            continue

        cmd = ["uv", "tool", "install", "-e", repo_path, "--force"]
        for dep in _PYTHON_TOOL_DEPS.get(name, []):
            dep_path = resolved_root / dep
            if dep_path.exists():
                cmd.extend(["--with-editable", str(dep_path)])

        deps_label = _PYTHON_TOOL_DEPS.get(name, [])
        extra = f" (with {', '.join(deps_label)})" if deps_label else ""
        click.echo(f"  {name}: reinstalling from {repo_path}{extra}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            click.echo(f"  {name}: ok")
            cfg.tools[name] = ToolEntry(version="", source="dev", bin=shutil.which(name))
        else:
            click.echo(f"  {name}: failed — {result.stderr.strip()}", err=True)

    save_config(cfg)


# ---------------------------------------------------------------------------
# tw switch <profile>
# ---------------------------------------------------------------------------


@main.command()
@click.argument("profile", required=False)
def switch(profile: str | None) -> None:
    """Switch the active workspace profile.

    Prints shell eval output to set environment variables.
    When run inside the tw fish wrapper, outputs env changes directly.
    When run outside, outputs __TW_EVAL__ protocol for wrapper to handle.
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

    # Collect export commands
    exports = [f"set -gx {key} {val!r}" for key, val in env.items()]

    if not exports:
        return

    # Always output __TW_EVAL__ protocol — the shell wrapper captures
    # stdout and evals the lines after the marker.
    click.echo("__TW_EVAL__")
    for export in exports:
        click.echo(export)



# ---------------------------------------------------------------------------
# tw shell [--fish|--bash|--zsh]
# ---------------------------------------------------------------------------


@main.group(invoke_without_command=True)
@click.option("--fish", "shell_type", flag_value="fish", help="Output fish shell wrapper.")
@click.option("--bash", "shell_type", flag_value="bash", help="Output bash shell wrapper.")
@click.option("--zsh", "shell_type", flag_value="zsh", help="Output zsh shell wrapper.")
@click.pass_context
def shell(ctx: click.Context, shell_type: str | None) -> None:
    """Shell wrappers and completions for tw.

    Without a subcommand, prints the wrapper to stdout (for piping).
    Use `tw shell install` to install directly.
    """
    if ctx.invoked_subcommand is not None:
        return

    from textworkspace.shell import generate_bash, generate_fish, generate_zsh

    if shell_type is None:
        shell_type = _detect_shell()

    generators = {"fish": generate_fish, "bash": generate_bash, "zsh": generate_zsh}
    click.echo(generators[shell_type]())


@shell.command()
@click.option("--fish", "shell_type", flag_value="fish", help="Install for fish.")
@click.option("--bash", "shell_type", flag_value="bash", help="Install for bash.")
@click.option("--zsh", "shell_type", flag_value="zsh", help="Install for zsh.")
@click.option("--all", "install_all", is_flag=True, default=False,
              help="Also install completions for other Paperworlds CLI tools.")
def install(shell_type: str | None, install_all: bool) -> None:
    """Install shell wrappers and completions.

    Detects your shell and writes the appropriate config:

      fish: ~/.config/fish/functions/tw.fish
      bash: appends to ~/.bashrc
      zsh:  appends to ~/.zshrc

    With --all, also generates completions for textforums, textaccounts,
    textsessions, and paperagents (if installed).
    """
    from textworkspace.shell import generate_bash, generate_fish, generate_zsh

    if shell_type is None:
        shell_type = _detect_shell()

    if shell_type == "fish":
        target = Path.home() / ".config" / "fish" / "functions" / "tw.fish"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(generate_fish())
        click.echo(f"Installed fish wrapper + completions -> {target}")
        click.echo("Run `source ~/.config/fish/functions/tw.fish` or open a new terminal.")
    elif shell_type == "bash":
        target = Path.home() / ".bashrc"
        marker = "# textworkspace shell wrapper"
        _install_posix_wrapper(target, marker, generate_bash())
        click.echo(f"Installed bash wrapper + completions -> {target}")
        click.echo("Run `source ~/.bashrc` or open a new terminal.")
    elif shell_type == "zsh":
        target = Path.home() / ".zshrc"
        marker = "# textworkspace shell wrapper"
        _install_posix_wrapper(target, marker, generate_zsh())
        click.echo(f"Installed zsh wrapper + completions -> {target}")
        click.echo("Run `source ~/.zshrc` or open a new terminal.")

    if install_all:
        click.echo("\nInstalling completions for other tools:")
        _install_all_tool_completions(shell_type)


def _generate_tool_completion(tool: str, env_prefix: str, shell_type: str) -> str | None:
    """Run Click's completion protocol to generate shell completions for a tool."""
    env_var = f"_{env_prefix}_COMPLETE"
    source_type = f"{shell_type}_source"
    try:
        result = subprocess.run(
            [tool],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, env_var: source_type},
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _install_all_tool_completions(shell_type: str) -> None:
    """Generate and install completions for all known Paperworlds CLI tools."""
    for tool, env_prefix, aliases in _COMPLETABLE_TOOLS:
        if not shutil.which(tool):
            click.echo(f"  {tool}: not installed, skipping")
            continue

        completion = _generate_tool_completion(tool, env_prefix, shell_type)
        if completion is None:
            click.echo(f"  {tool}: failed to generate completions, skipping")
            continue

        _write_tool_completion(tool, aliases, completion, shell_type)
        names = [tool] + aliases
        click.echo(f"  {', '.join(names)}: installed")


def _write_tool_completion(
    tool: str, aliases: list[str], completion: str, shell_type: str,
) -> None:
    """Write completion files for a tool and its aliases."""
    if shell_type == "fish":
        comp_dir = Path.home() / ".config" / "fish" / "completions"
        comp_dir.mkdir(parents=True, exist_ok=True)
        (comp_dir / f"{tool}.fish").write_text(completion)
        for alias in aliases:
            (comp_dir / f"{alias}.fish").write_text(
                f"# Alias completions — wraps {tool}\n"
                f"complete --command {alias} --wraps {tool}\n"
            )

    elif shell_type == "bash":
        comp_dir = Path.home() / ".local" / "share" / "bash-completion" / "completions"
        comp_dir.mkdir(parents=True, exist_ok=True)
        (comp_dir / tool).write_text(completion)
        for alias in aliases:
            (comp_dir / alias).write_text(
                f"# Alias completions — wraps {tool}\n"
                f"source {comp_dir / tool}\n"
            )

    elif shell_type == "zsh":
        comp_dir = Path.home() / ".zsh" / "completions"
        comp_dir.mkdir(parents=True, exist_ok=True)
        content = completion
        for alias in aliases:
            content += f"\ncompdef {alias}={tool}\n"
        (comp_dir / f"_{tool}").write_text(content)
        # Hint if fpath not configured
        zshrc = Path.home() / ".zshrc"
        if zshrc.exists() and ".zsh/completions" not in zshrc.read_text():
            click.echo(
                f"  Note: add to .zshrc: fpath=(~/.zsh/completions $fpath); "
                f"autoload -Uz compinit && compinit"
            )


def _install_posix_wrapper(rc_file: Path, marker: str, content: str) -> None:
    """Install or replace a wrapper block in a shell rc file."""
    end_marker = "# end textworkspace shell wrapper"
    block = f"{marker}\n{content}{end_marker}\n"

    if rc_file.exists():
        existing = rc_file.read_text()
        if marker in existing:
            import re
            pattern = re.escape(marker) + r".*?" + re.escape(end_marker) + r"\n?"
            updated = re.sub(pattern, block, existing, flags=re.DOTALL)
            rc_file.write_text(updated)
            return
        # Append
        with rc_file.open("a") as f:
            f.write(f"\n{block}")
    else:
        rc_file.write_text(block)


def _detect_shell() -> str:
    """Detect the user's active shell.

    Checks FISH_VERSION first (set by fish), then falls back to $SHELL.
    $SHELL is the login shell, which may differ from the running shell.
    """
    if os.environ.get("FISH_VERSION"):
        return "fish"
    shell_path = os.environ.get("SHELL", "")
    if "fish" in shell_path:
        return "fish"
    if "zsh" in shell_path:
        return "zsh"
    return "bash"


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
            all_sessions = load_sessions()
            items = filter_sessions(all_sessions, query=query)[:limit] if query else all_sessions[:limit]
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


def _get_textproxy_port() -> int:
    import json
    config_path = Path.home() / ".config" / "textproxy" / "config.json"
    try:
        data = json.loads(config_path.read_text())
        return int(data["port"])
    except Exception:  # noqa: BLE001
        return _TEXTPROXY_DEFAULT_PORT


def _proxy_stats_http(port: int = 0) -> dict:
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
@click.option("--port", default=None, type=int, help="textproxy HTTP port (reads from textproxy config by default).")
def stats(session_id: str | None, port: int | None) -> None:
    """Show token usage and stats from the textproxy.

    Queries the HTTP API first; falls back to `textproxy stats --json`.
    """
    if port is None:
        port = _get_textproxy_port()
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
        ("mode", _status_mode()),
        ("proxy", _status_proxy()),
        ("servers", _status_servers()),
        ("sessions", _status_sessions()),
        ("combos", _status_combos()),
    ]

    label_width = max(len(r[0]) for r in rows)
    for label, value in rows:
        click.echo(f"  {label:<{label_width}}  {value}")


def _status_profile() -> str:
    if not _HAS_TEXTACCOUNTS:
        return "(textaccounts not installed)"
    try:
        profiles = list_profiles()
        current_config_dir = os.environ.get("CLAUDE_CONFIG_DIR", "")

        # Infer active profile by matching CLAUDE_CONFIG_DIR against profiles
        active = "default"
        for p in profiles:
            try:
                env = env_for_profile(p)
                if env.get("CLAUDE_CONFIG_DIR") == current_config_dir:
                    active = p
                    break
            except Exception:  # noqa: BLE001
                continue
        else:
            # No match — fall back to first profile
            if profiles:
                active = profiles[0]

        env_part = f" (CLAUDE_CONFIG_DIR={current_config_dir})" if current_config_dir else ""
        return f"{active}{env_part}"
    except Exception as exc:  # noqa: BLE001
        return f"(error: {exc})"


def _status_proxy() -> str:
    import socket

    port = _get_textproxy_port()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return f"running :{port}"
    except OSError:
        pass

    if not shutil.which("textproxy"):
        return "not installed"
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
        from datetime import date

        items = load_sessions()
        total = len(items)
        today = date.today().isoformat()  # "2026-04-13"
        active_today = sum(
            1 for i in items
            if isinstance(i, dict) and i.get("last_active", "").startswith(today)
        )
        today_part = f" · {active_today} active today" if active_today else ""
        return f"{total} total{today_part}"
    except Exception as exc:  # noqa: BLE001
        return f"(error: {exc})"


def _status_mode() -> str:
    cfg = load_config()
    mode = cfg.defaults.get("mode", "user")
    if mode == "developer":
        dev_root = cfg.defaults.get("dev_root", "")
        return f"developer ({dev_root})" if dev_root else "developer"
    return mode


def _status_combos() -> str:
    try:
        combos = load_combos()
        if not combos:
            return "none (run tw init)"
        builtin = sum(1 for d in combos.values() if d.get("builtin"))
        user = len(combos) - builtin
        return f"{builtin} builtin + {user} user"
    except Exception:  # noqa: BLE001
        return "(error loading combos)"


# ---------------------------------------------------------------------------
# tw combos group
# ---------------------------------------------------------------------------


@main.group("combos", invoke_without_command=True)
@click.pass_context
def combos_cmd(ctx: click.Context) -> None:
    """Manage combo workflow recipes."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@combos_cmd.command("list")
def combos_list() -> None:
    """List all available combos with descriptions."""
    try:
        combos = load_combos()
    except Exception as exc:  # noqa: BLE001
        click.echo(f"combos list: error loading combos — {exc}", err=True)
        raise SystemExit(1)

    if not combos:
        click.echo("No combos defined. Run `tw init` to create the default combos.yaml.")
        return

    label_width = max(len(k) for k in combos)
    for name, defn in sorted(combos.items()):
        desc = defn.get("description", "")
        builtin_tag = "  [builtin]" if defn.get("builtin") else ""
        click.echo(f"  {name:<{label_width}}  {desc}{builtin_tag}")


@combos_cmd.command("edit")
def combos_edit() -> None:
    """Open combos.yaml in $EDITOR."""
    if not COMBOS_FILE.exists():
        click.echo(f"combos.yaml not found — run `tw init` first", err=True)
        raise SystemExit(1)
    editor = os.environ.get("EDITOR", "vi")
    subprocess.run([editor, str(COMBOS_FILE)], check=False)


@combos_cmd.command("add")
@click.argument("name")
def combos_add(name: str) -> None:
    """Scaffold a new combo entry interactively."""
    try:
        combos = load_combos()
    except Exception:  # noqa: BLE001
        combos = {}

    if name in combos:
        click.echo(f"warning: combo '{name}' already exists — it will be overwritten if you save")

    description = click.prompt("Description", default=f"Run the {name} combo")
    args_raw = click.prompt("Positional args (comma-separated, or blank)", default="")
    args_list = [a.strip() for a in args_raw.split(",") if a.strip()]
    step_count = click.prompt("How many steps?", default=1, type=int)
    steps = []
    for i in range(step_count):
        run_str = click.prompt(f"  step {i + 1} run")
        skip_if = click.prompt(f"  step {i + 1} skip_if (or blank)", default="")
        only_if = click.prompt(f"  step {i + 1} only_if (or blank)", default="")
        step: dict[str, str] = {"run": run_str}
        if skip_if:
            step["skip_if"] = skip_if
        if only_if:
            step["only_if"] = only_if
        steps.append(step)

    entry: dict[str, Any] = {"description": description, "steps": steps}
    if args_list:
        entry["args"] = args_list

    import yaml as _yaml  # noqa: PLC0415

    snippet = _yaml.dump({name: entry}, default_flow_style=False, indent=2)
    click.echo("\nAdd this to your combos.yaml under 'combos:':\n")
    click.echo(snippet)
    if COMBOS_FILE.exists() and click.confirm("Append to combos.yaml now?", default=True):
        with COMBOS_FILE.open() as f:
            existing = _yaml.safe_load(f) or {}
        if "combos" not in existing or not isinstance(existing["combos"], dict):
            existing["combos"] = {}
        existing["combos"][name] = entry
        with COMBOS_FILE.open("w") as f:
            _yaml.dump(existing, f, default_flow_style=False)
        click.echo(f"  saved '{name}' to {COMBOS_FILE}")


@combos_cmd.command("install")
@click.argument("source")
def combos_install(source: str) -> None:
    """Install a combo from a local file, gist URL, or gh:org/repo/name."""
    # Fetch raw YAML
    if source.startswith("gh:"):
        try:
            url = _source_to_url(source)
            raw = _fetch_url(url)
        except Exception as exc:  # noqa: BLE001
            click.echo(f"combos install: {exc}", err=True)
            raise SystemExit(1)
    elif source.startswith(("http://", "https://")):
        try:
            raw = _fetch_url(source)
        except Exception as exc:  # noqa: BLE001
            click.echo(f"combos install: could not fetch {source} — {exc}", err=True)
            raise SystemExit(1)
    else:
        path = Path(source)
        if not path.exists():
            click.echo(f"combos install: file not found: {source}", err=True)
            raise SystemExit(1)
        raw = path.read_text()

    try:
        name = install_combo(source, raw)
    except (ValueError, Exception) as exc:  # noqa: BLE001
        click.echo(f"combos install: {exc}", err=True)
        raise SystemExit(1)

    click.echo(f"installed '{name}' → {COMBOS_DIR / (name + '.yaml')}")


@combos_cmd.command("export")
@click.argument("name", required=False)
@click.option("--all", "export_all", is_flag=True, help="Export all installed combos.")
def combos_export(name: str | None, export_all: bool) -> None:
    """Export combo(s) as standalone YAML to stdout."""
    if export_all:
        installed = list_installed_combos()
        if not installed:
            click.echo("No installed combos to export.")
            return
        for combo_name, _ in installed:
            try:
                click.echo(export_combo(combo_name), nl=False)
                click.echo("---")
            except Exception as exc:  # noqa: BLE001
                click.echo(f"# error exporting {combo_name}: {exc}", err=True)
        return

    if not name:
        click.echo("combos export: provide a NAME or use --all", err=True)
        raise SystemExit(1)

    try:
        click.echo(export_combo(name), nl=False)
    except FileNotFoundError as exc:
        click.echo(f"combos export: {exc}", err=True)
        raise SystemExit(1)


@combos_cmd.command("update")
def combos_update_installed() -> None:
    """Re-fetch all installed combos from their source, skipping modified ones."""
    installed = list_installed_combos()
    if not installed:
        click.echo("No installed combos to update.")
        return

    for name, file_data in installed:
        result = update_combo(name, file_data)
        if result == "updated":
            click.echo(f"  {name}: updated")
        elif result == "skipped":
            click.echo(
                f"  {name}: skipped — _modified is true (edit combos.d/{name}.yaml to clear)",
                err=True,
            )
        else:
            click.echo(f"  {name}: {result}", err=True)


@combos_cmd.command("search")
@click.argument("query")
def combos_search(query: str) -> None:
    """Search the community repo (paperworlds/textcombos) for combos."""
    try:
        results = search_community(query)
    except RuntimeError as exc:
        click.echo(f"combos search: {exc}", err=True)
        raise SystemExit(1)

    if not results:
        click.echo(f"No combos found matching '{query}'.")
        return

    for item in results:
        tags_part = f"  [{', '.join(item['tags'])}]" if item.get("tags") else ""
        author_part = f" by {item['author']}" if item.get("author") else ""
        click.echo(f"  {item['name']}{author_part}  —  {item['description']}{tags_part}")
        if item.get("requires"):
            click.echo(f"    requires: {', '.join(item['requires'])}")


@combos_cmd.command("info")
@click.argument("name")
def combos_info(name: str) -> None:
    """Show details for a combo in the community repo before installing."""
    try:
        data = fetch_community_info(name)
    except RuntimeError as exc:
        click.echo(f"combos info: {exc}", err=True)
        raise SystemExit(1)

    click.echo(f"name:        {data.get('name', name)}")
    if data.get("author"):
        click.echo(f"author:      {data['author']}")
    if data.get("description"):
        click.echo(f"description: {data['description']}")
    tags = data.get("tags", [])
    if tags:
        click.echo(f"tags:        {', '.join(tags)}")
    requires = data.get("requires", [])
    if requires:
        click.echo(f"requires:    {', '.join(requires)}")
    steps = data.get("steps", [])
    if steps:
        click.echo(f"steps ({len(steps)}):")
        for i, step in enumerate(steps, 1):
            run_str = step.get("run", "")
            note = ""
            if step.get("skip_if"):
                note = f"  [skip_if: {step['skip_if']}]"
            elif step.get("only_if"):
                note = f"  [only_if: {step['only_if']}]"
            click.echo(f"  {i}. {run_str}{note}")
    click.echo(f"\nInstall: tw combos install gh:{name}")


@combos_cmd.command("remove")
@click.argument("name")
def combos_remove(name: str) -> None:
    """Remove an installed combo from combos.d/."""
    path = COMBOS_DIR / f"{name}.yaml"
    if not path.exists():
        click.echo(f"combos remove: '{name}' not found in combos.d/", err=True)
        raise SystemExit(1)
    path.unlink()
    click.echo(f"removed '{name}'")


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


# ---------------------------------------------------------------------------
# forums sub-group
# ---------------------------------------------------------------------------

main.add_command(forums_group, "forums")
