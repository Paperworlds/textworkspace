"""Tool detection and health-check diagnostics for textworkspace."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from textworkspace.config import get_textproxy_port

_FISH_FUNCTIONS_DIR = Path.home() / ".config" / "fish" / "functions"

_PYPI_TOOLS = ("textaccounts", "textsessions")
_GO_TOOLS = ("textproxy", "textserve")


# ---------------------------------------------------------------------------
# Tool detection
# ---------------------------------------------------------------------------


@dataclass
class ToolInfo:
    name: str
    installed: bool = False
    version: Optional[str] = None
    source: Optional[str] = None  # "pypi", "github", "path"
    bin_path: Optional[str] = None
    importable: bool = False


def detect_installed_tools() -> dict[str, ToolInfo]:
    """Detect installed tools, versions, and sources.

    Checks PATH, Python import availability, managed binary dir, and config.
    Returns a dict keyed by tool name in dependency order.
    """
    from textworkspace.bootstrap import BIN_DIR
    from textworkspace.config import load_config

    result: dict[str, ToolInfo] = {}

    for name in _PYPI_TOOLS:
        result[name] = _detect_python_tool(name)

    for name in _GO_TOOLS:
        result[name] = _detect_go_tool(name, bin_dir=BIN_DIR, load_config=load_config)

    return result


def _detect_python_tool(name: str) -> ToolInfo:
    from textworkspace.config import load_config

    info = ToolInfo(name=name)

    # Check importability (normalise hyphens to underscores)
    module_name = name.replace("-", "_")
    try:
        spec = importlib.util.find_spec(module_name)
        if spec is not None:
            info.importable = True
            info.installed = True
            info.source = "pypi"
    except (ImportError, ModuleNotFoundError, ValueError):
        pass

    # Binary on PATH
    bin_path = shutil.which(name)
    if bin_path:
        info.bin_path = bin_path
        if not info.installed:
            info.installed = True
            info.source = "path"

    # Config may override source (e.g. "dev" from tw dev on/reinstall)
    try:
        cfg = load_config()
        entry = cfg.tools.get(name)
        if entry and entry.source:
            info.source = entry.source
    except Exception:  # noqa: BLE001
        pass

    # Prefer binary --version over importlib.metadata (metadata can be stale
    # when tools are installed as uv tools with independent venvs)
    if info.bin_path:
        _try_version_from_binary(info)

    # Fall back to importlib.metadata if binary didn't yield a version
    if info.installed and not info.version:
        try:
            info.version = importlib.metadata.version(name)
        except Exception:  # noqa: BLE001
            pass

    return info


def _detect_go_tool(name: str, *, bin_dir: Path, load_config) -> ToolInfo:
    info = ToolInfo(name=name)

    # Check managed bin dir (our GitHub-downloaded binaries)
    managed = bin_dir / name
    if managed.exists():
        info.installed = True
        info.source = "github"
        info.bin_path = str(managed)

    # Check PATH (may override with system-wide install)
    bin_path = shutil.which(name)
    if bin_path:
        info.installed = True
        info.bin_path = bin_path
        if not info.source:
            info.source = "path"

    # Pull version and extra detail from config
    try:
        cfg = load_config()
        entry = cfg.tools.get(name)
        if entry:
            if entry.version:
                info.version = entry.version
            if entry.source:
                info.source = entry.source
            if entry.bin:
                p = Path(entry.bin).expanduser()
                if p.exists() and not info.bin_path:
                    info.bin_path = str(p)
                if not info.installed:
                    info.installed = p.exists()
    except Exception:  # noqa: BLE001
        pass

    # Last-resort: ask the binary for its version
    if info.installed and info.bin_path and not info.version:
        _try_version_from_binary(info)

    return info


def _try_version_from_binary(info: ToolInfo) -> None:
    try:
        res = subprocess.run(
            [info.bin_path, "--version"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        output = res.stdout + res.stderr
        for word in output.split():
            # Match "v0.1.3" or "0.6.0" — strip leading v if present
            clean = word.rstrip(",")
            if clean and clean[0].isdigit() and "." in clean:
                info.version = clean
                break
            if clean.startswith("v") and len(clean) > 1 and clean[1].isdigit():
                info.version = clean.lstrip("v")
                break
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Doctor checks
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    label: str
    detail: str
    status: str  # "ok", "warn", "fail"
    fix: Optional[str] = None


def run_doctor_checks() -> list[CheckResult]:
    """Run all doctor checks and return structured results."""
    from textworkspace.bootstrap import BIN_DIR
    from textworkspace.combos import COMBOS_DIR, COMBOS_FILE, load_combos
    from textworkspace.config import CONFIG_FILE, load_config

    results: list[CheckResult] = []

    # --- textworkspace itself ---
    from textworkspace import __version__ as tw_version
    results.append(CheckResult(label="textworkspace", detail=f"{tw_version}", status="ok"))

    tools = detect_installed_tools()

    # --- Per-tool checks ---
    _optional_tools = {"textproxy", "textserve"}
    for name, info in tools.items():
        if info.installed:
            ver = info.version or "?"
            src = info.source or "unknown"
            src_str = "via github binary" if src == "github" else f"via {src}"
            results.append(CheckResult(label=name, detail=f"{ver} {src_str}", status="ok"))
        else:
            fix = f"pip install {name}" if name in _PYPI_TOOLS else f"tw update {name}"
            status = "warn" if name in _optional_tools else "fail"
            results.append(CheckResult(label=name, detail="not installed", status=status, fix=fix))

    # --- Config check ---
    cfg = None
    if CONFIG_FILE.exists():
        try:
            cfg = load_config()
            missing_bins = [
                n for n, e in cfg.tools.items()
                if e.bin and not Path(e.bin).expanduser().exists()
            ]
            if missing_bins:
                results.append(CheckResult(
                    label="config",
                    detail=str(CONFIG_FILE).replace(str(Path.home()), "~"),
                    status="warn",
                    fix=f"run: tw update {missing_bins[0]}",
                ))
            else:
                results.append(CheckResult(
                    label="config",
                    detail=str(CONFIG_FILE).replace(str(Path.home()), "~"),
                    status="ok",
                ))
        except Exception as exc:  # noqa: BLE001
            results.append(CheckResult(
                label="config",
                detail=f"invalid: {exc}",
                status="fail",
                fix=f"edit: {CONFIG_FILE}",
            ))
    else:
        results.append(CheckResult(label="config", detail="not found", status="warn", fix="run: tw init"))

    # --- Combos check ---
    try:
        combos = load_combos()
        installed_count = len(list(COMBOS_DIR.glob("*.yaml"))) if COMBOS_DIR.exists() else 0
        user_count = max(0, len(combos) - installed_count)
        results.append(CheckResult(
            label="combos",
            detail=f"{user_count} user + {installed_count} installed",
            status="ok",
        ))
    except Exception as exc:  # noqa: BLE001
        results.append(CheckResult(
            label="combos",
            detail=f"error: {exc}",
            status="fail",
            fix=f"check {COMBOS_FILE}",
        ))

    # --- Fish functions check ---
    # tw is the only fish function needed (for __TW_EVAL__ protocol);
    # xtw, ta, xta are binary entry points, not fish functions.
    if (_FISH_FUNCTIONS_DIR / "tw.fish").exists():
        results.append(CheckResult(label="fish", detail="tw.fish installed", status="ok"))
    else:
        results.append(CheckResult(
            label="fish", detail="tw.fish not found", status="warn",
            fix="run: tw shell install --fish",
        ))

    # --- Third-party tools check ---
    try:
        for tool_name, entry in (cfg.third_party if cfg else {}).items():
            bin_name = entry.bin or tool_name
            on_path = shutil.which(bin_name) is not None
            if on_path:
                # Try to get version
                ver = ""
                if entry.version:
                    ver = entry.version
                else:
                    info = ToolInfo(name=tool_name, installed=True, bin_path=shutil.which(bin_name))
                    _try_version_from_binary(info)
                    ver = info.version or ""
                ver_str = f"v{ver}  " if ver else ""
                results.append(CheckResult(label=tool_name, detail=f"{ver_str}(third-party)", status="ok"))
            else:
                install_hint = ""
                if entry.install:
                    install_hint = f"  hint: {entry.install.method} {entry.install.value}"
                status = "fail" if entry.required else "warn"
                results.append(CheckResult(
                    label=tool_name,
                    detail=f"not installed{install_hint}",
                    status=status,
                    fix=f"run: tw tools install {tool_name}",
                ))
    except Exception:  # noqa: BLE001
        pass

    # --- Proxy check ---
    proxy_port = get_textproxy_port()
    if _is_port_responding(proxy_port):
        results.append(CheckResult(label="proxy", detail=f":{proxy_port} responding", status="ok"))
    else:
        tp = tools.get("textproxy")
        if tp and tp.installed:
            results.append(CheckResult(
                label="proxy",
                detail=f":{proxy_port} not responding",
                status="warn",
                fix="run: textproxy start",
            ))
        else:
            results.append(CheckResult(
                label="proxy", detail="not installed", status="warn", fix="run: tw update textproxy",
            ))

    # --- Servers check ---
    ts_info = tools.get("textserve")
    if ts_info and ts_info.installed:
        registry_paths = [
            Path.home() / ".config" / "paperworlds" / "registry.yaml",
            Path.home() / ".textserve" / "registry.yaml",
        ]
        if any(p.exists() for p in registry_paths):
            results.append(CheckResult(label="servers", detail="textserve installed, registry found", status="ok"))
        else:
            results.append(CheckResult(
                label="servers",
                detail="textserve installed, no registry.yaml",
                status="warn",
                fix="create ~/.config/paperworlds/registry.yaml",
            ))
    else:
        results.append(CheckResult(
            label="servers", detail="textserve not installed", status="warn", fix="run: tw init",
        ))

    return results


def _is_port_responding(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
