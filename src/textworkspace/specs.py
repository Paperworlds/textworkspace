"""Cross-repo specs: `docs/specs/<slug>.md` with YAML frontmatter.

A **spec** is a contract one repo publishes for others to follow. It lives
in the owner repo at ``docs/specs/<slug>.md``; discussion lives in a
textforums thread tagged ``spec``. Consumer repos declare what they follow
in ``docs/SPECS.yaml``.

Lifecycle: ``draft -> proposed -> adopted -> deprecated | superseded``.
Once adopted, frontmatter is frozen — new version = new slug + ``supersedes``.

See docs/SPECS-FORMAT.md for the canonical frontmatter schema.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


SPEC_TAG = "spec"
MARKER_RE = re.compile(r"#\s*SPEC:\s*([a-z0-9][a-z0-9_.\-]*)", re.IGNORECASE)
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)

# Frontmatter fields that are frozen once `status: adopted`.
IMMUTABLE_WHEN_ADOPTED: frozenset[str] = frozenset({
    "slug", "owner", "version", "supersedes", "adopted_at",
})

VALID_STATUSES: frozenset[str] = frozenset({
    "draft", "proposed", "adopted", "deprecated", "superseded",
})


@dataclass
class Spec:
    slug: str
    owner: str
    path: Path
    status: str = "draft"
    version: str = "0.1.0"
    consumers: list[str] = field(default_factory=list)
    supersedes: str | None = None
    adopted_at: str | None = None
    body: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_adopted(self) -> bool:
        return self.status == "adopted"

    def to_frontmatter(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "slug": self.slug,
            "owner": self.owner,
            "status": self.status,
            "version": self.version,
        }
        if self.consumers:
            out["consumers"] = list(self.consumers)
        if self.supersedes:
            out["supersedes"] = self.supersedes
        if self.adopted_at:
            out["adopted_at"] = self.adopted_at
        out.update(self.extra)
        return out


@dataclass
class ConsumerEntry:
    slug: str
    pinned_version: str | None = None
    implemented_in: list[Path] = field(default_factory=list)


@dataclass
class ConsumerManifest:
    repo: str
    path: Path
    follows: list[ConsumerEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parse / dump
# ---------------------------------------------------------------------------


def parse_spec_file(path: Path) -> Spec:
    """Read a spec .md and return a populated Spec.

    Raises ValueError on missing frontmatter or required fields.
    """
    text = path.read_text()
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError(f"{path}: missing YAML frontmatter (expected leading ---)")
    meta = yaml.safe_load(m.group(1)) or {}
    body = m.group(2)

    for required in ("slug", "owner"):
        if required not in meta:
            raise ValueError(f"{path}: frontmatter missing required field '{required}'")

    status = str(meta.get("status", "draft"))
    if status not in VALID_STATUSES:
        raise ValueError(f"{path}: unknown status '{status}' (valid: {sorted(VALID_STATUSES)})")

    known = {"slug", "owner", "status", "version", "consumers", "supersedes", "adopted_at"}
    extra = {k: v for k, v in meta.items() if k not in known}

    return Spec(
        slug=str(meta["slug"]),
        owner=str(meta["owner"]),
        path=path,
        status=status,
        version=str(meta.get("version", "0.1.0")),
        consumers=list(meta.get("consumers") or []),
        supersedes=meta.get("supersedes"),
        adopted_at=meta.get("adopted_at"),
        body=body,
        extra=extra,
    )


def dump_spec(spec: Spec) -> str:
    fm = yaml.safe_dump(spec.to_frontmatter(), sort_keys=False).strip()
    return f"---\n{fm}\n---\n{spec.body}"


def write_spec(spec: Spec) -> None:
    spec.path.parent.mkdir(parents=True, exist_ok=True)
    spec.path.write_text(dump_spec(spec))


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_specs(dev_root: Path) -> list[Spec]:
    """Walk dev_root/<repo>/docs/specs/*.md and parse each."""
    out: list[Spec] = []
    if not dev_root.exists():
        return out
    for repo in sorted(p for p in dev_root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        specs_dir = repo / "docs" / "specs"
        if not specs_dir.is_dir():
            continue
        for path in sorted(specs_dir.glob("*.md")):
            try:
                out.append(parse_spec_file(path))
            except ValueError:
                # Skip unparseable — the linter path (tw forums spec check)
                # can surface these errors separately.
                continue
    return out


def find_spec(dev_root: Path, slug: str) -> Spec | None:
    for spec in discover_specs(dev_root):
        if spec.slug == slug:
            return spec
    return None


def consumer_manifest_path(repo: Path) -> Path:
    return repo / "docs" / "SPECS.yaml"


def load_consumer_manifest(repo: Path) -> ConsumerManifest | None:
    path = consumer_manifest_path(repo)
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text()) or {}
    follows_raw = data.get("follows") or []
    entries: list[ConsumerEntry] = []
    for item in follows_raw:
        if not isinstance(item, dict) or "slug" not in item:
            continue
        entries.append(ConsumerEntry(
            slug=str(item["slug"]),
            pinned_version=item.get("pinned_version"),
            implemented_in=[Path(p) for p in item.get("implemented_in") or []],
        ))
    return ConsumerManifest(repo=repo.name, path=path, follows=entries)


def discover_consumer_manifests(dev_root: Path) -> list[ConsumerManifest]:
    out: list[ConsumerManifest] = []
    if not dev_root.exists():
        return out
    for repo in sorted(p for p in dev_root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        mf = load_consumer_manifest(repo)
        if mf is not None:
            out.append(mf)
    return out


# ---------------------------------------------------------------------------
# References (inline markers)
# ---------------------------------------------------------------------------


# Directories we skip when grepping for # SPEC: markers.
_IGNORE_DIRS: frozenset[str] = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", "target",
})


def find_markers(repo: Path, slug: str | None = None) -> list[tuple[Path, int, str]]:
    """Walk repo for '# SPEC: <slug>' markers.

    Returns (file, line_number, matched_slug). When *slug* is given, filters
    to matches with that slug (case-insensitive).
    """
    hits: list[tuple[Path, int, str]] = []
    for path in _iter_text_files(repo):
        try:
            for i, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
                m = MARKER_RE.search(line)
                if not m:
                    continue
                matched = m.group(1)
                if slug is None or matched.lower() == slug.lower():
                    hits.append((path, i, matched))
        except OSError:
            continue
    return hits


def _iter_text_files(root: Path):
    # Cheap walk — skip obvious non-text / vendored dirs.
    stack: list[Path] = [root]
    while stack:
        cur = stack.pop()
        try:
            children = list(cur.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_symlink():
                continue
            if child.is_dir():
                if child.name in _IGNORE_DIRS:
                    continue
                stack.append(child)
                continue
            if child.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".ico", ".woff", ".woff2", ".ttf", ".sqlite", ".db"}:
                continue
            yield child


# ---------------------------------------------------------------------------
# Check: does a consumer actually follow an adopted spec?
# ---------------------------------------------------------------------------


@dataclass
class CheckFinding:
    consumer: str
    slug: str
    level: str          # "error" | "warn"
    message: str


def check_consumer(
    dev_root: Path,
    consumer_repo: Path,
    specs_by_slug: dict[str, Spec],
) -> list[CheckFinding]:
    """Validate a single consumer's `follows:` manifest against adopted specs."""
    mf = load_consumer_manifest(consumer_repo)
    if mf is None:
        return []

    findings: list[CheckFinding] = []
    for entry in mf.follows:
        spec = specs_by_slug.get(entry.slug)
        if spec is None:
            findings.append(CheckFinding(
                consumer=consumer_repo.name, slug=entry.slug, level="error",
                message=f"declared in {mf.path} but no spec with slug '{entry.slug}' found under dev_root",
            ))
            continue
        if not spec.is_adopted:
            findings.append(CheckFinding(
                consumer=consumer_repo.name, slug=entry.slug, level="warn",
                message=f"follows '{entry.slug}' but spec is {spec.status!r} (not adopted)",
            ))
        if entry.pinned_version and entry.pinned_version != spec.version:
            findings.append(CheckFinding(
                consumer=consumer_repo.name, slug=entry.slug, level="warn",
                message=f"pinned_version {entry.pinned_version} != owner's current {spec.version}",
            ))
        # Implementation paths must exist.
        for rel in entry.implemented_in:
            if not (consumer_repo / rel).exists():
                findings.append(CheckFinding(
                    consumer=consumer_repo.name, slug=entry.slug, level="error",
                    message=f"implemented_in path missing: {rel}",
                ))
        # At least one # SPEC: <slug> marker must appear in source.
        if not find_markers(consumer_repo, entry.slug):
            findings.append(CheckFinding(
                consumer=consumer_repo.name, slug=entry.slug, level="warn",
                message=f"no '# SPEC: {entry.slug}' marker found in source",
            ))

    # Reverse direction: spec lists `consumers: [..repo..]` but repo doesn't follow it.
    for spec in specs_by_slug.values():
        if not spec.is_adopted or consumer_repo.name not in spec.consumers:
            continue
        if not any(e.slug == spec.slug for e in mf.follows):
            findings.append(CheckFinding(
                consumer=consumer_repo.name, slug=spec.slug, level="warn",
                message=f"spec lists this repo as consumer but {mf.path.name} has no entry",
            ))

    return findings


def check_all(dev_root: Path) -> list[CheckFinding]:
    specs_by_slug = {s.slug: s for s in discover_specs(dev_root)}
    out: list[CheckFinding] = []
    if not dev_root.exists():
        return out
    for repo in sorted(p for p in dev_root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        out.extend(check_consumer(dev_root, repo, specs_by_slug))
    return out


# ---------------------------------------------------------------------------
# Scaffold
# ---------------------------------------------------------------------------


_SCAFFOLD_BODY = """\
# {title}

## Summary

One-paragraph description of the contract this spec defines.

## Motivation

Why this needs to be standardised across repos.

## Interface

The concrete shape — types, wire format, function signatures, file layout.

## Conformance

What a consumer must do to claim compliance. List required behaviours and
mark each with `# SPEC: {slug}` in the consumer source.

## Open questions
"""


def scaffold_spec(owner_repo: Path, slug: str, title: str, owner_name: str) -> Spec:
    """Return a draft Spec (not yet written to disk)."""
    path = owner_repo / "docs" / "specs" / f"{slug}.md"
    return Spec(
        slug=slug,
        owner=owner_name,
        path=path,
        status="draft",
        version="0.1.0",
        body=_SCAFFOLD_BODY.format(title=title, slug=slug),
    )
