# tw-combo-judgment — Feature Context

Feature of: textworkspace

Extend the combo engine with step types that support human judgment, data
piping between steps, and optionally AI-assisted decision-making. The
motivating use case is the textsessions ghost-cleanup workflow, but the
primitives are general-purpose.

## Motivating example

```
ts scan-ghosts          → produces a list of orphaned sessions
human/AI decides        → which to archive, which to rename
ts scan-ghosts --discard / ts rename  → executes the decisions
ts reindex              → reindex
ts scan-ghosts          → verify 0 ghosts remain
```

The middle step requires *judgment* — it can't be a blind `shell:` command.
Today's combo engine has no way to express this.

## Feature scope

Three phases, each self-contained and shippable:

### Phase 1: `capture:` — pipe data between steps

A step can capture its stdout into a named variable. Later steps interpolate it.

```yaml
clean-ghosts:
  steps:
    - shell: ts scan-ghosts --json
      capture: ghosts
    - shell: echo "Found ghosts:\n{ghosts}"
```

**Semantics:**
- `capture: <name>` stores the step's stdout (stripped) into `context[name]`
- Captured variables join the existing `{arg}` and `{option}` interpolation
- Capture works with both `run:` and `shell:` steps
- If the step fails (non-zero exit), the variable is still set (to whatever was printed) — the combo stops on failure as usual unless `continue_on_error` is set

**Implementation:**
- `run_combo()` maintains a `context: dict[str, str]` alongside `options`
- `subprocess.run()` gains `capture_output=True` when `capture` is present
- `_interpolate()` receives merged `{**args, **options, **context}`

### Phase 2: `confirm:` — human-in-the-loop gate

A step that pauses execution, shows a message, and waits for the user to
continue or abort.

```yaml
clean-ghosts:
  steps:
    - shell: ts scan-ghosts
    - confirm: "Review the output above. Archive/rename as needed, then continue."
    - shell: ts reindex
    - shell: ts scan-ghosts
```

**Semantics:**
- `confirm: <message>` prints the message and prompts `[Enter to continue / Ctrl-C to abort]`
- The message supports `{variable}` interpolation
- If the user aborts (Ctrl-C or types "n"), the combo stops cleanly
- In non-interactive mode (piped stdin), `confirm:` is skipped with a warning

**Implementation:**
- New step type detected in `run_combo()` alongside `run:` and `shell:`
- Uses `click.confirm()` or `input()` for the gate
- Respects `sys.stdin.isatty()` for non-interactive detection

### Phase 3: `prompt:` — AI-assisted judgment

A step that sends context to a Claude session and captures the response.
This is the most powerful primitive — it turns combos into agentic workflows.

**Three design alternatives to evaluate:**

#### Alternative A: Inline `prompt:` step

```yaml
clean-ghosts:
  steps:
    - shell: ts scan-ghosts --json
      capture: ghosts
    - prompt: |
        Here are orphaned sessions:
        {ghosts}
        For each, decide: archive (ts scan-ghosts --repo <label> --discard)
        or rename (ts rename <id> <name>).
        Output ONLY the shell commands, one per line.
      capture: commands
    - approve: "{commands}"
    - shell: "{commands}"
```

New step types:
- `prompt: <text>` — sends to `claude -p "<text>"`, captures stdout
- `approve: <text>` — shows proposed commands, asks y/n before continuing

Pros: Self-contained, no external dependencies beyond `claude` CLI.
Cons: No session persistence, no tool use, limited to single-turn.

#### Alternative B: Session-backed `prompt:` step

```yaml
clean-ghosts:
  steps:
    - shell: ts scan-ghosts --json
      capture: ghosts
    - prompt:
        session: ghost-cleanup      # reuses or creates a textsessions session
        message: |
          Classify these ghosts: {ghosts}
          Output shell commands.
        tools: [ts]                 # allow tool use within the session
      capture: commands
    - approve: "{commands}"
    - shell: "{commands}"
```

Pros: Session persistence, tool use, multi-turn possible.
Cons: Depends on textsessions, heavier, more complex config.

#### Alternative C: External judgment file

```yaml
clean-ghosts:
  steps:
    - shell: ts scan-ghosts --json
      capture: ghosts
    - prompt:
        template: ghost-review      # loads from combos.d/templates/ghost-review.md
        input: "{ghosts}"
        output_format: commands     # "commands" | "json" | "text"
      capture: commands
    - approve: "{commands}"
    - shell: "{commands}"
```

Pros: Reusable templates, output format validation, separation of concerns.
Cons: More files to manage, template discovery adds complexity.

**Recommendation:** Start with Alternative A (simplest, `claude -p`). Add
session backing (B) later if single-turn proves limiting. Templates (C) are
a nice-to-have once the pattern stabilizes.

**Common to all alternatives — the `approve:` gate:**
- Shows the proposed output (commands, plan, etc.)
- Syntax-highlights if it looks like shell commands
- User sees the full plan and types y/n
- On "n", the combo stops (or optionally loops back to the prompt step)
- On "y", the captured variable is available to subsequent steps
- `approve:` is always required between `prompt:` and execution — never auto-execute AI output

## What exists

- Combo engine: `src/textworkspace/combos.py`
  - `run_combo()` — main execution loop
  - `_interpolate()` — `{placeholder}` substitution
  - `evaluate_condition()` — `only_if`/`skip_if` evaluation
  - `resolve_options()` — 3-tier option resolution
  - Step types: `run:` (tw subcommand) and `shell:` (external command)
- CLI: `src/textworkspace/cli.py`
  - `_make_combo_command()` — generates Click commands from combo YAML
  - Combo commands registered dynamically on the `main` group
- Tests: `tests/test_combos.py`
  - `TestShellSteps`, `TestOptions`, `TestDefaultCombos`

## Files to modify

- `src/textworkspace/combos.py` — add `capture`, `confirm`, `prompt`, `approve` step handling
- `src/textworkspace/cli.py` — no changes expected (steps are engine-level, not CLI-level)
- `tests/test_combos.py` — new test classes per phase
- `~/.config/paperworlds/combos.yaml` — add `clean-ghosts` example combo after phase 1

## Constraints

- Python >=3.11, Click for CLI
- No new dependencies for phases 1-2
- Phase 3 requires `claude` CLI on PATH (already a dev dependency)
- `approve:` is mandatory between `prompt:` and any `shell:` that executes AI output
- Non-interactive environments (CI, piped input) must degrade gracefully:
  `confirm:` skips with warning, `prompt:` fails loudly, `approve:` fails loudly
- Captured variables must not leak between combo runs (context is per-invocation)
- Backward-compatible: existing combos with only `run:`/`shell:` steps unchanged

## Test strategy

- **Phase 1**: Mock `subprocess.run` to return known stdout, verify `context` dict populated, verify interpolation in later steps
- **Phase 2**: Mock `click.confirm` / `input`, verify combo stops on abort, verify skip in non-interactive
- **Phase 3**: Mock `subprocess.run` for `claude -p`, verify prompt interpolation, verify `approve:` gate blocks execution
- **E2E (manual)**: The `clean-ghosts` recipe from the motivating example, documented in `docs/TESTING.md`
