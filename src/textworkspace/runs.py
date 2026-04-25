"""Read-only queries over playbook run threads.

A *run thread* is a forum thread tagged ``playbook:<slug>`` and
``run:<run-id>`` produced by ``pp playbook run``. This module reads
them; it does not write them.

Per-step audit entry shape (see ``docs/audit.yaml``):

  Each entry's content carries an optional YAML block delimited by
  ``---`` markers, with fields ``step_id``, ``status``, ``output_summary``,
  optional ``output_full``, ``agent_feedback``, ``agent_ideas``,
  ``duration_ms``, ``retry_count``. We parse it best-effort; entries
  that don't follow the convention are surfaced as plain text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from textworkspace.forums import Entry, Thread, list_threads, load_thread


PLAYBOOK_TAG_PREFIX = "playbook:"
REPO_TAG_PREFIX = "repo:"
RUN_TAG_PREFIX = "run:"


# Frontmatter at the start of an entry's content: ``---\n...\n---\n<rest>``.
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)


@dataclass
class StepEntry:
    """Parsed view of one entry in a run thread."""
    step_id: str
    status: str             # ok | failed | skipped | aborted
    output_summary: str = ""
    output_full: str = ""
    agent_feedback: str = ""
    agent_ideas: list[str] = field(default_factory=list)
    duration_ms: int | None = None
    retry_count: int | None = None
    raw: Entry | None = None


def parse_step_entry(entry: Entry) -> StepEntry | None:
    """Parse an entry's content as a step-entry. Return None if the
    convention isn't followed (caller should treat it as plain text).
    """
    m = _FRONTMATTER_RE.match(entry.content)
    if not m:
        return None
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict) or "step_id" not in data or "status" not in data:
        return None

    ideas = data.get("agent_ideas") or []
    if not isinstance(ideas, list):
        ideas = [str(ideas)]

    return StepEntry(
        step_id=str(data["step_id"]),
        status=str(data["status"]),
        output_summary=str(data.get("output_summary", "")),
        output_full=str(data.get("output_full", "")),
        agent_feedback=str(data.get("agent_feedback", "")),
        agent_ideas=[str(i) for i in ideas],
        duration_ms=data.get("duration_ms"),
        retry_count=data.get("retry_count"),
        raw=entry,
    )


@dataclass
class RunThread:
    """A run thread surfaces playbook slug + repo + steps."""
    slug: str
    playbook_slug: str
    repo: str | None
    run_id: str | None
    thread: Thread

    @property
    def steps(self) -> list[StepEntry]:
        out: list[StepEntry] = []
        for entry in self.thread.entries:
            step = parse_step_entry(entry)
            if step is not None:
                out.append(step)
        return out


def _tag_value(thread: Thread, prefix: str) -> str | None:
    for tag in thread.meta.tags:
        if tag.startswith(prefix):
            return tag[len(prefix):]
    return None


def to_run_thread(thread: Thread) -> RunThread | None:
    """Wrap a forum thread as a RunThread if it carries a playbook tag."""
    playbook = _tag_value(thread, PLAYBOOK_TAG_PREFIX)
    if not playbook:
        return None
    return RunThread(
        slug=thread.path.parent.name,
        playbook_slug=playbook,
        repo=_tag_value(thread, REPO_TAG_PREFIX),
        run_id=_tag_value(thread, RUN_TAG_PREFIX),
        thread=thread,
    )


def list_runs(
    root: Path,
    *,
    playbook: str | None = None,
    repo: str | None = None,
    status: str | None = None,
) -> list[RunThread]:
    """Return RunThreads under *root*, optionally filtered.

    *playbook* matches the ``playbook:<X>`` tag value.
    *repo* matches the ``repo:<Y>`` tag value.
    *status* is forwarded to the underlying forum filter.
    """
    runs: list[RunThread] = []
    for thread in list_threads(root, status=status):
        run = to_run_thread(thread)
        if run is None:
            continue
        if playbook is not None and run.playbook_slug != playbook:
            continue
        if repo is not None and run.repo != repo:
            continue
        runs.append(run)
    return runs


def find_run(root: Path, slug: str) -> RunThread | None:
    """Look up a single run by its forum-thread slug."""
    try:
        thread = load_thread(root, slug)
    except Exception:  # noqa: BLE001
        return None
    return to_run_thread(thread)
