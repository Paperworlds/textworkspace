# Spec: Agent Context — Forums + Knowledge Graph

Date: 2026-04-14
Status: draft

## Problem

Agents in the paperworlds stack work in isolation. When one agent hits a
cross-repo blocker (broken API, migration needed, missing config), it logs
`BLOCKED` and stops. No other agent or human sees the blocker until someone
reads the progress log. Meanwhile, the next agent on the same repo may run
into the same wall — or worse, work around it in an incompatible way.

Separately, agents have no awareness of the structural relationships between
repos — which functions call which, what depends on what, what changed
upstream. They discover breakage by crashing into it.

Two tools address these gaps:

- **textforums** — temporal coordination ("this API was renamed yesterday")
- **textmap** — structural knowledge graph ("tw status imports textsessions.list_sessions")

Both answer the same agent question: **"what do I need to know before I
start?"** This spec defines how they work together.

## Goal

Give every agent automatic, pre-task context drawn from two sources:

1. **Forums** — open threads relevant to the task (temporal, human-written)
2. **Knowledge graph** — structural facts about the code the task touches (persistent, auto-generated)

Three properties across both:

1. **Discovery** — an agent always knows what's relevant to its task
2. **Delivery** — discovery is automatic, not dependent on agent discipline
3. **Feedback** — agents write back (forum threads, graph annotations)

## textforums vs textmap — boundary

| | **textforums** | **textmap** |
|---|---|---|
| **Nature** | Temporal coordination | Structural knowledge |
| **Content** | Things happening now | Things that are true |
| **Written by** | Agents and humans | Automated analysis + agent annotations |
| **Lifespan** | Short — open, acted on, closed | Long — persists until code changes |
| **Example** | "load_sessions is being renamed" | "tw.status imports textsessions.list_sessions" |
| **Query** | "what's blocking me?" | "what depends on this function?" |
| **Storage** | `~/.textforums/<slug>/thread.yaml` | textmap's graph store (TBD) |

**Forums are the mutable inbox. Textmap is the stable map.**

### Where they overlap

Both feed pp context injection. When `pp run` prepends context to a prompt,
it shouldn't care whether a fact came from a forum thread or a graph query.
Both are just context the agent needs.

### Where they reinforce each other

