# Full Event Extraction E2E Test Plan

## Objective

Test the complete event extraction pipeline end-to-end and validate that:
1. Events are correctly extracted from documents
2. Event content makes semantic sense
3. No relevant events are missed (recall)
4. Extracted events are accurate (precision)

---

## Phase 1: Environment Setup

### 1.1 Start All Services
```bash
# Verify running:
- MCP Server v3.0 (port 3000)
- ChromaDB (port 8001)
- PostgreSQL (port 5432) with events database
- Event Worker (NEW - needs to be started)
```

### 1.2 Start Event Worker
```bash
cd .claude-workspace/implementation/mcp-server
source .venv/bin/activate
python -m src.worker.event_worker
```

The worker will:
- Poll Postgres for PENDING jobs
- Claim jobs atomically (FOR UPDATE SKIP LOCKED)
- Fetch artifact content from ChromaDB
- Call OpenAI to extract events (Prompt A)
- Canonicalize events if chunked (Prompt B)
- Write events to Postgres atomically
- Mark job as DONE

---

## Phase 2: Test Document Design

### 2.1 Create Test Document with Known Events

We'll use a carefully crafted meeting notes document where we KNOW exactly what events should be extracted:

```
EXPECTED EVENTS IN TEST DOCUMENT:

| # | Category | Event Description | Actor(s) | Time |
|---|----------|-------------------|----------|------|
| 1 | Decision | Launch date set to April 1st | Alice Chen | March 15, 2024 |
| 2 | Decision | Freemium pricing model adopted | Team | March 15, 2024 |
| 3 | Commitment | API integration delivery by March 25th | Bob Smith | March 15, 2024 |
| 4 | Commitment | UI mockups by March 20th | Carol Davis | March 15, 2024 |
| 5 | Commitment | OAuth2 implementation | Bob Smith | - |
| 6 | Commitment | Onboarding flow design | Carol Davis | - |
| 7 | Commitment | Marketing materials preparation | Alice Chen | - |
| 8 | QualityRisk | Aggressive timeline risk | - | - |
| 9 | QualityRisk | Third-party API reliability | - | - |
```

### 2.2 Test Document Content

```markdown
Meeting Notes - Product Launch Planning
Date: March 15, 2024
Attendees: Alice Chen (PM), Bob Smith (Engineering), Carol Davis (Design)

DECISIONS MADE:
1. Alice decided to launch the product on April 1st, 2024.
2. The team agreed to use a freemium pricing model.

COMMITMENTS:
1. Bob committed to delivering the API integration by March 25th.
2. Carol will complete the UI mockups by March 20th.

ACTION ITEMS:
- Bob: Implement OAuth2 authentication
- Carol: Design the onboarding flow
- Alice: Prepare marketing materials

RISKS IDENTIFIED:
- Timeline is aggressive, may need to cut scope
- Third-party API has known reliability issues
```

---

## Phase 3: Execute Test

### 3.1 Ingest Document
```python
result = artifact_ingest(
    artifact_type="note",
    source_system="e2e-validation",
    content=TEST_DOCUMENT,
    title="Product Launch Planning Meeting",
    source_id="validation-test-001",
    participants=["Alice Chen", "Bob Smith", "Carol Davis"],
    ts="2024-03-15T10:00:00Z"
)

# Capture:
artifact_uid = result["artifact_uid"]
revision_id = result["revision_id"]
job_id = result["job_id"]
```

### 3.2 Wait for Extraction
```python
# Poll job_status until DONE or FAILED
max_wait = 60 seconds
poll_interval = 2 seconds

while job_status != "DONE":
    status = job_status(artifact_uid=artifact_uid)
    if status["status"] == "FAILED":
        FAIL("Extraction failed: " + status["last_error_message"])
    sleep(poll_interval)
```

### 3.3 Retrieve Extracted Events
```python
result = event_list_for_artifact(
    artifact_uid=artifact_uid,
    include_evidence=True
)

extracted_events = result["events"]
```

---

## Phase 4: Validation

### 4.1 Event Count Check
```
Expected: 9 events (2 Decision, 5 Commitment, 2 QualityRisk)
Actual: [count from extraction]

PASS if: actual >= 7 (allowing some flexibility for LLM interpretation)
WARN if: actual < 7 or actual > 12
```

### 4.2 Category Distribution Check
```
Expected distribution:
- Decision: 2
- Commitment: 5
- QualityRisk: 2

Actual distribution: [count by category]

PASS if: all major categories present
WARN if: any category has 0 events
```

### 4.3 Key Event Presence Check (Recall)

