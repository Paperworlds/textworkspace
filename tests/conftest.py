"""Shared pytest fixtures for textworkspace tests."""

import pytest


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """Patch config.CONFIG_DIR and config.CONFIG_FILE to a temp directory.

    Returns the temp path so tests can use it as both the config root and
    a base directory for other temp files.
    """
    monkeypatch.setattr("textworkspace.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("textworkspace.config.CONFIG_FILE", tmp_path / "config.yaml")
    return tmp_path
