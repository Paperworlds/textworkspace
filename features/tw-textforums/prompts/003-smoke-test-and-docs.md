---
id: '003'
title: Smoke test and documentation
repo: textworkspace
model: sonnet
budget_usd: 1.50
phase: phase-1
depends_on: ['002']
---

# 003 — Smoke test and documentation

## Goal

End-to-end smoke test, update CLAUDE.md, bump version if needed.

## Depends on
002-cli-commands

## Steps

1. **Smoke test** — Run manually and verify:
   - `uv sync` installs `textforums` binary
   - `textforums new --title "test thread" --content "hello world" --tag test`
   - `textforums list` — shows the thread
   - `textforums add test-thread --content "reply here" --status ack`
   - `textforums show test-thread` — shows meta + 2 entries
   - `tw forums list` — same as standalone
   - `textforums close test-thread --content "all done"`
   - `textforums reopen test-thread`
   - Clean up: `rm -rf ~/.textforums/test-thread*`

2. **Run full test suite** — `uv run pytest tests/ -v` — all tests pass

3. **Update CLAUDE.md** — Add textforums to the Structure section

4. **Update CONVENTIONS.md or docs** if they exist — add textforums usage

## Commit message
docs: add textforums to project documentation
