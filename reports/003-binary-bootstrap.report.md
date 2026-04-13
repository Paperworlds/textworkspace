# Report: 003 — Go binary bootstrap from GitHub releases
Date: 2026-04-13T00:00:00Z
Status: DONE

## Changes
- 8b24d8f feat: Go binary bootstrap from GitHub releases (textworkspace)

## Test results
- textworkspace: 26 tests passed, 0 failed (0.20s)

## What was implemented

### bootstrap.py
- `platform_slug()` — detects darwin/linux + arm64/amd64
- `release_url(tool, version)` — builds tarball URL from GitHub releases pattern
- `checksum_url(tool, version)` — builds `.sha256` sidecar URL
- `latest_version(tool)` — queries GitHub releases API for latest tag
- `download_binary(tool, version, *, client)` — streaming httpx download, sha256 verify, tarball extract to `~/.local/share/textworkspace/cache/<tool>-v<ver>-<slug>/`; skips if already cached; accepts optional client for testing
- `install_binary(tool, version)` — creates symlink at `~/.local/share/textworkspace/bin/<tool>` → cache entry; prunes old versions keeping at most 1 previous

### cli.py
- `tw update [TOOL]` — checks GitHub for newer release, downloads + installs if available, updates config.yaml with `version` + `bin` path; without argument updates all known Go tools (textproxy, textserve)

### tests/test_bootstrap.py (14 new tests)
- Platform detection: darwin-arm64, linux-amd64, linux-arm64, unsupported OS/arch
- URL building: darwin-arm64 URL correctness, v-prefix stripping, .sha256 suffix
- download_binary: success path, checksum mismatch raises ValueError, cache hit skips HTTP
- install_binary: symlink creation, pruning (3→2 versions, oldest deleted), symlink replacement

## Notes for next prompt
- `tw update` currently only covers textproxy and textserve (hardcoded in `_GO_TOOLS`). If more Go tools are added, update that tuple or make it config-driven.
- The `.sha256` sidecar must be present in the GitHub release assets — ensure release workflows publish it.
- Push failed once (connection reset) but succeeded on retry; no action needed.
