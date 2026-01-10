# Deployment Notes: V9 Phase 1

**Date**: 2026-01-10
**Status**: No deployment changes required

---

## Changes Summary

The V9 Phase 1 fix modifies benchmark code only:

| File | Location | Description |
|------|----------|-------------|
| `benchmark_runner.py` | `.claude-workspace/benchmarks/tests/` | Increased wait timeout, added job status check |

---

## Deployment Impact

**None** - Changes are to benchmark/testing code, not production services.

---

## To Run Updated Benchmarks

```bash
# Replay mode (uses fixtures, fast)
cd .claude-workspace/benchmarks
python tests/benchmark_runner.py --mode=replay

# Live mode (requires running services, slow)
python tests/benchmark_runner.py --mode=live
```

---

## Service Requirements

For live mode benchmarks:
- Test environment services must be running (`./scripts/env-up.sh test`)
- OpenAI API key must be configured
- Expect ~15-20 minutes for full benchmark suite
