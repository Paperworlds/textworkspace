---
slug: playbook-format
owner: textworkspace
status: draft
version: 0.1.0
consumers:
- textprompts
---
# playbook-format: agent-instruction layer for `tw run` / `pp playbook run`

## Summary

A **playbook** is a named, versioned, frozen-when-adopted YAML file that
encodes a sequence of agent actions. `pp playbook run <slug>` executes
it; `tw run <slug>` is the registry/discovery wrapper. Each run produces
a forum thread tagged `playbook:<slug>` whose entries (one per step)
form an audit trail with structured slots for agent feedback and
suggestions (see `docs/audit.yaml`).

This is the **agent-instruction layer** — distinct from textmap's
ingestion format (frontmatter-in-markdown). A playbook may be
*referenced* from a textmap `protocol` node, not ingested into one.

## Motivation

Three things exist today that almost solve this, but don't:

1. **`tw combos`** — sequential shell steps with `skip_if` and `args`.
   No persona binding, no I/O contract, no freeze, no run trace.
2. **`pp run NNN-slug.md`** — prompt-DAG runner. Persona-aware via the
   spec system but optimized for one-shot prompt files; there's no
   reusable, parameterized "agent action" primitive.
3. **`idea-expander`** — proves the "named, versioned, frozen YAML that
   pp executes" pattern works, but is a one-off spec for one persona.

The lead loop (`tw-lead-loop` brainstorm) needs something concrete to
dispatch. The interactive-personas brainstorm
(idea-inbox-validator, textmap-inbox-reviewer) needs a place to live.
Cross-repo coordination needs a first-class artifact a `protocol` node
can point at. A playbook is the missing primitive: combos + persona +
typed I/O + adopt-freeze.

## Interface

### File layout

A playbook lives in its **owner repo** at:

```
<owner-repo>/docs/specs/playbooks/<slug>.yaml
```

The directory is new but follows the existing spec convention (owner
repo, frontmatter, immutable when `status: adopted`).

### Schema

```yaml
# docs/specs/playbooks/<slug>.yaml
---
# Frontmatter — same shape as other specs
slug: <slug>                 # filesystem-friendly, unique within owner
owner: <repo>                # repo that owns the playbook
status: draft | adopted | superseded
version: <semver>            # bump on any spec edit
adopted_at: <YYYY-MM-DD>     # set when status flips to adopted
supersedes: <slug>@<version> # optional — replaces an older playbook
consumers:                   # repos that register/discover this
  - <repo>
description: <one-line>
persona: <persona-slug>      # bound persona for any persona_turn steps
inputs:
  - name: <id>
    type: string | int | bool | path
    required: true | false
    default: <value>         # optional
    description: <one-line>
outputs:
  - kind: forum-thread | file | textmap-node | stdout
    tag: <pattern>           # for forum-thread: e.g. "playbook:<slug>"
    description: <one-line>
budget:
  max_turns: <int>           # optional cap on LLM turns
  budget_usd: <float>        # optional soft $ cap
---

# <playbook title>

<short prose explanation — what the playbook does and when to invoke it.>

steps:
  - id: <step-id>            # unique within the playbook
    kind: run                # one of: run | persona_turn
    run: <shell-command>     # for kind=run
    skip_if: <expression>    # optional; v1 only supports skip_if
    out: <var-name>          # optional; binds output for later steps

  - id: <step-id>
    kind: persona_turn
    persona_turn: |          # for kind=persona_turn — prompt body
      <multiline prompt; persona is the playbook's bound persona>
    out: <var-name>
```

#### Step kinds (v1)

Only two — keep the union tight. Composition (`sub_playbook`) is parked
for v2.

| Kind            | What runs                                 | Input                              | Output                   |
|---              |---                                        |---                                 |---                       |
| `run`           | shell command (sandboxed by persona scope)| stdout/stderr from prior steps    | stdout (parsed if JSON)  |
| `persona_turn`  | one LLM turn, bound to the playbook persona | conversation context + prompt body | LLM response text      |

#### Variable substitution

One syntax — `${...}`. No `{{ }}` to avoid ambiguity:

- `${inputs.<name>}` — declared input
- `${steps.<id>.out}` — output of a previous step
- `${env.<NAME>}` — env var (only if persona allows it)

Substitution happens **before** the step runs. Missing references fail
the run; no silent fallthrough.

