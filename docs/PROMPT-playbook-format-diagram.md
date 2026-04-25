# Playbook format — current vs proposed flow

## Today (what exists)

```mermaid
flowchart TB
    subgraph Humans["👤 Human / Agent"]
        U[user or claude session]
    end

    subgraph TW["textworkspace (tw)"]
        TWC[tw combos<br/>steps + skip_if + args]
        TWI[tw ideas<br/>capture + expand]
        TWF[tw forums<br/>threads + decisions]
        TWR[tw repo<br/>rename / move]
    end

    subgraph PP["textprompts (pp)"]
        PPP[pp run NNN-slug.md<br/>numbered prompt DAG]
        PPSPEC[specs<br/>idea-expander = 1 frozen spec]
        PPPER[personas<br/>system prompt + tools]
    end

    subgraph TM["textmap"]
        TMG[(graph: systems,<br/>decisions, protocols,<br/>initiatives)]
        TMI[textmap ingest<br/>frontmatter md]
    end

    subgraph Storage["State"]
        FORUMS[(~/.textforums/<br/>thread.yaml)]
        IDEAS[(docs/IDEAS.yaml<br/>or .files/ideas/)]
    end

    U --> TWC
    U --> TWI
    U --> TWF
    U --> PPP

    TWI -.idea:repo/id tag.-> TWF
    TWF -- decisions export --> TMI
    TMI --> TMG
    TWF --> FORUMS
    TWI --> IDEAS

    PPP -. invokes .-> PPPER
    PPSPEC -. shape for .-> PPP

    TWC -. can shell out to .-> PPP

    style TWC fill:#fff3cd
    style PPSPEC fill:#fff3cd
```

**What's missing (the gap):**
- `tw combos` is shell-step automation, no persona binding, no I/O contract, no freeze.
- `idea-expander` is a one-off spec, not a generic shape.
- No first-class artifact for "an agent action sequence" that textmap can point at as a `protocol`.
- Lead loop (`tw-lead-loop` brainstorm) has nothing concrete to dispatch.

---

## Proposed v1 — playbook as the missing primitive

```mermaid
flowchart TB
    subgraph Humans["👤 Human / Agent / Lead Loop"]
        U[user, claude session,<br/>or tw lead worker]
    end

    subgraph TW["textworkspace (tw) — registry"]
        TWRUN["tw run &lt;name&gt;<br/>(thin wrapper, discovery)"]
        TWLIST[tw playbook list]
        TWF[tw forums + decisions]
    end

    subgraph PP["textprompts (pp) — executor"]
        PPRUN["pp playbook run &lt;name&gt;<br/>NEW verb"]
        PPPER[personas<br/>unchanged]
    end

    subgraph PB["📘 Playbook spec (NEW)"]
        direction TB
        PBYAML["docs/specs/playbooks/&lt;slug&gt;.yaml<br/>frontmatter: slug, version, status,<br/>persona, inputs, outputs<br/>---<br/>steps:<br/>  - run: shell<br/>  - persona_turn: LLM call<br/>  - (sub_playbook: v2)"]
    end

    subgraph TM["textmap"]
        TMP["protocol node<br/>points at playbook spec"]
        TMD[decision node<br/>adopts the playbook]
        TMG[(graph)]
    end

    subgraph Storage["State"]
        FORUMS[(~/.textforums/)]
        RUNS[("run trace<br/>= forum thread<br/>tagged playbook:&lt;slug&gt;")]
    end

    U --> TWRUN
    TWRUN -- delegates --> PPRUN
    PPRUN -- reads --> PBYAML
    PPRUN -- binds --> PPPER
    PPRUN -- writes trace --> RUNS
    RUNS --> FORUMS

    PBYAML -. registered as .-> TMP
    TWF -- decision: adopt playbook v0.1 --> TMD
    TMD -- applies_to --> TMP
    TMP --> TMG

    style PBYAML fill:#d4edda,stroke:#28a745,stroke-width:3px
    style PPRUN fill:#d4edda
    style TMP fill:#d4edda
    style RUNS fill:#d4edda
```

**What changes:**

| Layer | Before | After v1 |
|---|---|---|
| Action sequence | `tw combos` (shell) OR ad-hoc prompt files | **playbook spec** (typed, versioned, frozen on adopt) |
| Persona binding | Implicit in prompt files | Explicit `persona: <slug>` in frontmatter |
| I/O contract | None | `inputs:` + `outputs:` declared, validated |
| Run trace | Scattered (logs, ad-hoc) | Forum thread tagged `playbook:<slug>` |
| textmap link | None | `protocol` node per playbook; `decision` node when adopted |
| CLI surface | Overloaded `pp run` | Split: `pp playbook run` (executor) / `tw run` (registry) |

---

## What v1 explicitly does NOT include

- ❌ Branches / loops (only `skip_if` + sequential steps)
- ❌ `sub_playbook` composition
- ❌ Runtime output-shape validation (static JSON Schema only)
- ❌ Fused persona-as-playbook (kept orthogonal)
- ❌ Auto-ingestion into textmap (one-shot export, like decisions today)

These all have hooks left in the schema, but they ship in v2 once the v1 shape is exercised.

---

## The smallest first playbook (proof point)

`triage-stale-pr` — see strawman in PROMPT-playbook-format.md. Three steps:
1. `run: gh pr view` — fetch PR data
2. `persona_turn:` — LLM decides close/ping/leave
3. `run: textforums new` — post the verdict thread

If this one playbook works end-to-end (frozen spec → `pp playbook run` → thread trace → textmap protocol node), the format is validated. Everything else is iteration.
