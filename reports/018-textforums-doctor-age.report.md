# Report: 018 — textforums doctor — machine-readable stale-thread output for tw doctor
Date: 2026-04-20T16:12:00Z
Status: DONE

## Changes
- 811e5b9 forums: add doctor command for machine-readable stale-thread output (textworkspace)

## What was added

### `forums.py`
- `stale_threads(root, age_days=14) -> list[tuple[str, int]]` — returns `(slug, days_idle)` for open threads idle for ≥ `age_days` days. Staleness is computed from the last entry timestamp (falls back to `created` if no entries).
- `textforums doctor [--age-days N]` CLI subcommand — prints one line per stale thread: `STALE <slug> <days>d`. Silent if no stale threads.

### `doctor.py`
- `run_doctor_checks()` now calls `stale_threads()` directly (no subprocess) and emits a `warn`-level `CheckResult` per stale thread with `fix: textforums close <slug>`.

## Test results
- textworkspace: 78 forum tests passed, 293 total (1 pre-existing unrelated failure in `test_status_with_mocked_integrations` due to `textserve list --json` not being supported)

## Notes for next prompt
- The stale threshold defaults to 14 days; `--age-days` can override it on the CLI. The `tw doctor` integration uses the 14-day default hardcoded — if a configurable threshold is desired, it could be read from `config.forums.stale_days`.
- `textforums doctor` output format: `STALE <slug> <days>d` — consistent with the existing STALE protocol used by other tools.
