# Plan — Pins + Decisions for textforums

Two distinct features, additive only, no migration needed. Ship in one version bump
to **0.11.0**.

## Feature 1: Pins (urgency)

### Data
Add to `ThreadMeta`:
```python
@dataclass
class ThreadMeta:
    ...
    priority: str = "normal"      # "high" | "normal" | "low"
    pinned_until: str = ""        # ISO date; empty = no expiry
```
Serialize only when non-default.

### CLI
- `textforums pin <slug> [--until YYYY-MM-DD] [--priority high|low]`
  - Default priority when pinning: `high`.
- `textforums unpin <slug>` — sets `priority=normal`, clears `pinned_until`.
- `textforums new --pin [--until YYYY-MM-DD]` — convenience on create.

### Behavior rules
- **Auto-expire**: on any load/list, if `pinned_until` is ≤ today, drop the pin in
  memory (don't rewrite the file). Optional `textforums doctor` line: "N expired
  pins — run `textforums unpin <slug>`."
- **Auto-unpin on close**: `textforums close <slug>` also clears pin fields.
- No frontmatter freeze — pins are mutable by design.

### Inbox surfacing
Add to `forums_inbox` (format=table):
- New **`## Pinned`** section before `## Unread`, listing threads with
  `priority=high` OR a future `pinned_until`. Same repo/role filter applies.
- A pinned thread also appearing in unread shows in Pinned only, not duplicated.
- In `--format prompt`: pinned threads render first with a `[PINNED]` prefix.

### Tests
- Pin sets priority=high by default.
- Unpin clears both fields.
- `pinned_until` in the past is ignored (not shown in Pinned).
- Close auto-unpins.
- Inbox puts pinned above unread.

## Feature 2: Decisions (canonical)

### Data
Add to `ThreadMeta`:
```python
@dataclass
class Decision:
    summary: str
    decided_at: str       # ISO date
    decided_by: str       # author

@dataclass
class ThreadMeta:
    ...
    decision: Decision | None = None
```

New terminal status `decided` (alongside `open`, `resolved`). Valid transitions:
- `open → decided`
- `resolved → decided` (promote a resolution to canonical)
- `decided → open` only with `textforums reopen --force` (warns loudly)

### Immutability
Once `status=decided`, these fields are frozen (same rule as adopted specs):
- `decision.summary`, `decision.decided_at`, `decision.decided_by`
- `meta.title`

Edits get flagged by `tw doctor`:
`decision:<slug> frozen field mutated — revert or reopen`.

Simpler check: verify non-empty and consistent with status. Full history diffing
is out of scope; rely on `git log` over `~/.textforums` if needed.

### CLI
- `textforums decide <slug> --summary "..." [--author NAME]`
  - Transitions to `status=decided`, stamps `decided_at=today`, `decided_by=author`.
  - Refuses if `status` already `decided` (unless `--force`).
  - Appends a final entry: `"Decision: <summary>"` with `status=decided`.
- `tw forums decisions` (parallel to `tw forums spec`):
  - `list [--repo X] [--query T] [--owner R] [--since YYYY-MM-DD]`
  - `show <slug>` — renders decision block + body compactly.
  - `supersede <old-slug> <new-slug>` — adds `rel: superseded-by` link, keeps
    both decided (ADR-history pattern). Does NOT auto-unlock frozen fields.
- `textforums reopen <slug> [--force]` — error unless `--force` when decided.

### Doctor integration
Add a pass in `doctor.py` after the spec check:
```python
# Decisions: warn on missing decision block for decided threads,
# and on decided threads without decided_at.
```

### Filter interactions
- `textforums list --status decided` works via existing `--status` option.
- `textforums list --decided` is a convenience alias (sugar).
- `tw forums inbox` **excludes** `status=decided` from unread by default. Add
  `--include-decided` flag.
- `tw forums decisions` is where you go to browse the law.

### Tests
- `decide` transitions state, stamps date/author, appends entry.
- Can't decide twice without --force.
- Reopen refuses without --force on decided.
- `decisions list --repo X` filters correctly.
- Doctor flags a decided thread with missing summary.

## Shared plumbing

### Serialization
- `_meta_to_dict` / `_parse_meta` handle the new fields.
- Empty `decision`, default `priority`, empty `pinned_until` are not written.
- Legacy threads parse fine.

### Show command
Add to `textforums show` output:
- After `Status:`: `Priority: high` if non-normal.
- If `pinned_until`: `Pinned until: <date>`.
- If `status=decided`: a **`Decision:`** section with summary/decided_at/decided_by
  before the entries list.

### Quickstart
Extend `tw forums quickstart` with a **"Pins and Decisions"** section:
- When to pin vs. decide.
- `textforums pin` / `decide` examples.
- "Decisions are the law — grep `tw forums decisions` before opening a new
  thread on a settled question."

### textmap hook (not in this version — note in IDEAS)
Add to `docs/IDEAS.yaml` under `textmap_population.data_sources`: ingest
`status=decided` threads as `decision` nodes in textmap.

## File map

| File | Changes |
|---|---|
| `src/textworkspace/forums.py` | `Decision` dataclass; `priority`/`pinned_until`/`decision` fields on `ThreadMeta`; serialize/parse; `pin`/`unpin`/`decide` commands; `forums_decisions` subgroup (`list`, `show`, `supersede`); `reopen --force`; inbox `## Pinned` section; inbox excludes `decided` by default; show command updates; quickstart text. |
| `src/textworkspace/doctor.py` | Decision immutability warnings (missing summary, stale `decided_at`). |
| `tests/test_forums.py` | ~10 new tests across both features. |
| `docs/IDEAS.yaml` | New entry under `textmap_population.data_sources`: ingest decisions as `decision` nodes. |
| `pyproject.toml` + `tests/test_cli.py` | Bump to 0.11.0. |

## Ordering for implementation

1. Data model: `Decision` + new `ThreadMeta` fields + serialization round-trip
   (test roundtrip first).
2. Pins: `pin`/`unpin` commands + close-auto-unpin + inbox `## Pinned` section.
3. Decisions: `decide` command + immutability rules in parser.
4. `tw forums decisions` subgroup.
5. `textforums reopen --force` gate.
6. `inbox --include-decided` flag + default exclusion.
7. `textforums show` updates.
8. Doctor warnings.
9. Quickstart text.
10. IDEAS.yaml textmap entry.
11. Bump to 0.11.0, push.

## Defaults (no blockers)

1. **Default priority**: `normal`. Only `high` gets the Pinned section.
2. **`decide` entry text**: `"Decision: <summary>"` with `author=decided_by`,
   `status=decided`. This is the final entry.
3. **Supersede decisions**: old stays `decided` but gets a `superseded-by` link.
   Both findable via `tw forums decisions`; default list hides superseded unless
   `--all`.
4. **Frozen fields on decide**: `title`, `decision.*`. NOT `tags`, `context`,
   `entries` — you can still add entries (comments on a decided thread are fine;
   reversing the decision requires `reopen --force`).
5. **`pinned_until` format**: YYYY-MM-DD (date, not datetime). Compared lexically
   to today's ISO date.

## Bigger picture this fits into

```
ideas            draft thinking
  ↓
threads          ongoing discussion
  ↓
decisions        "this is what we decided" (ADR-lite, durable, cheap)
  ↓
specs            cross-repo contracts (heavy, versioned, structured body)
  ↓
textmap nodes    queryable (decision nodes, protocol nodes)
```

Decisions are the missing "durable but cheap" layer between threads (ephemeral)
and specs (heavyweight). Specs stay for cross-repo contracts; decisions for
per-repo ADR-level commitments. Pins are pure UX on top of both.