- **Forums feed the graph.** A blocker thread saying "load_sessions renamed
  to list_sessions" is semantically a graph edge: `load_sessions --renamed_to-->
  list_sessions`. If textmap existed when the thread was posted, the forum
  would be a human-friendly wrapper around a graph mutation. Long-term,
  textmap could auto-generate forum threads from detected breaking changes.

- **Graph sharpens forum relevance.** Without the graph, pp injects all
  threads tagged `textworkspace` into any textworkspace prompt. With the
  graph, pp can ask: "which threads affect the specific functions this prompt
  touches?" This reduces noise — prompt 003 only sees threads about symbols
  it actually imports, not every open textworkspace thread.

- **Graph detects what forums miss.** An agent may forget to post a thread.
  But if textmap knows that `tw status` calls `load_sessions`, and
  `load_sessions` was deleted in the latest textsessions commit, textmap can
  flag the breakage automatically — no forum thread needed.

### textmap prototype: graph-roadmap

The textmap prototype lives at `/Users/projects/personal/graph-roadmap/`.

**Current state:** Kuzu-backed graph DB with `Node`/`Edge` tables. Nodes
have `id`, `type`, `labels`, `description`, `status`. Edges have `from`,
`to`, `relation`. Currently models company/project knowledge (goals,
problems, systems, agents) — not code dependencies yet.

**CLI:** `graphk query node|type|why|relation` — returns compact JSON.
**MCP server:** `graph_mcp` — wraps `graphk` CLI for agent access via
`query_node`, `query_type`, `query_relation`, `query_why`, `search`.

**What needs to happen for integration:**

1. **Code-level nodes and edges.** The graph needs to model code symbols:
   functions, modules, CLI commands, config paths. Node types like `function`,
   `module`, `cli_command`. Edges like `imports`, `calls`, `depends_on`,
   `reads_config`. The schema (`Node`/`Edge` with string properties) already
   supports this — it's a data population problem, not a schema problem.

2. **Repo-scoped queries.** pp needs to ask: "what changed in repo X that
   affects repo Y?" This maps to:
   ```
   graphk query relation textsessions depends_on --direction in
   ```
   Which returns all nodes that depend on textsessions. If those nodes
   include `tw.status`, pp knows prompt 003 is affected.

3. **Change detection.** Graph needs a `sync` step that diffs the current
   code state against the graph and flags changes. The existing `graph-sync`
   command syncs from YAML — a similar `graph-sync --from-code` could parse
   imports and build the code-level subgraph.

4. **Query interface for pp.** pp should call `graphk` CLI (like `graph_mcp`
   does) rather than importing Python directly. This keeps the tools
   decoupled. The MCP server is a bonus — agents with MCP access can query
   the graph interactively during their session.

## Unified injection model

pp context injection is the single delivery mechanism for both sources.
The agent sees one context block, not two separate systems.

```
pp run 003
  │
  ├─ read prompt frontmatter → repo: textsessions
  │
  ├─ FORUMS: textforums list --tag textsessions --status open
  │   └─ 1 thread: "load_sessions renamed to list_sessions"
  │
  ├─ GRAPH: textmap query --repo textsessions --scope prompt-003
  │   └─ 1 fact: "tw.status imports textsessions.load_sessions (DELETED)"
  │
  ├─ MERGE + DEDUPLICATE:
  │   the forum thread and the graph fact describe the same rename
  │   → merge into single entry, forum wording wins (human-authored)
  │
  ├─ format as unified context block:
  │   ┌──────────────────────────────────────────────┐
  │   │ ## Pre-task context for textsessions          │
  │   │                                              │
  │   │ ### blocker: load_sessions renamed            │
  │   │ > load_sessions() → list_sessions() in v0.4  │
  │   │ > — @worker-002 · forum: load-sessions-...   │
  │   │ > Affects: tw.status (import)                │
  │   │                                              │
  │   │ ### info: session-cache-moved                 │
  │   │ > Cache moved from _cache.json to YAML index │
  │   │ > — @lead · forum: session-cache-moved       │
  │   └──────────────────────────────────────────────┘
  │
  └─ spawn worker with enriched prompt
```

### Merge rules

1. If a forum thread and a graph fact describe the same change (matched by
   symbol name or commit hash), merge them into one entry. Forum wording
   takes precedence (it's human-curated), graph adds the "Affects:" line.
2. If only a forum thread exists (no graph data yet), inject it as-is.
3. If only a graph fact exists (no one posted a thread), inject it with
   an auto-generated summary: "textmap detected: {description}".
4. Deduplicate by symbol — don't tell the agent about the same rename twice.

### Phasing

textmap is in prototype. The injection model is designed so forums work
standalone today (rules 1-2 are sufficient), and textmap enriches them
later without changing the agent-facing format.

- **Now:** pp queries forums only. Agents see forum threads.
- **Next:** pp queries forums + textmap. Agents see merged context.
- **Later:** textmap auto-generates forum threads for detected breakage,
  closing the loop between structural analysis and human coordination.

---

## Design — Forums

### Layer 1: Tag convention (convention, no code)

Every forum thread MUST have at least one **repo tag** matching a repo name
in the stack (`textworkspace`, `textaccounts`, `textsessions`, `textworld`,
`textgame-io`, `paperagents`).

Additional tags are encouraged:
- Prompt ID: `003`, `prompt-003` — links thread to a specific task
- Category: `blocker`, `info`, `question`, `migration`

Tag rules:
- `textforums new` SHOULD warn if no `--tag` is provided (future: make required)
- Tags are lowercase, hyphen-separated
- First tag should be the target repo

### Layer 2: pp context injection (automatic, code in pp)

When `pp run <id>` spawns a worker, it prepends open forum threads to the
prompt context. The worker cannot miss them.

#### Injection flow

```
pp run 003
  │
  ├─ read prompt frontmatter → repo: textsessions
  │
  ├─ textforums list --tag textsessions --status open --raw
  │   └─ returns: 2 threads (slug, title, latest entry, priority)
  │
  ├─ format as markdown block:
  │   ┌──────────────────────────────────────────────┐
  │   │ ## Open forum threads for textsessions       │
  │   │                                              │
  │   │ ### blocker: api-rename-load-sessions         │
  │   │ > `load_sessions` is being renamed to        │
  │   │ > `list_sessions` in v0.4.0. Do NOT use the │
  │   │ > old name. — @paolo 2026-04-13              │
  │   │                                              │
  │   │ ### info: session-cache-moved                 │
  │   │ > Cache moved from _cache.json to per-index  │
  │   │ > YAML files. See textsessions v0.3.0 notes. │
  │   │ > — @lead 2026-04-12                         │
  │   └──────────────────────────────────────────────┘
  │
  ├─ prepend block to prompt content
  │
  └─ spawn worker with enriched prompt
