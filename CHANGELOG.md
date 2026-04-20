# Changelog

All notable changes to textworkspace are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## v0.4.1

- `_tool_version` timeout raised from 3s to 15s — cold Python startup after a fresh `uv tool install --force` exceeds 3s, causing version to read as `unknown`
- CI: GitHub Actions workflow runs `pytest` on every push and PR to `main`
- Tests: regression tests for `_tool_version` (timeout returns `unknown`, version string parsing, `None` bin path)

**Tests — 250 passing**

| Area | Coverage | Notes |
|---|---|---|
| CLI commands | high | all prior coverage plus `_tool_version` unit tests |
| Config load/save | high | round-trip, validation, field omission, YAML format |
| Combo engine | high | load, run, conditions, options, dry-run, install, export, update, search |
| Binary bootstrap | high | platform detection, download, checksum, symlink management, version pruning |
| Forums | medium | new/list/show/add/close/reopen, slug generation, file attachments |
| Shell generation | medium | fish/bash/zsh wrapper output, `tw shell install` |
| Not covered | — | live subprocesses (textproxy, textserve, textaccounts) — mocked throughout |

---

## v0.4.0

Structured refactor pass — no behaviour changes.

- `_TEXTPROXY_DEFAULT_PORT` and `_get_textproxy_port()` defined once in `config.py`, removed from `combos.py`, `doctor.py`, and `cli.py`
- Inline stdlib imports (`json`, `re`, `socket`, `yaml`) moved to module level in `cli.py` and `combos.py`
- `except Exception` in `_tool_version` narrowed to `(OSError, CalledProcessError, TimeoutExpired, ValueError)`
- `__init__.py` fallback changed from hardcoded `"0.3.0"` to `"unknown"` per convention
- `tests/conftest.py` added with shared `config_dir` fixture; 14 tests in `test_cli.py` updated to use it
- REFACTORS.md code example updated: `_sp` alias → plain `subprocess`
- Stale `test_version` assertion corrected from `0.2.3` to current version

**Tests — 180 passing**

| Area | Coverage | Notes |
|---|---|---|
| CLI commands | high | init, doctor, update, which, switch, sessions, stats, proxy, serve, status, combos, config, shell, dev, tools via CliRunner |
| Config load/save | high | round-trip, validation, field omission, YAML format |
| Combo engine | high | load, run, conditions, options, dry-run, install, export, update, search |
| Binary bootstrap | high | platform detection, download, checksum, symlink management, version pruning |
| Forums | medium | new/list/show/add/close/reopen, slug generation, file attachments |
| Shell generation | medium | fish/bash/zsh wrapper output, `tw shell install` |
| Not covered | — | live subprocesses (textproxy, textserve, textaccounts) — mocked throughout |

---

## [v0.3.0] — 2026-04-15

### Added

- **`tw proxy`** group — manage textproxy daemon from textworkspace: `start`, `stop`, `restart`, `log`, `os`, `os-install`, `os-uninstall`, `setup`. `tw proxy` with no args shows running state.
- **`tw tools`** group — third-party software registry: `list`, `add`, `install`. Register any binary (brew/url/script/path install methods). Persisted under `third_party:` in config.yaml.
- **`tw dev install`** — now also builds Go tools from local repo checkouts via `just install` (falls back to `make`). textproxy is the first registered Go dev tool.
- **`status.py`** — implemented proxy status via `textproxy status` subprocess. Parses running/stopped state, pid, port, version.
- **`ThirdPartyEntry`** config schema — `bin`, `description`, `required`, `install` (method + value), `version`. Loads/saves round-trip cleanly.
- **`tw doctor`** — shows all registered third-party tools with install status; `tw tools install <name>` fix hint.

---

## [v0.2.3] — 2026-04-15

### Added

- **`tw dev install`** — renamed from `tw dev reinstall`. Prints installed version (with git hash) after each tool.
- **`sync` combo** — built-in combo that runs `tw dev install` to reinstall all dev tools in one step.
- **Git hash in version string** — `tw --version` now shows `0.2.3 (abc1234)` when running from a git checkout. Matches textsessions convention.
- **`tw doctor`** — shows textworkspace itself as the first entry. Source label reads from config (`dev` vs `pypi`) rather than hardcoding.

### Fixed

- `tw shell install` now translates `switch` → `show` for the textaccounts fish wrapper, fixing `ta switch <profile>` which had no `switch` subcommand.

---

## [v0.2.2] — 2026-04-14

### Added

- **`tw shell install`** — one-stop install for the full stack: generates fish functions and completions for textaccounts, textsessions, textworkspace, and all aliases.

### Changed

- Removed per-tool `ta`/`ts` fish alias generation from textworkspace — each tool now owns its own shell install.

---

## [v0.2.1] — 2026-04-14

### Added

- **`tw status`** — shows current dev mode and total combos count.
- **Combo engine shell steps** — `shell:` step type for multi-line scripts; `options:` system for user-configurable combo parameters. Built-in `go` combo for profile + repo switching.

### Fixed

- `tw dev on` now includes textworkspace itself in editable installs so `tw` on PATH stays in sync.

---

## [v0.2.0] — 2026-04-14

### Added

- **`textforums`** standalone CLI — file-based async message board for cross-repo agent coordination. Threads stored as YAML at `~/.textforums/<slug>/thread.yaml`.
- Commands: `new`, `list`, `show`, `add`, `close`, `reopen`, `edit`.
- Also available as `tw forums <subcommand>`.
- Config integration: `forums.root` and `forums.author` in `~/.config/paperworlds/config.yaml`.
- `$TEXTFORUMS_ROOT` env override.

---

## [v0.1.1] — 2026-04-13

### Added

