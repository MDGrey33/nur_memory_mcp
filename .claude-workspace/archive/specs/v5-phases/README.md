# V5 Implementation Phases

## ⚠️ IMPLEMENTATION HOLD
**NO COMMITS OR PUSHES UNTIL EXPLICITLY APPROVED BY USER**

## Overview

V5 is a **clean-slate** implementation in **2 phases**. No migration, no legacy support.

| Aspect | V5 |
|--------|-----|
| Phases | 2 (Implementation + Cleanup) |
| Migration | None (clean slate) |
| Legacy IDs | Not supported (`art_` only) |
| Legacy Collections | Not created |

## Architectural Decisions

1. **Semantic Unification**: ALL `remember()` calls create artifacts and queue event extraction.
   - Exception: Conversation turns < 100 tokens skip event extraction (reduces noise)
2. **Clean Slate**: No migration scripts, no legacy IDs, no backward compatibility.
3. **Chunking Defaults**: 900 tokens, 100 overlap.
4. **Guide-to-Source**: `forget(evt_xxx)` returns error with source artifact ID.
5. **Structured Conversation History**: `recall(conversation_id=...)` returns `{turns: [...]}`.
6. **Single ID Family**: All content uses `art_` prefix, events use `evt_` prefix.

## Phase Summary

| Phase | Name | Scope | Version After |
|-------|------|-------|---------------|
| 1 | Implementation | Build all 4 tools + pipeline | 5.0.0-alpha |
| 2 | Cleanup + Reset | Remove legacy, document reset | 5.0.0 |

## Dependency Graph

```
Phase 1 (Implementation) ─► Phase 2 (Cleanup + Reset)
```

## Phase Details

### Phase 1: Implementation

Build the complete V5 system from scratch:

- [ ] `get_content_collection()` and `get_chunks_collection()`
- [ ] Internal services: `_store_content()`, `_search_content()`, `_delete_content()`
- [ ] `remember()` tool with chunking, embedding, event extraction
- [ ] `recall()` tool with hybrid search, graph expansion
- [ ] `forget()` tool with cascade deletion
- [ ] `status()` tool with V5 counts
- [ ] Conversation turn event gating (< 100 tokens skip extraction)
- [ ] Unit tests
- [ ] Integration tests

### Phase 2: Cleanup + Reset

Finalize and document:

- [ ] Delete any remaining legacy code
- [ ] Create reset script (`scripts/reset_v5.py`)
- [ ] Run E2E acceptance tests
- [ ] Verify graph expansion works in E2E
- [ ] Update README with V5 interface

## E2E Acceptance Tests Checklist

These tests MUST pass before release:

- [ ] `test_e2e_store_retrieve`: remember() → recall(query) returns results
- [ ] `test_e2e_event_extraction`: recall(include_events=True) returns events
- [ ] `test_e2e_graph_expansion`: recall(expand=True) returns related_context
- [ ] `test_e2e_cascade_delete`: forget() cascades to chunks/events/graph
- [ ] `test_e2e_status`: status() reports V5 collections and counts

## Phase Files

- [Phase 1: Implementation](./phase-1-implementation.md)
- [Phase 2: Cleanup + Reset](./phase-2-cleanup.md)

### Archived (Not Applicable)

- ~~phase-1a through 1d~~ (merged into Phase 1)
- ~~phase-2a-migration.md~~ (DELETED - clean slate)
- ~~phase-2b-collections.md~~ (merged into Phase 2)
- ~~phase-3-deprecation.md~~ (SKIPPED - no legacy)
- ~~phase-4-cleanup.md~~ (merged into Phase 2)

## Approval Checkpoints

- [ ] Phase 1 approved
- [ ] Phase 2 approved (FINAL)

## Version Progression

| After Phase | Version |
|-------------|---------|
| 1 | 5.0.0-alpha |
| 2 | 5.0.0 |
