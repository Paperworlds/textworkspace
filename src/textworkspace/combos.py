"""Combo loading and execution engine."""

from __future__ import annotations

import os
import shlex
import socket
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

import click
import yaml

from textworkspace.config import CONFIG_DIR, get_textproxy_port

COMBOS_FILE = CONFIG_DIR / "combos.yaml"
COMBOS_DIR = CONFIG_DIR / "combos.d"

COMMUNITY_REPO = "paperworlds/textcombos"
_GH_RAW_BASE = "https://raw.githubusercontent.com"
_GH_API_BASE = "https://api.github.com"

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

  go:
    description: Switch profile, ensure servers, launch Claude session
    builtin: true
    args: [profile, repo]
    options:
      servers: true
      tmux: false
      name: ""
    steps:
      - run: switch {profile}
      - shell: textserve start --tag {profile}
        only_if: options.servers
      - shell: textsessions new -r {repo} -p {profile} -n {name}
      - shell: tmux new-window -n {name}
        only_if: options.tmux

  sync:
    description: Reinstall all dev tools from local repos
    builtin: true
    steps:
      - run: dev install
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


def evaluate_condition(
    condition: str,
    *,
    options: dict[str, Any] | None = None,
) -> bool:
    """Return True if *condition* holds.

    Supported vocabulary:
      proxy.running          — textproxy is accepting connections
      proxy.stopped          — textproxy is not reachable
      servers.running        — at least one textserve server is running
      servers.none_running   — no textserve servers are running
      accounts.active <name> — TW_PROFILE env var equals <name>
      options.<key>          — truthy check on resolved combo option
    """
    parts = condition.strip().split(None, 1)
    key = parts[0]
    arg = parts[1] if len(parts) > 1 else None

    if key.startswith("options."):
        opt_key = key[len("options."):]
        if options is None:
            return False
        val = options.get(opt_key, False)
        # Falsy: False, 0, "", "false", "no", "0", None
        if isinstance(val, str):
            return val.lower() not in ("", "false", "no", "0")
        return bool(val)

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
        with socket.create_connection(("127.0.0.1", get_textproxy_port()), timeout=1):
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


