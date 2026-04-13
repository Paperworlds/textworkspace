# Changelog

All notable changes to textworkspace are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
