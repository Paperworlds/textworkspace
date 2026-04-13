# textworkspace

**Meta CLI and package manager for the [Paperworlds](https://github.com/paperworlds) text- stack.**

One install, one CLI surface. Bootstraps tools, manages workflows, unifies status across the entire stack.

## Quick Start

### Install

```bash
pipx install textworkspace
```

### Initialize

```bash
tw init
```

Walks you through onboarding: discovers existing tools, prompts for missing dependencies (textaccounts, textsessions, etc.), bootstraps Go binaries from GitHub releases.

### Check status

```bash
tw status
```

Shows unified stack view: active profile, proxy state, running servers, session count.

## CLI Reference

| Command | Description |
|---------|-------------|
| `tw init` | Initialise textworkspace config and install dependencies |
| `tw status` | Show unified status of all stack components |
| `tw doctor` | Check that all required binaries and services are healthy |
| `tw update [tool]` | Update all managed binaries and packages to latest versions |
| `tw switch <profile>` | Switch the active workspace profile (requires fish wrapper) |
| `tw sessions [query] [-n N]` | Launch or search textsessions with optional limit |
| `tw stats [--session ID] [--port N]` | Show aggregate stats across sessions and accounts |
| `tw serve [name] [--tag T] [--json]` | Start or inspect textserve servers |
| `tw config` | Show or edit config file |
| `tw which <tool>` | Print the path of a managed binary |
| `tw combos` | Manage workflow combos |
| `tw shell` | Output shell function definitions |

## Combo Examples

Combos are YAML-based workflow recipes that chain actions across tools. They're stored in `~/.config/paperworlds/combos.yaml` or `~/.config/paperworlds/combos.d/`.

### Built-in combos

```bash
tw up              # Start proxy and default servers
tw down            # Stop all servers and proxy
tw reset <profile> # Switch profile and restart stack
```

### Custom combo

```yaml
# In ~/.config/paperworlds/combos.yaml
combos:
  workday:
    description: Start work environment
    args: [profile]
    steps:
      - run: accounts switch {profile}
      - run: proxy start
        skip_if: proxy.running
      - run: servers start --tag default
```

Then run: `tw workday production`

### Combo conditions

- `proxy.running` / `proxy.stopped` — proxy state
- `servers.running [--tag T / name]` / `servers.none_running` — server state
- `accounts.active <profile>` — active profile

### Combo execution

```bash
tw <combo-name> [args]      # Run combo (dynamic dispatch)
tw --dry-run <combo-name>   # Preview steps without executing
tw <combo-name> --continue  # Continue on errors (stop at first failure is default)
```

Combos are also available via `tw combos list`, and installed from community via `tw combos install`.
Both dynamic dispatch (`tw workday`) and the `tw combos` namespace work.

## Combo Sharing

### Install from community

```bash
tw combos install gh:paperworlds/textcombos/workday
tw combos install https://gist.github.com/user/xyz
tw combos install ~/my-combos.yaml
```

### Export a combo

```bash
tw combos export <name>      # Dump to stdout
tw combos export --all       # Export all combos
```

### Search community

```bash
tw combos search "build"
tw combos info <name>
```

### Manage installed combos

```bash
tw combos list              # List all combos
tw combos edit              # Edit combos.yaml
tw combos add <name>        # Create new combo interactively
tw combos update            # Re-fetch from installed sources
tw combos remove <name>     # Delete a combo
```

## Fish Shell Setup

Automatic on `tw init`, or manually:

```bash
tw shell --fish >> ~/.config/fish/conf.d/paperworlds.fish
source ~/.config/fish/conf.d/paperworlds.fish
```

This creates:
- `tw` — main wrapper (handles `tw switch` for env setting)
- `xtw` — alias for `tw`
- `xta`, `xts`, `xtp`, `xtg` — aliases for `ta`, `ts`, `tp`, `tg`

## Configuration

### Config file

```
~/.config/paperworlds/config.yaml
```

Tracks installed tools, versions, binary paths, and preferences:

```yaml
tools:
  textaccounts:
    version: 0.3.1
    source: pypi
  textproxy:
    version: 0.5.0
    source: github
    bin: ~/.local/share/textworkspace/bin/textproxy
defaults:
  profile: work
  proxy_autostart: false
```

### Combos

```
~/.config/paperworlds/combos.yaml       # User's own combos
~/.config/paperworlds/combos.d/         # Community combos installed by tw
```

Inspect/edit:

```bash
tw config show              # Print config as YAML
tw config edit              # Open in $EDITOR
tw combos list              # List all combos
tw combos edit              # Open combos.yaml in $EDITOR
```

## Supported Tools

### Required
- **textaccounts** — account/profile management (Python, via `pipx`)
- **textsessions** — session indexing and TUI (Python, via `pipx`)

### Optional Go tools (auto-bootstrapped)
- **textproxy** — proxy server for tool coordination
- **textserve** — MCP fleet/server runner
- **textmap** — graph engine (planned)

## Advanced: Binary Bootstrap

Go tools are fetched as pre-built binaries from GitHub releases:

```
~/.local/share/textworkspace/bin/
├── textproxy → textproxy-v0.5.0-darwin-arm64
├── textserve → textserve-v0.2.1-darwin-arm64
└── textproxy-v0.4.0-darwin-arm64  # Previous version (for rollback)
```

Archives are named: `<tool>-v<version>-<os>-<arch>.tar.gz`

Checksum verification via `.sha256` sidecar.

## License

[Elastic License 2.0](LICENSE)
