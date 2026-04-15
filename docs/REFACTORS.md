# Paperworlds — Refactoring Directives

Lessons captured from refactoring sessions across the stack.
Apply these when starting a refactor on any repo.

---

## Process

1. **Find duplicates first, fix one by one.** Each duplicate gets its own commit. Don't batch.
2. **Then look at the bigger picture.** Once duplicates are gone, assess module structure and move things to better homes.
3. **Run `/simplify` last.** After structural changes are done, run simplify over the full result and fix what surfaces.
4. **One commit per logical change, one version bump per commit.**

---

## Version

- The canonical version lives in `pyproject.toml` only. Never hardcode it elsewhere.
- `__init__.py` reads it at runtime:
  ```python
  from importlib.metadata import version, PackageNotFoundError
  try:
      __version__ = version("<package>")
  except PackageNotFoundError:
      __version__ = "unknown"
  ```
- The CLI exposes it as `--version` / `-V` with a git hash suffix per CONVENTIONS.md:
  ```python
  try:
      _git_hash = _sp.check_output(
          ["git", "rev-parse", "--short", "HEAD"],
          stderr=_sp.DEVNULL, text=True,
          cwd=Path(__file__).parent,
      ).strip()
      _version_str = f"{__version__} ({_git_hash})"
  except Exception:
      _version_str = __version__

  @click.version_option(_version_str, "--version", "-V", prog_name="<tool>")
  ```

---

## Tests

- Shared test helpers belong in `tests/conftest.py` as plain functions, not duplicated per file.
- Import them explicitly: `from conftest import make_foo, make_bar`.
- Regression tests are mandatory for every bug fix — add a test that would have caught it.
- Keep fixtures small. Tests must complete in milliseconds.
- After a refactor pass, include a test confidence table in the CHANGELOG entry (see CONVENTIONS.md).

---

## Exception handling

- Never use bare `except Exception` to swallow errors silently — it hides bugs.
- Catch specific exceptions: `except (ValueError, subprocess.TimeoutExpired, FileNotFoundError)`.
- When converting between exception types (e.g. `click.UsageError` → `ValueError` at an API boundary), use `raise NewError(...) from None` to suppress chained traceback noise.
- In UI/TUI action handlers, `except Exception as e: notify(str(e))` is intentional — the app must not crash. This is the one valid broad-catch pattern.

---

## Magic strings

- Any string ID used across more than one method in the same class is a constant, not a literal.
- Put it at class level: `_PRIMARY_BTN = "save-btn"`, `_ALIAS_INPUT = "alias-input"`.
- Use it in `compose()`, event handlers, and `_submit()` — all from the same constant.

---

## Shared class behaviour (UI)

- When multiple UI classes share identical event handlers or bindings, extract a base class.
- Use the template method pattern: base implements the shared wiring, subclasses implement `_submit()`.
- Example: `_ModalBase` with shared `BINDINGS`, `on_button_pressed`, `on_input_submitted`.
- CSS type selectors match subclasses in Textual — collapse `A #x, B #x, C #x` to `_Base #x`.

---

## YAML / config loading

- Validate structure explicitly on load — don't trust that keys exist.
- Check `isinstance(entry, dict)` before accessing keys.
- Check required keys are present before using them.
- Raise `ValueError` with a message that names the offending entry and the missing key.

---

## Imports

- Module-level imports only. No inline `import foo` inside functions.
- Exception: truly optional/heavy dependencies that should not be imported at startup.

---

## Redundant checks

- Store the result of an existence check (`is_dir()`, `exists()`) in a variable. Don't call it twice.
- Computing the same filesystem metadata twice in one loop is both redundant and a minor TOCTOU smell.

---

## Version bumping rules (recap from CONVENTIONS.md)

| What changed | Bump |
|---|---|
| Bug fix, no API change | patch |
| New structural refactor (base class, module reorganisation) | minor |
| New public export or command | minor |
| Breaking API or config change | major |
