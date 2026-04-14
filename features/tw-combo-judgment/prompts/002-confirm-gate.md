---
id: '002'
title: "confirm: human-in-the-loop gate"
repo: textworkspace
model: opus
budget_usd: 3.00
phase: phase-2
depends_on: ['001']
---

# 002 — confirm: human-in-the-loop gate

## Goal

Add `confirm:` step type that pauses combo execution and waits for user
confirmation before continuing.

## Context

Read `LEAD.md` in this feature directory for full design. After prompt 001,
the combo engine already supports `capture:` and context interpolation.

Key files:
- `src/textworkspace/combos.py` — `run_combo()`
- `tests/test_combos.py`

## Steps

1. **combos.py — confirm step type** — In the step dispatch within `run_combo()`, detect `confirm:` as a new step type (alongside `run:` and `shell:`). When encountered:
   - Interpolate the message string (supports `{variables}`)
   - Print the message with `click.echo()`
   - If `sys.stdin.isatty()`: call `click.confirm("Continue?", default=True, abort=True)`
   - If non-interactive: print warning "confirm: skipped (non-interactive)" and continue

2. **combos.py — abort handling** — When the user declines (Ctrl-C or "n"):
   - `click.confirm(..., abort=True)` raises `click.Abort`
   - Catch it in `run_combo()` and return a clean exit (print "Combo aborted.", return non-zero)
   - Do NOT re-raise — the combo stops but the CLI doesn't crash

3. **Tests** — Add `TestConfirmSteps` class to `tests/test_combos.py`:
   - `test_confirm_continues_on_yes` — mock `click.confirm` to do nothing, verify later steps run
   - `test_confirm_aborts_on_no` — mock `click.confirm` to raise `click.Abort`, verify later steps skipped
   - `test_confirm_interpolates_variables` — confirm message uses `{captured}` from prior step
   - `test_confirm_skips_noninteractive` — mock `sys.stdin.isatty()` returning False, verify combo continues with warning
   - `test_confirm_with_capture_context` — confirm after a capture step, message includes captured data

4. **Commit** — `feat(combos): add confirm: step type for human-in-the-loop gates`

## Acceptance criteria

- `confirm: "message"` pauses and waits for user input
- Declining stops the combo cleanly (no traceback)
- Non-interactive mode skips the gate with a warning
- Message supports `{variable}` interpolation
- All new tests pass, all existing tests still pass
