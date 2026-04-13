"""Load/save ~/.config/paperworlds/config.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

CONFIG_DIR = Path.home() / ".config" / "paperworlds"
CONFIG_FILE = CONFIG_DIR / "config.yaml"

_DEFAULT_DEFAULTS: dict = {"profile": "default", "proxy_autostart": False}

STATE_DIR = Path.home() / ".local" / "state" / "paperworlds"


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
class Config:
    repos: dict[str, RepoEntry] = field(default_factory=dict)
    dirs: SharedDirs = field(default_factory=SharedDirs)
    tools: dict[str, ToolEntry] = field(default_factory=dict)
    defaults: dict = field(default_factory=lambda: {"profile": "default", "proxy_autostart": False})


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


def _config_to_dict(cfg: Config) -> dict:
    data: dict = {}
    if cfg.repos:
        data["repos"] = {name: _repo_to_dict(r) for name, r in cfg.repos.items()}
    data["dirs"] = _dirs_to_dict(cfg.dirs)
    data["tools"] = {name: _tool_to_dict(t) for name, t in cfg.tools.items()}
    data["defaults"] = cfg.defaults
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
    return Config(repos=repos, dirs=dirs, tools=tools, defaults=defaults)


def save_config(cfg: Config) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w") as f:
        yaml.dump(_config_to_dict(cfg), f, default_flow_style=False)


def config_as_yaml(cfg: Config) -> str:
    return yaml.dump(_config_to_dict(cfg), default_flow_style=False)
