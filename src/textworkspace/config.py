"""Load/save ~/.config/paperworlds/config.yaml."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

CONFIG_DIR = Path.home() / ".config" / "paperworlds"
CONFIG_FILE = CONFIG_DIR / "config.yaml"

_DEFAULT_DEFAULTS: dict = {"profile": "default", "proxy_autostart": False, "mode": "user"}

STATE_DIR = Path.home() / ".local" / "state" / "paperworlds"

_TEXTPROXY_DEFAULT_PORT = 9880
_TEXTPROXY_CONFIG = Path.home() / ".config" / "textproxy" / "config.json"


def get_textproxy_port() -> int:
    try:
        data = json.loads(_TEXTPROXY_CONFIG.read_text())
        return int(data["port"])
    except (OSError, ValueError, TypeError):
        return _TEXTPROXY_DEFAULT_PORT


@dataclass
class RepoEntry:
    path: str
    label: str = ""
    profile: str = ""


@dataclass
class SharedDirs:
    state: str = str(Path.home() / ".local" / "state" / "paperworlds")
    cache: str = str(Path.home() / ".cache" / "paperworlds")


@dataclass
class ToolEntry:
    version: str = ""
    source: str = "pypi"
    bin: Optional[str] = None


@dataclass
class ThirdPartyInstall:
    """Install method for a third-party tool."""
    method: str  # "brew", "url", "script", "path" (path = just track, no auto-install)
    value: str   # formula name, download URL, shell command, or binary path


@dataclass
class ThirdPartyEntry:
    """A third-party tool tracked in the workspace registry."""
    description: str = ""
    bin: str = ""           # binary name to check on PATH (e.g. "rtk")
    required: bool = False  # if True → doctor fails; if False → doctor warns
    install: Optional[ThirdPartyInstall] = None
    version: str = ""       # last known version, populated by tw tools install


@dataclass
class Config:
    repos: dict[str, RepoEntry] = field(default_factory=dict)
    dirs: SharedDirs = field(default_factory=SharedDirs)
    tools: dict[str, ToolEntry] = field(default_factory=dict)
    defaults: dict = field(default_factory=lambda: {"profile": "default", "proxy_autostart": False, "mode": "user"})
    forums: dict = field(default_factory=dict)
    third_party: dict[str, ThirdPartyEntry] = field(default_factory=dict)


def _parse_repo(data: dict) -> RepoEntry:
    return RepoEntry(
        path=data.get("path", ""),
        label=data.get("label", ""),
        profile=data.get("profile", ""),
    )


def _repo_to_dict(r: RepoEntry) -> dict:
    d: dict = {"path": r.path}
    if r.label:
        d["label"] = r.label
    if r.profile:
        d["profile"] = r.profile
    return d


def _parse_dirs(data: dict) -> SharedDirs:
    defaults = SharedDirs()
    return SharedDirs(
        state=data.get("state", defaults.state),
        cache=data.get("cache", defaults.cache),
    )


def _dirs_to_dict(d: SharedDirs) -> dict:
    return {"state": d.state, "cache": d.cache}


def _parse_tool(data: dict) -> ToolEntry:
    return ToolEntry(
        version=data.get("version", ""),
        source=data.get("source", "pypi"),
        bin=data.get("bin"),
    )


def _tool_to_dict(t: ToolEntry) -> dict:
    d: dict = {"version": t.version, "source": t.source}
    if t.bin:
        d["bin"] = t.bin
    return d


def _parse_third_party(data: dict) -> ThirdPartyEntry:
    install: Optional[ThirdPartyInstall] = None
    raw_install = data.get("install") or {}
    if raw_install:
        # First key is the method (brew, url, script, path)
        for method in ("brew", "url", "script", "path"):
            if method in raw_install:
                install = ThirdPartyInstall(method=method, value=str(raw_install[method]))
                break
    return ThirdPartyEntry(
        description=data.get("description", ""),
        bin=data.get("bin", ""),
        required=bool(data.get("required", False)),
        install=install,
        version=data.get("version", ""),
    )


def _third_party_to_dict(e: ThirdPartyEntry) -> dict:
    d: dict = {}
    if e.description:
        d["description"] = e.description
    if e.bin:
        d["bin"] = e.bin
    if e.required:
        d["required"] = True
    if e.install:
        d["install"] = {e.install.method: e.install.value}
    if e.version:
        d["version"] = e.version
    return d


def _config_to_dict(cfg: Config) -> dict:
    data: dict = {}
    if cfg.repos:
        data["repos"] = {name: _repo_to_dict(r) for name, r in cfg.repos.items()}
    data["dirs"] = _dirs_to_dict(cfg.dirs)
    data["tools"] = {name: _tool_to_dict(t) for name, t in cfg.tools.items()}
    data["defaults"] = cfg.defaults
    if cfg.forums:
        data["forums"] = cfg.forums
    if cfg.third_party:
        data["third_party"] = {name: _third_party_to_dict(e) for name, e in cfg.third_party.items()}
    return data


def load_config() -> Config:
    if not CONFIG_FILE.exists():
        cfg = Config()
        save_config(cfg)
        return cfg
    with CONFIG_FILE.open() as f:
        raw = yaml.safe_load(f) or {}
    repos = {
        name: _parse_repo(v or {})
        for name, v in (raw.get("repos") or {}).items()
    }
    dirs = _parse_dirs(raw.get("dirs") or {})
    tools = {
        name: _parse_tool(v or {})
        for name, v in (raw.get("tools") or {}).items()
    }
    defaults = raw.get("defaults") or dict(_DEFAULT_DEFAULTS)
    forums = raw.get("forums") or {}
    third_party = {
        name: _parse_third_party(v or {})
        for name, v in (raw.get("third_party") or {}).items()
    }
    return Config(repos=repos, dirs=dirs, tools=tools, defaults=defaults, forums=forums, third_party=third_party)


def save_config(cfg: Config) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w") as f:
        yaml.dump(_config_to_dict(cfg), f, default_flow_style=False)


def config_as_yaml(cfg: Config) -> str:
    return yaml.dump(_config_to_dict(cfg), default_flow_style=False)