- **`tw dev`** command group — developer mode for working from local repo checkouts.
  - `tw dev on [path]` — enable developer mode, install Python tools as editable uv tools.
  - `tw dev off` — restore PyPI installs.
  - `tw dev install` — re-run editable installs after version bumps.
- **`tw shell install`** — generate fish functions and completions.
- Tab completions for fish, bash, and zsh.
- Session count (active today) in `tw status`.

---

## [v0.1.0] — 2026-04-13

### Added

#### Core CLI
- **`tw init`** — Guided onboarding: detects existing tools, prompts for dependencies, bootstraps Go binaries
- **`tw status`** — Unified stack view: active profile, proxy state, running servers, session count
- **`tw doctor`** — Health checks: verifies binaries, Python dependencies, services, and configuration
- **`tw update [tool]`** — Update self and all managed binaries to latest versions from PyPI and GitHub releases
- **`tw switch <profile>`** — Switch active workspace profile via textaccounts (fish wrapper for env setting)
- **`tw sessions [query]`** — Browse and search textsessions with optional limit
- **`tw stats [--session]`** — Aggregate token and request stats across sessions and accounts
- **`tw serve <name|--tag>`** — Start local HTTP API server (textserve/mcpf)
- **`tw which <tool>`** — Show install path and version of a managed binary
- **`tw config`** — View or edit `~/.config/paperworlds/config.yaml`
- **`tw shell [--fish]`** — Generate shell functions for fish setup

#### Configuration
- YAML-based config at `~/.config/paperworlds/config.yaml`
- Tracks installed tools: version, source (PyPI or GitHub), binary paths
- Preferences: default profile, proxy autostart flag
- Automatic config creation on first use

#### Combo Engine
- **`tw combos list`** — List all available combos (built-in + user-defined + installed)
- **`tw combos edit`** — Edit `~/.config/paperworlds/combos.yaml`
- **`tw combos add <name>`** — Interactively create a new combo
- **`tw combos run <name> [args]`** — Execute a combo with optional positional arguments
- Sequential combo execution with early exit (use `--continue` to ignore failures)
- **Combo steps**: simple `run:` directives with shell command interpolation
- **Conditional steps**: `skip_if:` and `only_if:` with built-in conditions
- **Dry-run mode**: `--dry-run` preview combo steps without executing
- **Built-in combos**: shipped as templates (up, down, reset)
  - `up` — Start proxy and default servers
  - `down` — Stop all servers and proxy
  - `reset <profile>` — Switch profile and restart proxy/servers

#### Combo Conditions
- `proxy.running` — Check if proxy is running
- `proxy.stopped` — Check if proxy is stopped
- `servers.running [--tag T / name]` — Check if any/specific server is running
- `servers.none_running` — Check if no servers are running
- `accounts.active <profile>` — Check if profile is active

#### Combo Sharing
- **`tw combos install <source>`** — Install combos from:
  - Local files: `~/my-combos.yaml`
  - GitHub: `gh:paperworlds/textcombos/name`
  - URLs: `https://gist.github.com/user/xyz`
- **`tw combos export [name|--all]`** — Export combos to stdout for sharing
- **`tw combos search <query>`** — Search community repo (paperworlds/textcombos) via GitHub API
- **`tw combos info <name>`** — Show detailed info for a combo
- **`tw combos update`** — Re-fetch installed combos from original sources
- **`tw combos remove <name>`** — Delete a user combo

#### Binary Bootstrap (Go Tools)
- Platform detection: Linux/Darwin, x86_64/arm64
- Download from GitHub releases: `paperworlds/<tool>/releases/download/v*/`
- Archive format: `<tool>-v<ver>-<os>-<arch>.tar.gz`
- Checksum verification via `.sha256` sidecar
- Storage: `~/.local/share/textworkspace/bin/`
- Version management: symlink active version, keep one previous for rollback
- Graceful fallback: missing binaries warn but don't crash

#### Fish Shell Integration
- Automatic setup via `tw init` or manual: `tw shell --fish >> ~/.config/fish/conf.d/paperworlds.fish`
- **`tw` wrapper function** — Handles `__TW_EVAL__` protocol for env-setting commands (e.g., `tw switch`)
- **`xtw` alias** — Shorthand for `tw`
- **`xta`, `xts`, `xtp`, `xtg`** — Aliases for textaccounts, textsessions, textproxy, textgraph

#### Integration
- Graceful degradation: optional integration with textaccounts and textsessions
- Falls back to no-op if packages not installed
- Unified status display across all tools
- Support for named workspaces/profiles

### Technical Details

- **Python 3.11+**, built with hatchling, managed with `uv`
- **Dependencies**: click, PyYAML, requests, pydantic
- **Optional integrations**: textaccounts, textsessions (auto-detected)
- **Configuration**: `~/.config/paperworlds/` (shared namespace with all text- tools)
- **Licensing**: Elastic License 2.0

### Known Limitations

- `tw switch` requires fish shell wrapper to set environment variables in parent shell
- Combo `pre`/`post` hooks not yet implemented
- Telegram notifications for approval workflow planned for future release
- textmap integration planned for graph operations

### Testing

- Comprehensive CLI smoke tests (version, help, subcommands)
- Config load/save/round-trip tests with validation
- Combo engine tests: loading, execution, conditions, interpolation
- Binary bootstrap tests: platform detection, GitHub API, checksum verification
- Combo sharing tests: install, export, search, update
- All tests in `tests/test_cli.py` using pytest and click.testing.CliRunner

---

## Links

- **Repository**: https://github.com/paperworlds/textworkspace
- **Issues**: https://github.com/paperworlds/textworkspace/issues
- **Paperworlds Stack**: https://github.com/paperworlds
