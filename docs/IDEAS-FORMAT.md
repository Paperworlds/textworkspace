# IDEAS.yaml — canonical format

`tw ideas list` aggregates `IDEAS.yaml` (or `.yml`) files from every repo
under `dev_root`. Each repo can ship its own backlog; `tw ideas` normalises
across a few historical shapes but new files should follow the canonical one.

## Canonical shape (recommended)

```yaml
ideas:
  - id: mcp-proxy
    title: textserve proxy — single aggregating MCP endpoint
    status: idea                # idea | exploring | planned | parked | done
    priority: 1                 # optional, integer, smaller = higher
    summary: |
      Free-form description. Markdown is fine; it's only rendered when
      `tw ideas show <repo> <id>` is run.
```

## Also accepted

Mapping form (id is the key):

```yaml
ideas:
  mcp_proxy:
    title: ...
    status: idea
```

Arbitrary top-level list name (first list-of-dicts wins):

```yaml
brainstorm:
  - name: some-slug           # `name` also accepted as id
    title: ...
    status: brainstorm
```

## Lookup order

Per repo, the first path that exists is used:

1. `docs/IDEAS.yaml`
2. `docs/IDEAS.yml`
3. `IDEAS.yaml` (repo root)
4. `IDEAS.yml`
5. `docs/IDEAS.md` (surfaced as an opaque pointer — `tw ideas show` dumps it)
6. `IDEAS.md`

## Commands

```bash
tw ideas                                 # list across all repos
tw ideas list --status idea              # filter by status
tw ideas list --repo textread            # filter by repo
tw ideas list --query proxy              # substring on id/title/summary
tw ideas list --no-md                    # exclude IDEAS.md placeholders

tw ideas show <repo>                     # dump the full IDEAS file
tw ideas show <repo> <id>                # print one idea's summary
```

## Watch out for

Bare list items with `:` in the text look like mappings to YAML. Quote them:

```yaml
ideas:
  - id: x
    key_design_points:
      - "CLAUDE_CONFIG_DIR must be set: the parser reads colons as keys."
```

Parse errors surface as a single placeholder entry with `status: error`.
