"""Tests for bootstrap.py — platform detection, URL building, symlink management."""

from __future__ import annotations

import hashlib
import io
import sys
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from textworkspace.bootstrap import (
    _sha256_file,
    _versioned_cache_dirs,
    checksum_url,
    download_binary,
    install_binary,
    platform_slug,
    release_url,
)


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

def test_platform_slug_darwin_arm64():
    with patch("platform.system", return_value="Darwin"), \
         patch("platform.machine", return_value="arm64"):
        assert platform_slug() == "darwin-arm64"


def test_platform_slug_linux_amd64():
    with patch("platform.system", return_value="Linux"), \
         patch("platform.machine", return_value="x86_64"):
        assert platform_slug() == "linux-amd64"


def test_platform_slug_linux_arm64():
    with patch("platform.system", return_value="Linux"), \
         patch("platform.machine", return_value="aarch64"):
        assert platform_slug() == "linux-arm64"


def test_platform_slug_unsupported_os():
    with patch("platform.system", return_value="Windows"):
        with pytest.raises(RuntimeError, match="Unsupported OS"):
            platform_slug()


def test_platform_slug_unsupported_arch():
    with patch("platform.system", return_value="Linux"), \
         patch("platform.machine", return_value="i686"):
        with pytest.raises(RuntimeError, match="Unsupported architecture"):
            platform_slug()


# ---------------------------------------------------------------------------
# URL building
# ---------------------------------------------------------------------------

def test_release_url_darwin_arm64():
    with patch("platform.system", return_value="Darwin"), \
         patch("platform.machine", return_value="arm64"):
        url = release_url("textproxy", "0.2.0")
    assert url == (
        "https://github.com/paperworlds/textproxy/releases/download/v0.2.0/"
        "textproxy-v0.2.0-darwin-arm64.tar.gz"
    )


def test_release_url_strips_v_prefix():
    with patch("platform.system", return_value="Linux"), \
         patch("platform.machine", return_value="x86_64"):
        url = release_url("textserve", "v1.3.0")
    assert "v1.3.0" in url
    assert url.endswith("textserve-v1.3.0-linux-amd64.tar.gz")


def test_checksum_url_has_sha256_suffix():
    with patch("platform.system", return_value="Darwin"), \
         patch("platform.machine", return_value="arm64"):
        url = checksum_url("textproxy", "0.2.0")
    assert url.endswith(".sha256")
    assert "textproxy-v0.2.0-darwin-arm64.tar.gz.sha256" in url


# ---------------------------------------------------------------------------
# download_binary — mocked HTTP
# ---------------------------------------------------------------------------

