"""Load/save ~/.config/paperworlds/config.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

CONFIG_DIR = Path.home() / ".config" / "paperworlds"
CONFIG_FILE = CONFIG_DIR / "config.yaml"

_DEFAULT_DEFAULTS: dict = {"profile": "default", "proxy_autostart": False}


@dataclass
class ToolEntry:
    version: str = ""
    source: str = "pypi"
    bin: Optional[str] = None


@dataclass
class Config:
    tools: dict[str, ToolEntry] = field(default_factory=dict)
    defaults: dict = field(default_factory=lambda: {"profile": "default", "proxy_autostart": False})


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


def load_config() -> Config:
    if not CONFIG_FILE.exists():
        cfg = Config()
        save_config(cfg)
        return cfg
    with CONFIG_FILE.open() as f:
        raw = yaml.safe_load(f) or {}
    tools = {
        name: _parse_tool(v or {})
        for name, v in (raw.get("tools") or {}).items()
    }
    defaults = raw.get("defaults") or dict(_DEFAULT_DEFAULTS)
    return Config(tools=tools, defaults=defaults)


def save_config(cfg: Config) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data: dict = {
        "tools": {name: _tool_to_dict(t) for name, t in cfg.tools.items()},
        "defaults": cfg.defaults,
    }
    with CONFIG_FILE.open("w") as f:
        yaml.dump(data, f, default_flow_style=False)


def config_as_yaml(cfg: Config) -> str:
    data: dict = {
        "tools": {name: _tool_to_dict(t) for name, t in cfg.tools.items()},
        "defaults": cfg.defaults,
    }
    return yaml.dump(data, default_flow_style=False)
