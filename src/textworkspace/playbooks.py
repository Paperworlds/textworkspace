"""Playbook discovery + parsing.

A **playbook** is a single-document YAML file at
``<owner-repo>/docs/specs/playbooks/<slug>.yaml`` that encodes a sequence
of agent actions (shell ``run`` steps and bound-persona ``persona_turn``
steps). See ``docs/specs/playbook-format.md`` for the full contract.

This module is the registry/discovery side. Execution lives in
textprompts (``pp playbook run``); textworkspace only resolves specs,
validates them, and lists them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


VALID_STATUSES: frozenset[str] = frozenset({"draft", "adopted", "superseded"})
VALID_STEP_KINDS: frozenset[str] = frozenset({"run", "persona_turn"})
RESERVED_STEP_KEYS_V2: frozenset[str] = frozenset({"sub_playbook", "when", "for_each"})


@dataclass
class Step:
    id: str
    kind: str           # "run" | "persona_turn"
    body: str           # shell cmd or persona prompt body
    skip_if: str | None = None
    out: str | None = None


@dataclass
class Input:
    name: str
    type: str           # string | int | bool | path
    required: bool = False
    default: Any = None
    description: str = ""


@dataclass
class Output:
    kind: str           # forum-thread | file | textmap-node | stdout
    tag: str = ""
    description: str = ""


@dataclass
class Playbook:
    slug: str
    owner: str
    path: Path
    status: str = "draft"
    version: str = "0.1.0"
    persona: str = ""
    description: str = ""
    consumers: list[str] = field(default_factory=list)
    supersedes: str | None = None
    adopted_at: str | None = None
    inputs: list[Input] = field(default_factory=list)
    outputs: list[Output] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)
    steps: list[Step] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_adopted(self) -> bool:
        return self.status == "adopted"


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def _parse_step(raw: dict[str, Any], path: Path, idx: int) -> Step:
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: step #{idx} is not a mapping")

    reserved = RESERVED_STEP_KEYS_V2 & set(raw.keys())
    if reserved:
        raise ValueError(
            f"{path}: step #{idx} uses keys reserved for v2 — {sorted(reserved)} "
            "(rejected by v1 runners)"
        )

    step_id = raw.get("id")
    kind = raw.get("kind")
    if not step_id:
        raise ValueError(f"{path}: step #{idx} missing required 'id'")
    if kind not in VALID_STEP_KINDS:
        raise ValueError(
            f"{path}: step '{step_id}' has invalid kind {kind!r} "
            f"(valid: {sorted(VALID_STEP_KINDS)})"
        )

    body_key = "run" if kind == "run" else "persona_turn"
    body = raw.get(body_key)
    if not isinstance(body, str) or not body.strip():
        raise ValueError(
            f"{path}: step '{step_id}' (kind={kind}) missing required '{body_key}' string"
        )

    return Step(
        id=str(step_id),
        kind=kind,
        body=body,
        skip_if=raw.get("skip_if"),
        out=raw.get("out"),
    )


def _parse_inputs(raw: list[Any] | None, path: Path) -> list[Input]:
    if not raw:
        return []
    out: list[Input] = []
    for item in raw:
        if not isinstance(item, dict) or "name" not in item or "type" not in item:
            raise ValueError(f"{path}: input entry missing 'name' or 'type': {item!r}")
        out.append(Input(
            name=str(item["name"]),
            type=str(item["type"]),
            required=bool(item.get("required", False)),
            default=item.get("default"),
            description=str(item.get("description", "")),
        ))
    return out


def _parse_outputs(raw: list[Any] | None, path: Path) -> list[Output]:
    if not raw:
        return []
    out: list[Output] = []
    for item in raw:
        if not isinstance(item, dict) or "kind" not in item:
            raise ValueError(f"{path}: output entry missing 'kind': {item!r}")
        out.append(Output(
            kind=str(item["kind"]),
            tag=str(item.get("tag", "")),
            description=str(item.get("description", "")),
        ))
    return out


def parse_playbook_file(path: Path) -> Playbook:
    """Read a playbook .yaml and return a populated Playbook.

    Raises ValueError on missing required fields, invalid status, invalid
    step kinds, or reserved-for-v2 keys.
    """
    text = path.read_text()
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"{path}: invalid YAML — {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level must be a mapping")

    for required in ("slug", "owner", "persona", "steps"):
        if required not in data:
            raise ValueError(f"{path}: missing required field '{required}'")

    status = str(data.get("status", "draft"))
    if status not in VALID_STATUSES:
        raise ValueError(
            f"{path}: unknown status {status!r} (valid: {sorted(VALID_STATUSES)})"
        )

    steps_raw = data.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise ValueError(f"{path}: 'steps' must be a non-empty list")
    steps = [_parse_step(s, path, i) for i, s in enumerate(steps_raw)]

    seen_ids: set[str] = set()
    for s in steps:
        if s.id in seen_ids:
            raise ValueError(f"{path}: duplicate step id {s.id!r}")
        seen_ids.add(s.id)

    known = {
        "slug", "owner", "status", "version", "persona", "description",
        "consumers", "supersedes", "adopted_at", "inputs", "outputs",
        "budget", "steps",
    }
    extra = {k: v for k, v in data.items() if k not in known}

    return Playbook(
        slug=str(data["slug"]),
        owner=str(data["owner"]),
        path=path,
        status=status,
        version=str(data.get("version", "0.1.0")),
        persona=str(data["persona"]),
        description=str(data.get("description", "")),
        consumers=list(data.get("consumers") or []),
        supersedes=data.get("supersedes"),
        adopted_at=data.get("adopted_at"),
        inputs=_parse_inputs(data.get("inputs"), path),
        outputs=_parse_outputs(data.get("outputs"), path),
        budget=dict(data.get("budget") or {}),
        steps=steps,
        extra=extra,
    )


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _as_repo_map(source: Path | dict[str, Path]) -> dict[str, Path]:
    """Normalise a dev_root Path or an explicit name→path dict."""
    if isinstance(source, dict):
        return source
    if not source.exists():
        return {}
    return {
        p.name: p
        for p in sorted(source.iterdir())
        if p.is_dir() and not p.name.startswith(".") and not p.is_symlink()
    }


@dataclass
class DiscoveryResult:
    playbooks: list[Playbook] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)


def discover_playbooks(source: Path | dict[str, Path]) -> DiscoveryResult:
    """Walk every repo's docs/specs/playbooks/*.yaml and parse each.

    Unparseable files are collected as errors rather than raising — the
    caller (CLI / doctor) decides whether to surface them.
    """
    result = DiscoveryResult()
    for _name, repo in sorted(_as_repo_map(source).items()):
        playbooks_dir = repo / "docs" / "specs" / "playbooks"
        if not playbooks_dir.is_dir():
            continue
        for path in sorted(playbooks_dir.glob("*.yaml")):
            if path.name.startswith("_"):
                # _schema.json, _examples.yaml etc. — skip meta files.
                continue
            try:
                result.playbooks.append(parse_playbook_file(path))
            except ValueError as e:
                result.errors.append((path, str(e)))
    return result


def find_playbook(source: Path | dict[str, Path], slug: str) -> Playbook | None:
    """Return the first playbook with the given slug, or None."""
    for pb in discover_playbooks(source).playbooks:
        if pb.slug == slug:
            return pb
    return None
