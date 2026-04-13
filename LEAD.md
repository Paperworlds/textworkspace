# textworkspace — Feature Context

Feature of: paperworlds (new repo: paperworlds/textworkspace)

Single entry point and package manager for the entire Paperworlds text- stack.
One install, one CLI surface. Onboards users in dependency order, bootstraps Go
binaries from GitHub releases, and supports user-defined combo commands that chain
actions across tools.

## Feature scope

### 1. Project skeleton + CLI framework

- Python package: `textworkspace`
- Binary: `textworkspace` (aliased `tw`, `xtw` via fish functions)
- CLI framework: `click` (consistent with textsessions/textprompts)
- Structure: `src/textworkspace/` with `cli.py`, `config.py`, `combos.py`, `bootstrap.py`
- pyproject.toml with dependencies on textaccounts, textsessions (optional on textmap)

### 2. Config model

Shared config namespace at `~/.config/paperworlds/`:

```
~/.config/paperworlds/
├── config.yaml          # installed tools, versions, preferences
├── combos.yaml          # user's own combos
└── combos.d/            # installed combo files
```

`config.yaml` tracks:
- Tool versions and install sources (pypi vs github binary)
- Binary paths for Go tools
- Default profile
- Proxy autostart preference

### 3. Core commands

Flat shortcuts (daily driver):
- `tw status` — unified stack view (profile, proxy state, running MCPs, session count)
- `tw switch <profile>` — textaccounts switch (needs fish wrapper for env)
- `tw sessions [query]` — textsessions browse/search
- `tw stats` — textproxy stats
- `tw serve <name|--tag>` — textserve start

Namespaced (full tool access):
- `tw accounts <cmd>`
- `tw proxy <cmd>`
- `tw servers <cmd>`
- `tw prompts <cmd>`
- `tw graph <cmd>`

Meta:
- `tw init` — guided onboarding, dependency-ordered
- `tw doctor` — health check across stack
- `tw update [tool]` — update self + managed binaries
- `tw which <tool>` — show install path + version
- `tw config` — show/edit shared config

### 4. Binary bootstrap (Go tools)

- Detect platform/arch via `platform.system()` + `platform.machine()`
- Download from GitHub releases: `paperworlds/<tool>/releases/download/v*/`
- Naming: `<tool>-v<ver>-<os>-<arch>.tar.gz`
- Verify checksum via `.sha256` sidecar
- Store in `~/.local/share/textworkspace/bin/`
- Symlink active version, keep one previous for rollback

### 5. Combo engine

YAML-based workflow recipes in `combos.yaml`:

```yaml
combos:
  workday:
    description: Switch to work, start core stack
    args: [profile]
    steps:
      - run: accounts switch {profile}
      - run: proxy start
        skip_if: proxy.running
      - run: servers start --tag core
```

Features:
- Sequential execution with early exit (--continue to ignore failures)
- Positional arg interpolation (`{profile}`)
- Conditional steps: `skip_if` and `only_if` with fixed condition set
- `--dry-run` mode
- Optional `pre`/`post` shell hooks
- Builtin combos shipped as templates (marked `builtin: true`)

Condition vocabulary:
- `proxy.running` / `proxy.stopped`
- `servers.running [--tag T / name]` / `servers.none_running`
- `accounts.active <profile>`

### 6. Combo sharing

- `tw combos install <source>` — local file, gist URL, or `gh:org/repo/name`
- `tw combos export [name|--all]` — dump to stdout
- `tw combos search <query>` — search community repo via GitHub API
- `tw combos update` — re-fetch installed combos from source
- Installed combos in `combos.d/` with `_source` and `_installed` metadata
- Modified combos skipped on update with warning

### 7. Fish shell integration

- `tw` function: wraps `textworkspace` for env-setting commands (switch)
- `xtw` alias: same as `tw`
- Pattern matches `ta`/`xta` from textaccounts

## What exists

- textaccounts: Python API at `textaccounts.api` (switch, list_profiles, env_for_profile)
- textsessions: Python API for session index queries
- textproxy: Go binary with `--json` output + HTTP API when running
- textserve: Go binary (mcp-fleet), CLI with `mcpf` commands
- textmap: not yet extracted (graph-roadmap has Kuzu DB + MCP server)

## Constraints

- Python package, distributed via pipx
- Go tools fetched as binaries, never compiled locally
- No brew dependency for end users
- All config is YAML (consistent with rest of stack)
- Graceful degradation: missing tools = warning, not crash
- `tw switch` must set env in parent shell (fish wrapper required)
- Follow click CLI patterns from textsessions/textprompts
- No docstrings unless file already uses them
- Elastic License 2.0
