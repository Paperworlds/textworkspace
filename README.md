# textworkspace

**Meta CLI and package manager for the [Paperworlds](https://github.com/paperworlds) text- stack.**

One install, one CLI surface. Bootstraps tools, manages workflows, unifies status across the entire stack.

## Install

```bash
pipx install textworkspace
tw init
```

`tw init` discovers existing tools, prompts for missing dependencies, and bootstraps Go binaries from GitHub releases. To enable shell integration (required for `tw switch`):

```bash
tw shell install --fish   # or --bash / --zsh
```

## Usage

### Core commands

| Command | Description |
|---------|-------------|
| `tw init` | Initialise config and install dependencies |
| `tw status` | Unified stack view: profile, proxy, servers, sessions |
| `tw doctor` | Check all binaries and services are healthy |
| `tw update [tool]` | Update managed binaries and packages to latest |
| `tw switch <profile>` | Switch active workspace profile (requires shell wrapper) |
| `tw sessions [query]` | Launch or search textsessions |
| `tw stats` | Aggregate stats across sessions and accounts |
| `tw serve [name]` | Start or inspect textserve servers |
| `tw config show` | Print config as YAML |
| `tw which <tool>` | Print path of a managed binary |
| `tw dev install` | Reinstall all dev tools from local repos (editable) |

### Combos

Combos are YAML workflow recipes stored in `~/.config/paperworlds/combos.yaml` or `combos.d/`.

```bash
tw up              # Start proxy and default servers
tw down            # Stop all servers and proxy
tw reset <profile> # Switch profile and restart stack
tw <combo> [args]  # Run any custom combo by name
tw --dry-run <combo>  # Preview steps without executing
```

Define your own:

```yaml
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

Install from community:

```bash
tw combos install gh:paperworlds/textcombos/workday
tw combos install https://gist.github.com/user/xyz
tw combos list / edit / export / update / remove
```

## Configuration

```
~/.config/paperworlds/config.yaml   # tools, versions, defaults
~/.config/paperworlds/combos.yaml   # user combos
~/.config/paperworlds/combos.d/     # community combos
```

Schema excerpt:

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

## How it works

`tw init` interrogates the system for each known tool — Python packages via `uv`, Go binaries via GitHub Releases — and records versions and binary paths in `config.yaml`. On subsequent runs, `tw doctor` re-checks each binary and flags drift.

Go tools (textproxy, textserve) are fetched as pre-built archives and unpacked into `~/.local/share/textworkspace/bin/`. A symlink points to the active version; old versions are kept for rollback. Archives follow the naming convention `<tool>-v<version>-<os>-<arch>.tar.gz` and are verified against a `.sha256` sidecar.

Combos are loaded at startup from all YAML files in `combos.yaml` and `combos.d/`. Each combo declares steps using a small DSL: `run` (shell command via the tool's own CLI), `skip_if` (condition expression), and `args` (named positional arguments). Dynamic dispatch means any combo name becomes a top-level `tw` subcommand.

Shell integration works by writing fish/bash/zsh wrapper functions via `tw shell install`. The wrappers handle commands that modify shell state (`tw switch`, `ta switch`) which cannot work as subprocess calls.

`tw dev install` builds every tool from local repo checkouts in editable mode (`uv tool install -e`), then records the git hash in the version string so `tw doctor` can detect stale installs without re-running the install.

## Roadmap

- [ ] `tw repo move <name> <new-path>` — orchestrate path updates across all tools when a repo moves
- [ ] `tw doctor` — aggregate `STALE` lines from each tool's own `doctor` command
- [ ] `tw sync` — push repos from `config.yaml` into each tool's own config
- [ ] `tw repo import` — pull repos from any tool that exposes `<tool> repos`
- [ ] Publish to PyPI

## Part of Paperworlds

textworkspace is part of [Paperworlds](https://github.com/paperworlds) — an open org
building tools and games around AI agents and text interfaces.

## License

[Elastic License 2.0](LICENSE)
