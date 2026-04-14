---
id: '001'
title: "capture: pipe stdout between combo steps"
repo: textworkspace
model: opus
budget_usd: 3.00
phase: phase-1
---

# 001 — capture: pipe stdout between combo steps

## Goal

Add `capture:` support to combo steps so a step's stdout can be stored in a
named variable and interpolated into later steps.

## Context

Read `LEAD.md` in this feature directory for full design. Key files:
- `src/textworkspace/combos.py` — `run_combo()`, `_interpolate()`
- `tests/test_combos.py` — existing step tests

## Steps

1. **combos.py — context dict** — In `run_combo()`, initialize a `context: dict[str, str] = {}` at the start. Pass it through to `_interpolate()` alongside args and options.

2. **combos.py — capture handling** — When a step has a `capture: <name>` key:
   - Run the subprocess with `capture_output=True, text=True`
   - Store `result.stdout.strip()` into `context[name]`
   - Still print stdout to the terminal (tee behavior: store AND display)
   - If the step had no `capture:`, run as before (stdout inherited)

3. **combos.py — interpolation** — Update `_interpolate()` to accept and merge context into the replacement dict. The merge order is: `{**args, **options, **context}` — context wins on collision (a capture can shadow an arg).

4. **Tests** — Add `TestCaptureSteps` class to `tests/test_combos.py`:
   - `test_capture_stores_stdout` — step with `capture: foo`, verify `context["foo"]` has stdout
   - `test_capture_interpolated_in_later_step` — step 1 captures, step 2 uses `{foo}` in its command
   - `test_capture_works_with_shell_and_run` — both step types support capture
   - `test_capture_output_still_printed` — verify stdout is printed even when captured
   - `test_no_capture_unchanged` — steps without capture work exactly as before

5. **Commit** — `feat(combos): add capture: step type for piping stdout between steps`

## Acceptance criteria

- `capture: name` on any step stores stdout in context
- `{name}` in later steps interpolates the captured value
- Existing combos without capture are unchanged (backward-compatible)
- All new tests pass, all existing tests still pass
