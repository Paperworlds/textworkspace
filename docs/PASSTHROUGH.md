# Passthrough subcommand pattern

`tw` wraps several Go/Python tools (`textproxy`, `textaccounts`, ...). Rather
than hand-registering every subcommand of every tool, we use a Click `Group`
subclass that forwards unknown subcommands to the underlying binary.

## Behavior

Given `tw proxy <sub> <args...>`:

1. If `<sub>` is explicitly registered on the group, it runs normally.
2. Otherwise, `_PassthroughGroup.get_command` synthesizes a command on the fly
   that execs `<tool> <sub> <args...>` and propagates the exit code.
3. `--help` on an unknown subcommand is forwarded to the tool, so users see
   the tool's native help (e.g. Go-style `Usage of stats:`), not a Click stub.

The group is defined in `src/textworkspace/cli.py` as `_PassthroughGroup` with
per-tool subclasses — `_ProxyPassthroughGroup` (textproxy),
`_ServePassthroughGroup` (textserve), and `_ReadPassthroughGroup` (textread)
are the current users.

## Why

- **No drift.** New tool subcommands work in `tw` the moment the tool ships
  them — no CLI change, no version bump, no coordination.
- **No boilerplate.** A pure-passthrough `start`/`stop`/`status`/`log` wrapper
  with no extra logic is just noise. Delete it; the fallback covers it.
- **Native flags.** `tw proxy stats --json` and `tw proxy log -f` just work,
  including flags the wrapper author didn't know about.

## When to keep an explicit wrapper

Keep an explicit `@proxy_cmd.command(...)` only when the `tw` name needs to
differ from a literal forward. Current examples:

- `tw proxy os-install` → `textproxy os install` (dash → space)
- `tw proxy os-uninstall` → `textproxy os uninstall`

If you just want to document a subcommand, add it to the group's docstring
instead of wrapping it.

## Trade-offs

- No Click-style help page for forwarded subs (tool's native help instead).
- Tab-completion won't list forwarded subs unless completion is wired to the
  tool's own completion output.
- `tw proxy <typo>` runs `textproxy <typo>` and lets the tool reject it,
  rather than failing at the Click layer. Usually fine; the tool's error is
  clearer than "no such command" anyway.

## Adding passthrough to another tool

```python
class _AccountsPassthroughGroup(_PassthroughGroup):
    tool_name = "textaccounts"

@main.group("accounts", cls=_AccountsPassthroughGroup, invoke_without_command=True)
@click.pass_context
def accounts_cmd(ctx):
    """Manage textaccounts. Unknown subcommands forward to `textaccounts`."""
    if ctx.invoked_subcommand is None:
        _run_tool("textaccounts", "list")  # or whatever the default should be
```

That's it — every `textaccounts <sub>` now works as `tw accounts <sub>`.
