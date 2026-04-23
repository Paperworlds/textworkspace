# Report: 201 — workspace config model

Date: 2026-04-20T17:48:00Z
Status: DONE

## Summary

Task 201 requested verification and documentation of the WorkspaceConfig and ServersConfig dataclasses in `config.py`. Review found that these dataclasses were previously implemented in commit 5988dd7 ("feat: workspace profiles — tw start/stop, tw workspaces group") and are fully functional with complete validation and serialization logic.

## Implementation Review

### WorkspaceConfig Dataclass (config.py:75)
```python
@dataclass
class WorkspaceConfig:
    name: str
    profile: str
    servers: ServersConfig = field(default_factory=ServersConfig)
    description: str = ""
    project: str = ""
    default_session_name: str = ""
```

**Features:**
- `name`: Workspace identifier (required)
- `profile`: textaccounts profile reference (required, validated in _parse_workspace)
- `servers`: ServersConfig for filtering servers by tag or name (optional)
- `description`: Human-readable workspace description (optional)
- `project`: Project directory path (optional)
- `default_session_name`: Default Claude session name for this workspace (optional)

### ServersConfig Dataclass (config.py:69)
```python
@dataclass
class ServersConfig:
    tags: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
```

**Features:**
- `tags`: Filter servers by tag(s)
- `names`: Filter servers by name(s)
- Mutually exclusive enforcement in _parse_workspace (lines 179-182)

### Validation Logic (_parse_workspace, lines 172-190)

1. **Profile validation**: profile is required and must be non-empty
2. **Tags/Names exclusion**: servers.tags and servers.names cannot both be specified
3. **Default values**: All optional fields default to empty strings or empty lists
4. **Type coercion**: Ensures tags and names are lists

### Serialization/Deserialization

- **Parsing**: `_parse_workspace()` converts YAML dict → WorkspaceConfig
- **Serialization**: `_workspace_to_dict()` converts WorkspaceConfig → YAML dict
- **Integration**: Full round-trip support in load_config/save_config

## Test Coverage

All workspace-related tests pass (30/30):
- `test_parse_workspace_tags_and_names_raises` — validates mutual exclusion
- `test_parse_workspace_empty_profile_raises` — validates profile requirement
- `test_parse_workspace_missing_profile_raises` — validates profile presence
- `test_parse_workspace_valid_tags` — validates tags parsing
- `test_parse_workspace_valid_names` — validates names parsing
- `test_parse_workspace_optional_fields_default` — validates defaults
- Workspace manager tests (17 additional integration tests)

## Architecture Integration

WorkspaceConfig is integrated into:
- **Config class** (line 92): `workspaces: dict[str, WorkspaceConfig]`
- **workspace.py**: WorkspaceManager consumes WorkspaceConfig for start/stop operations
- **CLI** (cli.py): `tw start`, `tw stop`, `tw workspaces` commands

## Notes for Next Prompt

- ServersConfig supports both tag-based and name-based server filtering for flexibility
- Validation prevents invalid state at parse time (fail-fast approach)
- default_session_name field enables workspace-specific Claude session defaults
- Implementation follows existing patterns in config.py (other dataclasses have no internal validators; validation happens at parse time)

## Test Results
- Total tests run: 307
- Passed: 306
- Failed: 1 (unrelated — textserve --json flag issue in test_cli.py:399)
- Workspace-specific tests: 30/30 passed ✓
