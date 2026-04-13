# textworkspace

Meta CLI and package manager for the [Paperworlds](https://github.com/paperworlds) text- stack.

## Install

```bash
uv tool install git+https://github.com/paperworlds/textworkspace.git
```

## Usage

```
textworkspace [OPTIONS] COMMAND [ARGS]...

Options:
  -V, --version  Show the version and exit.
  --help         Show this message and exit.

Commands:
  init      Initialise textworkspace config and install dependencies.
  status    Show unified status of all stack components.
  doctor    Check that all required binaries and services are healthy.
  update    Update all managed binaries and packages to latest versions.
  switch    Switch the active workspace profile.
  sessions  Launch or attach to a textsessions TUI.
  stats     Show aggregate stats across sessions and accounts.
  serve     Start a local workspace HTTP API server.
  config    Get or set a config value.
  which     Print the path of a managed binary.
```

## License

[Elastic License 2.0](LICENSE)
