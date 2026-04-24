"""Tests for textworkspace.repos (union of dev_root scan + config.repos)."""

from __future__ import annotations

from pathlib import Path

from textworkspace.config import Config, RepoEntry
from textworkspace.repos import (
    iter_all_repos,
    register,
    repo_name_from_path,
    resolve_repo,
    unregister,
)


def _mk_dev_repo(root: Path, name: str) -> Path:
    p = root / name
    p.mkdir()
    (p / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    return p


def test_iter_union_dev_root_and_registered(tmp_path: Path) -> None:
    dev_root = tmp_path / "dev"
    dev_root.mkdir()
    _mk_dev_repo(dev_root, "alpha")
    external = tmp_path / "work" / "external"
    external.mkdir(parents=True)
    (external / "pyproject.toml").write_text("")

    cfg = Config(defaults={"dev_root": str(dev_root)})
    register(cfg, "external", external, profile="work")

    repos = iter_all_repos(cfg)
    assert set(repos.keys()) == {"alpha", "external"}
    assert repos["alpha"].name == "alpha"
    assert repos["external"] == external


def test_registered_overrides_dev_root_with_same_name(tmp_path: Path) -> None:
    dev_root = tmp_path / "dev"
    dev_root.mkdir()
    _mk_dev_repo(dev_root, "alpha")
    other = tmp_path / "other" / "alpha"
    other.mkdir(parents=True)

    cfg = Config(defaults={"dev_root": str(dev_root)})
    register(cfg, "alpha", other)

    repos = iter_all_repos(cfg)
    assert repos["alpha"] == other


def test_resolve_repo(tmp_path: Path) -> None:
    dev_root = tmp_path / "dev"
    dev_root.mkdir()
    _mk_dev_repo(dev_root, "alpha")
    cfg = Config(defaults={"dev_root": str(dev_root)})
    assert resolve_repo(cfg, "alpha") is not None
    assert resolve_repo(cfg, "nope") is None


def test_repo_name_from_path_matches_longest_prefix(tmp_path: Path) -> None:
    dev_root = tmp_path / "dev"
    dev_root.mkdir()
    _mk_dev_repo(dev_root, "alpha")
    nested = dev_root / "alpha" / "src" / "deep"
    nested.mkdir(parents=True)

    cfg = Config(defaults={"dev_root": str(dev_root)})
    assert repo_name_from_path(cfg, nested) == "alpha"
    assert repo_name_from_path(cfg, tmp_path) is None


def test_unregister_returns_false_when_missing(tmp_path: Path) -> None:
    cfg = Config()
    assert unregister(cfg, "nonexistent") is False
    register(cfg, "x", tmp_path)
    assert unregister(cfg, "x") is True
    assert "x" not in cfg.repos


def test_missing_path_does_not_surface(tmp_path: Path) -> None:
    """A registered repo whose path was deleted silently drops from the map."""
    cfg = Config()
    cfg.repos["gone"] = RepoEntry(path=str(tmp_path / "nonexistent"))
    assert "gone" not in iter_all_repos(cfg)


def test_filter_by_profile_keeps_matching(tmp_path: Path) -> None:
    from textworkspace.repos import filter_by_profile

    work = tmp_path / "work-a"; work.mkdir()
    pers = tmp_path / "personal-a"; pers.mkdir()
    no_profile = tmp_path / "scratch"; no_profile.mkdir()
    cfg = Config()
    register(cfg, "work-a", work, profile="work")
    register(cfg, "personal-a", pers, profile="personal")
    register(cfg, "scratch", no_profile)  # no profile

    repos = iter_all_repos(cfg)
    work_only = filter_by_profile(cfg, repos, "work")
    assert set(work_only.keys()) == {"work-a"}
    personal_only = filter_by_profile(cfg, repos, "personal")
    assert set(personal_only.keys()) == {"personal-a"}
    # Unknown profile → empty.
    assert filter_by_profile(cfg, repos, "ghost") == {}


def test_scan_skips_symlinked_repo(tmp_path: Path) -> None:
    """Symlinks in dev_root (back-compat aliases) are not double-counted."""
    dev_root = tmp_path / "dev"
    dev_root.mkdir()
    real = _mk_dev_repo(dev_root, "real-name")
    # Back-compat symlink: old name → real folder.
    alias = dev_root / "old-name"
    alias.symlink_to(real, target_is_directory=True)

    cfg = Config(defaults={"dev_root": str(dev_root)})
    repos = iter_all_repos(cfg)
    assert "real-name" in repos
    assert "old-name" not in repos
