# V4 `hybrid_search` Quality Measurement Plan (Decision-Driven)
Date: 2025-12-28  
Owner: Roland + Agent  
Scope: Measure, tune, and re-measure `hybrid_search` quality without overfitting.

## 0) Goal (what “done” means)
Ship tunings only when they improve **portable memory utility** and **precision** with **no unacceptable regressions**.  
All decisions are based on a repeatable scorecard, not anecdotal examples.

---

## 0.5) The 6-step iteration loop (the controlling process)
We will **only** change behavior by running this loop end-to-end:

1) **Define**: pick the failing KPI(s), stratum, and success thresholds.\n
2) **Baseline**: run the benchmark manifest on the current build and record the scorecard.\n
3) **Hypothesize**: state the smallest plausible change that will improve the failing KPI(s), and what it might regress.\n
4) **Implement**: apply the change (single theme; minimal surface area).\n
5) **Re-benchmark**: rerun the exact same benchmark (same corpus + manifest + runs) and compute deltas.\n
6) **Decide**: keep/revert based on gates; document the outcome and next hypothesis.\n

Deliverables map to the loop like this:
- Step 1–2: `temp/benchmark_manifest.json` + `temp/run_hybrid_search_benchmark.py`\n
- Step 2 & 5: `temp/benchmark_results_latest.json` + appended section in `temp/hybrid_search_benchmark.md`\n
- Step 6: decision note in `temp/hybrid_search_benchmark.md` and updated `temp/progress_plan.md`\n

## 1) What we are optimizing (3 outcomes)
### 1.1 Primary relevance (artifacts/chunks)
- Keep `primary_results` dominated by on-topic artifacts/chunks for specific queries.
- Avoid generic chunk pollution (“handbook” noise).

### 1.2 Event usefulness
- Events surfaced in `primary_results` should be on-topic for specific queries.
- Broad queries (`risk`) should still surface many events (recall).

### 1.3 Graph “portable memory” (V4 expansion)
- For connected scenarios, `related_context` should add *new relevant* context (not duplicates).
- For isolate scenarios, `related_context` should be empty (or near-empty) to avoid hallucinated connections.

---

## 2) Measurement strategy (the “adult” part)
We measure on **strata** and use **baseline vs variant** comparison.

### 2.1 Strata (avoid overfitting)
We split our benchmark queries into:
- **Connected-project queries** (should produce `related_context`)
- **Entity-centric queries** (should produce `related_context`)
- **Isolated-topic queries** (should *not* produce `related_context`)
- **Noise zoo queries** (stress “risk” distractors)
- **Chunk-stress queries** (stress generic chunk pollution)

### 2.2 Ground truth (lightweight)
We define a **benchmark manifest** that lists, per query:
- expected “should_have_related_context” (boolean)
- expected anchor phrases (for automatic scoring)
- expected event categories (optional)
- expected top artifact titles/source_ids (optional)

This is not perfect “human labeling” but it is explicit and stable.

### 2.3 Scorecard + gates
We report metrics overall and per stratum. Decisions are based on gates.

---

## 3) KPIs (what we compute)
### 3.1 Event precision/recall
- **EventPrecision@3 (specific)**: in the first 3 `type=event` items, share ≥2 anchors with query  
  - Target: **≥ 0.95** on specific strata
- **EventRecall (specific)**: at least one on-topic event appears in `primary_results`  
  - Target: **≥ 0.90**

### 3.2 Chunk noise
- **ChunkNoiseRate (specific)**: fraction of `artifact_chunks` entries with 0 anchor overlap  
  - Target: **≤ 0.10** (ideal 0)

### 3.3 Graph utility (portable memory)
- **RelatedContextHitRate (connected strata)**: % queries with `related_context_count ≥ 1` when expected true  
  - Target: **≥ 0.70**
- **RelatedContextFalsePositiveRate (isolate strata)**: % queries with `related_context_count ≥ 1` when expected false  
  - Target: **≤ 0.10**
- **RelatedContextOffTopicRate (specific)**: % related_context items failing anchor overlap threshold  
  - Target: **≤ 0.10**

### 3.4 Latency (best-effort)
- **LatencyP95** (per query group)  
  - Target: **≤ 1500ms local**

---

## 4) Process (ingest → baseline → tune → re-benchmark)

### 4.1 Corpus
- Use the existing 50-doc corpus runner (idempotent source_ids).  
  - Corpus spec: `temp/hybrid_search_benchmark_corpus_50.md`

### 4.2 Baseline run
- Ingest corpus (or verify already present).
- Wait for extraction/graph jobs (bounded).
- Run the benchmark manifest queries 3× each.
- Produce:
  - `temp/hybrid_search_benchmark.md` appended table(s)
  - `temp/benchmark_results_latest.json` (machine-readable scorecard)

### 4.3 Tune (only if gates fail)
Choose the smallest change that addresses the failing stratum:
- If **connected-project graph hit rate** is low: investigate entity/subject linkage + graph upsert + seeding logic.
- If **event precision** fails: adjust event gating/ranking thresholds.
- If **chunk noise** fails: tune vector distance cutoff / anchor threshold.

### 4.4 Re-benchmark
- Re-run the same manifest against the same corpus.
- Compare delta metrics (baseline vs variant) and accept only if:
  - targets met or improved materially
  - no regressions beyond tolerance

---

## 5) Deliverables (files)
- `temp/quality_measurement_plan.md` (this doc)
- `temp/benchmark_manifest.json` (queries + expected outcomes + strata)
- `temp/run_hybrid_search_benchmark.py` (runner updated to use manifest + output JSON scorecard)
- `temp/hybrid_search_benchmark.md` (human-readable history)

---

## 6) Immediate next step
1) Create `temp/benchmark_manifest.json` covering ~20–30 queries across all strata.\n
2) Update the runner to:\n
   - ingest corpus\n
   - run manifest queries 3×\n
   - compute stratum metrics + gates\n
   - write `temp/benchmark_results_latest.json`\n
   - append a summarized scorecard section to `temp/hybrid_search_benchmark.md`\n
3) Run baseline, review the scorecard, and pick the next tuning.\n


