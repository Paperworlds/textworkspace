# Cross-repo specs

A **spec** is a contract one repo publishes for others to follow. Specs live
in the owner repo; discussion lives in a textforums thread tagged `spec`.

## File locations

- **Owner** writes `docs/specs/<slug>.md` in its own repo.
- **Consumers** declare what they follow in `docs/SPECS.yaml` and mark
  implementations with `# SPEC: <slug>` comments.
- **Companion thread** at `~/.textforums/spec-<slug>/` (created by
  `tw forums spec new`).

## Spec file format

```markdown
---
slug: protocol-envelope-v2
owner: textgame-io
status: draft          # draft | proposed | adopted | deprecated | superseded
version: 0.1.0
consumers: [textworld, textworld-clients]
supersedes: protocol-envelope-v1   # optional
adopted_at: 2026-04-20             # set by `tw forums spec adopt`
---
# Protocol Envelope v2

## Summary
## Motivation
## Interface
## Conformance
## Open questions
```

Once `status: adopted`, `slug` / `owner` / `version` / `supersedes` /
`adopted_at` are immutable — drift warnings fire from `tw doctor`. New
version = new slug + `supersedes`.

## Consumer manifest

```yaml
# docs/SPECS.yaml in the consumer repo
follows:
  - slug: protocol-envelope-v2
    pinned_version: 2.0.0          # optional
    implemented_in:
      - src/protocol/envelope.ts
```

`implemented_in` paths must exist AND each followed spec must have at least
one `# SPEC: <slug>` marker somewhere in source.

## Commands

```bash
tw forums spec list                        # all specs, filter by --owner/--consumer/--status
tw forums spec new <slug> --owner <repo> --title "..." --consumer <repo>
tw forums spec show <slug>
tw forums spec refs <slug>                 # grep `# SPEC: <slug>` markers
tw forums spec check [--repo <name>] [--strict]
tw forums spec adopt <slug>                # draft/proposed → adopted, set adopted_at
tw forums spec supersede <old> <new>       # old → superseded, new → adopted
tw forums spec brief [--repo <name>]       # agent-facing brief
```

`tw doctor` surfaces all findings from `check`.

## For agents working in a repo

Run `tw forums spec brief` from inside the repo (or pass `--repo <name>`)
for a one-screen summary:

- specs this repo OWNS (status, marker count)
- specs this repo FOLLOWS (upstream status, pinned vs current, check findings)
- exact next commands

A good per-repo `CLAUDE.md` snippet:

> Before starting work, run `tw forums spec brief`. Implement against adopted
> specs only; if a change touches a spec, update `docs/SPECS.yaml` and the
> `# SPEC: <slug>` markers in the same commit. Before you commit, run
> `tw forums spec check --repo <this>`.
