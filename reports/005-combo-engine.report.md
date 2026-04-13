# Report: 005 — Combo engine with conditions and builtins
Date: 2026-04-13T17:34:15Z
Status: DONE

## Changes
- 24cc0c4 feat: combo engine with conditions and builtins (textworkspace)

## Test results
- textworkspace: 84 tests passed (42 new + 42 existing), 0 failed

## Notes for next prompt
- combos.py implements full engine: loader, condition evaluator, step executor, dry-run
- CLI: `tw --dry-run <combo>`, `tw combos list/edit/add`, dynamic dispatch via ComboGroup
- Built-in combos (up/down/reset) written to combos.yaml by `tw init`
- Condition vocab: proxy.running, proxy.stopped, servers.running, servers.none_running, accounts.active <name>
- Step executor calls `textworkspace <subcommand>` via subprocess; proxy/servers subcommands are planned but not yet implemented

