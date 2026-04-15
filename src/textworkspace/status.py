"""Unified status display for the Paperworlds stack."""

from __future__ import annotations

import shutil
import socket
import subprocess
from typing import Optional


def _textproxy_status() -> dict:
    """Return proxy status dict: {running, pid, port, version, detail}."""
    binary = shutil.which("textproxy")
    if binary is None:
        return {"running": False, "detail": "not installed"}

    try:
        result = subprocess.run(
            [binary, "status"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        line = (result.stdout + result.stderr).strip()
        if line.startswith("running"):
            # "running  pid=1234  port=9880  version=0.2.0"
            parts = dict(p.split("=") for p in line.split() if "=" in p)
            return {
                "running": True,
                "pid": int(parts.get("pid", 0)),
                "port": int(parts.get("port", 0)),
                "version": parts.get("version", ""),
                "detail": line,
            }
        return {"running": False, "detail": line}
    except Exception as exc:  # noqa: BLE001
        return {"running": False, "detail": f"error: {exc}"}


def get_status() -> dict:
    """Return a dict of component → status info."""
    return {
        "proxy": _textproxy_status(),
    }


def print_status() -> None:
    """Print unified stack status to stdout."""
    s = get_status()
    proxy = s["proxy"]
    if proxy["running"]:
        port = proxy.get("port", "?")
        ver = proxy.get("version", "")
        ver_part = f"  v{ver}" if ver else ""
        print(f"  proxy  running :{port}{ver_part}")
    else:
        print(f"  proxy  {proxy['detail']}")