```

#### Filtering

- Default: inject only threads tagged with the prompt's `repo:` field
- `blocker` threads are always injected (highlighted with warning)
- `info` threads are injected but visually quieter
- Resolved threads are never injected
- If no matching threads exist, no block is prepended (no noise)

#### Format

The injected block uses this template:

```markdown
## Open forum threads for {repo}

> **Read these before starting work.** If any blocker applies to your task,
> address it or post a reply explaining your approach.

### {priority}: {title}
> {latest_entry_content} — @{author} {date}
> Thread: {slug} | Tags: {tags} | Entries: {count}

---
```

### Layer 3: Write-on-block (convention, enforced by prompt template)

When an agent encounters a cross-repo dependency it cannot resolve, it MUST:

1. Post a forum thread: `textforums new --title "<description>" --tag <target-repo> --tag blocker --content "<details>"`
2. Log the slug in its progress log: `[timestamp] BLOCKED — posted forum thread: <slug>`
3. Continue with other work if possible, or exit with state `BLOCKED`

This is enforced via the standard prompt template. Every prompt includes:

```
If you hit a cross-repo dependency you cannot resolve:
1. Run: textforums new --title "<what's blocked>" --tag <repo> --tag blocker -c "<details>"
2. Log the thread slug in your progress log
3. Set state to BLOCKED if you cannot continue
```

### Layer 4: pp post-task scan (visibility, code in pp)

After a worker completes, `pp` checks for new forum threads created during
the run:

```
pp run 003 completes
  │
  ├─ check: any threads in ~/.textforums/ modified after task start time?
  │   └─ yes: blocks-003-session-api (created by worker)
  │
  ├─ log: "Worker created 1 new forum thread: blocks-003-session-api"
  │
  └─ notify: include thread info in macOS notification
```

This gives the lead (human or orchestrator) immediate visibility into
cross-repo requests without reading every progress log.

### Layer 5: Forums as dependency (hard enforcement, code in pp)

A thread tagged `blocks:<prompt-id>` prevents that prompt from running:

```yaml
# Thread meta
title: "Session API rename blocks prompt 003"
tags: [textsessions, blocker, "blocks:003"]
status: open
```

```
pp run 003
  │
  ├─ check: textforums list --tag "blocks:003" --status open
  │   └─ found 1 blocking thread
  │
  ├─ log: "BLOCKED by forum thread: blocks-003-session-api"
  │
  └─ exit without spawning worker
