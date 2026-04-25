"""Tests for runs_ideas — aggregator over agent_ideas across run threads."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import yaml

from textworkspace.forums import Entry, Thread, ThreadMeta, save_thread
from textworkspace.runs_ideas import (
    RunIdea,
    collect_run_ideas,
    find_run_idea,
    promote,
    promoted_keys,
)


def _make_run_thread(
    forums_root: Path,
    slug: str,
    *,
    playbook: str = "p1",
    repo: str | None = "ownerA",
    entries: list[Entry] | None = None,
) -> None:
    slug_dir = forums_root / slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    tags = [f"playbook:{playbook}"]
    if repo:
        tags.append(f"repo:{repo}")
    meta = ThreadMeta(
        title=f"{playbook} run",
        created=datetime.utcnow().isoformat(),
        author="agent",
        tags=tags,
    )
    thread = Thread(meta=meta, entries=list(entries or []), path=slug_dir / "thread.yaml")
    save_thread(thread)


def _step_entry(step_id: str, ideas: list[str], feedback: str = "") -> Entry:
    front = {"step_id": step_id, "status": "ok", "output_summary": "ok"}
    if ideas:
        front["agent_ideas"] = ideas
    if feedback:
        front["agent_feedback"] = feedback
    fm = yaml.safe_dump(front, default_flow_style=False, sort_keys=False).strip()
    return Entry(
        author="agent",
        timestamp=datetime.utcnow().isoformat(),
        status="ok",
        content=f"---\n{fm}\n---\nstep ran",
    )


# ---------------------------------------------------------------------------
# collect_run_ideas
# ---------------------------------------------------------------------------


def test_collect_yields_one_per_idea(tmp_path):
    _make_run_thread(tmp_path, "run-a", entries=[
        _step_entry("classify", ["pin gh", "check reviewer"], feedback="schema drift"),
        _step_entry("post", []),
    ])
    ideas = collect_run_ideas(tmp_path)
    assert len(ideas) == 2
    assert {i.text for i in ideas} == {"pin gh", "check reviewer"}
    assert ideas[0].step_id == "classify"
    assert ideas[0].idea_index == 0
    assert ideas[1].idea_index == 1
    assert ideas[0].agent_feedback == "schema drift"


def test_collect_only_playbook_threads(tmp_path):
    _make_run_thread(tmp_path, "run-a", entries=[_step_entry("s1", ["one"])])
    # Plain forum thread (no playbook tag) — should be ignored.
    plain = tmp_path / "plain"
    plain.mkdir()
    Thread(
        meta=ThreadMeta(
            title="plain", created=datetime.utcnow().isoformat(),
            author="x", tags=["spec"],
        ),
        entries=[_step_entry("s1", ["should-not-appear"])],
        path=plain / "thread.yaml",
    )
    save_thread(Thread(
        meta=ThreadMeta(
            title="plain", created=datetime.utcnow().isoformat(),
            author="x", tags=["spec"],
        ),
        entries=[_step_entry("s1", ["should-not-appear"])],
        path=plain / "thread.yaml",
    ))

    ideas = collect_run_ideas(tmp_path)
    assert [i.text for i in ideas] == ["one"]


def test_find_run_idea(tmp_path):
    _make_run_thread(tmp_path, "run-a", entries=[
        _step_entry("classify", ["a", "b", "c"]),
    ])
    ri = find_run_idea(tmp_path, "run-a", "classify", 1)
    assert ri is not None and ri.text == "b"
    assert find_run_idea(tmp_path, "run-a", "classify", 99) is None
    assert find_run_idea(tmp_path, "missing", "classify", 0) is None


# ---------------------------------------------------------------------------
# promoted_keys
# ---------------------------------------------------------------------------


def test_promoted_keys_finds_provenance(tmp_path):
    repo = tmp_path / "ownerA"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "IDEAS.yaml").write_text(yaml.safe_dump({
        "ideas": [
            {"id": "from-run-x", "title": "promoted", "status": "idea",
             "from_run": "run-a", "from_step": "classify", "from_idea_index": 0},
            {"id": "fresh", "title": "no provenance", "status": "idea"},
        ]
    }))
    keys = promoted_keys({"ownerA": repo})
    assert keys == {("run-a", "classify", 0)}


def test_promoted_keys_empty_when_no_repos(tmp_path):
    assert promoted_keys({}) == set()


# ---------------------------------------------------------------------------
# promote
# ---------------------------------------------------------------------------


def test_promote_creates_ideas_file_when_missing(tmp_path):
    target = tmp_path / "ownerA"
    target.mkdir()

    ri = RunIdea(
        run_slug="run-a", playbook_slug="p1", repo="ownerA",
        step_id="classify", idea_index=0, text="pin gh version",
    )
    written = promote(ri, target, promoted_by="paolo", promoted_at="2026-04-25")

    assert written == target / "docs" / "IDEAS.yaml"
    data = yaml.safe_load(written.read_text())
    assert "ideas" in data
    assert len(data["ideas"]) == 1
    entry = data["ideas"][0]
    assert entry["from_run"] == "run-a"
    assert entry["from_step"] == "classify"
    assert entry["from_idea_index"] == 0
    assert entry["from_playbook"] == "p1"
    assert entry["promoted_by"] == "paolo"
    assert entry["promoted_at"] == "2026-04-25"
    assert entry["title"].startswith("pin gh")


def test_promote_appends_to_existing_list(tmp_path):
    target = tmp_path / "ownerA"
    (target / "docs").mkdir(parents=True)
    (target / "docs" / "IDEAS.yaml").write_text(yaml.safe_dump({
        "ideas": [{"id": "existing", "title": "x", "status": "idea"}]
    }))

    ri = RunIdea("run-a", "p1", "ownerA", "classify", 0, "new one")
    promote(ri, target, promoted_by="x", promoted_at="2026-04-25")

    data = yaml.safe_load((target / "docs" / "IDEAS.yaml").read_text())
    assert len(data["ideas"]) == 2
    assert data["ideas"][0]["id"] == "existing"
    assert data["ideas"][1]["from_run"] == "run-a"


def test_promote_then_promoted_keys_round_trip(tmp_path):
    target = tmp_path / "ownerA"
    target.mkdir()
    ri = RunIdea("run-a", "p1", "ownerA", "classify", 2, "third idea")
    promote(ri, target, promoted_by="x", promoted_at="2026-04-25")

    keys = promoted_keys({"ownerA": target})
    assert keys == {("run-a", "classify", 2)}
