# Outcome Evaluation Test

**Status: IMPLEMENTED**

Simple LLM-based outcome evaluation for the MCP Memory system.

## What It Does

1. **Stores** 3 related documents (meeting, email, decision) about a project
2. **Queries** the system asking about connections between people and work
3. **Evaluates** using GPT-4o-mini to check if 5 expected outcomes are found
4. **Reports** clear pass/fail with evidence

## Usage

```bash
cd .claude-workspace/benchmarks
export $(grep OPENAI_API_KEY ../deployment/.env)

# Run the test
python outcome_eval.py

# With debug output (shows MCP responses)
python outcome_eval.py --debug

# Clean up test documents after
python outcome_eval.py --cleanup
```

## Expected Output

```
==================================================
MCP OUTCOME EVALUATION
==================================================

Connecting to MCP at http://localhost:3001...
Connected!

Storing documents...
  Stored: outcome_test/meeting.txt
  Stored: outcome_test/email.txt
  Stored: outcome_test/decision.txt
  Waiting for event extraction...
Querying: What is Priya working on for the Zephyr project and who else is involved?
Evaluating with LLM...

==================================================
RESULTS
==================================================

  ✓ Priya is working on a GraphQL API for Zephyr analytics dashboard
  ✓ The API deadline is December 20th
  ✓ Marcus Weber is involved with the MongoDB database schema
  ✓ Elena Rodriguez is involved as project manager or stakeholder
  ✓ MongoDB was chosen as the database

Score: 5 found, 0 partial, 0 missing
Pass Rate: 100% (threshold: 80%)

>>> PASS <<<
```

## Cost

~$0.006 per run:
- 3 document stores (embedding calls)
- 1 recall query
- 1 GPT-4o-mini evaluation call

## Pass Criteria

- **Threshold**: 80% (4/5 outcomes)
- Each outcome can be: FOUND, PARTIAL, or MISSING
- FOUND and PARTIAL count toward pass rate

## Why This Approach

The V7 benchmark suite had complex metrics that didn't reflect actual system quality:
- Event F1 scores depended on exact text matching
- Entity extraction used regex (fundamentally limited)
- Graph metrics had ID format mismatches

This simple test answers one question: **Does the system find and connect related information?**

If this test passes, the core retrieval and storage functionality works.