```

The thread must be closed (`textforums close <slug>`) before the prompt
can run. This is the nuclear option — use sparingly.

## Priority field

Threads have a `priority` value in their first tag set:

| Priority | Meaning | Injection | Blocks pp? |
|----------|---------|-----------|------------|
| `blocker` | Must address before proceeding | Always, highlighted | Only with `blocks:NNN` tag |
| `info` | Useful context, not blocking | Always, quieter | Never |
| `question` | Needs answer, may or may not block | Always | Never |

Priority is a tag, not a separate field. This avoids schema changes to
textforums — it's just a tag convention.

## Slug conventions

For prompt-linked threads, use this naming pattern:

```
blocks-{prompt_id}-{description}
info-{prompt_id}-{description}
question-{description}
```

Examples:
- `blocks-003-session-api-rename`
- `info-001-new-config-format`
- `question-which-yaml-parser`

`pp` can pattern-match on `blocks-NNN` for automatic prompt linking,
falling back to the `blocks:NNN` tag for explicit links.

## Implementation phases

| Phase | What | Where | Effort |
|-------|------|-------|--------|
| 1 | Tag convention docs, warn on missing tags | textforums, CONVENTIONS.md | Low |
| 2 | pp context injection (forums only) | paperagents | Medium |
| 3 | Write-on-block prompt template | paperagents/prompts template | Low |
| 4 | pp post-task scan | paperagents | Medium |
| 5 | Forums as dependency | paperagents | Medium |
| 6 | Code-level nodes/edges in graph-roadmap | graph-roadmap | Medium |
| 7 | `graphk query` integration in pp injection | paperagents, graph-roadmap | Medium |
| 8 | Merge/dedup logic (forums + graph facts) | paperagents | Medium |
| 9 | textmap auto-posts forum threads on breakage | graph-roadmap, textforums | High |

Phase 1 can ship today. Phase 2-3 are the real value — target next.
Phase 4-5 are follow-ups once forums are validated.
Phase 6 is the bridge — graph-roadmap needs code-level data before pp
can query it. Phase 7-9 require graph queries to be stable.

## Files affected

### textworkspace (this repo)
- `src/textworkspace/forums.py` — `list_threads()` already supports `--tag` + `--status` filtering (no changes for phase 1-2)
- `docs/CONVENTIONS.md` — tag convention docs

### paperagents
- Injection logic in `pp run` — query forums, later query graphk, merge, prepend
- Post-task scan — check for new threads after worker completes
- `prompts/` template — write-on-block instructions
- `CLAUDE.md` — document injection behavior

### graph-roadmap
- `src/graph_roadmap/sync.py` — add `--from-code` to populate code-level nodes
- `src/graph_roadmap/query.py` — no changes needed, existing `relation`/`node` queries work
- `src/graph_mcp/tools.py` — no changes needed, existing wrappers work
- New: change detection logic (diff graph state vs current code)

## Scenario: Cross-repo API rename

A 5-prompt pipeline for `textsessions` v0.4.0. Prompt 002 renames
`load_sessions` to `list_sessions`. Prompts 003 and 004 (in `textworkspace`
and `paperagents` respectively) consume the renamed API.

### Without forums

1. Worker 002 renames the function, commits, DONE
2. Worker 003 starts, imports `load_sessions`, gets `ImportError`, logs BLOCKED
3. Worker 004 starts independently, same crash, same BLOCKED
4. Lead reads both progress logs, realizes the rename landed, manually re-runs 003 and 004
5. Worker 004 had already worked around it by pinning the old import — now there's divergent code

Two wasted runs, one silent divergence, manual log reading required.

### With forums only (today)

**Step 1 — Worker 002 finishes the rename, posts a thread:**

```bash
textforums new \
    --title "load_sessions renamed to list_sessions" \
    --tag textsessions --tag textworkspace --tag paperagents \
    --tag blocker \
    -c "load_sessions() is now list_sessions() as of v0.4.0.
        All consumers must update their imports.
        Old name will be removed in v0.5.0."
```

**Step 2 — pp run 003 starts (textworkspace repo):**

pp reads prompt 003 frontmatter (`repo: textworkspace`), queries
`textforums list --tag textworkspace --status open`, finds the thread,
and prepends it to the prompt:

```
## Pre-task context for textworkspace

