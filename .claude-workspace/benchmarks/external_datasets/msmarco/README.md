# MS MARCO MCP Memory Evaluation

End-to-end retrieval evaluation using the MCP Memory Server.

## What It Tests

1. **Ingest** passages via `remember()`
2. **Query** via `recall()`
3. **Measure** retrieval quality against ground truth

## Dataset

| File | Queries | Passages |
|------|---------|----------|
| `dev_small.json` | 100 | ~1,028 |

## Running

```bash
cd .claude-workspace/implementation/mcp-server
source .venv/bin/activate
cd ../../benchmarks/external_datasets/msmarco

# Quick test (3 queries, ~20s)
python evaluate.py --max-queries 3

# Medium test (10 queries, ~1 min)
python evaluate.py --max-queries 10

# Full evaluation (100 queries, ~10-15 min)
python evaluate.py

# Skip cleanup (keep passages in memory)
python evaluate.py --max-queries 10 --no-cleanup

# Reuse ingested passages
python evaluate.py --skip-ingest
```

## Metrics

| Metric | Description |
|--------|-------------|
| **MRR@10** | Mean Reciprocal Rank - how high is the first correct passage? |
| **Precision@10** | Fraction of top-10 that are correct |
| **Recall@10** | Fraction of correct passages found in top-10 |
| **Hit Rate@10** | Queries with at least one correct result |

## Sample Results (3 queries)

```
MRR@10: 0.7500
Precision@10: 0.2000
Recall@10: 1.0000
Hit Rate@10: 100.00%
```

## Time Estimates

| Queries | Passages | Ingest | Query | Total |
|---------|----------|--------|-------|-------|
| 3 | 30 | ~15s | ~1s | ~20s |
| 10 | ~100 | ~50s | ~5s | ~1 min |
| 100 | ~1,028 | ~8 min | ~30s | ~10 min |
