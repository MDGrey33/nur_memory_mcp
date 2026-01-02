# V4 Graph Expansion / Worker Bug — Progress Plan

## V5 Specs (links)
- **V5 spec**: [`/.claude-workspace/specs/v5-specification.md`](../.claude-workspace/specs/v5-specification.md)
- **V5 phases index**: [`/.claude-workspace/specs/v5-phases/README.md`](../.claude-workspace/specs/v5-phases/README.md)
  - **Phase 1a (Remember)**: [`phase-1a-remember.md`](../.claude-workspace/specs/v5-phases/phase-1a-remember.md)
  - **Phase 1b (Recall)**: [`phase-1b-recall.md`](../.claude-workspace/specs/v5-phases/phase-1b-recall.md)
  - **Phase 1c (Forget)**: [`phase-1c-forget.md`](../.claude-workspace/specs/v5-phases/phase-1c-forget.md)
  - **Phase 1d (Status)**: [`phase-1d-status.md`](../.claude-workspace/specs/v5-phases/phase-1d-status.md)
  - **Phase 2a (Migration)**: [`phase-2a-migration.md`](../.claude-workspace/specs/v5-phases/phase-2a-migration.md)
  - **Phase 2b (Collections)**: [`phase-2b-collections.md`](../.claude-workspace/specs/v5-phases/phase-2b-collections.md)
  - **Phase 3 (Deprecation)**: [`phase-3-deprecation.md`](../.claude-workspace/specs/v5-phases/phase-3-deprecation.md)
  - **Phase 4 (Cleanup)**: [`phase-4-cleanup.md`](../.claude-workspace/specs/v5-phases/phase-4-cleanup.md)
- **V5 architecture ADR**: [`/.claude-workspace/architecture/v5/ADR-001-simplified-interface.md`](../.claude-workspace/architecture/v5/ADR-001-simplified-interface.md)

## Context
The V4 stack is operational enough to ingest artifacts, enqueue `extract_events`, and run the worker to populate relational tables (`semantic_event`, `entity`, `event_actor`, etc.). However, **graph materialization is blocked** because `graph_upsert` jobs are being claimed and processed incorrectly, leaving the Apache AGE graph empty.

## Current Status (as of 2025-12-28)
- **Verified working**
  - Artifact revision writes to Postgres
  - `extract_events` worker path runs and writes events/evidence
  - V4 entity extraction + resolution writes `entity`, `entity_alias`, `entity_mention`
  - `graph_upsert` jobs are enqueued (but not processed correctly)
- **Broken / blocked**
  - AGE graph nodes/edges remain empty
  - `graph_expand=true` yields 0 related items because the graph is empty

## Active Issue
**Graph upsert jobs not processed correctly**  
Handover doc: `.claude-workspace/implementation/mcp-server/docs/BUG-GRAPH-UPSERT-NOT-PROCESSING.md`

## Next Actions (handoff-ready)
- Fix worker/job-queue routing so `graph_upsert` jobs are only claimed by the graph path:
  - Prefer **Option B**: update `EventWorker.process_one_job()` to use `claim_job_by_type(..., "extract_events")`
  - Or **Option A**: fix `JobQueueService.claim_job()` to filter by job_type and return job_type
- After fix:
  - Run worker end-to-end and confirm AGE graph has nodes/edges
  - Re-test `hybrid_search(graph_expand=true)` and validate related_context/entities behavior

## Update (implemented in this session)
- Worker now claims extract jobs explicitly via `claim_job_by_type(..., "extract_events")`
- `JobQueueService.claim_job()` now delegates to `claim_job_by_type(..., "extract_events")` to prevent future regressions
- GraphService Cypher upserts fixed for AGE compatibility (`MERGE ... SET`, no `ON CREATE/ON MATCH`)
- Graph expansion fixed for AGE compatibility (no relationship unions; safe UNION query + Python-side sorting)
- Worker entity map improved (canonical + surface_form + aliases) so ABOUT edges materialize reliably
- `hybrid_search` tool updated to return structured JSON and expose `graph_filters`
- Graph expansion results include evidence + entity alias/mention count enrichment
- Full test suite passing (inside container): `143 passed`
- Spec aligned: `v4.md` `expand_options[]` section updated to include full schema, required options, and validation rules (static UX capability metadata)
- Runtime aligned: `hybrid_search` now returns full `expand_options[]` on every call (static), with V4 defaults and validation for graph parameters
- Default behavior aligned: `hybrid_search.graph_filters` defaults to ["Decision","Commitment","QualityRisk"]; callers can opt out by passing `graph_filters=null` (all categories)
- Best-quality default: `hybrid_search.graph_expand` now defaults to true (callers can opt out with `graph_expand=false`)
- Best-quality default (tuned): `hybrid_search.graph_seed_limit` now defaults to 1 to keep related_context anchored to the top hit (reduces off-topic graph expansion)
- Best-quality graph seeding: when `include_events=true` and Postgres event hits exist, graph expansion now seeds from those event_ids (more relevant related_context than seeding via vector hits)
- Best-quality primary precision: retrieval applies a default Chroma distance cutoff (env `RETRIEVAL_MAX_DISTANCE`, default 0.35) to reduce noisy chunk hits
- Benchmark added: `/temp/hybrid_search_benchmark.md` defines artifact sets, KPIs, and targets to evaluate retrieval + graph expansion quality before further tuning
- Benchmark corpus + runner added:
  - `/temp/hybrid_search_benchmark_corpus_50.md` (50-doc design: connected chains + noise zoo + chunk stress)
  - `/temp/run_hybrid_search_benchmark.py` (scripted ingest + job wait + hybrid_search KPI benchmark)
- Benchmark run executed (Corpus50) and appended to `/temp/hybrid_search_benchmark.md` (UTC 2025-12-28T21:57:58Z)
  - Event precision for specific project queries: Off-topic events in top3 = 0 across runs
  - Chunk noise stays low (0.00 for specific queries; 0.05–0.08 for broad risk/audit queries)
  - Graph utility mixed: `related_context` non-empty for `Jordan Lee security audit` (count=4), but remains 0 for project-specific queries (next investigation)

## Update (docs / communication)
- Added a simplified, color-coded Mermaid diagram showing:
  - artifact ingest/processing across layers (storage into Chroma + Postgres + AGE graph)
  - how `hybrid_search` retrieves from each store (Chroma vector hits + Postgres event FTS + optional AGE graph expansion)
- File: `temp/artifact_processing_and_hybrid_search_diagram.md`

## Definition of Done Tracking (high-level)
- Graph materialization + graph expansion: **working end-to-end**
- Remaining follow-ups (non-blocking):
  - Ensure the docker image / compose setup mounts or rebuilds so changes are picked up without manual `docker cp`


