# MCP Memory Tool Consolidation Proposal

## Problem Statement

The MCP Memory server currently exposes **21 tools** to calling models:

| Category | Tools | Count |
|----------|-------|-------|
| V5 (new) | `remember`, `recall`, `forget`, `status` | 4 |
| Memory | `memory_store`, `memory_search`, `memory_list`, `memory_delete` | 4 |
| Artifacts | `artifact_ingest`, `artifact_search`, `artifact_get`, `artifact_delete` | 4 |
| Events | `event_search_tool`, `event_get_tool`, `event_list_for_artifact`, `event_reextract` | 4 |
| History | `history_append`, `history_get` | 2 |
| Search | `hybrid_search` | 1 |
| Utility | `embedding_health`, `job_status` | 2 |

### Issues

1. **Context bloat**: Each tool definition consumes tokens in the model's context window
2. **Decision fatigue**: Models must choose between overlapping tools
3. **Redundancy**: V5 tools cover most legacy tool functionality
4. **Confusion**: Similar tools with subtle differences (e.g., `hybrid_search` vs `recall`)

### Impact

- Increased latency (more tokens to process)
- Higher API costs
- Potential for models to choose suboptimal tools
- Reduced context available for actual task content

---

## Current State Analysis

### V5 Tools (Recommended)

| Tool | Purpose | Replaces |
|------|---------|----------|
| `remember()` | Store any content | `artifact_ingest`, `memory_store`, `history_append` |
| `recall()` | Search with graph expansion | `hybrid_search`, `artifact_search`, `memory_search`, `event_search` |
| `forget()` | Delete with cascade | `artifact_delete`, `memory_delete` |
| `status()` | Health and job status | `embedding_health`, `job_status` |

### Legacy Tools with Unique Value

| Tool | Unique Capability | V5 Gap |
|------|-------------------|--------|
| `event_search_tool` | Filter by category, time range, artifact | `recall()` has `graph_filters` but not full event filtering |
| `event_reextract` | Force re-run extraction on artifact | No V5 equivalent |
| `event_get_tool` | Get single event by ID | `recall(id="evt_xxx")` handles this |
| `event_list_for_artifact` | List all events for one artifact | Could add to `recall()` |

### Legacy Tools Fully Replaced by V5

| Legacy Tool | V5 Replacement |
|-------------|----------------|
| `memory_store` | `remember(context="preference")` |
| `memory_search` | `recall(context="preference")` |
| `memory_list` | `recall(context="preference", limit=100)` |
| `memory_delete` | `forget(id="...")` |
| `artifact_ingest` | `remember()` with full metadata |
| `artifact_search` | `recall()` |
| `artifact_get` | `recall(id="art_xxx")` |
| `artifact_delete` | `forget()` |
| `hybrid_search` | `recall(expand=True)` |
| `history_append` | `remember(context="conversation", ...)` |
| `history_get` | `recall(conversation_id="...")` |
| `embedding_health` | `status()` |
| `job_status` | `status(artifact_id="...")` |

---

## Proposed Resolutions

### Option A: Disable Legacy Tools (Recommended)

**Action**: Comment out `@mcp.tool()` decorators on legacy tools

**Result**: 4 tools exposed (V5 only)

**Pros**:
- Minimal context usage
- Clean, simple interface
- Code preserved for power users
- Easy to reverse

**Cons**:
- Loses fine-grained event filtering
- No `event_reextract` capability

**Implementation**:
```python
# Keep these
@mcp.tool()
async def remember(...): ...

@mcp.tool()
async def recall(...): ...

@mcp.tool()
async def forget(...): ...

@mcp.tool()
async def status(...): ...

# Disable these (remove decorator, keep code)
# @mcp.tool()
async def memory_store(...): ...

# @mcp.tool()
async def artifact_ingest(...): ...
# ... etc
```

---

### Option B: Selective Legacy Tools

**Action**: Keep V5 + 2 unique legacy tools

**Result**: 6 tools exposed

**Keep**:
- V5: `remember`, `recall`, `forget`, `status`
- Legacy: `event_search_tool` (filtered queries), `event_reextract` (force extraction)

**Pros**:
- Preserves unique capabilities
- Still minimal context
- Power users have options

**Cons**:
- Slight overlap between `event_search_tool` and `recall()`
- 50% more tools than Option A

---

### Option C: Extend V5 Tools

**Action**: Add missing capabilities to V5 tools, then disable all legacy

**Changes to `recall()`**:
```python
async def recall(
    # ... existing params ...

    # New event filtering (from event_search_tool)
    event_category: Optional[str] = None,  # Commitment, Decision, etc.
    event_time_from: Optional[str] = None,
    event_time_to: Optional[str] = None,
    artifact_id: Optional[str] = None,  # events for specific artifact
): ...
```

**New `reextract()` tool or parameter**:
```python
async def status(
    artifact_id: Optional[str] = None,
    reextract: bool = False,  # Force re-extraction
): ...
```

**Result**: 4 tools with full capability coverage

**Pros**:
- Complete feature parity
- Minimal tool count
- Single source of truth

**Cons**:
- More parameters on V5 tools
- Development effort required

---

### Option D: Meta-Tool Pattern

**Action**: Create one `memory` tool that dispatches to sub-operations

```python
@mcp.tool()
async def memory(
    action: str,  # "store", "search", "delete", "status", "reextract"
    **kwargs
): ...
```

**Result**: 1 tool exposed

**Pros**:
- Absolute minimum context
- Extensible

**Cons**:
- Less discoverable
- Models must learn action parameter
- Loses type hints per action
- Harder to document

---

## Recommendation

**Option A (Disable Legacy)** for immediate implementation:
- Quick win: comment out 17 decorators
- 80% context reduction
- Reversible if issues arise

**Option C (Extend V5)** for future enhancement:
- Add event filtering to `recall()`
- Add `reextract` flag to `status()`
- Then remove legacy code entirely

---

## Implementation Checklist

### Phase 1: Disable Legacy (Immediate)

- [ ] Comment out `@mcp.tool()` on 17 legacy tools
- [ ] Update tool count in documentation
- [ ] Test V5 tools still work
- [ ] Verify legacy code still callable internally

### Phase 2: Extend V5 (Future)

- [ ] Add event filtering params to `recall()`
- [ ] Add `reextract` param to `status()`
- [ ] Add `list_events` mode to `recall()`
- [ ] Remove legacy tool code entirely
- [ ] Update all documentation

---

## Appendix: Token Impact Estimate

| Scenario | Tools | Est. Tokens | Savings |
|----------|-------|-------------|---------|
| Current (all tools) | 21 | ~4,200 | - |
| Option A (V5 only) | 4 | ~800 | 81% |
| Option B (V5 + 2) | 6 | ~1,200 | 71% |
| Option C (Extended V5) | 4 | ~1,000 | 76% |
| Option D (Meta-tool) | 1 | ~400 | 90% |

*Estimates based on ~200 tokens per tool definition*
