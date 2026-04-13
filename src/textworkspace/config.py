"""Load/save ~/.config/paperworlds/config.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml

CONFIG_DIR = Path.home() / ".config" / "paperworlds"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    with CONFIG_FILE.open() as f:
        return yaml.safe_load(f) or {}


def save_config(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w") as f:
        yaml.dump(data, f, default_flow_style=False)


def get(key: str, default=None):
    return load_config().get(key, default)


def set_key(key: str, value) -> None:
    data = load_config()
    data[key] = value
    save_config(data)
