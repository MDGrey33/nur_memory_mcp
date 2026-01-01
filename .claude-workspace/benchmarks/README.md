# MCP Memory Benchmarks

Quality measurement for MCP Memory Server.

## Quick Start: Outcome Evaluation (Recommended)

The simplest way to verify the system works:

```bash
cd .claude-workspace/benchmarks
export $(grep OPENAI_API_KEY ../deployment/.env)
python outcome_eval.py
```

This test:
1. Stores 3 related documents (meeting, email, decision)
2. Queries for connections between people and work
3. Uses GPT-4o-mini to verify 5 expected outcomes are found
4. Returns clear pass/fail

**Cost:** ~$0.006 per run

See [OUTCOME_EVAL_PLAN.md](OUTCOME_EVAL_PLAN.md) for details.

---

## V7 Benchmark Suite (Advanced)

For detailed metrics on extraction and retrieval quality:

```bash
# Replay mode (uses fixtures, no API calls)
python tests/benchmark_runner.py --mode=replay

# Live mode (requires full stack running)
python tests/benchmark_runner.py --mode=live
```

### Directory Structure

```
benchmarks/
├── outcome_eval.py          # Simple outcome test (recommended)
├── OUTCOME_EVAL_PLAN.md     # Outcome test documentation
├── corpus/                  # Test documents (12 files)
├── ground_truth/            # Expected extractions
├── queries/                 # Benchmark queries (15)
├── fixtures/                # Recorded outputs for replay
├── metrics/                 # Metric implementations
├── tests/                   # Benchmark runner
└── reports/                 # Generated reports
```

### Metrics

| Metric | Description | Threshold |
|--------|-------------|-----------|
| Retrieval MRR | How quickly relevant docs appear | 0.60 |
| Retrieval NDCG | Ranking quality | 0.65 |
| Event F1 | Event extraction accuracy | 0.70 |
| Entity F1 | Entity extraction accuracy | 0.70 |
| Graph F1 | Graph expansion accuracy | 0.60 |

### Known Limitations

The V7 benchmark has structural issues that make some metrics hard to achieve:
- Event matching uses fuzzy text (LLM output varies)
- Entity extraction uses regex from narratives (can't find projects/orgs)
- Graph expansion has ID format mismatches

**Recommendation:** Use `outcome_eval.py` for CI gates. Use V7 for detailed analysis only.

---

## Prerequisites

```bash
# Start services
cd ../deployment
docker compose up -d
./scripts/health-check.sh --wait
```

---

**Version**: 7.1.0
**Updated**: 2026-01-01
