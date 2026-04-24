"""Tests for textworkspace.rename_sweep."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from textworkspace.config import Config, RepoEntry
from textworkspace.rename_sweep import (
    RenamePlan,
    apply_plan,
    format_plan,
    plan_rename,
)


def _write_thread(root: Path, slug: str, *, repos: list[str], tags: list[str]) -> Path:
    (root / slug).mkdir(parents=True, exist_ok=True)
    path = root / slug / "thread.yaml"
    data = {
        "meta": {
            "title": slug,
            "created": "2026-04-24T00:00:00Z",
            "author": "x",
            "tags": tags,
            "status": "open",
            "context": {"repos": repos},
        },
        "entries": [],
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def test_plan_rejects_same_name():
    cfg = Config()
    with pytest.raises(ValueError):
        plan_rename(cfg, Path("/tmp"), "foo", "foo")


def test_plan_config_entry_rename(tmp_path):
    cfg = Config()
    cfg.repos["paperagents"] = RepoEntry(path=str(tmp_path), profile="personal")
    plan = plan_rename(cfg, tmp_path, "paperagents", "textprompts")
    assert plan.config_change is not None
    assert "paperagents" in plan.config_change.detail
    assert "textprompts" in plan.config_change.detail


def test_plan_thread_context_repos(tmp_path):
    forums = tmp_path / "forums"
    _write_thread(forums, "t1", repos=["paperagents", "textworkspace"], tags=["x"])
    _write_thread(forums, "t2", repos=["unrelated"], tags=[])

    plan = plan_rename(Config(), forums, "paperagents", "textprompts")
    # Only t1 matches.
    paths = [p.parent.name for p, _ in plan.thread_changes]
    assert paths == ["t1"]
    changes = plan.thread_changes[0][1]
    assert any(c.kind == "thread.context.repos" for c in changes)


def test_plan_thread_idea_tags(tmp_path):
    forums = tmp_path / "forums"
    _write_thread(forums, "t1", repos=["other"], tags=[
        "idea:paperagents/some-id",
        "idea:paperagents/another",
        "idea:textworkspace/unaffected",
        "random-tag",
    ])
    plan = plan_rename(Config(), forums, "paperagents", "textprompts")
    changes = plan.thread_changes[0][1]
    tag_changes = [c for c in changes if c.kind == "thread.tag"]
    assert len(tag_changes) == 2
    # Other-repo idea tag untouched, random tag untouched.
    details = "\n".join(c.detail for c in tag_changes)
    assert "idea:textworkspace/unaffected" not in details
    assert "random-tag" not in details


def test_apply_rewrites_thread_file(tmp_path):
    forums = tmp_path / "forums"
    path = _write_thread(forums, "t", repos=["paperagents", "other"], tags=[
        "idea:paperagents/xid", "plain"
    ])
    cfg = Config()
    cfg.repos["paperagents"] = RepoEntry(path=str(tmp_path))

    plan = plan_rename(cfg, forums, "paperagents", "textprompts")
    apply_plan(plan, cfg, forums)

    data = yaml.safe_load(path.read_text())
    assert data["meta"]["context"]["repos"] == ["textprompts", "other"]
    assert "idea:textprompts/xid" in data["meta"]["tags"]
    assert "plain" in data["meta"]["tags"]
    # And the config key is renamed.
    assert "textprompts" in cfg.repos
    assert "paperagents" not in cfg.repos


def test_apply_is_noop_when_nothing_matches(tmp_path):
    forums = tmp_path / "forums"
    _write_thread(forums, "t", repos=["other"], tags=["plain"])
    cfg = Config()
    cfg.repos["other"] = RepoEntry(path=str(tmp_path))

    plan = plan_rename(cfg, forums, "ghost", "newname")
    assert plan.total_changes == 0
    apply_plan(plan, cfg, forums)    # should not raise
    assert "other" in cfg.repos
    assert "ghost" not in cfg.repos
    assert "newname" not in cfg.repos


def test_decision_export_dir_cleared_on_apply(tmp_path):
    forums = tmp_path / "forums"
    export = tmp_path / "export"
    export.mkdir()
    (export / "decision-a.md").write_text("x")
    (export / "decision-b.md").write_text("x")
    (export / "README.md").write_text("kept")   # non-decision file kept

    cfg = Config()
    cfg.repos["old"] = RepoEntry(path=str(tmp_path))
    plan = plan_rename(cfg, forums, "old", "new", decision_export_dir=export)
    apply_plan(plan, cfg, forums)

    assert not (export / "decision-a.md").exists()
    assert not (export / "decision-b.md").exists()
    assert (export / "README.md").exists()


def test_format_plan_empty_is_readable(tmp_path):
    plan = RenamePlan(old="a", new="b")
    out = format_plan(plan)
    assert "nothing to do" in out


def test_format_plan_with_changes(tmp_path):
    forums = tmp_path / "forums"
    _write_thread(forums, "t", repos=["paperagents"], tags=["idea:paperagents/x"])
    cfg = Config()
    cfg.repos["paperagents"] = RepoEntry(path=str(tmp_path))
    plan = plan_rename(cfg, forums, "paperagents", "textprompts")
    out = format_plan(plan)
    assert "paperagents → textprompts" in out
    assert "config.yaml" in out
    assert "forum threads" in out
