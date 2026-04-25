"""Tests for runs.py — read-only queries over playbook run threads."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from textworkspace.forums import (
    Entry,
    Thread,
    ThreadMeta,
    save_thread,
)
from textworkspace.runs import (
    find_run,
    list_runs,
    parse_step_entry,
    to_run_thread,
)


def _make_thread(
    root: Path,
    slug: str,
    *,
    title: str = "test",
    tags: list[str],
    entries: list[Entry] | None = None,
    status: str = "open",
) -> Thread:
    slug_dir = root / slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    meta = ThreadMeta(
        title=title,
        created=datetime.utcnow().isoformat(),
        author="test",
        tags=list(tags),
        status=status,
    )
    thread = Thread(meta=meta, entries=list(entries or []), path=slug_dir / "thread.yaml")
    save_thread(thread)
    return thread


def _entry(content: str, status: str = "ok") -> Entry:
    return Entry(
        author="agent",
        timestamp=datetime.utcnow().isoformat(),
        status=status,
        content=content,
    )


# ---------------------------------------------------------------------------
# parse_step_entry
# ---------------------------------------------------------------------------


def test_parse_step_entry_full():
    content = """\
---
step_id: classify
status: ok
output_summary: verdict ping
agent_feedback: gh schema changed
agent_ideas:
  - pin gh version
  - check reviewer activity
duration_ms: 4210
retry_count: 2
---
classify step ran ok"""
    entry = _entry(content)
    step = parse_step_entry(entry)
    assert step is not None
    assert step.step_id == "classify"
    assert step.status == "ok"
    assert step.output_summary == "verdict ping"
    assert step.agent_feedback == "gh schema changed"
    assert step.agent_ideas == ["pin gh version", "check reviewer activity"]
    assert step.duration_ms == 4210
    assert step.retry_count == 2


def test_parse_step_entry_minimum():
    content = """\
---
step_id: fetch
status: ok
---
"""
    step = parse_step_entry(_entry(content))
    assert step is not None
    assert step.step_id == "fetch"
    assert step.output_summary == ""


def test_parse_step_entry_plain_text_returns_none():
    assert parse_step_entry(_entry("just a reviewer reply")) is None


def test_parse_step_entry_missing_required_returns_none():
    content = "---\nfoo: bar\n---\n"
    assert parse_step_entry(_entry(content)) is None


def test_parse_step_entry_invalid_yaml_returns_none():
    content = "---\nfoo: : bad\n---\n"
    assert parse_step_entry(_entry(content)) is None


# ---------------------------------------------------------------------------
# to_run_thread / list_runs / find_run
# ---------------------------------------------------------------------------


def test_to_run_thread_extracts_tag_values(tmp_path):
    thread = _make_thread(
        tmp_path,
        "x",
        tags=["playbook:triage-stale-pr", "repo:foo/bar", "run:abc123"],
    )
    run = to_run_thread(thread)
    assert run is not None
    assert run.playbook_slug == "triage-stale-pr"
    assert run.repo == "foo/bar"
    assert run.run_id == "abc123"


def test_to_run_thread_returns_none_when_no_playbook_tag(tmp_path):
    thread = _make_thread(tmp_path, "x", tags=["spec", "bug"])
    assert to_run_thread(thread) is None


def test_list_runs_filters_by_playbook(tmp_path):
    _make_thread(tmp_path, "a", tags=["playbook:p1"])
    _make_thread(tmp_path, "b", tags=["playbook:p2"])
    _make_thread(tmp_path, "c", tags=["spec"])  # not a run

    runs = list_runs(tmp_path)
    assert {r.slug for r in runs} == {"a", "b"}

    runs = list_runs(tmp_path, playbook="p1")
    assert [r.slug for r in runs] == ["a"]


def test_list_runs_filters_by_repo(tmp_path):
    _make_thread(tmp_path, "a", tags=["playbook:p1", "repo:foo/x"])
    _make_thread(tmp_path, "b", tags=["playbook:p1", "repo:bar/y"])

    runs = list_runs(tmp_path, repo="foo/x")
    assert [r.slug for r in runs] == ["a"]


def test_list_runs_filters_by_status(tmp_path):
    _make_thread(tmp_path, "a", tags=["playbook:p1"], status="open")
    _make_thread(tmp_path, "b", tags=["playbook:p1"], status="resolved")

    runs = list_runs(tmp_path, status="resolved")
    assert [r.slug for r in runs] == ["b"]


def test_find_run_known_slug(tmp_path):
    _make_thread(tmp_path, "x", tags=["playbook:p1"])
    run = find_run(tmp_path, "x")
    assert run is not None and run.playbook_slug == "p1"


def test_find_run_unknown_returns_none(tmp_path):
    assert find_run(tmp_path, "missing") is None


def test_find_run_non_playbook_thread_returns_none(tmp_path):
    _make_thread(tmp_path, "x", tags=["spec"])
    assert find_run(tmp_path, "x") is None


def test_run_steps_property(tmp_path):
    """RunThread.steps yields parsed StepEntries in order."""
    e1 = _entry("---\nstep_id: fetch\nstatus: ok\n---\n")
    e2 = _entry("plain reviewer comment")
    e3 = _entry("---\nstep_id: classify\nstatus: ok\noutput_summary: ping\n---\n")
    _make_thread(tmp_path, "x", tags=["playbook:p1"], entries=[e1, e2, e3])

    run = find_run(tmp_path, "x")
    assert run is not None
    steps = run.steps
    assert [s.step_id for s in steps] == ["fetch", "classify"]
    assert steps[1].output_summary == "ping"
