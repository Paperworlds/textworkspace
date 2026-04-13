# Paperworlds — Cross-Repo Conventions

## Public API surface

Every repo that exports functions for use by other repos MUST declare its
public API explicitly. Other repos depend on these — breaking them breaks
the stack.

### Rules

1. **Declare exports in `__init__.py` or a dedicated `api.py` module.**
   If the repo uses `api.py`, that file IS the contract. If not, the
   `__all__` list in `__init__.py` is the contract.

2. **Document the public API in the README** under a `## API` section.
   List every public function with its signature. This is the source of
   truth for consumers writing import statements.

3. **Never remove or rename a public function without a deprecation cycle.**
   - Add a `warnings.warn("X is deprecated, use Y", DeprecationWarning)`
   - Keep the old name working for at least one minor version
   - Update all in-tree consumers (textworkspace, etc.) before removing

4. **Never change a function signature in a breaking way.**
   Adding optional parameters is fine. Removing parameters, changing
   required parameter order, or changing return types is a breaking change.
   Use a new function name instead.

5. **Semver signals intent.**
   - Patch (0.x.1): bug fixes, no API changes
   - Minor (0.x.0): new features, new exports, deprecations
   - Major (x.0.0): removals of deprecated APIs

### Current public APIs

| Repo | Module | Exports |
|------|--------|---------|
| textaccounts | `textaccounts.api` | `list_profiles`, `env_for_profile`, `active_profile`, `resolve_profile`, `profile_dir`, `available`, `load_registry` |
| textsessions | `textsessions.sessions` | `load_sessions`, `load_sessions_fast`, `filter_sessions`, `CACHE_PATH`, `STATE_DIR`, `Session` |
| textsessions | `textsessions.config` | `Config` |
| textproxy | CLI only | `textproxy stats`, `textproxy start/stop/restart`, `textproxy config --path` |
| textserve | CLI only | `textserve list`, `textserve start/stop` |

### Go tools (CLI-only APIs)

Go tools expose their API via CLI flags and stdout. Conventions:

- Structured output via `--json` flag where supported (textserve)
- textproxy does NOT support `--json` on stats — parse human output or
  use the config file at `~/.config/textproxy/config.json` for port info
- Config file locations are stable and can be read directly

## Cache and config paths

Shared paths that other tools may read:

| Path | Owner | Stable | Format |
|------|-------|--------|--------|
| `~/.config/paperworlds/config.yaml` | textworkspace | yes | YAML |
| `~/.config/paperworlds/combos.yaml` | textworkspace | yes | YAML |
| `~/.config/textproxy/config.json` | textproxy | yes | JSON |
| `~/.local/state/claude-sessions/_cache.json` | textsessions | yes | JSON array |
| `~/.local/state/claude-sessions/*.yaml` | textsessions | yes | YAML dict keyed by session ID |

## Shared config — repos and dirs

textworkspace owns a shared config at `~/.config/paperworlds/config.yaml`
that tracks repos and shared directories. Other tools MAY read this file
but MUST NOT depend on it.

### Design principle: opt-in, never required

Every tool in the stack must work standalone without textworkspace installed.
The shared config is a convenience layer, not a dependency.

```
~/.config/paperworlds/config.yaml    ← textworkspace writes this
~/.config/textsessions/config.toml   ← textsessions owns this
~/.config/textprompts/config.toml    ← textprompts will own this
```

### Shared config schema (repos + dirs)

```yaml
repos:
  mono:
    path: /Users/projects/paradigm/mono
    label: mono
    profile: work
  paperworlds:
    path: /Users/projects/personal/paperworlds
    label: paperworlds
    profile: personal

dirs:
  state: ~/.local/state/paperworlds
  cache: ~/.cache/paperworlds
```

### How tools use it

1. **Without textworkspace**: tool uses its own config exclusively.
   textsessions reads `~/.config/textsessions/config.toml` for repos.
   textprompts reads its own config for repos. No cross-dependency.

2. **With textworkspace**: `tw init` or `tw sync` writes shared repos
   into each tool's native config. Tools still read their own config —
   they never import from or depend on textworkspace.

3. **Tools never import textworkspace.** If a tool wants to read the
   shared config as a hint, it reads the YAML file directly:
   ```python
   from pathlib import Path
   import yaml

   _PW_CONFIG = Path.home() / ".config" / "paperworlds" / "config.yaml"

   def _shared_repos() -> dict:
       if not _PW_CONFIG.exists():
           return {}
       with _PW_CONFIG.open() as f:
           data = yaml.safe_load(f) or {}
       return data.get("repos", {})
   ```

### Sync direction

```
textworkspace config.yaml  ──tw sync──▸  textsessions config.toml
                           ──tw sync──▸  textprompts config.toml
```

textworkspace is the writer. Tools are readers of their own config.
`tw sync` is the bridge. No circular dependencies.

### `tw sync` command (planned)

**Purpose:** push repos from `~/.config/paperworlds/config.yaml` into each
tool's native config format, so tools stay standalone but benefit from a
single source of truth when textworkspace is installed.

**Behaviour:**

```
tw sync [--dry-run]
```

1. Read `repos` from paperworlds config.yaml
2. For each supported tool config:
   - **textsessions** (`~/.config/textsessions/config.toml`):
     Merge repos into `[[repos]]` TOML array. Match by path — update
     existing entries, append new ones, never delete repos the tool
     already has (user may have added tool-specific repos).
   - **textprompts** (future): same pattern, different config path.
3. Print a diff of what changed (or would change with `--dry-run`).

**Merge rules:**
- Match by `path` (canonical, no trailing slash)
- If a repo exists in both, textworkspace values win for `label` and
  `profile` fields
- If a repo exists only in the tool config, leave it untouched
- If a repo exists only in textworkspace config, append it
- Never delete repos from tool configs

**Not in scope (v1):**
- Pulling repos from tool configs back into textworkspace
- Syncing non-repo settings (proxy, integrations, UI prefs)
- Auto-sync on `tw init` (manual `tw sync` only)

## Adding a new repo to the stack

1. Decide: Python package or Go binary
2. If Python: declare public API in `api.py` or `__all__`, add to the table above
3. If Go: document CLI flags and output format, add to the table above
4. Add to textworkspace: config model entry, doctor check, status line
5. Update this file