### blocker: load_sessions renamed to list_sessions
> load_sessions() is now list_sessions() as of v0.4.0.
> All consumers must update their imports.
> — @worker-002 2026-04-14
> Thread: load-sessions-renamed-to-list-sessions | Entries: 1
```

Worker 003 sees this in its prompt context. It uses `list_sessions()` from
the start. No crash. No workaround. DONE.

**Step 3 — pp run 004 starts (paperagents repo):**

Same injection — the thread is also tagged `paperagents`. Worker 004
sees it, also uses `list_sessions()`. DONE.

**Step 4 — Lead closes the thread:**

```bash
textforums close load-sessions-renamed-to-list-sessions \
    -c "All consumers updated in prompts 003 and 004."
```

Future pipeline runs no longer see it.

**Result:** Zero wasted runs, zero divergent workarounds, zero manual log
reading. The thread is the single source of truth for cross-repo changes.

### With forums + textmap (future)

Same scenario, but textmap is now active.

**Step 1 — Worker 002 renames the function and commits.**

textmap detects the rename via commit analysis:
```
textmap: load_sessions DELETED in textsessions
textmap: list_sessions ADDED in textsessions
textmap: consumers of load_sessions: tw.status, pp.session_loader
```

textmap auto-posts a forum thread (no agent action needed):
```bash
textforums new \
    --title "breaking: load_sessions removed" \
    --tag textsessions --tag textworkspace --tag paperagents \
    --tag blocker \
    -c "textmap detected: load_sessions() was removed in textsessions@abc123.
        Replacement: list_sessions(). Affected consumers: tw.status, pp.session_loader."
```

Worker 002 may ALSO post a thread with human context ("old name removed in
v0.5.0"). The merge rules deduplicate — the human wording wins, the graph
adds the "Affects:" line.

**Step 2 — pp run 003 starts:**

pp queries both sources and merges:
```
## Pre-task context for textworkspace

### blocker: load_sessions renamed to list_sessions
> load_sessions() is now list_sessions() as of v0.4.0.
> All consumers must update their imports.
> — @worker-002 2026-04-14
> Affects: tw.status (direct import) ← from textmap
> Thread: load-sessions-renamed-to-list-sessions | Entries: 2
```

The "Affects" line is new — textmap knows exactly which function in
textworkspace calls the renamed symbol, so the agent knows where to look.

**Step 3 — What if worker 002 forgot to post a thread?**

textmap still detected the breaking change. pp injects it anyway:
```
### blocker (auto-detected): load_sessions removed
> textmap detected: load_sessions() was removed in textsessions@abc123.
> Replacement: list_sessions(). Affects: tw.status (direct import).
```

The safety net catches what conventions miss.

## Open questions

1. Should `textforums new` require `--tag` or just warn? Requiring it
   forces discipline but adds friction for quick notes.
2. Should injection include the full thread or just the latest entry?
   Full thread has more context but may be long. Recommendation: latest
   entry + entry count, with a `textforums show <slug>` pointer.
3. Should resolved threads leave a "was resolved" trace in injection for
   N days? Prevents agents from re-encountering a fixed issue. Probably
   not worth the complexity — skip for v1.
4. How does pp call graphk? Recommendation: shell out to `graphk query`
   CLI (same pattern as `graph_mcp/tools.py` which already does this).
   Keeps pp and graph-roadmap decoupled. If graphk is not on PATH, skip
   graph queries silently (forums-only fallback).
5. When textmap auto-generates forum threads, who is the author? Suggest
   `@textmap` as a system author, distinct from human and agent authors.
6. Merge/dedup heuristics — matching by symbol name is straightforward,
   but fuzzy matches ("session loading" thread vs `load_sessions` symbol)
   need thought. Start with exact symbol match only.
7. graph-roadmap currently models company knowledge (goals, problems,
   systems). Code-level nodes (functions, modules, imports) are a new
   layer. Should they live in the same Kuzu DB or a separate one?
   Recommendation: same DB, different node types (`type: function` vs
   `type: system`). The query interface doesn't change.
8. How does `graph-sync --from-code` discover imports? AST parsing is
   accurate but language-specific. Grep-based is fast but imprecise.
   Start with Python AST (`ast.parse` + walk `Import`/`ImportFrom` nodes),
   expand later.