#### `skip_if`

A boolean expression evaluated in a small, sandboxed scope. v1 supports:

- comparisons: `==`, `!=`, `>`, `<`, `>=`, `<=`
- string ops: `startswith`, `contains`
- date ops: `> now-Nd`, `< now-Nd`

Branches and loops are **not** in v1. The schema reserves `when:` and
`for_each:` keys for v2 — runners must reject them today.

### Invocation

Two entry points, same execution path:

1. **Direct (executor):** `pp playbook run <slug> [--input name=value ...]`
   Reads the spec, validates inputs, runs the steps, writes the run
   trace as a forum thread.

2. **Via tw (registry):** `tw run <slug> [--input name=value ...]`
   Thin wrapper. Resolves the spec across all registered owner repos,
   shells out to `pp playbook run`, surfaces its exit state.

Note: `pp playbook run` is a **new verb**. Do NOT overload `pp run`
(which executes prompt files). This is the lesson from `idea-expander`.

### Persona binding

Playbooks reference personas by slug; they do not redefine them. The
referenced persona's `allowed_tools` / `disallowed_tools` apply to
every `kind: run` step in the playbook. A playbook MUST NOT widen the
persona's tool scope; tightening (subset) is allowed via an optional
`step.tools_subset:` list, deferred to v1.1.

### Run trace (audit)

The full run-trace contract lives in `docs/audit.yaml`. Quick summary:

- **One thread per run.** Title `playbook:<slug> run <run_id>`. Tags:
  `playbook:<slug>`, `run:<run_id>`, owner repo.
- **One entry per step.** Required fields: `step_id`, `status`,
  `output_summary`. Optional: `output_full`, `agent_feedback`,
  `agent_ideas`, `duration_ms`, `retry_count`.
- **Reviewer interaction is plain forum verbs.** No new commands except
  `tw runs ideas promote` for graduating an `agent_ideas` entry.

### Resume semantics

The thread is the state, but unlike `idea-expander` (single-purpose),
playbooks are multi-step — so resume needs richer signal:

- Each step entry, on success, includes `status: ok` and any `out:`
  binding written into the thread `meta.bindings` map.
- On resume, `pp playbook run --resume <run-slug>` reads `meta.bindings`,
  finds the first step without an entry, and continues.
- `--restart` ignores prior state and runs from step 1 (writes a new
  thread).

### Validation

- **Static.** A JSON Schema lives at
  `<owner>/docs/specs/playbooks/_schema.json`. `tw run` validates the
  spec before delegating; `pp playbook run` re-validates as a
  belt-and-braces check.
- **Runtime.** v1 does **not** validate `outputs:` shape at runtime.
  The frontmatter declares intent; enforcement is v1.1.

### Versioning

Same `supersedes:` chain as other specs. A playbook lifecycle:

1. `status: draft` — editable, no consumer guarantees.
2. `status: adopted` — frozen content. Edits require a version bump
   AND a new file (`<slug>-v0.2.0.yaml` or similar) with
   `supersedes: <slug>@0.1.0`.
3. `status: superseded` — kept for archival; runners refuse new runs.

### textmap projection

A registered playbook spec **may** be projected into textmap as a
`protocol` node:

```
node id:        playbook-<slug>
type:           protocol
status:         active | deprecated
labels:         [playbook]
applies_to:     [<owner-repo>, ...consumers]
implements:     <decision-node-id>   # if a decision adopted it
replaces:       <previous-protocol>  # if it supersedes
```

A run does **not** become a node (high churn). A *decided* run — i.e.
one that produced a thread closed with `tw forums decide` — flows
through the existing decision-export pipeline like any other decided
thread.

This projection is **not** in v1. v1 ships the spec format and the
runner; the protocol-node projection is a follow-up.

## Conformance

A consumer (e.g. textworkspace registering playbooks across repos) MUST:

1. Provide `tw run <slug>` discovery: scan registered repos for
   `docs/specs/playbooks/*.yaml`, validate, and shell out to
   `pp playbook run`.
2. Surface the run thread: `tw runs list`, `tw runs show <run-slug>`.
3. Implement the aggregated ideas inbox: `tw runs ideas list / promote /
   dismiss` per `docs/audit.yaml` §4.

textprompts (executor owner) MUST:

1. Ship `pp playbook run <slug>` as a first-class CLI command, distinct
   from `pp run`.
