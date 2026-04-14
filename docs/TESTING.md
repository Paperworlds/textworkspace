# textworkspace — E2E Testing Checklist

Manual testing steps for live validation. Run after `tw dev reinstall`.

## Prerequisites

```bash
tw dev reinstall          # rebuild all tools from local repos
tw shell install --fish   # regenerate wrappers + completions
exec fish                 # reload shell
```

---

## Shell Integration

### ta switch (textaccounts)

The fish wrapper must translate `switch` to `show` internally.

```bash
# Verify wrapper content
cat ~/.config/fish/functions/textaccounts.fish
# Should contain: eval (command textaccounts show $argv[2..-1])
# Should NOT contain: eval (command textaccounts $argv)

# Test switch
ta switch personal
ta status                 # should show profile: personal

ta switch work
ta status                 # should show profile: work

# Switch back
ta switch personal
```

### Aliases

```bash
ta --version              # should match textaccounts --version
ts --version              # should match textsessions --version
pp --version              # should match paperagents --version (if installed)
```

### Completions

```bash
tw <TAB>                  # should show subcommands
ta <TAB>                  # should show textaccounts subcommands
ts <TAB>                  # should show textsessions subcommands
```

---

## Doctor & Status

```bash
tw doctor
# Verify:
#   - textworkspace row with current version
#   - Python tools show "via dev" (not "via pypi")
#   - Go tools show version + source
#   - fish: tw.fish installed → ok
#   - proxy: responding or not-installed warning

tw status
# Verify:
#   - profile matches current ta profile
#   - mode shows "developer" when dev_root is set
#   - combos count matches defined combos
```

---

## Combos

### up — Start proxy and servers

```bash
tw up
# Expected:
#   - textproxy starts (if installed, skip_if: proxy.running)
#   - textserve starts default servers (if installed)
tw status                 # proxy should show "running"
```

### down — Stop everything

```bash
tw down
# Expected:
#   - servers stop
#   - proxy stops (skip_if: proxy.stopped)
tw status                 # proxy should show not running
```

### reset — Switch profile + restart

```bash
tw reset personal
# Expected:
#   - accounts switch personal
#   - proxy restart
#   - servers restart with default tag
ta status                 # should show personal
```

### go — Full session launch

The "go" combo is the daily driver: switch profile, start servers, open a new Claude session.

```bash
# Basic usage (no tmux, no name)
tw go work my-repo
# Expected:
#   - switch to "work" profile
#   - textserve start --tag work (if options.servers is true)
#   - textsessions new -r my-repo -p work

# With name
tw go work my-repo --name "feature-x"
# Expected:
#   - same as above but session named "feature-x"

# With tmux
tw go work my-repo --name "feature-x" --tmux
# Expected:
#   - same as above + tmux new-window -n feature-x

# Skip servers
tw go work my-repo --no-servers
# Expected:
#   - textserve step skipped (only_if: options.servers)

# Config-level defaults override
# In ~/.config/paperworlds/config.yaml:
#   defaults:
#     combos:
#       go:
#         tmux: true
# Then: tw go work my-repo
# Expected: tmux window opens by default without --tmux flag
```

**Dependencies for go:**
- textaccounts (for profile switch)
- textserve (for server management — optional, controlled by `--servers/--no-servers`)
- textsessions (for Claude session creation)
- tmux (optional, controlled by `--tmux/--no-tmux`)

---

## textforums

```bash
# Create thread
textforums new --title "test thread" --content "hello" --tag test
# Should create ~/.textforums/test-thread/thread.yaml

# List threads
textforums list
textforums list --status open
textforums list --tag test

# Show thread
textforums show test-thread
textforums show test-thread --raw

# Add entry
textforums add test-thread --content "reply" --status ack

# Via tw
tw forums list
tw forums show test-thread

# Close + reopen
textforums close test-thread --content "done"
textforums list                    # should show resolved
textforums list --status resolved  # should show it
textforums reopen test-thread
textforums list                    # should show open again

# Edit in $EDITOR
textforums edit test-thread

# Cleanup
rm -rf ~/.textforums/test-thread
```

---

## Dev Workflow

```bash
# Reinstall picks up local changes
# Make a trivial change in a sibling repo, then:
tw dev reinstall
tw doctor                 # version should reflect local build

# Dev mode flag persists
tw status                 # mode: developer
tw doctor                 # tools show "via dev"
```

---

## Known Limitations

- `tw go` requires textserve for the servers step — currently shows as "not installed". Use `--no-servers` to skip.
- `tw up`/`tw down`/`tw reset` depend on proxy and servers subcommands that delegate to textproxy/textserve.
- Combo conditions like `proxy.running` and `servers.running` require the respective tools to be installed and responding.
