"""Go binary download and management."""

from __future__ import annotations

import hashlib
import platform
import tarfile
import tempfile
from pathlib import Path
from typing import Optional

import httpx

GITHUB_API = "https://api.github.com"
GITHUB_ORG = "paperworlds"

# Storage layout: ~/.local/share/textworkspace/{bin,cache}/
DATA_DIR = Path.home() / ".local" / "share" / "textworkspace"
BIN_DIR = DATA_DIR / "bin"
CACHE_DIR = DATA_DIR / "cache"


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

def _os_name() -> str:
    system = platform.system().lower()
    if system == "darwin":
        return "darwin"
    if system == "linux":
        return "linux"
    raise RuntimeError(f"Unsupported OS: {platform.system()}")


def _arch_name() -> str:
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("x86_64", "amd64"):
        return "amd64"
    raise RuntimeError(f"Unsupported architecture: {platform.machine()}")


def platform_slug() -> str:
    """Return platform string like 'darwin-arm64' or 'linux-amd64'."""
    return f"{_os_name()}-{_arch_name()}"


def release_url(tool: str, version: str) -> str:
    """Build the tarball download URL for a given tool and version.

    URL pattern:
    https://github.com/paperworlds/<tool>/releases/download/v<ver>/<tool>-v<ver>-<os>-<arch>.tar.gz
    """
    slug = platform_slug()
    ver = version.lstrip("v")
    filename = f"{tool}-v{ver}-{slug}.tar.gz"
    return f"https://github.com/{GITHUB_ORG}/{tool}/releases/download/v{ver}/{filename}"


def checksum_url(tool: str, version: str) -> str:
    """Build the .sha256 sidecar URL for a given tool and version."""
    slug = platform_slug()
    ver = version.lstrip("v")
    filename = f"{tool}-v{ver}-{slug}.tar.gz.sha256"
    return f"https://github.com/{GITHUB_ORG}/{tool}/releases/download/v{ver}/{filename}"


# ---------------------------------------------------------------------------
# GitHub releases API
# ---------------------------------------------------------------------------

def latest_release(repo: str) -> dict:
    """Fetch the latest release metadata for a GitHub repo (owner/repo)."""
    url = f"{GITHUB_API}/repos/{repo}/releases/latest"
    response = httpx.get(url, follow_redirects=True)
    response.raise_for_status()
    return response.json()


def latest_version(tool: str) -> str:
    """Return the latest release tag (e.g. 'v0.2.0') for a tool."""
    meta = latest_release(f"{GITHUB_ORG}/{tool}")
    return meta["tag_name"]


# ---------------------------------------------------------------------------
# Download and verify
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def download_binary(tool: str, version: str, *, client: Optional[httpx.Client] = None) -> Path:
    """Download, verify, and extract a tool binary into the cache directory.

    Returns the directory where the binary was extracted:
        ~/.local/share/textworkspace/cache/<tool>-v<ver>-<slug>/

    Raises ValueError on checksum mismatch.
    """
    ver = version.lstrip("v")
    slug = platform_slug()
    cache_entry = CACHE_DIR / f"{tool}-v{ver}-{slug}"

    if cache_entry.exists():
        # Already cached — return immediately.
        return cache_entry

    tar_url = release_url(tool, ver)
    sha_url = checksum_url(tool, ver)

    close_client = False
    if client is None:
        client = httpx.Client(follow_redirects=True)
        close_client = True

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            # Download tarball (streaming)
            tar_path = tmp / f"{tool}.tar.gz"
            with client.stream("GET", tar_url) as resp:
                resp.raise_for_status()
                with tar_path.open("wb") as f:
                    for chunk in resp.iter_bytes(65536):
                        f.write(chunk)

            # Download sha256 sidecar
            sha_resp = client.get(sha_url)
            sha_resp.raise_for_status()
            expected_hash = sha_resp.text.split()[0].strip().lower()

            # Verify checksum
            actual_hash = _sha256_file(tar_path)
            if actual_hash != expected_hash:
                raise ValueError(
                    f"Checksum mismatch for {tool} v{ver}: "
                    f"expected {expected_hash}, got {actual_hash}"
                )

            # Extract to cache
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with tarfile.open(tar_path) as tf:
                tf.extractall(cache_entry)  # noqa: S202 — trusted source after sha256 verify

    finally:
        if close_client:
            client.close()

    return cache_entry


# ---------------------------------------------------------------------------
# Symlink management
# ---------------------------------------------------------------------------

def _versioned_cache_dirs(tool: str) -> list[Path]:
    """Return existing cache dirs for *tool*, sorted oldest-first."""
    if not CACHE_DIR.exists():
        return []
    prefix = f"{tool}-v"
    dirs = [d for d in CACHE_DIR.iterdir() if d.is_dir() and d.name.startswith(prefix)]
    dirs.sort(key=lambda p: p.name)
    return dirs


def install_binary(tool: str, version: str) -> Path:
    """Install a binary from the cache into the bin dir via symlink.

    - Creates ~/.local/share/textworkspace/bin/<tool> → ../cache/<entry>/<tool>
    - Keeps at most ONE previous version; deletes anything older.

    Returns the symlink path.
    """
    ver = version.lstrip("v")
    slug = platform_slug()
    cache_entry = CACHE_DIR / f"{tool}-v{ver}-{slug}"

    if not cache_entry.exists():
        raise FileNotFoundError(
            f"Cache entry not found: {cache_entry}. "
            "Run download_binary() first."
        )

    binary_in_cache = cache_entry / tool
    if not binary_in_cache.exists():
        raise FileNotFoundError(f"Binary not found in cache: {binary_in_cache}")

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    symlink = BIN_DIR / tool

    # Atomically replace symlink
    if symlink.exists() or symlink.is_symlink():
        symlink.unlink()
    symlink.symlink_to(binary_in_cache)

    # Prune old versions: keep at most 1 previous (i.e. total of 2 cache entries)
    all_dirs = _versioned_cache_dirs(tool)
    # Remove the current entry from consideration
    old_dirs = [d for d in all_dirs if d != cache_entry]
    # Keep the most recent previous; delete the rest
    to_delete = old_dirs[:-1] if len(old_dirs) > 1 else []
    for old in to_delete:
        import shutil
        shutil.rmtree(old, ignore_errors=True)

    return symlink
