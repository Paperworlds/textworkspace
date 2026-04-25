"""Aggregator for ``agent_ideas`` across all playbook run threads.

Stage 1 (this module): on-demand scan over forum threads tagged
``playbook:*``. No index file, no persisted state — promotion status
is derived by scanning IDEAS files for ``from_run`` provenance.

See docs/audit.yaml §4.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from textworkspace.ideas import _CANDIDATE_PATHS, load_all_ideas
from textworkspace.runs import RunThread, list_runs


@dataclass
class RunIdea:
    """One ``agent_ideas`` entry, identified by (run_slug, step_id, index)."""
    run_slug: str
    playbook_slug: str
    repo: str | None
    step_id: str
    idea_index: int
    text: str
    agent_feedback: str = ""

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.run_slug, self.step_id, self.idea_index)


def collect_run_ideas(forums_root: Path) -> list[RunIdea]:
    """Walk every playbook run thread and collect every ``agent_ideas`` entry."""
    out: list[RunIdea] = []
    for run in list_runs(forums_root):
        for step in run.steps:
            for idx, idea_text in enumerate(step.agent_ideas):
                out.append(RunIdea(
                    run_slug=run.slug,
                    playbook_slug=run.playbook_slug,
                    repo=run.repo,
                    step_id=step.step_id,
                    idea_index=idx,
                    text=idea_text,
                    agent_feedback=step.agent_feedback,
                ))
    return out


def promoted_keys(repos: dict[str, Path]) -> set[tuple[str, str, int]]:
    """Return the set of (run_slug, step_id, idea_index) keys already promoted.

    Scans every repo's IDEAS file for entries carrying
    ``from_run`` / ``from_step`` / ``from_idea_index`` provenance.
    """
    keys: set[tuple[str, str, int]] = set()
    for idea in load_all_ideas(repos):
        raw = idea.raw or {}
        run_slug = raw.get("from_run")
        step_id = raw.get("from_step")
        idea_index = raw.get("from_idea_index")
        if run_slug and step_id and isinstance(idea_index, int):
            keys.add((str(run_slug), str(step_id), idea_index))
    return keys


def find_run_idea(forums_root: Path, run_slug: str, step_id: str, idea_index: int) -> RunIdea | None:
    """Look up one specific run idea."""
    for ri in collect_run_ideas(forums_root):
        if ri.key == (run_slug, step_id, idea_index):
            return ri
    return None


def _ideas_file_for(repo: Path) -> Path:
    """Return the IDEAS file path to write into. Prefers the existing one;
    falls back to docs/IDEAS.yaml."""
    for rel in _CANDIDATE_PATHS:
        p = repo / rel
        if p.exists():
            return p
    return repo / "docs" / "IDEAS.yaml"


def promote(
    run_idea: RunIdea,
    target_repo: Path,
    *,
    promoted_by: str,
    promoted_at: str,
) -> Path:
    """Append the run-idea into the target repo's IDEAS file with provenance.

    Returns the path written. Format-preserving where possible: appends to
    the first list/mapping found at the top level. Falls back to writing a
    new ``ideas:`` list.
    """
    path = _ideas_file_for(target_repo)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and path.suffix in (".yaml", ".yml"):
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError:
            data = {}
    else:
        data = {}
    if not isinstance(data, dict):
        data = {}

    # Pick or create a target list/dict.
    target_list_key = None
    for key, value in data.items():
        if isinstance(value, list):
            target_list_key = key
            break

    new_id = f"from-run-{run_idea.run_slug}-{run_idea.step_id}-{run_idea.idea_index}"
    new_entry = {
        "id": new_id,
        "title": run_idea.text[:80],
        "status": "idea",
        "summary": run_idea.text,
        "from_run": run_idea.run_slug,
        "from_step": run_idea.step_id,
        "from_idea_index": run_idea.idea_index,
        "from_playbook": run_idea.playbook_slug,
        "promoted_at": promoted_at,
        "promoted_by": promoted_by,
    }

    if target_list_key is None:
        data["ideas"] = data.get("ideas") or []
        if not isinstance(data["ideas"], list):
            data["ideas"] = []
        data["ideas"].append(new_entry)
    else:
        data[target_list_key].append(new_entry)

    path.write_text(yaml.safe_dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True))
    return path
