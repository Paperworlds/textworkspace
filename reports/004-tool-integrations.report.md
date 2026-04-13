# Report: 004 — Integrate Python tools via direct import
Date: 2026-04-13T00:00:00Z
Status: DONE

## Changes
- 26a68cc feat: tool integrations and unified status command (textworkspace)

## Test results
- textworkspace: 42 tests passed, 0 failed

## Notes for next prompt
- `_ta_switch`, `_ts_list`, `env_for_profile`, `list_profiles` are always present on the cli module (stub stubs when packages absent), so monkeypatching works unconditionally.
- `tw stats` queries `http://localhost:9880/stats` first, then falls back to `textproxy stats --json`.
- `tw serve` uses `shutil.which("textserve")` then `BIN_DIR/textserve`; `list` subcommand expects JSON array output from `textserve list --json`.
- `tw status` helper functions (`_status_*`) are module-level and can be monkeypatched independently.
- `tw sessions --limit` defaults to 20; `_status_sessions()` fetches up to 1000 to count totals.
