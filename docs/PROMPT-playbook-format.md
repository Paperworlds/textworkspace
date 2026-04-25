# Prompt: Design the playbook YAML format (agent-instruction layer)

Pick this up in a fresh session. Goal: design v1 of the YAML format that
encodes a sequence of agent actions — what `tw run <name>` or
`pp run <name>` would execute, and what a `protocol` node in textmap
points at.

This is the **agent-instruction layer** — separate from textmap's own
ingestion format (frontmatter-in-markdown, already shipped). Don't
conflate the two.

## Where we are right now

- **No decision exists.** `tw forums decisions list` shows only the
  idea-expander decision. Playbook format is still brainstorm.
- **Two existing artifacts to study:**
  - `paperagents/docs/specs/idea-expander.md` (textprompts/docs/specs/
    after the rename) — adopted spec for a single-purpose persona run.
    Shows the precedent for "named, versioned, frozen-when-adopted YAML
    that pp executes."
  - `textmap/docs/schema.md` and `textmap/docs/ingest.md` — show how
    textmap consumes structured artifacts. A playbook should be
    *referenceable* from a `protocol` node, not necessarily *ingested*
    into one.
- **Brainstorms to absorb (in `textworkspace/docs/IDEAS.yaml`):**
  - `tw-lead-loop` (~line 645) — the broader context: lead loop reads
    state, dispatches workers, aggregates. Playbooks are what the lead
    invokes.
  - `tw_actions` / `tw run` mentions (~line 703 onwards) — the
    "action-spec" framing. Includes phrases like "YAML-defined action
    sequences (playbooks)" and "a playbook can be stored as a subgraph
    template." Use these as constraints, not gospel.
  - `pp-forums-integration` — describes "playbook YAML stays as the
    contract; thread is the trace." Confirms separation: playbook =
    static contract, thread = dynamic execution log.

## The design space (open questions)

Aim to land 6–10 of these in v1; punt the rest to v2.

1. **Granularity of a step.** Is each step a shell command, a tool call,
   a sub-playbook, or an arbitrary "agent turn"? Steps need to be
   re-runnable / dry-runnable — what's the smallest unit that supports
   that?

2. **Owner repo + spec system.** Playbooks should follow the spec
   pattern: owner repo, frontmatter, immutable when `status=adopted`.
   That's already built. Question: do they live in
   `<repo>/playbooks/<slug>.yaml` or extend the existing `docs/specs/`
   convention?

3. **Inputs / outputs.** How does a playbook declare what it needs (CLI
   args, env, prior playbook output) and what it produces (artifacts,
   forum threads, textmap nodes)? Look at idea-expander's
   `--idea <repo>/<id>` for one shape.

4. **Conditions, branches, loops.** Minimal v1 should probably support
   `skip_if` (we already have it in combos) and sequential steps.
   Branches and loops likely v2 — but the schema needs to leave room.

5. **Tool scope (allow-list).** Like personas — playbooks restrict what
   tools the runner can call. Reuse the persona shape (`allowed_tools`,
   `disallowed_tools`)?

6. **Resume semantics.** Like idea-expander: thread IS the state for
   single-run personas. Multi-step playbooks need richer state — a
   `state.yaml` per run? Or every step writes a forum entry and resume
   replays from there?

7. **Validation.** Static (the file parses against a JSON Schema) and
   runtime (each step's output matches its declared shape). Static is
   table-stakes; runtime is the harder ask.

8. **textmap projection.** When a playbook is registered, what becomes
   a graph node? Probably one `protocol` node per playbook with edges
   `applies_to` → systems / repos. A run probably does NOT become a
   node (high churn) — but a *decided run* might.

9. **Versioning.** Same `supersedes:` pattern as specs. A playbook
   adopt → freeze → supersede chain.

10. **Composition.** Can playbook A include playbook B? Useful for
    library-style playbooks (e.g. "deploy-with-approval" wraps "deploy").
    Risk: composition without good schema = chaos. Maybe v2.

11. **Persona × playbook.** A persona is "who runs it" (system prompt,
    tools, model). A playbook is "what gets run." Are these orthogonal
    (playbook references persona by slug) or fused (playbook *is* a
    persona with steps)? Lean orthogonal — but pin it down.

12. **Where `tw` fits.** `tw run <name>`? `tw playbook run <name>`?
    Or always `pp playbook run <name>` since pp is the executor?
    Probably the textworkspace side is just the registry/discovery —
    pp owns execution (same split as personas).

## Strawman to react against (NOT a proposal — a starting target)

```yaml
# textworkspace/playbooks/triage-stale-pr.yaml  (or docs/specs/playbooks/...)
---
slug: triage-stale-pr
owner: textworkspace
version: 0.1.0
status: draft
persona: pr-reviewer            # references a persona spec by slug
inputs:
  - name: pr_number
    type: int
    required: true
outputs:
  - kind: forum-thread
    tag: "playbook:triage-stale-pr"
---

# Triage stale PR
Steps run sequentially; output of step N available as ${steps.<id>.out} in step N+1.

steps:
  - id: fetch
    run: gh pr view {{ pr_number }} --json author,updatedAt,title
    out: pr

  - id: classify
    skip_if: "${steps.fetch.out.updatedAt} > now-14d"
    persona_turn: |
      Decide if this PR should be closed, pinged, or left alone.
      Context: ${steps.fetch.out}
    out: verdict

  - id: post
    run: textforums new --tag playbook:triage-stale-pr \
            --title "PR #{{ pr_number }} triage: ${steps.classify.out.verdict}" \
            --content "..."
```

This is **deliberately rough** — half the syntax is hand-wavy. The point
is to get reactions on:
- frontmatter shape (probably good — matches specs)
- step granularity (mixing shell `run` with `persona_turn` — does that
  fly, or should they be separate kinds?)
- variable substitution (`{{ inputs.x }}` vs `${steps.id.out}` — pick one)
- output declaration (what does "produces a forum thread" mean
  formally?)

## Deliverable

What I'd like out of this discussion:

1. A `spec-playbook-format-v1` thread opened in textforums, owner
   `textworkspace` (or paperagents/textprompts — argue it).
2. A draft `docs/specs/playbook-format.md` in the owner repo with
   frontmatter, status `draft`, the agreed schema and 1–2 worked
   examples.
3. A short list of open questions parked in the thread for v2.

Don't try to ship a fully-decided spec in one shot. The goal is to
graduate the brainstorm to a draft, with a thread that captures the
debate.

## Things to NOT do (lessons from idea-expander)

- Don't overload an existing CLI verb. We split `pp run` from
  `pp persona run` after-the-fact; do it right the first time here.
- Don't bake textmap ingestion into v1. The protocol-node projection
  can be a follow-up.
- Don't pre-decide composition or branching. v1 is sequential steps.

## Pointers to read first

```
textworkspace/docs/IDEAS.yaml         (search: tw-lead-loop, tw_actions, playbook)
textprompts/docs/specs/idea-expander.md   (shape precedent)
textprompts/personas/idea-expander.yaml   (persona shape)
textmap/docs/schema.md                (don't conflate ingestion with this)
textworkspace/src/textworkspace/specs.py  (spec-as-data implementation)
textworkspace/src/textworkspace/combos.py (existing skip_if / args / steps DSL — closest existing thing)
```

Combos is the closest existing artifact — it already has `steps`,
`run`, `skip_if`, `args`. Read it first; the playbook may be combos +
persona + structured I/O + adopt-freeze.
