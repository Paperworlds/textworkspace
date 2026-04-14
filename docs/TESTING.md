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

### Unit tests

```bash
just test-v -k forums              # all forums tests
just test-v -k "forums and slug"   # slug generation only
just test-v -k "forums and cli"    # CLI commands only
```

Tests in `tests/test_forums.py` use `tmp_path` as forums root — no real
data is touched. See the test file for helpers: `_runner()`, `_make_thread()`,
`_make_and_save()`.

**Current coverage:**
- Slug generation (6 tests): lowercase, punctuation, unicode, truncation
- YAML round-trip: save/load preserves all fields
- Data operations: add_entry, list_threads with status/tag filters
- Resolution chain: get_root (env > config > default), get_author (4 levels)
- All 7 CLI commands: new, list, show, add, close, reopen, edit
- Integration: standalone `textforums` entry point, `tw forums` subcommand

### Manual E2E — basic operations

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

### Manual E2E — agent coordination flow

This simulates the pp injection scenario from `docs/FORUMS-AGENT-SPEC.md`.
Use a temp root to avoid polluting real data:

```bash
export TEXTFORUMS_ROOT=$(mktemp -d)
```

**Step 1: Worker posts a blocker**

```bash
textforums new \
    --title "load_sessions renamed to list_sessions" \
    --tag textsessions --tag textworkspace --tag blocker \
    --content "load_sessions() is now list_sessions() as of v0.4.0. All consumers must update imports."
# Should print slug: load-sessions-renamed-to-list-sessions
```

**Step 2: pp queries for open blockers (simulated)**

```bash
# This is what pp injection will run
textforums list --tag textworkspace --status open
# Should show the thread with status "open"

textforums show load-sessions-renamed-to-list-sessions
# Should show title, tags (textsessions, textworkspace, blocker), and entry
```

**Step 3: Another worker replies**

```bash
textforums add load-sessions-renamed-to-list-sessions \
    --content "Updated imports in tw status — using list_sessions() now" \
    --author worker-003

textforums show load-sessions-renamed-to-list-sessions
# Should show 2 entries (original + reply)
```

**Step 4: Lead closes the thread**

```bash
textforums close load-sessions-renamed-to-list-sessions \
    --content "All consumers updated in prompts 003 and 004."

# Verify it's gone from open queries
textforums list --tag textworkspace --status open
# Should show: No threads found.

# But visible in resolved
textforums list --status resolved
# Should show the thread with status "resolved"
```

**Step 5: Cleanup**

```bash
rm -rf $TEXTFORUMS_ROOT
unset TEXTFORUMS_ROOT
```

### Manual E2E — multi-repo tagging

Tests that a single thread reaches agents in different repos:

```bash
export TEXTFORUMS_ROOT=$(mktemp -d)

textforums new \
    --title "YAML parser migration" \
    --tag textworkspace --tag textsessions --tag paperagents --tag info \
    --content "Switching from PyYAML to ruamel.yaml across all repos."

# Each repo's pp injection would query its own tag
textforums list --tag textworkspace --status open    # should find it
textforums list --tag textsessions --status open     # should find it
textforums list --tag paperagents --status open      # should find it
textforums list --tag textworld --status open        # should NOT find it

rm -rf $TEXTFORUMS_ROOT
unset TEXTFORUMS_ROOT
```

### Test gaps (to be filled)

These need unit tests in `tests/test_forums.py`:

- **Tag round-trip**: `new --tag a --tag b` → load → verify both tags present
- **Combined filters**: `list_threads(tag="x", status="open")` — both applied
- **Error paths**: show/add/close on nonexistent slug → ClickException
- **Duplicate slug**: `new` with same title twice → error
- **Malformed YAML**: corrupt `thread.yaml` → `list_threads` skips it
- **Multi-entry ordering**: 10+ entries stay in insertion order
- **pp injection query**: the exact `list_threads(tag=repo, status="open")`
  call that pp will make, verified against threads with mixed tags/statuses

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
