# Report: 006 — Combo sharing — install, export, search, update
Date: 2026-04-13T00:00:00Z
Status: DONE

## Changes
- 505ade8 feat: combo sharing — install, export, search, update (textworkspace)

## What was implemented

### `combos.py` — new sharing functions
- `install_combo(source, raw_yaml)` — parses standalone YAML, checks `requires`, saves to `combos.d/<name>.yaml` with `_source`/`_installed`/`_modified` metadata header
- `export_combo(name)` — reads `combos.d/<name>.yaml`, strips metadata, outputs standalone YAML
- `list_installed_combos()` — iterates `combos.d/`, returns files with `_source` metadata
- `update_combo(name, file_data)` — re-fetches from `_source`, returns `"updated"` / `"skipped"` / `"error:<msg>"`
- `search_community(query)` — queries GitHub API for `paperworlds/textcombos`, matches on name/tags/description
- `fetch_community_info(name)` — fetches single combo YAML from community repo
- `_fetch_url(url)` — httpx GET helper
- `_source_to_url(source)` — converts `gh:org/repo/name` to raw GitHub URL

### `cli.py` — new subcommands under `tw combos`
- `tw combos install <source>` — local path, http/https URL, or `gh:org/repo/name`
- `tw combos export [name]` / `--all`
- `tw combos update` — skips `_modified: true` combos with warning
- `tw combos search <query>`
- `tw combos info <name>`
- `tw combos remove <name>`

### File format (combos.d)
Installed combos are stored with metadata at top level + `combos:` section compatible with the existing `_load_file()` loader:
```yaml
_source: /tmp/test-combo.yaml
_installed: '2026-04-13'
_modified: false
combos:
  my-stack:
    description: ...
    steps: [...]
```

## Test results
- textworkspace: 106/106 passed (22 new tests)
- All tests complete in ~0.45s

## Notes for next prompt
- The `paperworlds/textcombos` community repo does not yet exist — `tw combos search` and `tw combos info` will fail until it's created
- `_modified: true` must be set manually by the user in the YAML file to prevent auto-update; no automatic change detection
- `tw combos update` currently skips combos from local file sources if the file is missing (reports error); this is expected
