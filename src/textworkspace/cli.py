"""textworkspace CLI — meta CLI and package manager for the Paperworlds text- stack."""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import yaml
from pathlib import Path
from typing import Any

import click

from textworkspace import __version__

try:
    _git_hash = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"],
        stderr=subprocess.DEVNULL,
        text=True,
        cwd=Path(__file__).parent,
    ).strip()
    _version_str = f"{__version__} ({_git_hash})"
except Exception:
    _version_str = __version__
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
from textworkspace.config import CONFIG_DIR, CONFIG_FILE, ToolEntry, config_as_yaml, get_textproxy_port, load_config, save_config
from textworkspace.forums import forums as forums_group

# ---------------------------------------------------------------------------
# Optional integration imports — degrade gracefully if not installed
# ---------------------------------------------------------------------------

# SPEC: textaccounts-api
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
@click.version_option(_version_str, "--version", "-V", prog_name="textworkspace")
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
    _init_textread(cfg, tools)
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


def _init_textread(cfg: Any, tools: dict) -> None:
    info = tools.get("textread")
    click.echo("textread  (context-aware link reader, optional)")
    if not (info and info.installed):
        click.echo("  not installed — install with: pip install textread")
        return

    click.echo(f"  already installed ({info.version or '?'})")
    cfg.tools["textread"] = ToolEntry(
        version=info.version or "",
        source=info.source or "pypi",
        bin=info.bin_path,
    )

    # Show current config knobs
    _TEXTREAD_CFG_PATH = Path.home() / ".config" / "paperworlds" / "textread.yaml"
    tr_cfg: dict = {}
    if _TEXTREAD_CFG_PATH.exists():
        try:
            import yaml as _yaml
            tr_cfg = _yaml.safe_load(_TEXTREAD_CFG_PATH.read_text()) or {}
        except Exception:
            pass

    model = tr_cfg.get("default_model", "haiku")
    backend = tr_cfg.get("agent_backend", "sdk")
    current_profile = tr_cfg.get("default_profile")
    click.echo(f"  default_model={model}  agent_backend={backend}  default_profile={current_profile or '(none)'}")

    # Offer to set default_profile from textaccounts if available
    try:
        from textaccounts.api import list_profiles as _list_profiles
        profiles = _list_profiles()
        if profiles and isinstance(profiles[0], dict):
            profile_names = [p["name"] for p in profiles]
        else:
            profile_names = list(profiles)
        if profile_names:
            click.echo(f"  available profiles: {', '.join(profile_names)}")
            chosen = click.prompt(
                "  Set default_profile (enter name or leave blank to skip)",
                default="",
                show_default=False,
            ).strip()
            if chosen and chosen in profile_names:
                tr_cfg["default_profile"] = chosen
                _TEXTREAD_CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
                import yaml as _yaml
                _TEXTREAD_CFG_PATH.write_text(_yaml.dump(tr_cfg, default_flow_style=False))
                click.echo(f"  default_profile set to '{chosen}'")
    except ImportError:
        pass


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
    "textread": [],
    "textmap": [],
}

