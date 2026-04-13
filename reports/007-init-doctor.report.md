# Report: 007 — Guided init onboarding and doctor diagnostics
Date: 2026-04-13T00:00:00Z
Status: DONE

## Changes
- 12b30a8 feat: guided init onboarding and doctor diagnostics (textworkspace)

## What was implemented

### New file: `src/textworkspace/doctor.py`
- `ToolInfo` dataclass — holds installed/version/source/bin_path/importable per tool
- `detect_installed_tools()` — checks PATH, importlib.util.find_spec, importlib.metadata, managed BIN_DIR, and config for all 4 tools (textaccounts, textsessions, textproxy, textserve)
- `CheckResult` dataclass — holds label/detail/status/fix for a single doctor check
- `run_doctor_checks()` — runs all checks: per-tool, config.yaml, combos, fish functions, proxy port, servers/registry
- `_is_port_responding()` — TCP probe helper

### Updated: `src/textworkspace/cli.py`
- `tw init` — full guided onboarding: detects tools, walks textaccounts → textproxy → textsessions → textserve in dependency order with click.confirm prompts, writes config.yaml + combos.yaml
- `tw doctor` — aligned column output (label / detail / ok|warn|FAIL / fix hint)
- Private helpers: `_init_textaccounts/proxy/sessions/serve`, `_bootstrap_go_tool`

### Updated: `tests/test_cli.py`
- 14 new tests: `_detect_python_tool` (found/missing/path-only), Go tool detection from BIN_DIR, `run_doctor_checks` (all-ok, missing required tool, missing config, partial fish, proxy responding), `tw init` CLI (creates files, registers tools, preserves existing combos.yaml), `tw doctor` output format

### Updated: `tests/test_combos.py`
- Fixed `test_init_creates_combos_yaml` to mock `detect_installed_tools` (needed after `tw init` became interactive)

## Test results
- textworkspace: 121/121 passed (0.49s)

## Notes for next prompt
- `tw shell install` is referenced in doctor fix hints but not yet implemented — fish function generation is in `shell.py` but there's no `tw shell` CLI subcommand
- `textserve registry.yaml` check probes `~/.config/paperworlds/registry.yaml` and `~/.textserve/registry.yaml`; the real path may differ when textserve is implemented
