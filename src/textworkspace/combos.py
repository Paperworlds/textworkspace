"""Combo loading and execution engine."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_combos(path: Path) -> list[dict[str, Any]]:
    """Load combo definitions from a YAML file."""
    if not path.exists():
        return []
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return data.get("combos", [])


def run_combo(combo: dict[str, Any]) -> None:
    """Execute a single combo definition."""
    raise NotImplementedError("combo execution not yet implemented")
