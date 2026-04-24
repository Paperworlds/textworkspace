# textworkspace

**Meta CLI and package manager for the [Paperworlds](https://github.com/paperworlds) text- stack.**

One install, one CLI surface. Bootstraps tools, manages workflows, and gives your
repos — and the agents working on them — a shared communication layer: threads,
decisions, specs, and ideas, all queryable from the terminal.

## Install

```bash
pipx install textworkspace
tw init
tw shell install --fish      # or --bash / --zsh
```

`tw init` discovers existing tools, prompts for missing ones, and bootstraps Go
binaries from GitHub releases. The shell wrapper is required for commands that
need to modify shell state (`tw switch`, `ta switch`).

Optional — enable tab completion:

```bash
env _TW_COMPLETE=fish_source tw > ~/.config/fish/completions/tw.fish
env _TEXTFORUMS_COMPLETE=fish_source textforums > ~/.config/fish/completions/textforums.fish
```

## What it gives you

### 1. One tool to manage the stack

```
tw init              # guided first-run, bootstraps binaries
tw status            # unified view: profile, proxy, servers, sessions
tw doctor            # health + stale paths + spec conformance across repos
tw up / tw down      # bring the whole MCP fleet up / down via textserve
tw update [tool]     # update managed binaries and packages
tw dev install       # install every tool from its local repo (editable mode)
tw sync              # reinstall after pulling; also reconciles combos
tw which <tool>      # where is this binary installed, what version
```

Each installed tool also becomes a passthrough: `tw proxy <anything>`,
`tw serve <anything>`, `tw read <anything>`, `tw accounts <anything>`,
`tw map <anything>` forward unknown subcommands to the real binary — so
`tw` is one muscle-memory entry point, not a shim that hides features.

### 2. Workspaces + combos

A **workspace** is a named join of profile + servers + project — one command
to switch context. **Combos** are YAML recipes for multi-step workflows.

```bash
tw start data              # switch profile, start servers, open a session
tw start data my-session   # same, custom session name
tw stop data
tw workspaces list / status / add / edit

tw <combo> [args]          # any combo name becomes a top-level command
tw --dry-run <combo>       # preview without executing
tw combos list / edit / export / update / remove
tw combos install gh:paperworlds/textcombos/workday
```

Example combo:

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

### 3. Repo registry + profiles

`tw` keeps a registry of repos you work on — personal, work, scratch — so
every cross-repo command (forums, ideas, specs) agrees on what "mono" or
"textread" means. Filter by `profile` to separate work from personal.

```bash
tw repo add mono /Users/projects/paradigm/mono --profile work
tw repo list [--profile work]
tw repo move mono /new/path   # updates config + ~/.claude/projects + every tool's own config
tw repo import                # pull repos from any tool that exposes them
```

When a folder moves, `tw repo move` orchestrates: rename on disk,
rewrite `config.yaml`, rename `~/.claude/projects/<encoded>`, and call
each installed tool's `<tool> repo move` to update downstream state.
`tw doctor` aggregates `STALE <name> <path>` warnings from every tool
that implements the contract.

### 4. textforums — threads, pins, decisions, inbox

Async notes, bug reports, cross-repo coordination — agents and humans in
the same channel. Threads live in `~/.textforums/<slug>/thread.yaml`.

```bash
textforums new --title "proxy status broken" --repo textworkspace --tag bug
textforums list --repo textworkspace --status open
textforums show <slug>
textforums add <slug> --content "reproduced on 0.4.2"
textforums close <slug> --content "shipped in 0.4.3"
```

Also available as `tw forums <sub>` — same commands, same semantics.

**Pins** — mark a thread urgent so it surfaces above everything else:

```bash
textforums pin <slug>                      # priority=high
textforums pin <slug> --until 2026-12-31   # auto-expire
textforums new --pin --title "…"           # pin on create
```

**Decisions** — promote a concluded thread to canonical, ADR-lite:

```bash
textforums decide <slug> --summary "Use protobuf for the wire format."
tw forums decisions list [--repo X] [--query T] [--since YYYY-MM-DD]
tw forums decisions show <slug>
tw forums decisions supersede <old> <new>      # ADR-history pattern
```

Once decided, the thread is frozen (title + decision fields) and drops
out of inbox by default — decisions are the law, not the queue.

**Decisions → textmap** — promote decided threads into a queryable graph:

```bash
tw forums decisions export              # write decision-<slug>.md files
tw forums decisions ingest              # export + `textmap ingest` in one
```

Each decided thread becomes a `decision` node in textmap; `superseded-by`
chains become `replaces` edges (direction inverted to match textmap
convention, OLD marked `deprecated`), `context.repos` become `applies_to`
edges, `context.spec` becomes an `implements` edge, tags + repos become
labels. The forum stays the source of truth — export is a full rewrite,
stale files are pruned.

**Inbox** — per-repo mailbox with unread state, one-stop agent onboarding:

```bash
tw forums inbox                                # this repo, CWD-inferred
tw forums inbox --as reviewer                  # address-filtered
tw forums inbox --profile work                 # aggregate across all work repos
tw forums inbox --format prompt                # paste-ready dump for handoff
tw forums inbox --mark-read                    # once you've processed it
```

`--format prompt` is the key primitive for agent handoffs — a fresh
session can resume purely by reading the thread.

Every thread carries rich context (`repos`, `paths`, `spec`, `to`,
`mentions`, `commit`) so filters compose:

```bash
textforums new --title "migration plan" \
  --repo textworkspace --repo textaccounts \
  --spec textaccounts-api \
  --to reviewer --mention deployer \
  --tag planning --pin
```

Run `tw forums quickstart` for a 30-second agent onboarding, or
`tw forums example` for an annotated lifecycle.

### 5. Cross-repo specs

Owned by one repo, followed by others, checked automatically.
Specs live in the owner repo at `docs/specs/<slug>.md` (YAML frontmatter
+ markdown body); consumers declare what they follow in `docs/SPECS.yaml`
and mark implementations with `# SPEC: <slug>` comments in source.

```bash
tw forums spec new <slug> --owner <repo> --title "..."
tw forums spec list [--owner R] [--consumer R] [--status S]
tw forums spec show <slug>
tw forums spec refs <slug>              # grep `# SPEC:` markers across repos
tw forums spec check [--repo R]         # conformance check
tw forums spec adopt <slug>             # freeze frontmatter (slug/owner/version/…)
tw forums spec supersede <old> <new>
tw forums spec brief [--repo R]         # agent-ready 'what do I own / follow' brief
tw forums spec explain                  # the full format reference, inline
```

Drift is surfaced by `tw doctor` — missing implementations, pinned
versions out of sync with upstream, frozen fields mutated post-adoption.

### 6. Ideas across all your repos

Discover and aggregate `IDEAS.yaml` (or directory of per-file YAMLs) from
every registered repo. Personal repos drop a `docs/IDEAS.yaml`; work
repos can use `.files/ideas/*.yaml` where each file is one idea.

```bash
tw ideas list                                    # profile | repo | id | status | title
tw ideas list --profile work
tw ideas list --status planned --query forums
tw ideas show mono deploy-notifications          # full reasoning, not just summary
tw ideas threads mono deploy-notifications       # forum threads tagged idea:mono/deploy-notifications
tw ideas quickstart                              # onboarding
```

Idea → thread link is by tag convention (`idea:<repo>/<id>`), so
expansion / proposal / decision loops use the same forums primitives.

## A 60-second tour

```bash
# 1. Set the stage
tw init && tw shell install --fish
tw repo add mono ~/work/mono --profile work

# 2. See what's pending
tw forums inbox --profile work --format prompt | pbcopy   # paste into next session

# 3. Capture an idea at work
mkdir -p ~/work/mono/.files/ideas
cat > ~/work/mono/.files/ideas/deploy-notifications.yaml <<'YAML'
title: "Deploy notifications for all services in #eng-team-delta"
status: brainstorm
priority: 2
summary: Extend the paradex-backend→Jenkins→Slack hook to the whole stack.
YAML
tw ideas list --profile work

# 4. Open discussion, pin it, decide
textforums new \
  --title "expand: deploy notifications" \
  --repo mono --to lead \
  --tag idea:mono/deploy-notifications --pin
textforums add <slug> --content "Proposal A: central Jenkins listener…"
textforums decide <slug> --summary "Going with Proposal A"

# 5. Promote to a cross-repo spec once it's durable
tw forums spec new mono-deploy-notifs --owner mono --title "Deploy notif protocol"
```

## Configuration

```
~/.config/paperworlds/config.yaml   # tools, versions, defaults, repos, workspaces
~/.config/paperworlds/combos.yaml   # user combos
~/.config/paperworlds/combos.d/     # community combos
~/.textforums/<slug>/thread.yaml    # forum threads + per-repo last_read state
```

`$TEXTFORUMS_ROOT` overrides the forums root; `config.forums.root` overrides
the default per install. `$TEXTFORUMS_AUTHOR` / `config.forums.author` set the
default author for new entries.

## How it works

`tw init` interrogates the system for each known tool — Python packages via
`uv`, Go binaries via GitHub Releases — and records versions and binary
paths in `config.yaml`. Go tools (textproxy, textserve) ship as pre-built
archives verified against a `.sha256` sidecar and unpacked into
`~/.local/share/textworkspace/bin/`; symlinks point at the active version.

Combos are loaded at startup from all YAML files in `combos.yaml` and
`combos.d/`. Each combo declares steps using a small DSL (`run`, `skip_if`,
`args`) and the combo name becomes a top-level `tw` subcommand via dynamic
dispatch.

Passthrough groups (`tw proxy`, `tw serve`, `tw read`, `tw accounts`,
`tw map`) forward unknown subcommands to the underlying binary with a
custom Click group — so the full tool surface is always reachable without
re-implementing every subcommand here.

Cross-repo features (forums, specs, ideas) share a repo registry — the
union of `config.repos` and a scan of `dev_root`. Registered entries win
on conflict and can carry a `profile` tag used by `--profile` filters.

Shell integration writes fish/bash/zsh wrapper functions via
`tw shell install`. The wrappers handle commands that modify shell state
(`tw switch`, `ta switch`) which cannot work as subprocess calls.

`tw dev install` builds every tool from local repo checkouts in editable
mode (`uv tool install -e`), then records the git hash in the version
string so `tw doctor` can detect stale installs without re-running.

## Roadmap

- [ ] `tw ideas expand <repo> <id>` — spawn a pp worker that opens a thread
      with 2–3 proposals for an idea (coordination thread decided; paperagents
      side has a draft `idea-expander` persona spec)
- [ ] Live forums → textmap dual-write on `decide` / `supersede` (today:
      batch via `tw forums decisions ingest`)
- [ ] Extract `textforums` into its own repo (current home: inside textworkspace)
- [ ] Publish to PyPI
- [ ] `tw forums decisions import` — pull paper ADRs from any repo that ships them

## Part of Paperworlds

textworkspace is part of [Paperworlds](https://github.com/paperworlds) — an
open org building tools and games around AI agents and text interfaces.

## License

[Elastic License 2.0](LICENSE)
