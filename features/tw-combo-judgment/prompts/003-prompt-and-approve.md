---
id: '003'
title: "prompt: and approve: AI-assisted judgment steps"
repo: textworkspace
model: opus
budget_usd: 5.00
phase: phase-3
depends_on: ['001', '002']
---

# 003 — prompt: and approve: AI-assisted judgment steps

## Goal

Add `prompt:` step (send context to Claude, capture response) and `approve:`
step (show proposed output, require explicit y/n before continuing).

## Context

Read `LEAD.md` for the three design alternatives. This prompt implements
**Alternative A** (inline `claude -p`), the simplest approach. Session-backed
prompts (Alternative B) can be added later as an enhancement.

After prompts 001-002, the engine has `capture:` and `confirm:`. This prompt
adds the final two primitives.

Key files:
- `src/textworkspace/combos.py` — `run_combo()`
- `tests/test_combos.py`

## Steps

1. **combos.py — prompt step type** — Detect `prompt:` as a new step type. When encountered:
   - Interpolate the prompt text (supports `{variables}` from args, options, context)
   - Run: `subprocess.run(["claude", "-p", interpolated_text], capture_output=True, text=True)`
   - If `capture:` is present, store stdout in context (same as shell capture)
   - Print the response to the terminal (tee behavior)
   - If `claude` is not on PATH, fail with clear error: "prompt: step requires claude CLI"
   - If the subprocess fails (non-zero exit), stop the combo

2. **combos.py — approve step type** — Detect `approve:` as a new step type. When encountered:
   - Interpolate the content string
   - Print a header: "--- Proposed output ---"
   - Print the interpolated content
   - Print a footer: "--- End proposed output ---"
   - If interactive: `click.confirm("Execute the above?", default=False, abort=True)` — note `default=False` (safe by default)
   - If non-interactive: fail with error "approve: requires interactive terminal" — NEVER auto-approve

3. **combos.py — safety rule** — Add a validation pass in `run_combo()` before execution starts:
   - If a combo has a `prompt:` step with `capture: X`, and a later `shell:` step interpolates `{X}`, there MUST be an `approve:` step between them
   - If this validation fails, abort with: "Safety: approve: required between prompt: output and shell: execution"
   - This prevents accidentally auto-executing AI-generated commands

4. **Tests** — Add `TestPromptSteps` and `TestApproveSteps` to `tests/test_combos.py`:

   **TestPromptSteps:**
   - `test_prompt_calls_claude_cli` — mock subprocess, verify `["claude", "-p", ...]` called
   - `test_prompt_captures_response` — verify stdout stored in context
   - `test_prompt_interpolates_variables` — prompt text uses `{captured}` from prior step
   - `test_prompt_fails_without_claude` — mock `shutil.which("claude")` returning None, verify error
   - `test_prompt_fails_on_nonzero_exit` — claude returns exit 1, combo stops

   **TestApproveSteps:**
   - `test_approve_continues_on_yes` — mock confirm, verify later steps run
   - `test_approve_aborts_on_no` — mock confirm to raise Abort, verify combo stops
   - `test_approve_default_is_no` — verify the confirm prompt defaults to "n" (safe)
   - `test_approve_fails_noninteractive` — non-interactive terminal, verify error (not skip)
   - `test_approve_interpolates_content` — approve message uses `{variable}`

   **TestSafetyValidation:**
   - `test_prompt_to_shell_requires_approve` — prompt captures X, shell uses {X}, no approve between → error
   - `test_prompt_to_shell_with_approve_ok` — same but with approve between → runs fine
   - `test_prompt_without_shell_no_approve_needed` — prompt captures X, only used in echo → no error

5. **Example combo** — Add a `clean-ghosts` example to `LEAD.md` appendix showing all four new step types working together:
   ```yaml
   clean-ghosts:
     description: AI-assisted ghost session cleanup
     args: []
     steps:
       - shell: ts scan-ghosts --json
         capture: ghosts
       - prompt: |
           Here are orphaned sessions:
           {ghosts}
           For each, output a shell command: either
             ts scan-ghosts --repo <label> --discard
           or
             ts rename <id-prefix> <descriptive-name>
           Output ONLY the commands, one per line, no explanation.
         capture: commands
       - approve: "{commands}"
       - shell: |
           {commands}
       - shell: ts reindex
       - shell: ts scan-ghosts
   ```

6. **Commit** — `feat(combos): add prompt: and approve: steps for AI-assisted judgment`

## Acceptance criteria

- `prompt: "text"` sends to `claude -p` and captures response
- `approve: "content"` shows content and requires explicit y/n (default: n)
- Safety validation prevents prompt output reaching shell without approval
- Non-interactive: approve fails loudly (never auto-executes AI output)
- All new tests pass, all existing tests still pass
- The clean-ghosts example combo works end-to-end (manual verification)