# Tools eligible for `tw shell install`.
# Each entry: (binary_name, click_env_prefix, aliases, eval_translations)
# eval_translations: dict mapping virtual subcommand → real subcommand for shell
# eval wrappers.  e.g. {"switch": "show"} means the user types
# `textaccounts switch foo` but the binary receives `textaccounts show foo`.
# textworkspace/tw/xtw excluded — handled by the main shell wrapper.
_INSTALLABLE_TOOLS: list[tuple[str, str, list[str], dict[str, str]]] = [
    ("textforums", "TEXTFORUMS", [], {}),
    ("textaccounts", "TEXTACCOUNTS", ["ta"], {"switch": "show"}),
    ("textsessions", "TEXTSESSIONS", ["ts"], {}),
    ("paperagents", "PAPERAGENTS", ["pp"], {}),
    ("textread", "TEXTREAD", [], {}),
    ("textmap", "TEXTMAP", [], {}),
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
_PYTHON_TOOLS = ("textaccounts", "textsessions", "textread", "textmap", "textworkspace")
_PYTHON_TOOL_DEPS: dict[str, list[str]] = {
    "textaccounts": [],
    "textsessions": ["textaccounts"],
    "textread": [],
    "textmap": [],
    "textworkspace": [],
}

# Go tools that can be built from local repos via `just install`.
# Each entry: (tool_name, just_recipe)  — recipe defaults to "install".
_GO_TOOLS_DEV: list[tuple[str, str]] = [
    ("textproxy", "install"),
    ("textserve", "install"),
]


@main.group(invoke_without_command=True)
@click.pass_context
def dev(ctx: click.Context) -> None:
    """Developer mode — install tools from local repo checkouts.

    Requires `defaults.dev_root` in config, pointing to the directory
    containing tool repos (e.g. ~/projects/personal/paperworlds).

    \b
    tw dev on        — enable dev mode, install tools editable
    tw dev off       — switch back to user mode (PyPI)
    tw dev install   — re-run editable installs after version bumps
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


def _repo_up_to_date(repo_path: str, tool_entry: Any) -> bool:
    """Return True if the stored version hash matches the repo's current HEAD."""
    if not tool_entry or not tool_entry.version:
        return False
    # Stored format: "X.Y.Z (hash)" or just "X.Y.Z"
    m = re.search(r"\((\w+)\)", tool_entry.version)
    if not m:
        return False
    stored_hash = m.group(1)
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_path,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return head == stored_hash
    except Exception:
        return False


def _tool_version(name: str, bin_path: str | None) -> str:
    """Get installed version string from binary --version output."""
    if not bin_path:
        return "unknown"
    try:
        out = subprocess.check_output(
            [bin_path, "--version"], stderr=subprocess.DEVNULL, text=True, timeout=15
        ).strip()
        # Extract "X.Y.Z (hash)" or just "X.Y.Z" from e.g. "tool, version X.Y.Z (hash)"
        for word in out.split():
            clean = word.rstrip(",")
            if clean and (clean[0].isdigit() or (clean.startswith("v") and len(clean) > 1)):
                # Grab version + optional parenthesised hash on same line
                idx = out.index(word)
                rest = out[idx:]
                # Capture "X.Y.Z" or "X.Y.Z (hash)"
                m = re.search(r"(v?\d+\.\d+[\w.\-]*(?:\s+\(\w+\))?)", rest)
                if m:
                    return m.group(1)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        pass
    return "unknown"


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


@dev.command("install")
def dev_reinstall() -> None:
    """Install all dev tools from local repos (editable). Runs after version bumps."""
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

        if _repo_up_to_date(repo_path, cfg.tools.get(name)):
            stored = cfg.tools[name].version
            click.echo(f"  {name}: up to date  {stored}")
            continue

        cmd = ["uv", "tool", "install", "-e", repo_path, "--force"]
        for dep in _PYTHON_TOOL_DEPS.get(name, []):
            dep_path = resolved_root / dep
            if dep_path.exists():
                cmd.extend(["--with-editable", str(dep_path)])

        deps_label = _PYTHON_TOOL_DEPS.get(name, [])
        extra = f" (with {', '.join(deps_label)})" if deps_label else ""
        click.echo(f"  {name}: installing from {repo_path}{extra}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            bin_path = shutil.which(name)
            version = _tool_version(name, bin_path)
            click.echo(f"  {name}: ok  {version}")
            cfg.tools[name] = ToolEntry(version=version, source="dev", bin=bin_path)
        else:
            click.echo(f"  {name}: failed — {result.stderr.strip()}", err=True)

    # --- Go tools ---
    for go_tool, just_recipe in _GO_TOOLS_DEV:
        repo_path = _dev_repo_path(cfg, go_tool)
        if not repo_path or not Path(repo_path).exists():
            click.echo(f"  {go_tool}: skipping (not found in dev_root)")
            continue

        if _repo_up_to_date(repo_path, cfg.tools.get(go_tool)):
            stored = cfg.tools[go_tool].version
            click.echo(f"  {go_tool}: up to date  {stored}")
            continue

        # Prefer `just <recipe>` if just is available, else fall back to make
        just_bin = shutil.which("just")
        make_bin = shutil.which("make")
        if just_bin:
            cmd = [just_bin, just_recipe]
        elif make_bin:
            cmd = [make_bin, just_recipe]
        else:
            click.echo(f"  {go_tool}: skipping (neither just nor make found)", err=True)
            continue

        click.echo(f"  {go_tool}: building from {repo_path} (just {just_recipe})")
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=repo_path)
        if result.returncode == 0:
            bin_path = shutil.which(go_tool)
            version = _tool_version(go_tool, bin_path)
            click.echo(f"  {go_tool}: ok  {version}")
            cfg.tools[go_tool] = ToolEntry(version=version, source="dev", bin=bin_path)
        else:
            err = (result.stderr or result.stdout).strip()
            click.echo(f"  {go_tool}: failed — {err}", err=True)

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
def install(shell_type: str | None) -> None:
    """Install shell wrappers, aliases, and completions for the entire stack.

    Detects your shell and writes:

    \b
      1. tw wrapper (eval support for tw switch)
      2. Wrappers for tools that need eval (e.g. textaccounts switch)
      3. Alias functions (ta -> textaccounts, ts -> textsessions, pp -> paperagents)
      4. Tab completions for all installed tools
    """
    from textworkspace.shell import generate_bash, generate_fish, generate_zsh

    if shell_type is None:
        shell_type = _detect_shell()

    # 1. Install tw wrapper
    if shell_type == "fish":
        target = Path.home() / ".config" / "fish" / "functions" / "tw.fish"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(generate_fish())
        click.echo(f"  tw: wrapper + completions -> {target}")
    elif shell_type == "bash":
        target = Path.home() / ".bashrc"
        marker = "# textworkspace shell wrapper"
        _install_posix_wrapper(target, marker, generate_bash())
        click.echo(f"  tw: wrapper + completions -> {target}")
    elif shell_type == "zsh":
        target = Path.home() / ".zshrc"
        marker = "# textworkspace shell wrapper"
        _install_posix_wrapper(target, marker, generate_zsh())
        click.echo(f"  tw: wrapper + completions -> {target}")

    # 2-4. Install wrappers, aliases, and completions for all tools
    _install_all_tools(shell_type)

    click.echo("\nDone. Open a new terminal or source your shell config.")


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


def _install_all_tools(shell_type: str) -> None:
    """Install wrappers, aliases, and completions for all Paperworlds tools."""
    for tool, env_prefix, aliases, eval_translations in _INSTALLABLE_TOOLS:
        if not shutil.which(tool):
            click.echo(f"  {tool}: not installed, skipping")
            continue

        parts = []

        # Wrappers + aliases (fish functions / bash/zsh aliases)
        if shell_type == "fish":
            _install_fish_tool(tool, aliases, eval_translations)
        else:
            _install_posix_tool_aliases(tool, aliases, eval_translations, shell_type)
        if aliases:
            parts.append(f"aliases ({', '.join(aliases)})")
        if eval_translations:
            parts.append(f"eval wrapper ({', '.join(eval_translations)})")

        # Completions
        completion = _generate_tool_completion(tool, env_prefix, shell_type)
        if completion:
            _write_tool_completion(tool, aliases, completion, shell_type)
            parts.append("completions")

        names = ", ".join([tool] + aliases)
        detail = " + ".join(parts) if parts else "installed"
        click.echo(f"  {names}: {detail}")


def _install_fish_tool(tool: str, aliases: list[str], eval_translations: dict[str, str]) -> None:
    """Write fish function files for a tool: eval wrapper + alias functions."""
    func_dir = Path.home() / ".config" / "fish" / "functions"
    func_dir.mkdir(parents=True, exist_ok=True)

    # Main tool wrapper (with eval support for specific subcommands)
    if eval_translations:
        # Build if/else-if chain for each virtual → real subcommand translation
        branches = []
        for i, (virtual, real) in enumerate(eval_translations.items()):
            keyword = "if" if i == 0 else "    else if"
            branches.append(
                f"    {keyword} test (count $argv) -ge 1; and test \"$argv[1]\" = \"{virtual}\"\n"
                f"        eval (command {tool} {real} $argv[2..-1])"
            )
        branches_str = "\n".join(branches)
        wrapper = (
            f"# {tool} — shell wrapper (installed by tw shell install)\n"
            f"function {tool} --description '{tool} with eval support'\n"
            f"{branches_str}\n"
            f"    else\n"
            f"        command {tool} $argv\n"
            f"    end\n"
            f"end\n"
        )
        (func_dir / f"{tool}.fish").write_text(wrapper)

    # Alias functions
    for alias in aliases:
        alias_func = (
            f"# {alias} -> {tool} (installed by tw shell install)\n"
            f"function {alias} --description '{tool} alias' --wraps {tool}\n"
            f"    {tool} $argv\n"
            f"end\n"
        )
        (func_dir / f"{alias}.fish").write_text(alias_func)


def _install_posix_tool_aliases(
    tool: str, aliases: list[str], eval_translations: dict[str, str], shell_type: str,
) -> None:
    """Write bash/zsh aliases and eval wrappers for a tool."""
    rc_file = Path.home() / (".bashrc" if shell_type == "bash" else ".zshrc")
    marker = f"# {tool} shell integration"
    lines = []

    if eval_translations:
        # Wrap specific subcommands with eval, translating virtual → real
        lines.append(f'{tool}() {{')
        lines.append(f'    case "$1" in')
        for virtual, real in eval_translations.items():
            lines.append(f'        {virtual}) shift; eval "$(command {tool} {real} "$@")" ;;')
        lines.append(f'        *) command {tool} "$@" ;;')
        lines.append(f'    esac')
        lines.append(f'}}')

    for alias in aliases:
        lines.append(f'alias {alias}="{tool}"')

    if lines:
        _install_posix_wrapper(rc_file, marker, "\n".join(lines) + "\n")


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
    end_marker = marker.replace("# ", "# end ")
    block = f"{marker}\n{content}{end_marker}\n"

    if rc_file.exists():
        existing = rc_file.read_text()
        if marker in existing:
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

def _proxy_stats_http(port: int = 0) -> dict:
    """Query textproxy HTTP API; raises on any error."""
    import httpx  # local import — optional dep

    url = f"http://localhost:{port}/stats"
    resp = httpx.get(url, timeout=3)
    resp.raise_for_status()
    return resp.json()


def _proxy_stats_subprocess() -> dict:
    """Fall back to `textproxy stats --json` subprocess."""
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
        port = get_textproxy_port()
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
        click.echo(json.dumps(data, indent=2))
        return
    click.echo("\n".join(lines))


# ---------------------------------------------------------------------------
# tw proxy — manage the textproxy daemon
# ---------------------------------------------------------------------------


def _textproxy_bin() -> str | None:
    """Return path to textproxy binary or None."""
    p = shutil.which("textproxy")
    if p:
        return p
    managed = BIN_DIR / "textproxy"
    if managed.exists():
        return str(managed)
    return None


class _PassthroughGroup(click.Group):
    """Click group that forwards unknown subcommands (and --help) to a binary.

    Explicitly-registered subcommands still take precedence; unknown names are
    forwarded to the wrapped tool as `<tool> <name> <args...>`. This includes
    `--help`, so `tw proxy <unknown> --help` calls the tool's own help.
    """

    tool_name: str = ""

    def _tool_bin(self) -> str | None:
        return _textproxy_bin() if self.tool_name == "textproxy" else shutil.which(self.tool_name)

    def get_command(self, ctx: click.Context, name: str) -> click.Command | None:
        cmd = super().get_command(ctx, name)
        if cmd is not None:
            return cmd
        tool = self.tool_name

        @click.command(
            name=name,
            context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
            add_help_option=False,
            help=f"Forwarded to `{tool} {name}`. Run with --help for tool docs.",
        )
        @click.argument("args", nargs=-1, type=click.UNPROCESSED)
        def _passthrough(args: tuple[str, ...]) -> None:
            binary = self._tool_bin()
            if binary is None:
                click.echo(f"{tool}: not installed — run: tw update {tool}", err=True)
                raise SystemExit(1)
            result = subprocess.run([binary, name, *args], check=False)
            raise SystemExit(result.returncode)

        return _passthrough


class _ProxyPassthroughGroup(_PassthroughGroup):
    tool_name = "textproxy"


@main.group("proxy", cls=_ProxyPassthroughGroup, invoke_without_command=True)
@click.pass_context
def proxy_cmd(ctx: click.Context) -> None:
    """Manage the textproxy daemon.

    \b
    tw proxy            — show running state
    tw proxy start      — start background daemon
    tw proxy stop       — stop daemon
    tw proxy restart    — restart daemon
    tw proxy log        — tail daemon log
    tw proxy os         — show launchd agent status
    tw proxy os-install — install launchd agent (auto-start on login)
    tw proxy setup      — generate CA cert + install to keychain

    Any other subcommand is forwarded to `textproxy <sub>` automatically
    (e.g. `tw proxy status`, `tw proxy stats --json`). Use
    `tw proxy <sub> --help` to see the tool's own help.
    """
    if ctx.invoked_subcommand is None:
        _proxy_passthrough("status")


def _proxy_passthrough(*args: str) -> None:
    binary = _textproxy_bin()
    if binary is None:
        click.echo("proxy: textproxy not installed — run: tw update textproxy", err=True)
        raise SystemExit(1)
    result = subprocess.run([binary, *args], check=False)
    raise SystemExit(result.returncode)


# Explicit wrappers only for subcommands that cannot be expressed as pure
# passthrough. `os install` and `os uninstall` are space-separated in textproxy,
# so we expose them with dashes and translate here. All other subcommands
# (start, stop, restart, log, status, stats, setup, sessions, ...) flow through
# _ProxyPassthroughGroup automatically.


@proxy_cmd.command("os-install")
def proxy_os_install() -> None:
    """Install launchd agent — auto-start on login, restart on crash."""
    _proxy_passthrough("os", "install")


@proxy_cmd.command("os-uninstall")
def proxy_os_uninstall() -> None:
    """Remove launchd agent."""
    _proxy_passthrough("os", "uninstall")


# ---------------------------------------------------------------------------
# tw repo move <name> <new-path>
# ---------------------------------------------------------------------------

@main.group("repo", invoke_without_command=True)
@click.pass_context
def repo_cmd(ctx: click.Context) -> None:
    """Manage repo references across the stack."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@repo_cmd.command("add")
@click.argument("name")
@click.argument("path")
@click.option("--profile", default="", help="Associate this repo with a textaccounts profile.")
@click.option("--label", default="", help="Human-readable label.")
def repo_add(name: str, path: str, profile: str, label: str) -> None:
    """Register a repo outside dev_root (e.g. a work repo).

    Registered repos participate in forums (inbox, list --repo), ideas
    discovery, and spec discovery — same as repos under dev_root.
    """
    from textworkspace.repos import register

    repo_path = Path(path).expanduser()
    if not repo_path.exists():
        raise click.ClickException(f"path does not exist: {repo_path}")
    if not repo_path.is_dir():
        raise click.ClickException(f"not a directory: {repo_path}")

    cfg = load_config()
    existing = cfg.repos.get(name)
    register(cfg, name, repo_path, profile=profile, label=label)
    save_config(cfg)

    verb = "updated" if existing else "added"
    profile_str = f" (profile: {profile})" if profile else ""
    click.echo(f"{verb} repo '{name}' → {repo_path}{profile_str}")


@repo_cmd.command("list")
def repo_list() -> None:
    """List all repos — dev_root scan + registered entries."""
    from textworkspace.repos import iter_all_repos, _registered_repos, _scan_dev_root, _dev_root_path

    cfg = load_config()
    dev_root = _dev_root_path(cfg)
    scanned = _scan_dev_root(dev_root)
    registered = _registered_repos(cfg)
    merged = iter_all_repos(cfg)

    if not merged:
        click.echo("No repos found. Set dev_root (tw dev on <path>) or register one (tw repo add <name> <path>).")
        return

    name_w = max(len(n) for n in merged)
    for name in sorted(merged):
        path = merged[name]
        if name in registered:
            origin = "registered"
            profile = (cfg.repos[name].profile or "")
            extra = f" (profile: {profile})" if profile else ""
        elif name in scanned:
            origin = "dev_root"
            extra = ""
        else:
            origin = "?"
            extra = ""
        click.echo(f"  {name:<{name_w}}  {origin:<10}  {path}{extra}")


@repo_cmd.command("remove")
@click.argument("name")
def repo_remove(name: str) -> None:
    """Unregister a repo from config.repos (does NOT touch the filesystem)."""
    from textworkspace.repos import unregister

    cfg = load_config()
    if not unregister(cfg, name):
        raise click.ClickException(f"repo '{name}' is not registered")
    save_config(cfg)
    click.echo(f"unregistered '{name}' (files untouched)")


@repo_cmd.command("move")
@click.argument("name")
@click.argument("new_path")
def repo_move(name: str, new_path: str) -> None:
    """Update all references when a repo folder moves.

    Detects whether the physical move has already happened and asks if not.
    Updates config.yaml and delegates ~/.claude/projects/ renaming to each
    tool's own repo move (textsessions handles all profile dirs).
    """
    from textworkspace.config import load_config, save_config
    from textworkspace.doctor import detect_installed_tools

    cfg = load_config()

    if name not in cfg.repos:
        raise click.UsageError(f"repo '{name}' not found in config — run: tw config repos")

    old_path = Path(cfg.repos[name].path).expanduser().resolve()
    new_path_resolved = Path(new_path).expanduser().resolve()

    if old_path == new_path_resolved:
        click.echo("Old and new paths are the same — nothing to do.")
        return

    # --- Smart move detection ---
    old_exists = old_path.exists()
    new_exists = new_path_resolved.exists()

    if new_exists and not old_exists:
        click.echo(f"  folder: already at {new_path_resolved} (skipping physical move)")
    elif old_exists and not new_exists:
        click.confirm(
            f"'{old_path}' still exists. Move it to '{new_path_resolved}'?",
            abort=True,
        )
        old_path.rename(new_path_resolved)
        click.echo(f"  folder: moved → {new_path_resolved}")
    elif old_exists and new_exists:
        raise click.UsageError(
            f"Both '{old_path}' and '{new_path_resolved}' exist — ambiguous.\n"
            f"Move or remove one manually, then re-run."
        )
    else:
        click.echo(f"  [WARN] '{old_path}' not found on disk — updating references only")

    # --- Update config.yaml ---
    cfg.repos[name].path = str(new_path_resolved)
    save_config(cfg)
    click.echo(f"  config.yaml: {old_path} → {new_path_resolved}")

    # --- Call each installed tool's repo move ---
    tools = detect_installed_tools()
    for tool_name, tool_info in tools.items():
        if not tool_info.installed or not tool_info.bin_path:
            continue
        result = subprocess.run(
            [tool_info.bin_path, "repo", "move", name, str(new_path_resolved)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            moved_line = result.stdout.strip()
            click.echo(f"  {tool_name}: {moved_line or 'ok'}")
        elif result.returncode == 2:
            pass  # tool does not support the contract — skip silently
        else:
            click.echo(f"  [WARN] {tool_name}: {result.stderr.strip()}", err=True)

    # --- Warn about unresolvable references ---
    click.echo(f"\nCheck for hardcoded paths that could not be auto-updated:")
    click.echo(f"  grep -r '{old_path}' ~/.config/paperworlds/")


# ---------------------------------------------------------------------------
# tw repo import [tool] [--all]
# ---------------------------------------------------------------------------


@repo_cmd.command("import")
@click.argument("tool", required=False, default=None)
@click.option("--all", "import_all", is_flag=True, help="Import from all installed tools.")
def repo_import(tool: str | None, import_all: bool) -> None:
    """Import repos from tool(s) that support `<tool> repos`.

    tw repo import textsessions
    tw repo import --all
    """
    from textworkspace.repo_import import (
        collect_from_all,
        collect_from_tool,
        deduplicate,
        find_conflicts,
    )
    from textworkspace.doctor import detect_installed_tools

    cfg = load_config()

    if not tool and not import_all:
        raise click.UsageError("Specify a tool name or use --all.")

    # Collect repos
    if import_all:
        tools = detect_installed_tools()
        raw = collect_from_all(tools)
    else:
        tools = detect_installed_tools()
        info = tools.get(tool)
        if not info or not info.installed or not info.bin_path:
            raise click.UsageError(f"'{tool}' is not installed or not found.")
        raw, code = collect_from_tool(info.bin_path, tool)
        if code == 2:
            click.echo(f"{tool} does not support `repos` — nothing to import.")
            return
        if code != 0:
            click.echo(f"[WARN] {tool} repos failed (exit {code}).", err=True)
            return

    incoming = deduplicate(raw)

    if not incoming:
        click.echo("No repos found.")
        return

    # Detect conflicts
    conflicts = find_conflicts(incoming, cfg.repos)
    conflict_names = {c.incoming.name for c in conflicts}

    click.echo(f"\nFound {len(incoming)} repo(s):\n")
    for repo in incoming:
        exists = "  [!]" if repo.name in conflict_names else ""
        click.echo(f"  {repo.name:<20} {repo.path}{exists}")

    if conflicts:
        click.echo(f"\n{len(conflicts)} conflict(s) to resolve:\n")

    to_add: list = []
    skipped = 0
    renamed = 0

    non_conflict = [r for r in incoming if r.name not in conflict_names]
    to_add.extend(non_conflict)

    for conflict in conflicts:
        repo = conflict.incoming
        if conflict.kind == "name":
            click.echo(
                f"  Name conflict: '{repo.name}' already exists at {conflict.existing_path}\n"
                f"    incoming:     {repo.path}"
            )
            choice = click.prompt(
                "  [k]eep existing / [r]ename new / [s]kip",
                default="k",
            ).strip().lower()
            if choice == "k":
                skipped += 1
            elif choice == "r":
                new_name = click.prompt("    New name").strip()
                repo.name = new_name
                to_add.append(repo)
                renamed += 1
            else:
                skipped += 1
        elif conflict.kind == "path":
            click.echo(
                f"  Path conflict: {repo.path} already registered as '{conflict.existing_name}'\n"
                f"    incoming name: '{repo.name}'"
            )
            choice = click.prompt(
                "  [k]eep existing name / [r]ename to incoming / [s]kip",
                default="k",
            ).strip().lower()
            if choice == "r":
                # Update the existing entry's name would require removal + add
                # Simpler: add with incoming name, user resolves duplicate
                to_add.append(repo)
                renamed += 1
            else:
                skipped += 1

    # Apply
    from textworkspace.config import RepoEntry
    added = 0
    for repo in to_add:
        if not repo.path.exists():
            click.echo(f"  [WARN] {repo.name}: path does not exist on disk ({repo.path})")
        cfg.repos[repo.name] = RepoEntry(
            path=str(repo.path),
            profile=repo.meta.get("profile", ""),
        )
        added += 1

    save_config(cfg)
    click.echo(f"\nImported {added} new, skipped {skipped}, renamed {renamed}.")


# ---------------------------------------------------------------------------
# tw serve [name] [--tag TAG]
# ---------------------------------------------------------------------------


def _textserve_bin() -> str | None:
    p = shutil.which("textserve")
    if p:
        return p
    managed = BIN_DIR / "textserve"
    if managed.exists():
        return str(managed)
    return None


def _textserve_passthrough(*args: str) -> None:
    binary = _textserve_bin()
    if binary is None:
        click.echo("serve: textserve not installed — run: tw update textserve", err=True)
        raise SystemExit(1)
    result = subprocess.run([binary, *args], check=False)
    raise SystemExit(result.returncode)


class _ServePassthroughGroup(_PassthroughGroup):
    tool_name = "textserve"

    def _tool_bin(self) -> str | None:
        return _textserve_bin()


@main.group("serve", cls=_ServePassthroughGroup, invoke_without_command=True)
@click.pass_context
def serve(ctx: click.Context) -> None:
    """Start or inspect textserve servers.

    With no subcommand, shows `textserve status` (the fleet table).
    Any other subcommand (start, stop, logs, restart, doctor, ...) is
    forwarded to `textserve` — use `tw serve <sub> --help` for tool docs.
    """
    if ctx.invoked_subcommand is None:
        _textserve_passthrough("status")


# ---------------------------------------------------------------------------
# tw ideas — aggregate IDEAS.yaml/md from all sibling repos
# ---------------------------------------------------------------------------


@main.group("ideas", invoke_without_command=True)
@click.pass_context
def ideas_cmd(ctx: click.Context) -> None:
    """List and explore per-repo IDEAS backlogs.

    Scans `<dev_root>/*/docs/IDEAS.yaml` (also IDEAS.yml / IDEAS.md at the
    repo root as fallbacks) and prints a unified backlog.
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(ideas_list)


def _ideas_dev_root() -> Path | None:
    cfg = load_config()
    root = cfg.defaults.get("dev_root", "")
    return Path(root).expanduser() if root else None


def _ideas_repos() -> dict[str, Path] | None:
    """Union of dev_root + registered repos. None if neither is usable."""
    from textworkspace.repos import iter_all_repos

    repos = iter_all_repos(load_config())
    return repos or None


@ideas_cmd.command("list")
@click.option("--status", "-s", default=None, help="Filter by status (idea, planned, ...).")
@click.option("--repo", "-r", default=None, help="Filter by repo name.")
@click.option("--query", "-q", default=None, help="Substring match on id/title/summary.")
@click.option("--md/--no-md", default=True, show_default=True, help="Include IDEAS.md placeholders.")
def ideas_list(status: str | None, repo: str | None, query: str | None, md: bool) -> None:
    """List ideas across all repos under dev_root."""
    from textworkspace.ideas import load_all_ideas

    repos = _ideas_repos()
    if repos is None:
        click.echo("ideas: no repos found — set dev_root or register with `tw repo add`", err=True)
        raise SystemExit(1)

    ideas = load_all_ideas(repos)

    if not md:
        ideas = [i for i in ideas if i.format != "md"]
    if status:
        ideas = [i for i in ideas if i.status == status]
    if repo:
        ideas = [i for i in ideas if i.repo == repo]
    if query:
        q = query.lower()
        ideas = [i for i in ideas if q in i.id.lower() or q in i.title.lower() or q in i.summary.lower()]

    if not ideas:
        click.echo("No ideas found.")
        return

    repo_w = max(len(i.repo) for i in ideas)
    id_w = min(max(len(i.id) for i in ideas), 32)
    status_w = max(len(i.status) for i in ideas)
    for i in ideas:
        prio = f"p{i.priority} " if i.priority else ""
        click.echo(f"  {i.repo:<{repo_w}}  {i.id[:id_w]:<{id_w}}  {i.status:<{status_w}}  {prio}{i.title}")


@ideas_cmd.command("show")
@click.argument("repo_name")
@click.argument("idea_id", required=False)
def ideas_show(repo_name: str, idea_id: str | None) -> None:
    """Print an idea's full summary, or dump the repo's IDEAS file if no id."""
    from textworkspace.ideas import load_ideas_for_repo

    repos = _ideas_repos()
    if repos is None:
        click.echo("ideas: no repos found", err=True)
        raise SystemExit(1)

    repo_path = repos.get(repo_name)
    if repo_path is None:
        click.echo(f"ideas: repo '{repo_name}' not found (try `tw repo list`)", err=True)
        raise SystemExit(1)

    ideas = load_ideas_for_repo(repo_path)
    if not ideas:
        click.echo(f"No IDEAS file in {repo_name}.")
        return

    if idea_id is None:
        # Dump the source file
        click.echo(ideas[0].path.read_text(), nl=False)
        return

    for i in ideas:
        if i.id == idea_id:
            click.echo(f"repo:     {i.repo}")
            click.echo(f"file:     {i.path}")
            click.echo(f"id:       {i.id}")
            click.echo(f"title:    {i.title}")
            click.echo(f"status:   {i.status}")
            if i.priority:
                click.echo(f"priority: {i.priority}")
            if i.summary:
                click.echo("")
                click.echo(i.summary)
            return

    click.echo(f"ideas: '{idea_id}' not found in {repo_name}", err=True)
    raise SystemExit(1)


_IDEAS_QUICKSTART = """\
# tw ideas — quickstart

Each repo can keep an `IDEAS.yaml` (docs/IDEAS.yaml preferred) with items
like brainstorms, plans, experiments. `tw ideas` aggregates them across
all repos under your dev_root.

## See what's on everyone's minds

  tw ideas                             # everything, every repo
  tw ideas list --repo textaccounts    # just this repo
  tw ideas list --status idea          # filter by status
  tw ideas list --query "passthrough"  # substring match on title/id/summary
  tw ideas list --no-md                # hide IDEAS.md placeholders

## Read one idea in full

  tw ideas show <repo>                 # dump the repo's entire IDEAS file
  tw ideas show <repo> <id>            # pretty-print one idea's summary

## Canonical YAML shape

  ideas:
    - id: my-slug
      title: Short title
      status: idea              # idea | exploring | planned | parked | done
      priority: 1               # optional
      summary: |
        Free-form prose.

Also accepted: mapping form (slug as key), any top-level list-of-dicts
(e.g. 'brainstorm:' — the first one wins).

## When an idea graduates

Ideas that become cross-repo contracts should promote to specs:

  tw forums spec new <slug> --owner <repo> --title "..."

Then delete or park the idea entry.
"""


@ideas_cmd.command("quickstart")
def ideas_quickstart() -> None:
    """Print a 30-second onboarding for tw ideas."""
    click.echo(_IDEAS_QUICKSTART, nl=False)


# ---------------------------------------------------------------------------
# tw up / tw down — bring the whole MCP fleet up or down via textserve
# ---------------------------------------------------------------------------


@main.command("up")
def up_cmd() -> None:
    """Bring the whole MCP fleet up (`textserve up --all`)."""
    _textserve_passthrough("up", "--all")


@main.command("down")
def down_cmd() -> None:
    """Bring the whole MCP fleet down (`textserve down --all`)."""
    _textserve_passthrough("down", "--all")


# ---------------------------------------------------------------------------
# tw accounts — passthrough to textaccounts
# ---------------------------------------------------------------------------


class _AccountsPassthroughGroup(_PassthroughGroup):
    tool_name = "textaccounts"


@main.group("accounts", cls=_AccountsPassthroughGroup, invoke_without_command=True)
@click.pass_context
def accounts_cmd(ctx: click.Context) -> None:
    """Manage textaccounts profiles.

    Subcommands (list, status, doctor, adopt, create, rename, alias,
    show, ...) are forwarded to `textaccounts`. Run `tw accounts <sub>
    --help` for the tool's own docs. With no subcommand, runs
    `textaccounts status`.

    Note: `tw accounts show <profile>` prints shell eval output. To
    actually activate a profile in your shell, use `tw switch <profile>`
    (handled separately for shell-eval propagation).
    """
    if ctx.invoked_subcommand is None:
        binary = shutil.which("textaccounts")
        if binary is None:
            click.echo("accounts: textaccounts not installed — run: pip install textaccounts", err=True)
            raise SystemExit(1)
        result = subprocess.run([binary, "status"], check=False)
        raise SystemExit(result.returncode)


# ---------------------------------------------------------------------------
# tw map — passthrough to textmap
# ---------------------------------------------------------------------------


class _MapPassthroughGroup(_PassthroughGroup):
    tool_name = "textmap"


@main.group("map", cls=_MapPassthroughGroup, invoke_without_command=True)
@click.pass_context
def map_cmd(ctx: click.Context) -> None:
    """Query and manage the knowledge graph via textmap.

    Subcommands (init, doctor, daily, add, sync, inbox, validate, ingest,
    expand, query, ...) are forwarded to `textmap`. Run `tw map <sub>
    --help` for the tool's own docs. With no subcommand, runs
    `textmap --help`.
    """
    if ctx.invoked_subcommand is None:
        binary = shutil.which("textmap")
        if binary is None:
            click.echo("map: textmap not installed — run: pip install textmap", err=True)
            raise SystemExit(1)
        result = subprocess.run([binary, "--help"], check=False)
        raise SystemExit(result.returncode)


# ---------------------------------------------------------------------------
# tw read — passthrough to textread
# ---------------------------------------------------------------------------


class _ReadPassthroughGroup(_PassthroughGroup):
    tool_name = "textread"


@main.group("read", cls=_ReadPassthroughGroup, invoke_without_command=True)
@click.pass_context
def read_cmd(ctx: click.Context) -> None:
    """Read URLs and PDFs via textread.

    Subcommands (read, url, pdf, cache, context, remap, ...) are forwarded
    to `textread`. Run `tw read <sub> --help` for the tool's own docs.
    With no subcommand, prints textread's top-level help.
    """
    if ctx.invoked_subcommand is None:
        binary = shutil.which("textread")
        if binary is None:
            click.echo("read: textread not installed — run: pip install textread", err=True)
            raise SystemExit(1)
        result = subprocess.run([binary, "--help"], check=False)
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
    port = get_textproxy_port()
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

    snippet = yaml.dump({name: entry}, default_flow_style=False, indent=2)
    click.echo("\nAdd this to your combos.yaml under 'combos:':\n")
    click.echo(snippet)
    if COMBOS_FILE.exists() and click.confirm("Append to combos.yaml now?", default=True):
        with COMBOS_FILE.open() as f:
            existing = yaml.safe_load(f) or {}
        if "combos" not in existing or not isinstance(existing["combos"], dict):
            existing["combos"] = {}
        existing["combos"][name] = entry
        with COMBOS_FILE.open("w") as f:
            yaml.dump(existing, f, default_flow_style=False)
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


@combos_cmd.command("sync")
@click.option("--dry-run", is_flag=True, help="Show changes without writing.")
def combos_sync(dry_run: bool) -> None:
    """Refresh builtin combos in combos.yaml against the current defaults.

    Drops builtin combos that were removed from DEFAULT_COMBOS_YAML, updates
    those that changed, and preserves user-defined (non-builtin) combos.
    """
    import yaml as _yaml

    if not COMBOS_FILE.exists():
        click.echo(f"combos.yaml not found at {COMBOS_FILE} — run `tw init`", err=True)
        raise SystemExit(1)

    defaults = _yaml.safe_load(DEFAULT_COMBOS_YAML) or {}
    default_combos = defaults.get("combos", {}) or {}

    current = _yaml.safe_load(COMBOS_FILE.read_text()) or {}
    user_combos = current.get("combos", {}) or {}

    added: list[str] = []
    removed: list[str] = []
    updated: list[str] = []
    kept: list[str] = []

    new_combos: dict[str, Any] = {}
    for name, defn in user_combos.items():
        if defn.get("builtin"):
            if name not in default_combos:
                removed.append(name)
                continue
            if defn != default_combos[name]:
                updated.append(name)
                new_combos[name] = default_combos[name]
            else:
                kept.append(name)
                new_combos[name] = defn
        else:
            kept.append(name)
            new_combos[name] = defn

    for name, defn in default_combos.items():
        if name not in new_combos:
            added.append(name)
            new_combos[name] = defn

    if not (added or removed or updated):
        click.echo("combos sync: up to date.")
        return

    for n in added:
        click.echo(f"  + {n}")
    for n in updated:
        click.echo(f"  ~ {n}")
    for n in removed:
        click.echo(f"  - {n}")

    if dry_run:
        click.echo("(dry-run — no changes written)")
        return

    COMBOS_FILE.write_text(_yaml.safe_dump({"combos": new_combos}, sort_keys=False))
    click.echo(f"wrote {COMBOS_FILE}")


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
# tw tools — third-party software registry
# ---------------------------------------------------------------------------


@main.group("tools", invoke_without_command=True)
@click.pass_context
def tools_cmd(ctx: click.Context) -> None:
    """Manage third-party tools tracked in the workspace registry.

    \b
    tw tools list           — show all registered tools with status
    tw tools add            — register a new tool
    tw tools install [NAME] — install one or all missing tools
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(tools_list)


@tools_cmd.command("list")
def tools_list() -> None:
    """List all tracked third-party tools with their install status."""
    from textworkspace.config import load_config

    cfg = load_config()
    if not cfg.third_party:
        click.echo("No third-party tools registered. Use `tw tools add` to register one.")
        return

    for name, entry in cfg.third_party.items():
        bin_name = entry.bin or name
        installed = shutil.which(bin_name) is not None
        status_icon = "✓" if installed else "✗"
        desc = f"  {entry.description}" if entry.description else ""
        ver = f"  v{entry.version}" if entry.version else ""
        method = f"  [{entry.install.method}:{entry.install.value}]" if entry.install else ""
        req = "  (required)" if entry.required else ""
        click.echo(f"  {status_icon} {name}{ver}{desc}{method}{req}")


@tools_cmd.command("add")
@click.option("--name", required=True, help="Tool identifier (e.g. rtk)")
@click.option("--bin", "bin_name", default=None, help="Binary name on PATH (defaults to --name)")
@click.option("--description", default="", help="Short description")
@click.option("--brew", default=None, help="Homebrew formula name")
@click.option("--url", default=None, help="Direct download URL for the binary")
@click.option("--script", default=None, help="Shell install command (piped to sh)")
@click.option("--path", "local_path", default=None, help="Existing binary path (track only, no auto-install)")
@click.option("--required", is_flag=True, default=False, help="Fail doctor if missing (default: warn)")
def tools_add(
    name: str,
    bin_name: str | None,
    description: str,
    brew: str | None,
    url: str | None,
    script: str | None,
    local_path: str | None,
    required: bool,
) -> None:
    """Register a third-party tool in the workspace registry."""
    from textworkspace.config import ThirdPartyEntry, ThirdPartyInstall, load_config, save_config

    # Determine install method
    install: ThirdPartyInstall | None = None
    if brew:
        install = ThirdPartyInstall(method="brew", value=brew)
    elif url:
        install = ThirdPartyInstall(method="url", value=url)
    elif script:
        install = ThirdPartyInstall(method="script", value=script)
    elif local_path:
        install = ThirdPartyInstall(method="path", value=local_path)

    cfg = load_config()
    entry = ThirdPartyEntry(
        description=description,
        bin=bin_name or name,
        required=required,
        install=install,
    )
    cfg.third_party[name] = entry
    save_config(cfg)

    method_str = f" ({install.method}: {install.value})" if install else " (no install method)"
    click.echo(f"registered: {name}{method_str}")
    click.echo(f"  run `tw tools install {name}` to install it now")


@tools_cmd.command("install")
@click.argument("name", required=False)
def tools_install(name: str | None) -> None:
    """Install one or all missing third-party tools.

    Without NAME, installs all registered tools that aren't on PATH.
    With NAME, installs that specific tool regardless of current state.
    """
    from textworkspace.config import ThirdPartyEntry, ToolEntry, load_config, save_config

    cfg = load_config()
    if not cfg.third_party:
        click.echo("No third-party tools registered. Use `tw tools add` first.")
        return

    to_install: list[tuple[str, ThirdPartyEntry]] = []
    if name:
        if name not in cfg.third_party:
            click.echo(f"tools install: '{name}' not in registry", err=True)
            raise SystemExit(1)
        to_install = [(name, cfg.third_party[name])]
    else:
        for n, e in cfg.third_party.items():
            bin_name = e.bin or n
            if not shutil.which(bin_name):
                to_install.append((n, e))
        if not to_install:
            click.echo("All registered tools are already installed.")
            return

    for tool_name, entry in to_install:
        if not entry.install:
            click.echo(f"  {tool_name}: no install method configured — add one with `tw tools add`")
            continue

        method = entry.install.method
        value = entry.install.value

        if method == "brew":
            click.echo(f"  {tool_name}: brew install {value}")
            result = subprocess.run(["brew", "install", value], check=False)
            ok = result.returncode == 0
        elif method == "script":
            click.echo(f"  {tool_name}: running install script")
            result = subprocess.run(value, shell=True, check=False)  # noqa: S602
            ok = result.returncode == 0
        elif method == "path":
            p = Path(value).expanduser()
            if p.exists():
                click.echo(f"  {tool_name}: found at {p}")
                ok = True
            else:
                click.echo(f"  {tool_name}: path {p} does not exist", err=True)
                ok = False
        elif method == "url":
            click.echo(f"  {tool_name}: downloading from {value}")
            dest = Path.home() / ".local" / "bin" / (entry.bin or tool_name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                ["curl", "-fsSL", "-o", str(dest), value], check=False
            )
            if result.returncode == 0:
                dest.chmod(0o755)
                click.echo(f"  {tool_name}: installed to {dest}")
                ok = True
            else:
                click.echo(f"  {tool_name}: download failed", err=True)
                ok = False
        else:
            click.echo(f"  {tool_name}: unknown install method '{method}'", err=True)
            continue

        if ok:
            bin_path = shutil.which(entry.bin or tool_name)
            ver = _tool_version(tool_name, bin_path) if bin_path else ""
            if ver:
                cfg.third_party[tool_name].version = ver
                click.echo(f"  {tool_name}: ok  {ver}")

    save_config(cfg)


# ---------------------------------------------------------------------------
# tw start / tw stop — workspace lifecycle
# ---------------------------------------------------------------------------


@main.command("start")
@click.argument("workspace")
@click.argument("session_name", required=False, default=None)
@click.option("--profile", default=None, help="Override the workspace's profile.")
def workspace_start(workspace: str, session_name: str | None, profile: str | None) -> None:
    """Start a workspace — profile switch, server start, session open.

    \b
    tw start data                           — start with default session name
    tw start data reporting-orderbook-bug   — start with a custom session name
    tw start data --profile personal        — override the workspace profile
    """
    from textworkspace.workspace import WorkspaceManager

    cfg = load_config()
    WorkspaceManager(cfg).start(workspace, session_name=session_name, profile=profile)


@main.command("stop")
@click.argument("workspace")
def workspace_stop(workspace: str) -> None:
    """Stop a workspace's servers and clear active state.

    Does not revert the active profile.
    """
    from textworkspace.workspace import WorkspaceManager

    cfg = load_config()
    WorkspaceManager(cfg).stop(workspace)


# ---------------------------------------------------------------------------
# tw workspaces group
# ---------------------------------------------------------------------------


@main.group("workspaces", invoke_without_command=True)
@click.pass_context
def workspaces_cmd(ctx: click.Context) -> None:
    """Manage workspace profiles.

    \b
    tw workspaces list    — list all workspaces
    tw workspaces status  — show active workspace
    tw workspaces add     — add a workspace interactively
    tw workspaces edit    — open config.yaml in $EDITOR
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@workspaces_cmd.command("list")
def workspaces_list() -> None:
    """List all configured workspaces."""
    from textworkspace.workspace import WorkspaceManager

    cfg = load_config()
    items = WorkspaceManager(cfg).list()
    if not items:
        click.echo("No workspaces configured. Use `tw workspaces add` to create one.")
        return

    name_w = max(len(w.name) for w in items)
    desc_w = max((len(w.description) for w in items), default=0)
    prof_w = max(len(w.profile) for w in items)

    for ws in items:
        if ws.servers.tags:
            srv = f"tags: {', '.join(ws.servers.tags)}"
        elif ws.servers.names:
            srv = f"names: {', '.join(ws.servers.names)}"
        else:
            srv = "(no servers)"
        click.echo(
            f"  {ws.name:<{name_w}}  {ws.description:<{desc_w}}  {ws.profile:<{prof_w}}  {srv}"
        )


@workspaces_cmd.command("status")
def workspaces_status() -> None:
    """Show the currently active workspace."""
    from textworkspace.workspace import WorkspaceManager

    cfg = load_config()
    state = WorkspaceManager(cfg).status()
    if state is None:
        click.echo("No active workspace.")
        return
    click.echo(f"  active:     {state.get('active_workspace', '?')}")
    click.echo(f"  started_at: {state.get('started_at', '?')}")


def _prompt_pick_list(items: list[str], prompt: str, allow_freetext: bool = True) -> str:
    """Show a numbered pick-list and return the chosen value.

    If items is empty, falls back to a plain free-text prompt.
    Typing a valid number selects that item; any other input is accepted as
    free-text (when allow_freetext is True).
    """
    if not items:
        return click.prompt(prompt, default="")
    click.echo(f"{prompt}:")
    for i, item in enumerate(items, 1):
        click.echo(f"  {i}) {item}")
    if allow_freetext:
        click.echo("  or type a value directly")
    raw = click.prompt("  choice", default="").strip()
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(items):
            return items[idx]
    return raw


@workspaces_cmd.command("add")
def workspaces_add() -> None:
    """Add a new workspace interactively."""
    from textworkspace.config import ServersConfig, WorkspaceConfig

    cfg = load_config()

    name = click.prompt("Workspace name (e.g. data)")
    if name in cfg.workspaces:
        click.echo(f"warning: workspace '{name}' already exists — it will be overwritten")
    description = click.prompt("Description", default="")

    # Profile — pick-list from textaccounts if available (R15, R17)
    profile_choices: list[str] = []
    if _HAS_TEXTACCOUNTS:
        try:
            profile_choices = list_profiles()
        except Exception:
            pass
    profile = _prompt_pick_list(profile_choices, "Profile") if profile_choices else click.prompt("Profile (textaccounts profile name)")

    # Project — pick-list from known repos (R16)
    repo_items = [f"{n}  ({r.path})" for n, r in cfg.repos.items()]
    repo_paths = [r.path for r in cfg.repos.values()]
    if repo_items:
        choice = _prompt_pick_list(repo_items, "Project path (optional)", allow_freetext=True)
        # If user picked a number, resolve to the path; otherwise use as-is
        if choice in repo_items:
            idx = repo_items.index(choice)
            project = repo_paths[idx]
        else:
            project = choice
    else:
        project = click.prompt("Project path (optional)", default="")

    default_session_name = click.prompt("Default session name (optional)", default="")

    srv_type = click.prompt("Servers by (tags/names/none)", default="none")
    servers = ServersConfig()
    if srv_type == "tags":
        raw = click.prompt("Tag(s), comma-separated")
        servers = ServersConfig(tags=[t.strip() for t in raw.split(",") if t.strip()])
    elif srv_type == "names":
        raw = click.prompt("Server name(s), comma-separated")
        servers = ServersConfig(names=[n.strip() for n in raw.split(",") if n.strip()])

    ws = WorkspaceConfig(
        name=name,
        profile=profile,
        servers=servers,
        description=description,
        project=project,
        default_session_name=default_session_name,
    )
    cfg.workspaces[name] = ws
    save_config(cfg)
    click.echo(f"workspace '{name}' added — run: tw start {name}")


@workspaces_cmd.command("edit")
def workspaces_edit() -> None:
    """Open config.yaml in $EDITOR."""
    load_config()
    editor = os.environ.get("EDITOR", "vi")
    subprocess.run([editor, str(CONFIG_FILE)], check=False)


# ---------------------------------------------------------------------------
# forums sub-group
# ---------------------------------------------------------------------------

main.add_command(forums_group, "forums")