def _make_tarball_bytes(tool: str) -> bytes:
    """Create a minimal in-memory .tar.gz containing a fake binary."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        content = b"#!/bin/sh\necho hello\n"
        info = tarfile.TarInfo(name=tool)
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def test_download_binary_success(tmp_path):
    tool = "textproxy"
    version = "0.2.0"
    tarball = _make_tarball_bytes(tool)
    expected_sha = hashlib.sha256(tarball).hexdigest()

    mock_client = MagicMock()

    # Mock streaming response for tarball
    stream_ctx = MagicMock()
    stream_ctx.__enter__ = MagicMock(return_value=stream_ctx)
    stream_ctx.__exit__ = MagicMock(return_value=False)
    stream_ctx.raise_for_status = MagicMock()
    stream_ctx.iter_bytes = MagicMock(return_value=iter([tarball]))
    mock_client.stream = MagicMock(return_value=stream_ctx)

    # Mock sha256 sidecar response
    sha_resp = MagicMock()
    sha_resp.raise_for_status = MagicMock()
    sha_resp.text = expected_sha
    mock_client.get = MagicMock(return_value=sha_resp)

    with patch("platform.system", return_value="Darwin"), \
         patch("platform.machine", return_value="arm64"), \
         patch("textworkspace.bootstrap.CACHE_DIR", tmp_path / "cache"), \
         patch("textworkspace.bootstrap.DATA_DIR", tmp_path):
        result = download_binary(tool, version, client=mock_client)

    assert result.exists()
    assert result.name == "textproxy-v0.2.0-darwin-arm64"
    assert (result / tool).exists()


def test_download_binary_checksum_mismatch(tmp_path):
    tool = "textproxy"
    version = "0.2.0"
    tarball = _make_tarball_bytes(tool)

    mock_client = MagicMock()

    stream_ctx = MagicMock()
    stream_ctx.__enter__ = MagicMock(return_value=stream_ctx)
    stream_ctx.__exit__ = MagicMock(return_value=False)
    stream_ctx.raise_for_status = MagicMock()
    stream_ctx.iter_bytes = MagicMock(return_value=iter([tarball]))
    mock_client.stream = MagicMock(return_value=stream_ctx)

    sha_resp = MagicMock()
    sha_resp.raise_for_status = MagicMock()
    sha_resp.text = "deadbeef" * 8  # wrong hash
    mock_client.get = MagicMock(return_value=sha_resp)

    with patch("platform.system", return_value="Darwin"), \
         patch("platform.machine", return_value="arm64"), \
         patch("textworkspace.bootstrap.CACHE_DIR", tmp_path / "cache"), \
         patch("textworkspace.bootstrap.DATA_DIR", tmp_path):
        with pytest.raises(ValueError, match="Checksum mismatch"):
            download_binary(tool, version, client=mock_client)


def test_download_binary_skips_if_cached(tmp_path):
    tool = "textproxy"
    version = "0.2.0"
    cache = tmp_path / "cache"
    entry = cache / "textproxy-v0.2.0-darwin-arm64"
    entry.mkdir(parents=True)

    mock_client = MagicMock()

    with patch("platform.system", return_value="Darwin"), \
         patch("platform.machine", return_value="arm64"), \
         patch("textworkspace.bootstrap.CACHE_DIR", cache):
        result = download_binary(tool, version, client=mock_client)

    mock_client.stream.assert_not_called()
    assert result == entry


# ---------------------------------------------------------------------------
# install_binary — symlink management
# ---------------------------------------------------------------------------

def test_install_binary_creates_symlink(tmp_path):
    tool = "textproxy"
    version = "0.2.0"
    slug = "darwin-arm64"
    cache = tmp_path / "cache"
    entry = cache / f"{tool}-v{version}-{slug}"
    entry.mkdir(parents=True)
    (entry / tool).write_bytes(b"binary")

    bin_dir = tmp_path / "bin"

    with patch("platform.system", return_value="Darwin"), \
         patch("platform.machine", return_value="arm64"), \
         patch("textworkspace.bootstrap.CACHE_DIR", cache), \
         patch("textworkspace.bootstrap.BIN_DIR", bin_dir):
        symlink = install_binary(tool, version)

    assert symlink.is_symlink()
    assert symlink.resolve() == (entry / tool).resolve()


def test_install_binary_prunes_old_versions(tmp_path):
    tool = "textproxy"
    slug = "darwin-arm64"
    cache = tmp_path / "cache"
    bin_dir = tmp_path / "bin"

    # Create three cache entries (old, prev, current)
    for ver in ("0.1.0", "0.1.1", "0.2.0"):
        entry = cache / f"{tool}-v{ver}-{slug}"
        entry.mkdir(parents=True)
        (entry / tool).write_bytes(b"binary")

    with patch("platform.system", return_value="Darwin"), \
         patch("platform.machine", return_value="arm64"), \
         patch("textworkspace.bootstrap.CACHE_DIR", cache), \
         patch("textworkspace.bootstrap.BIN_DIR", bin_dir):
        install_binary(tool, "0.2.0")

    remaining = {d.name for d in cache.iterdir()}
    # Current (0.2.0) and one previous (0.1.1) kept; 0.1.0 deleted
    assert f"{tool}-v0.2.0-{slug}" in remaining
    assert f"{tool}-v0.1.1-{slug}" in remaining
    assert f"{tool}-v0.1.0-{slug}" not in remaining


def test_install_binary_replaces_existing_symlink(tmp_path):
    tool = "textproxy"
    slug = "darwin-arm64"
    cache = tmp_path / "cache"
    bin_dir = tmp_path / "bin"

    for ver in ("0.1.0", "0.2.0"):
        entry = cache / f"{tool}-v{ver}-{slug}"
        entry.mkdir(parents=True)
        (entry / tool).write_bytes(b"binary")

    with patch("platform.system", return_value="Darwin"), \
         patch("platform.machine", return_value="arm64"), \
         patch("textworkspace.bootstrap.CACHE_DIR", cache), \
         patch("textworkspace.bootstrap.BIN_DIR", bin_dir):
        install_binary(tool, "0.1.0")
        symlink = install_binary(tool, "0.2.0")

    assert symlink.is_symlink()
    assert f"v0.2.0" in str(symlink.resolve())
