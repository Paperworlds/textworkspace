# Report: 002 — Implement shared config model
Date: 2026-04-13T00:00:00Z
Status: DONE

## Changes
- 7cd6544 feat: shared config model and tw config/which commands (textworkspace)

## Test results
- textworkspace: 12 tests passed, 0 failed (0.32s)

## Notes for next prompt
- `ToolEntry` and `Config` dataclasses live in `config.py`; `load_config()` auto-creates `~/.config/paperworlds/config.yaml` on first access
- `tw config` / `tw config show` prints config as YAML; `tw config edit` opens `$EDITOR`
- `tw which <tool>` looks up tool in config and prints version, source, bin path; exits 1 if not found
- `bin` field is omitted from YAML serialisation when `None` (pypi tools)
- Tests use `monkeypatch` to redirect `CONFIG_DIR`/`CONFIG_FILE` to `tmp_path` — no real `~/.config` touched