2. Bind the playbook's `persona:` for `persona_turn` steps; apply tool
   scope to `run` steps.
3. Write the run trace as a forum thread per the audit contract.
4. Acquire a per-run lock at `<state_dir>/locks/playbook-<slug>-<run-id>.lock`
   (same pattern as `idea-expander`).
5. Validate the spec against the JSON Schema before executing.

A playbook author (anyone writing `<owner>/docs/specs/playbooks/X.yaml`) MUST:

1. Set frontmatter: slug, owner, status, version, persona.
2. Declare `inputs:` and `outputs:`.
3. Write only `kind: run` or `kind: persona_turn` steps in v1.
4. Ensure each step has a unique `id:`.
5. Use `${...}` substitution only.

## Worked example

`textworkspace/docs/specs/playbooks/triage-stale-pr.yaml`:

```yaml
---
slug: triage-stale-pr
owner: textworkspace
status: draft
version: 0.1.0
consumers:
  - textworkspace
description: Triage a single PR — fetch state, classify, post verdict.
persona: pr-reviewer
inputs:
  - name: pr_number
    type: int
    required: true
    description: GitHub PR number
  - name: repo
    type: string
    required: true
    description: owner/repo slug
outputs:
  - kind: forum-thread
    tag: "playbook:triage-stale-pr"
    description: one thread per run carrying the verdict
budget:
  max_turns: 3
  budget_usd: 0.10
---

# Triage a stale PR

Fetches PR metadata, asks the persona to classify (close / ping /
leave), then posts a forum thread with the verdict.

steps:
  - id: fetch
    kind: run
    run: gh pr view ${inputs.pr_number} --repo ${inputs.repo} --json author,updatedAt,title
    out: pr

  - id: classify
    kind: persona_turn
    persona_turn: |
      Decide whether this PR should be closed, pinged, or left alone.
      Reply with exactly one of: CLOSE | PING | LEAVE — followed by a
      one-line reason. Context:

      ${steps.fetch.out}
    out: verdict

  - id: post
    kind: run
    skip_if: "${steps.classify.out} startswith 'LEAVE'"
    run: |
      textforums new \
        --tag playbook:triage-stale-pr \
        --tag repo:${inputs.repo} \
        --title "PR #${inputs.pr_number}: ${steps.classify.out}" \
        --content "Verdict: ${steps.classify.out}\n\nMetadata:\n${steps.fetch.out}"
```

## Open questions (parked for v2 / v1.1)

1. **Composition (`sub_playbook`).** Playbook A includes B. Useful for
   wrapping a base playbook with approval gates. Schema reserves the
   key; runners reject it in v1.

2. **Branches / loops.** `when:` (conditional step) and `for_each:`
   (iterate over a list). Schema reserves both; runners reject in v1.
   Most use cases can be lifted into a wrapping playbook for now.

3. **Runtime output validation.** Type-check `step.out` against an
   expected shape (e.g. JSON Schema per output). v1.1.

4. **Tool scope subset per step.** `step.tools_subset:` to tighten the
   persona's tool list for one step. v1.1.

5. **textmap protocol-node projection.** Auto-emit / sync. v1.1 — once
   we have a few real playbooks to look at.

6. **Cross-run idea dedup.** When 5 runs all suggest "pin gh CLI
   version", the aggregator should dedup. Exact-match v1; embeddings
   v2.

7. **Concurrency policy.** Today: per-run lock. Should multiple runs of
   the same playbook with different inputs run in parallel? v1: yes
   (different `run-id`, different lock file). Cross-run rate limits:
   v1.1.

8. **Persona vs playbook ownership.** A playbook references a persona
   by slug. If the persona lives in another repo, who reviews changes?
   For now: persona owner reviews persona; playbook owner reviews
   playbook. Cross-repo concerns surface in the consumer list.

## Things to NOT do (lessons from idea-expander)

- **Don't overload an existing CLI verb.** `pp playbook run` is a new
  verb, not a flag on `pp run`.
- **Don't bake textmap ingestion into v1.** Protocol-node projection
  is a follow-up.
- **Don't pre-decide composition or branching.** v1 ships sequential
  steps. The schema leaves room; runners reject.
- **Don't fuse persona and playbook.** Orthogonal. A playbook
  references a persona; it does not redefine one.
