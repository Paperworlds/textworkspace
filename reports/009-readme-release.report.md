# Report: 009 — README, CHANGELOG, and release prep

**Date:** 2026-04-13T17:28:52Z  
**Status:** DONE

## Summary

Successfully completed v0.1.0 release prep for textworkspace. README and CHANGELOG are comprehensive, all tests pass, and all commands are functional.

## Changes

- **e9d09f4** — docs: README and CHANGELOG for v0.1.0 release (textworkspace)

## Deliverables

### README.md
- **Quick start**: Installation via pipx, tw init walkthrough, tw status overview
- **CLI reference table**: All commands with descriptions (13 entries)
- **Combo examples**: Built-in combos (up, down, reset), custom combo YAML syntax
- **Combo conditions**: Fixed condition set (proxy.running/stopped, servers.running, accounts.active)
- **Combo sharing**: install, export, search, info, update, remove subcommands
- **Fish shell setup**: Automatic via tw init, manual setup instructions
- **Configuration**: config.yaml structure, combos.yaml + combos.d/ directory layout
- **Supported tools**: Required (textaccounts, textsessions), optional Go tools (textproxy, textserve)
- **Binary bootstrap**: Platform detection, GitHub release download, checksum verification, rollback strategy

### CHANGELOG.md
- **v0.1.0** with complete feature list:
  - Core CLI: 12 commands (init, status, doctor, update, switch, sessions, stats, serve, which, config, shell, combos)
  - Configuration: YAML-based at ~/.config/paperworlds/
  - Combo engine: YAML recipes, conditions, dry-run, continue-on-error
  - Combo sharing: install (local/GitHub), export, search, update, remove
  - Binary bootstrap: Platform detection, GitHub releases, checksums, version management
  - Fish integration: tw wrapper, xtw alias, x-aliases
  - Integration: Graceful degradation for textaccounts + textsessions
  - Known limitations: fish wrapper required for tw switch, pre/post hooks not yet implemented

## Test Results

- **textworkspace**: 121/121 tests passed ✓
  - CLI smoke tests (version, help, subcommands)
  - Config load/save/round-trip
  - Combo loading and execution
  - Conditions and interpolation
  - Binary bootstrap and platform detection
  - Combo sharing (install, export, search, update)
  - Integration tests

## Verification

- `tw --help` — Shows 13 commands (12 built-in + dynamic combos)
- `tw doctor` — Runs and reports on tools, config, combos, fish setup, proxy, servers
- `tw init --dry-run` — Shows planned initialization steps
- `tw combos list` — Lists available combos
- `tw version` — Reports 0.1.0

## Notes for Next Release

1. **Telegram approval notifications** — Feature flagged in CLAUDE.md as TODO
2. **Splash screen** — "Continue as <name>" vs "New Game" — depends on textworld
3. **Periodic state saves** — Not yet implemented
4. **Combo pre/post hooks** — Not yet implemented (marked as known limitation in README)
5. **Version bumping** — Currently hardcoded to 0.1.0 in `__init__.py`
6. **GitHub Actions** — No release workflow yet (versioned Docker images listed in CLAUDE.md TODO)

All v0.1.0 features are documented and tested. Ready for release.