Must find these critical events:

| Event | Search Method | Required Match |
|-------|---------------|----------------|
| April 1st launch | narrative contains "April" or "launch" | YES |
| Freemium pricing | narrative contains "freemium" or "pricing" | YES |
| Bob's API commitment | narrative contains "Bob" AND "API" | YES |
| Carol's mockup commitment | narrative contains "Carol" AND "mockup" | YES |
| Timeline risk | narrative contains "timeline" or "aggressive" | YES |

```python
CRITICAL_EVENTS = [
    {"search": "April", "description": "Launch date decision"},
    {"search": "freemium", "description": "Pricing model decision"},
    {"search": "Bob", "description": "Bob's commitment"},
    {"search": "Carol", "description": "Carol's commitment"},
    {"search": "risk", "description": "Risk identification"},
]

for event in CRITICAL_EVENTS:
    found = any(event["search"].lower() in e["narrative"].lower()
                for e in extracted_events)
    if not found:
        FAIL(f"Missing critical event: {event['description']}")
```

### 4.4 Event Quality Check (Precision)

For each extracted event, verify:
1. **Narrative is coherent** - reads like a complete sentence
2. **Category matches content** - Decision events are about decisions, etc.
3. **Actors are correctly identified** - names match document
4. **Evidence links to source** - quote exists in original document

```python
for event in extracted_events:
    # Check narrative quality
    assert len(event["narrative"]) > 20, "Narrative too short"
    assert len(event["narrative"]) < 500, "Narrative too long"

    # Check evidence
    for evidence in event["evidence"]:
        assert evidence["quote"] in TEST_DOCUMENT, "Evidence quote not in source"

    # Check actors exist in document
    for actor in event["actors"]:
        assert actor["ref"] in TEST_DOCUMENT, f"Actor {actor['ref']} not in document"
```

### 4.5 Semantic Coherence Check

Manual/LLM validation:
- Does each event make sense?
- Are there any hallucinated facts?
- Are actors correctly attributed?

---

## Phase 5: Reporting

### 5.1 Generate Validation Report

```markdown
# Event Extraction Validation Report

## Summary
- Document: Product Launch Planning Meeting
- Extraction Time: X seconds
- Total Events Extracted: Y

## Recall Analysis
| Critical Event | Found | Narrative |
|----------------|-------|-----------|
| Launch date | ✅/❌ | "..." |
| Pricing model | ✅/❌ | "..." |
| Bob's commitment | ✅/❌ | "..." |
| Carol's commitment | ✅/❌ | "..." |
| Risk identified | ✅/❌ | "..." |

Recall Score: X/5 (Y%)

## Precision Analysis
| Event # | Category | Narrative | Valid? | Issues |
|---------|----------|-----------|--------|--------|
| 1 | Decision | "..." | ✅/❌ | ... |
| 2 | Commitment | "..." | ✅/❌ | ... |
| ... | ... | ... | ... | ... |

Precision Score: X/Y (Z%)

## Evidence Quality
| Event # | Evidence Count | All Valid? |
|---------|----------------|------------|
| 1 | 2 | ✅/❌ |
| ... | ... | ... |

## Missing Events (False Negatives)
- [List any expected events not found]

## Incorrect Events (False Positives)
- [List any hallucinated or wrong events]

## Overall Assessment
- Recall: X%
- Precision: Y%
- F1 Score: Z%
- PASS/FAIL
```

---

## Phase 6: Test Execution Script

Create `validate_event_extraction.py`:

```python
#!/usr/bin/env python3
"""
Full Event Extraction Validation Test

Tests:
1. Document ingestion triggers extraction job
2. Worker processes job and extracts events
3. Extracted events match expected events
4. Evidence correctly links to source text
5. No critical events are missed
"""

# Implementation in next step
```

---

## Success Criteria

| Metric | Threshold | Notes |
|--------|-----------|-------|
| Extraction completes | < 60s | Job goes to DONE |
| Event count | 7-12 | ~9 expected |
| Critical event recall | 100% | All 5 must be found |
| Evidence validity | 100% | All quotes in source |
| Precision (manual check) | > 80% | No major hallucinations |

---

## Execution Steps

1. ☐ Verify MCP server v3.0 running with Postgres
2. ☐ Start event worker process
3. ☐ Run validation script
4. ☐ Review extracted events manually
5. ☐ Generate validation report
6. ☐ Document any issues found

---

## Next Steps After Validation

If PASS:
- V3 ready for `/approve`

If FAIL:
- Document specific failures
- Adjust extraction prompts if needed
- Re-test
