"""Unified repo discovery — dev_root scan ∪ config.repos registry.

`dev_root` is the canonical location where most personal/open-source repos
live (e.g. ~/projects/personal/paperworlds). But repos elsewhere — a work
monorepo, a borrowed upstream, a scratch dir — can still participate in
forums, ideas, and specs if they're registered in `config.repos` via
`tw repo add`.

Callers get a single dict[str, Path] and don't need to know where each
repo came from.
"""

from __future__ import annotations

from pathlib import Path

from textworkspace.config import Config, RepoEntry


def _dev_root_path(cfg: Config) -> Path | None:
    raw = (cfg.defaults or {}).get("dev_root", "")
    return Path(raw).expanduser() if raw else None


def _scan_dev_root(dev_root: Path | None) -> dict[str, Path]:
    if dev_root is None or not dev_root.exists():
        return {}
    out: dict[str, Path] = {}
    for child in sorted(dev_root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if any((child / marker).exists() for marker in ("pyproject.toml", "go.mod", "package.json", "Cargo.toml")):
            out[child.name] = child
    return out


def _registered_repos(cfg: Config) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for name, entry in (cfg.repos or {}).items():
        if not entry.path:
            continue
        p = Path(entry.path).expanduser()
        if p.exists():
            out[name] = p
    return out


def iter_all_repos(cfg: Config) -> dict[str, Path]:
    """Union of dev_root scan and `config.repos`. Registered entries win on conflict.

    Only directories that still exist on disk are included.
    """
    merged = _scan_dev_root(_dev_root_path(cfg))
    # Registered repos override dev_root entries (explicit > discovered).
    merged.update(_registered_repos(cfg))
    return merged


def resolve_repo(cfg: Config, name: str) -> Path | None:
    """Return the path for *name* using iter_all_repos, or None."""
    return iter_all_repos(cfg).get(name)


def repo_name_from_path(cfg: Config, path: Path) -> str | None:
    """Given a directory path, return the repo name it belongs to (or None).

    Matches the longest prefix — so nested paths resolve to the enclosing repo.
    """
    path = path.resolve()
    best: tuple[int, str] | None = None
    for name, repo_path in iter_all_repos(cfg).items():
        try:
            repo_resolved = repo_path.resolve()
        except OSError:
            continue
        try:
            path.relative_to(repo_resolved)
        except ValueError:
            continue
        depth = len(repo_resolved.parts)
        if best is None or depth > best[0]:
            best = (depth, name)
    return best[1] if best else None


def register(cfg: Config, name: str, path: Path, *, profile: str = "", label: str = "") -> None:
    """Add or update an entry in cfg.repos. Caller saves the config."""
    cfg.repos[name] = RepoEntry(path=str(path), label=label, profile=profile)


def unregister(cfg: Config, name: str) -> bool:
    """Remove an entry from cfg.repos. Returns True if it existed."""
    return cfg.repos.pop(name, None) is not None
