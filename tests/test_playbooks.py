"""Tests for playbook discovery + parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from textworkspace.playbooks import (
    Playbook,
    discover_playbooks,
    find_playbook,
    parse_playbook_file,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


VALID_MIN = """\
slug: pb-min
owner: textworkspace
persona: pr-reviewer
steps:
  - id: fetch
    kind: run
    run: gh pr view 1
"""


VALID_FULL = """\
slug: pb-full
owner: textworkspace
status: draft
version: 0.2.0
persona: pr-reviewer
description: Fetch + classify + post
consumers: [textworkspace]
inputs:
  - name: pr_number
    type: int
    required: true
outputs:
  - kind: forum-thread
    tag: "playbook:pb-full"
budget:
  max_turns: 3
  budget_usd: 0.10
steps:
  - id: fetch
    kind: run
    run: gh pr view ${inputs.pr_number}
    out: pr
  - id: classify
    kind: persona_turn
    persona_turn: |
      Classify the PR.
    out: verdict
  - id: post
    kind: run
    skip_if: "${steps.classify.out} startswith 'LEAVE'"
    run: textforums new --content "..."
"""


# ---------------------------------------------------------------------------
# parse_playbook_file
# ---------------------------------------------------------------------------


def test_parse_minimum_required_fields(tmp_path):
    path = _write(tmp_path / "pb.yaml", VALID_MIN)
    pb = parse_playbook_file(path)
    assert pb.slug == "pb-min"
    assert pb.owner == "textworkspace"
    assert pb.persona == "pr-reviewer"
    assert pb.status == "draft"          # default
    assert pb.version == "0.1.0"         # default
    assert len(pb.steps) == 1
    assert pb.steps[0].id == "fetch"
    assert pb.steps[0].kind == "run"
    assert pb.steps[0].body == "gh pr view 1"


def test_parse_full(tmp_path):
    path = _write(tmp_path / "pb.yaml", VALID_FULL)
    pb = parse_playbook_file(path)
    assert pb.version == "0.2.0"
    assert pb.description == "Fetch + classify + post"
    assert pb.consumers == ["textworkspace"]
    assert len(pb.inputs) == 1 and pb.inputs[0].name == "pr_number" and pb.inputs[0].type == "int"
    assert len(pb.outputs) == 1 and pb.outputs[0].kind == "forum-thread"
    assert pb.budget == {"max_turns": 3, "budget_usd": 0.10}
    assert [s.id for s in pb.steps] == ["fetch", "classify", "post"]
    assert pb.steps[1].kind == "persona_turn"
    assert pb.steps[1].out == "verdict"
    assert pb.steps[2].skip_if and "LEAVE" in pb.steps[2].skip_if


def test_parse_missing_slug(tmp_path):
    path = _write(tmp_path / "pb.yaml", "owner: x\npersona: y\nsteps: [{id: a, kind: run, run: ls}]\n")
    with pytest.raises(ValueError, match="missing required field 'slug'"):
        parse_playbook_file(path)


def test_parse_invalid_status(tmp_path):
    text = VALID_MIN.replace("persona: pr-reviewer", "persona: pr-reviewer\nstatus: published")
    path = _write(tmp_path / "pb.yaml", text)
    with pytest.raises(ValueError, match="unknown status"):
        parse_playbook_file(path)


def test_parse_invalid_step_kind(tmp_path):
    text = """\
slug: pb
owner: x
persona: y
steps:
  - id: bad
    kind: subprocess
    run: ls
"""
    path = _write(tmp_path / "pb.yaml", text)
    with pytest.raises(ValueError, match="invalid kind"):
        parse_playbook_file(path)


def test_parse_persona_turn_missing_body(tmp_path):
    text = """\
slug: pb
owner: x
persona: y
steps:
  - id: ask
    kind: persona_turn
"""
    path = _write(tmp_path / "pb.yaml", text)
    with pytest.raises(ValueError, match="missing required 'persona_turn'"):
        parse_playbook_file(path)


def test_parse_run_missing_command(tmp_path):
    text = """\
slug: pb
owner: x
persona: y
steps:
  - id: cmd
    kind: run
