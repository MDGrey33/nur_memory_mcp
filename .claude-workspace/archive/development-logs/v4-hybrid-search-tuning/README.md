# V4 Hybrid Search Tuning - Development Logs

**Archived**: 2026-01-02
**Period**: 2025-12-28
**Status**: Completed - superseded by V7 benchmark suite

## Context

These files document the development work during V4 hybrid_search quality tuning, including graph expansion bug investigation and the initial measurement-driven tuning approach.

## Files

| File | Description |
|------|-------------|
| `quality_measurement_plan.md` | 6-step iteration loop methodology for quality tuning |
| `debugging_progress.md` | Iteration log tracking V4 graph upsert bug investigation |
| `progress_plan.md` | Handoff document for V4 worker/graph bug fixes |
| `run_hybrid_search_benchmark.py` | Early benchmark runner with 50-doc corpus generator |

## Key Outcomes

1. **Graph Upsert Bug Fixed** - Worker was incorrectly claiming `graph_upsert` jobs via the extract path. Fixed by using `claim_job_by_type()`.

2. **AGE Cypher Compatibility** - Multiple fixes for Apache AGE compatibility:
   - Replaced `ON CREATE SET` / `ON MATCH SET` with `MERGE ... SET`
   - Removed relationship-type unions
   - Moved UNION result ordering to Python-side

3. **Quality Defaults Tuned**:
   - `graph_expand=true` by default
   - `graph_seed_limit=1` (anchored to top hit)
   - Default vector distance cutoff for noise reduction

## Superseded By

The V7 Quality Benchmark Suite provides a more comprehensive approach:
- `.claude-workspace/benchmarks/` - Full benchmark infrastructure
- `.claude-workspace/specs/v7-quality-benchmarks.md` - Detailed specification
- Includes replay mode, fixtures, and outcome evaluation

## Historical Value

These logs show the evolution from ad-hoc tuning to a structured measurement approach, which informed the design of the V7 benchmark suite.
