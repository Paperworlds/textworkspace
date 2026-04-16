# textworkspace v0.4.0 — E2E Smoke Checklist

Manual checks to run after the v0.4.0 refactor. All are CLI invocations — no setup required beyond the normal running stack.

---

## 1. Proxy port resolution

`get_textproxy_port()` was moved from three separate copies in `cli.py`, `combos.py`, and `doctor.py` into a single function in `config.py`. These commands all call it.

```
tw status
```
- [ ] Proxy line shows `running :9880` (or `stopped`) — not a crash or wrong port

```
tw stats
```
- [ ] Reports token/session data (or "textproxy not running" — no crash)

```
tw doctor
```
- [ ] Proxy line shows `:9880 responding` or a clean "not running" message

Run a combo that has `proxy.running` / `proxy.stopped` conditions (e.g. `tw up` or `tw down`):
- [ ] Steps with `skip_if: proxy.running` are skipped when proxy is up
- [ ] Steps with `only_if: proxy.running` are skipped when proxy is down

---

## 2. Version extraction

`_tool_version()` exception narrowed from `except Exception` to
`except (OSError, CalledProcessError, TimeoutExpired, ValueError)`.
If a binary exists but the version regex fails, it should return `"unknown"` rather than crash.

```
tw which textaccounts
tw which textsessions
tw which textproxy
```
- [ ] Each shows a version string (not `"unknown"` if the tool is installed)

```
tw doctor
```
- [ ] All installed tools show a version number, not `"unknown"`

```
tw update
```
- [ ] Reports current version for each Go tool before checking for newer

---

## 3. yaml now module-level in cli.py

`import yaml` moved from inline (two different function bodies) to module level.

```
tw combos add mytest
```
- [ ] Prompts for steps, prints a valid YAML snippet at the end
- [ ] When asked to append: combo appears in `combos.yaml`

```
tw config
```
- [ ] Output is valid YAML (pipe through `python3 -c "import sys,yaml; yaml.safe_load(sys.stdin)"`)

---

## 4. Combo engine imports (combos.py)

`import json`, `import shutil` moved to module level in `combos.py`.

```
tw combos list
```
- [ ] Lists built-in and user combos without error

```
tw down   # or any combo that checks _are_servers_running()
```
- [ ] Executes cleanly, `textserve list --json` result parsed correctly

---

## Priority order

If time is short, run these three first — they exercise the highest-risk change (port resolution) across all three modules that used to have their own copy:

1. `tw status`
2. `tw doctor`
3. `tw stats`