"""
    path = _write(tmp_path / "pb.yaml", text)
    with pytest.raises(ValueError, match="missing required 'run'"):
        parse_playbook_file(path)


def test_parse_v2_reserved_keys_rejected(tmp_path):
    """v1 must reject sub_playbook / when / for_each — schema reserves these."""
    for key in ("sub_playbook", "when", "for_each"):
        text = f"""\
slug: pb
owner: x
persona: y
steps:
  - id: a
    kind: run
    run: ls
    {key}: anything
"""
        path = _write(tmp_path / f"pb-{key}.yaml", text)
        with pytest.raises(ValueError, match="reserved for v2"):
            parse_playbook_file(path)


def test_parse_duplicate_step_id(tmp_path):
    text = """\
slug: pb
owner: x
persona: y
steps:
  - id: same
    kind: run
    run: ls
  - id: same
    kind: run
    run: pwd
"""
    path = _write(tmp_path / "pb.yaml", text)
    with pytest.raises(ValueError, match="duplicate step id"):
        parse_playbook_file(path)


def test_parse_empty_steps(tmp_path):
    text = "slug: pb\nowner: x\npersona: y\nsteps: []\n"
    path = _write(tmp_path / "pb.yaml", text)
    with pytest.raises(ValueError, match="non-empty list"):
        parse_playbook_file(path)


def test_parse_invalid_yaml(tmp_path):
    path = _write(tmp_path / "pb.yaml", "slug: x\n  bad:\nindent: -")
    with pytest.raises(ValueError, match="invalid YAML"):
        parse_playbook_file(path)


# ---------------------------------------------------------------------------
# discover_playbooks
# ---------------------------------------------------------------------------


def test_discover_walks_owner_repos(tmp_path):
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    _write(repo_a / "docs/specs/playbooks/one.yaml", VALID_MIN)
    _write(repo_b / "docs/specs/playbooks/two.yaml", VALID_FULL)

    result = discover_playbooks(tmp_path)
    assert {p.slug for p in result.playbooks} == {"pb-min", "pb-full"}
    assert result.errors == []


def test_discover_skips_underscore_files(tmp_path):
    """_schema.json and other meta files must not be parsed as playbooks."""
    repo = tmp_path / "repo"
    _write(repo / "docs/specs/playbooks/real.yaml", VALID_MIN)
    _write(repo / "docs/specs/playbooks/_schema.yaml", "{}")  # would be invalid otherwise

    result = discover_playbooks(tmp_path)
    assert [p.slug for p in result.playbooks] == ["pb-min"]
    assert result.errors == []


def test_discover_collects_errors_without_aborting(tmp_path):
    """One bad file does not break discovery for the rest."""
    repo = tmp_path / "repo"
    _write(repo / "docs/specs/playbooks/good.yaml", VALID_MIN)
    _write(repo / "docs/specs/playbooks/bad.yaml", "this is: not\n  valid: -indent")

    result = discover_playbooks(tmp_path)
    assert [p.slug for p in result.playbooks] == ["pb-min"]
    assert len(result.errors) == 1
    assert result.errors[0][0].name == "bad.yaml"


def test_discover_skips_symlinks_and_dotfiles(tmp_path):
    real = tmp_path / "real"
    _write(real / "docs/specs/playbooks/x.yaml", VALID_MIN)
    (tmp_path / "linky").symlink_to(real)
    (tmp_path / ".hidden").mkdir()

    result = discover_playbooks(tmp_path)
    # Only the real repo should contribute.
    assert len(result.playbooks) == 1


def test_discover_empty_dev_root(tmp_path):
    result = discover_playbooks(tmp_path)
    assert result.playbooks == [] and result.errors == []


def test_discover_accepts_explicit_repo_map(tmp_path):
    repo = tmp_path / "owner"
    _write(repo / "docs/specs/playbooks/x.yaml", VALID_MIN)
    result = discover_playbooks({"owner": repo})
    assert len(result.playbooks) == 1


def test_find_playbook_by_slug(tmp_path):
    repo = tmp_path / "owner"
    _write(repo / "docs/specs/playbooks/one.yaml", VALID_MIN)
    _write(repo / "docs/specs/playbooks/two.yaml", VALID_FULL)

    pb = find_playbook(tmp_path, "pb-full")
    assert pb is not None and pb.slug == "pb-full"
    assert find_playbook(tmp_path, "missing") is None
