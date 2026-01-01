# V6 Cleanup Plan: Tool Consolidation

**Version:** 6.0.0
**Date:** 2026-01-01
**Status:** IMPLEMENTED

---

## Objective

Reduce from 21 tools to **4 tools** by deleting all legacy tools. This reduces model context usage by ~80%.

## Final Tool Set (V6)

| Tool | Purpose |
|------|---------|
| `remember()` | Store content |
| `recall()` | Search, graph expansion, events (`include_events=True`) |
| `forget()` | Delete with cascade |
| `status()` | System health |

**Event access:** Via `recall(include_events=True)` - no separate event tools needed.

---

## Tools to Delete (17)

### Memory Tools (4)
- `memory_store`
- `memory_search`
- `memory_list`
- `memory_delete`

### Artifact Tools (4)
- `artifact_ingest`
- `artifact_search`
- `artifact_get`
- `artifact_delete`

### Event Tools (4)
- `event_search_tool`
- `event_get_tool`
- `event_list_for_artifact`
- `event_reextract`

### History Tools (2)
- `history_append`
- `history_get`

### Search Tools (1)
- `hybrid_search`

### Utility Tools (2)
- `embedding_health`
- `job_status`

---

## Implementation Steps

### Step 1: Delete Tool Functions from server.py

Delete these 17 functions entirely from `src/server.py`:

```python
# DELETE:
memory_store()
memory_search()
memory_list()
memory_delete()
artifact_ingest()
artifact_search()
artifact_get()
artifact_delete()
event_search_tool()
event_get_tool()
event_list_for_artifact()
event_reextract()
history_append()
history_get()
hybrid_search()
embedding_health()
job_status()
```

**Estimated reduction:** ~1,200 lines

### Step 2: Delete Supporting Modules

Check and delete if unused by V6 tools:

| File | Action |
|------|--------|
| `src/tools/memory_tools.py` | Delete if unused |
| `src/tools/event_tools.py` | Keep if recall() uses it, else delete |
| `src/tools/artifact_tools.py` | Delete if unused |

### Step 3: Delete Legacy Tests

```
DELETE:
- tests/integration/test_memory_*.py
- tests/integration/test_artifact_*.py
- tests/integration/test_hybrid_search.py
- tests/unit/test_memory_*.py
- tests/unit/test_artifact_*.py

KEEP:
- tests/v5/ (V6 tests)
- tests/unit/services/ (core services)
```

### Step 4: Clean Up Imports

Remove unused imports from server.py after deletions.

### Step 5: Update Version

```python
__version__ = "6.0.0"
```

---

## Verification

```bash
# 1. Check only 4 tools exposed
python -c "from server import mcp; print([t.name for t in mcp.list_tools()])"
# Expected: ['remember', 'recall', 'forget', 'status']

# 2. Run tests
pytest tests/v5/ -v

# 3. E2E test
MCP_URL="http://localhost:3100/mcp/" pytest tests/v5/e2e/ --run-e2e -v
```

---

## Rollback

Git history preserves everything:

```bash
git checkout HEAD~1 -- src/server.py
```
