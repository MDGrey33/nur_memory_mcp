# Debugging / Progress Log (Quality Improvements)
Date: 2025-12-28

Goal: improve `hybrid_search` quality using a measurement-driven loop and avoid overfitting.

## Working rules
- No commits.
- Update this log after each step.
- Only report back to user on **meaningful KPI movement** (not busywork).

## Iteration loop (per change)
1) Define failing KPI(s) and target thresholds
2) Baseline benchmark run (manifest) → capture scorecard JSON
3) Hypothesis (smallest change that should move the KPI)
4) Implement (single-theme change)
5) Re-benchmark (same corpus + manifest + runs)
6) Decide (keep/revert) + log delta

## Current state snapshot
- Corpus: 50 docs (connected chains + noise zoo + chunk stress)
- Manifest: `temp/benchmark_manifest.json`
- Runner: `temp/run_hybrid_search_benchmark.py`

### Latest baseline (manifest run)
- Run timestamp: 2025-12-28T22:12:44Z
- Scorecard: `temp/benchmark_results_latest.json`
- Observations:
  - connected_project: expected `related_context=yes` but observed `0` across all project-specific queries
  - entity_centric: `entity_jordan` returns `related_context=4`, `entity_auth_gateway` returns `0`
  - event precision for specific queries: off-topic events in top3 = 0

## Next planned changes
1) Manifest expectations: add `related_context_mode` so broad queries can be `dont_care` (avoid mislabeling graph FP).
2) Category normalization: fix plural categories at extraction time so graph filters (`Decision`,`Commitment`,`QualityRisk`) match stored graph categories.

## Iteration log

### Iteration 1 — Manifest expectation modes + category normalization
- Step 1 (Define): failing KPI = `connected_project` related_context hit rate (must_have → currently 0).
- Step 2 (Baseline): manifest run showed `connected_project` related_context_count=0 for all must_have tests.
- Step 3 (Hypothesis): category pluralization (“Commitments”) causes graph filters to exclude events; normalizing should increase related_context for connected queries.
- Step 4 (Implement):
  - manifest now uses `related_context_mode` (must_have/must_not/dont_care)
  - event extraction now normalizes plural categories to canonical singulars during validation
- Step 5 (Re-benchmark): reran ingestion + manifest benchmark (UTC 2025-12-28T22:18:51Z).
- Step 6 (Decide): **No improvement yet** for the primary failing KPI:
  - `connected_project` related_context still 0 across must_have tests
  - `entity_jordan` still returns related_context=4 (graph still works in at least one path)
  - `entity_auth_gateway` still returns 0 (suggests entity type/edge modeling mismatch or seeding/filter mismatch)
Next hypothesis: graph expansion isn’t returning project-local related events because seed events are not linked to the other project events via shared entities in the graph (entity extraction/typing, subject/actor refs, or graph_upsert missing edges).

### Iteration 2 — Rebalance corpus to realistic 50 docs (avoid overfitting)
- Step 1 (Define): keep the KPI focus on `connected_project_*` hit rate and `entity_auth_gateway` must_have.\n
- Step 2 (Baseline): prior runs show `connected_project` hit rate = 0.\n
- Step 3 (Hypothesis): our previous corpus had too few *realistic* documents that mention systems/vendors/policies in a way that yields stable actor/subject entity edges. A better-curated 50-doc set should increase actual graph connectivity and reveal whether the expander can work for project queries.\n
- Step 4 (Implement): updated runner corpus generator to a realistic 50-doc mix (meetings/plans/arch/evals/policies/contracts/chats) with explicit cross-links (Jordan Lee + Auth Gateway + VendorX).\n
- Step 5 (Re-benchmark): pending.\n
- Step 6 (Decide): pending.\n

Update:
- Rerun completed (UTC 2025-12-28T22:45:36Z) but **job_status timed out** waiting for extraction jobs (0 completed within window), so results are not trustworthy for graph KPIs yet.
- Observed `related_context_count` stayed 0 across must_have tests, and even `entity_jordan` regressed to 0 (previously 4), consistent with extraction/graph pipeline not being ready at query time.
- Next fix: adjust runner wait strategy (increase timeout, poll fewer ids with backoff, and/or wait on worker health) before interpreting graph KPIs.

# Debugging Progress — Graph Upsert Not Materializing AGE Graph

## Problem Statement
`graph_upsert` jobs are enqueued but the Apache AGE graph remains empty; `hybrid_search(graph_expand=true)` reports 0 related items.

## Confirmed Root Cause (code-level)
- `JobQueueService.claim_job()` (in `src/services/job_queue_service.py`) claims **any** `PENDING` job with no `job_type` filter and does **not** return `job_type`.
- `EventWorker.process_one_job()` (in `src/worker/event_worker.py`) calls `claim_job()` first and unconditionally routes the claimed job to `_process_extract_events_job()`.
- Result: `graph_upsert` jobs are stolen by the extract path; `_process_graph_upsert_job()` is never reached.

See the full handover doc:
`.claude-workspace/implementation/mcp-server/docs/BUG-GRAPH-UPSERT-NOT-PROCESSING.md`

## Repro (observed)
- `extract_events` completes and enqueues a `graph_upsert` job
- Worker logs show “Processing extract_events job …” for the `graph_upsert` job_id
- Graph stays empty

## Fix Options
- **Option B (smallest change)**: in `EventWorker.process_one_job()`, replace `claim_job()` with `claim_job_by_type(..., "extract_events")`.
- **Option A (more robust API)**: fix `claim_job()` to accept/require `job_type` and include `job_type` in return payload.
- **Option C (routing)**: ensure `claim_job()` returns `job_type` then dispatch based on it.

## Post-fix Verification Checklist
- Worker logs include “Processing graph_upsert job …”
- AGE query returns nodes/edges
- `hybrid_search(graph_expand=true)` returns non-empty `related_context` (given data with shared entities)

## Resolution Notes (completed)
- Root cause (job claiming/routing) fixed:
  - Worker claims `extract_events` via `claim_job_by_type(..., \"extract_events\")`
  - Legacy `claim_job()` delegates to typed claim (prevents regression)
- Follow-on bug discovered and fixed:
  - AGE Cypher compatibility issues:
    - `ON CREATE SET` / `ON MATCH SET` caused syntax errors → replaced with `MERGE ... SET`
    - Relationship-type unions (`ACTED_IN|ABOUT`) caused syntax errors → replaced with safe patterns
    - AGE had issues with ordering UNION results → moved ordering to Python-side sort
- End-to-end verification:
  - Two related docs (“VendorX risk A/B”) ingested and processed
  - Postgres: `event_actor` and `event_subject` populated
  - AGE: Entity/Event nodes and ACTED_IN + ABOUT edges present
  - `hybrid_search(graph_expand=true, graph_seed_limit=1)` returns non-empty `related_context` with evidence