def resolve_options(
    name: str,
    defn: dict[str, Any],
    cli_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve combo options: combo defaults < config overrides < CLI flags."""
    defaults = defn.get("options", {})
    resolved = dict(defaults)

    # Config-level overrides: combos.<name>.<key> in config.yaml
    try:
        from textworkspace.config import load_config
        cfg = load_config()
        config_combos = cfg.defaults.get("combos", {})
        if isinstance(config_combos, dict) and name in config_combos:
            combo_cfg = config_combos[name]
            if isinstance(combo_cfg, dict):
                resolved.update(combo_cfg)
    except Exception:  # noqa: BLE001
        pass

    # CLI flag overrides (highest priority)
    if cli_overrides:
        resolved.update(cli_overrides)

    return resolved


def run_combo(
    name: str,
    defn: dict[str, Any],
    args_map: dict[str, str],
    *,
    dry_run: bool = False,
    continue_on_error: bool = False,
    options: dict[str, Any] | None = None,
) -> int:
    """Execute combo *name*.  Returns 0 on success, non-zero on first failure."""
    steps = defn.get("steps", [])
    if not steps:
        click.echo(f"combo '{name}': no steps defined")
        return 0

    if options is None:
        options = resolve_options(name, defn)

    # Merge options into args_map for interpolation
    full_args = dict(args_map)
    for k, v in options.items():
        if k not in full_args:
            full_args[k] = str(v)

    if dry_run:
        click.echo(f"[dry-run] combo: {name}")
        if options:
            click.echo(f"  options: {options}")

    failed = 0
    for i, step in enumerate(steps, 1):
        # Support both run: (tw subcommand) and shell: (external command)
        is_shell = "shell" in step
        raw_cmd = step.get("shell") or step.get("run", "")
        cmd_str = _interpolate(raw_cmd, full_args)
        skip_if = step.get("skip_if")
        only_if = step.get("only_if")

        skip = False
        reason = ""

        if skip_if:
            if evaluate_condition(skip_if, options=options):
                skip = True
                reason = f"skip_if '{skip_if}' is true"

        if not skip and only_if:
            if not evaluate_condition(only_if, options=options):
                skip = True
                reason = f"only_if '{only_if}' is false"

        if dry_run:
            prefix = "shell" if is_shell else "run"
            status = "SKIP" if skip else "RUN"
            note = f"  ({reason})" if reason else ""
            click.echo(f"  step {i}: {prefix}: {cmd_str}  [{status}]{note}")
            continue

        if skip:
            click.echo(f"  step {i}: {cmd_str}  [skipped — {reason}]")
            continue

        click.echo(f"  step {i}: {cmd_str}")
        if is_shell:
            proc = subprocess.run(shlex.split(cmd_str))
        else:
            proc = subprocess.run(["textworkspace"] + shlex.split(cmd_str))
        if proc.returncode != 0:
            click.echo(f"  step {i}: failed (exit {proc.returncode})", err=True)
            failed += 1
            if not continue_on_error:
                return proc.returncode

    return 1 if (failed and continue_on_error) else 0


# ---------------------------------------------------------------------------
# Sharing helpers — fetch, install, export, update, search
# ---------------------------------------------------------------------------


def _fetch_url(url: str) -> str:
    """Fetch raw text content from a URL."""
    import httpx

    resp = httpx.get(url, timeout=10, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def _source_to_url(source: str) -> str:
    """Convert a gh: source spec to a raw GitHub URL."""
    if not source.startswith("gh:"):
        raise ValueError(f"Not a gh: source: {source}")
    path = source[3:]  # strip "gh:"
    parts = path.split("/")
    if len(parts) < 3:
        raise ValueError(f"gh: source must be gh:org/repo/name, got: {source}")
    org, repo = parts[0], parts[1]
    name = "/".join(parts[2:])
    if not name.endswith(".yaml"):
        name = f"{name}.yaml"
    return f"{_GH_RAW_BASE}/{org}/{repo}/main/{name}"


def _parse_standalone(raw: str) -> dict[str, Any]:
    """Parse a standalone combo YAML.  Must have 'name' and 'steps'."""
    data = yaml.safe_load(raw) or {}
    if "name" not in data:
        raise ValueError("Combo YAML missing required 'name' field")
    if "steps" not in data:
        raise ValueError("Combo YAML missing required 'steps' field")
    return data


def install_combo(source: str, raw_yaml: str) -> str:
    """Install a combo from raw YAML string.  Returns the installed combo name."""
    data = _parse_standalone(raw_yaml)
    name: str = data["name"]

    # Warn about missing requires
    requires: list[str] = data.get("requires", [])
    if requires:
        from textworkspace.config import load_config

        cfg = load_config()
        missing = [r for r in requires if r not in cfg.tools]
        if missing:
            click.echo(
                f"  warning: missing required tools: {', '.join(missing)}"
                " — install them before using this combo",
                err=True,
            )

    # Build combo definition (strip standalone-only fields)
    _standalone_keys = {"name", "author", "tags", "requires"}
    combo_defn: dict[str, Any] = {k: v for k, v in data.items() if k not in _standalone_keys}

    # Preserve useful fields in the definition
    if "author" in data:
        combo_defn.setdefault("description", data.get("description", ""))
    if "tags" in data:
        combo_defn["tags"] = data["tags"]
    if "requires" in data:
        combo_defn["requires"] = data["requires"]

    # Wrap with metadata
    file_data: dict[str, Any] = {
        "_source": source,
        "_installed": date.today().isoformat(),
        "_modified": False,
        "combos": {name: combo_defn},
    }

    COMBOS_DIR.mkdir(parents=True, exist_ok=True)
    dest = COMBOS_DIR / f"{name}.yaml"
    with dest.open("w") as f:
        yaml.dump(file_data, f, default_flow_style=False, allow_unicode=True)

    return name


def export_combo(name: str) -> str:
    """Return standalone YAML for a named combo from combos.d."""
    path = COMBOS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Installed combo '{name}' not found in combos.d/")

    with path.open() as f:
        file_data = yaml.safe_load(f) or {}

    combos_section = file_data.get("combos", {})
    defn = combos_section.get(name)
    if defn is None:
        # Try to find any combo in the file
        if combos_section:
            defn = next(iter(combos_section.values()))
        else:
            raise ValueError(f"No combo definition found in {path}")

    # Build standalone format
    standalone: dict[str, Any] = {"name": name}
    for key in ("description", "author", "tags", "requires", "args", "steps"):
        if key in defn:
            standalone[key] = defn[key]
    # Include any extra fields
    for key, val in defn.items():
        if key not in standalone:
            standalone[key] = val

    return yaml.dump(standalone, default_flow_style=False, allow_unicode=True)


def list_installed_combos() -> list[tuple[str, dict[str, Any]]]:
    """Return (name, file_data) pairs for all installed combos in combos.d."""
    if not COMBOS_DIR.exists():
        return []
    result = []
    for path in sorted(COMBOS_DIR.glob("*.yaml")):
        with path.open() as f:
            file_data = yaml.safe_load(f) or {}
        if "_source" in file_data:
            name = path.stem
            result.append((name, file_data))
    return result


def update_combo(name: str, file_data: dict[str, Any]) -> str:
    """Re-fetch and reinstall a combo.  Returns 'updated', 'skipped', or 'error:<msg>'."""
    source: str = file_data.get("_source", "")
    if not source:
        return "error:no _source"

    if file_data.get("_modified", False):
        return "skipped"

    try:
        if source.startswith("gh:"):
            url = _source_to_url(source)
            raw = _fetch_url(url)
        elif source.startswith(("http://", "https://")):
            raw = _fetch_url(source)
        else:
            # local file
            local = Path(source)
            if not local.exists():
                return f"error:local file not found: {source}"
            raw = local.read_text()
    except Exception as exc:  # noqa: BLE001
        return f"error:{exc}"

    try:
        install_combo(source, raw)
    except Exception as exc:  # noqa: BLE001
        return f"error:{exc}"

    return "updated"


def search_community(query: str) -> list[dict[str, Any]]:
    """Search community repo for combos matching query string."""
    import httpx

    url = f"{_GH_API_BASE}/repos/{COMMUNITY_REPO}/contents/"
    try:
        resp = httpx.get(
            url,
            timeout=10,
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        resp.raise_for_status()
        items = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Could not reach community repo: {exc}") from exc

    query_lower = query.lower()
    results: list[dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        if not item.get("name", "").endswith(".yaml"):
            continue
        download_url = item.get("download_url")
        if not download_url:
            continue
        try:
            raw = _fetch_url(download_url)
            data = yaml.safe_load(raw) or {}
        except Exception:  # noqa: BLE001
            continue

        combo_name = data.get("name", item["name"].removesuffix(".yaml"))
        desc = data.get("description", "")
        tags = data.get("tags", [])
        tags_str = " ".join(tags) if isinstance(tags, list) else str(tags)

        haystack = f"{combo_name} {desc} {tags_str}".lower()
        if query_lower in haystack:
            results.append(
                {
                    "name": combo_name,
                    "description": desc,
                    "tags": tags if isinstance(tags, list) else [],
                    "author": data.get("author", ""),
                    "requires": data.get("requires", []),
                }
            )

    return results


def fetch_community_info(name: str) -> dict[str, Any]:
    """Fetch a named combo's info from the community repo."""
    url = f"{_GH_RAW_BASE}/{COMMUNITY_REPO}/main/{name}.yaml"
    try:
        raw = _fetch_url(url)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Could not fetch '{name}' from community repo: {exc}") from exc
    return yaml.safe_load(raw) or {}
