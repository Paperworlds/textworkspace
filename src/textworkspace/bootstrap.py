"""Go binary download and management."""

from __future__ import annotations

import httpx

GITHUB_API = "https://api.github.com"


def latest_release(repo: str) -> dict:
    """Fetch the latest release metadata for a GitHub repo (owner/repo)."""
    url = f"{GITHUB_API}/repos/{repo}/releases/latest"
    response = httpx.get(url, follow_redirects=True)
    response.raise_for_status()
    return response.json()


def download_binary(url: str, dest: str) -> None:
    """Download a binary from url to dest path."""
    raise NotImplementedError("binary download not yet implemented")
