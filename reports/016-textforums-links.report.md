# Report: 016 — textforums link — thread-to-thread relationships (blocks, relates-to)
Date: 2026-04-20T00:00:00Z
Status: DONE

## Changes
- 70fb215 forums: add thread-to-thread link/unlink commands (blocks, relates-to) (textworkspace)

## Test results
- textworkspace: 62 tests passed, 0 failed (0.19s)

## What was added

**Data model:**
- `ThreadLink` dataclass (`rel`, `slug`, `note`)
- `links: list[ThreadLink]` field on `ThreadMeta` (defaults to `[]`)
- Serialized under `meta.links` in YAML; key omitted when list is empty (backward-compatible)

**CLI commands:**
- `textforums link <slug> <target> [--rel <rel>] [--note <text>]`
  - Common rels: `blocks`, `blocked-by`, `relates-to` (default: `relates-to`)
  - Warns to stderr if target doesn't exist
  - Rejects duplicates (same rel + target)
- `textforums unlink <slug> <target> [--rel <rel>]`
  - Without `--rel`: removes all links to target
  - Errors if no matching link found

**Updated commands:**
- `textforums show`: displays `Links:` section when thread has links (with note in parentheses)
- `textforums list`: added `LINKS` count column

## Notes for next prompt
- Links are one-directional; no automatic back-link is created
- `blocked-by` is a valid but conventional inverse of `blocks` — callers manage symmetry if desired
- `textforums list --linked-to <slug>` (find threads linking to a given slug) could be a future addition
