# Phase 2: Cleanup + Reset

## ⚠️ IMPLEMENTATION HOLD
**NO COMMITS OR PUSHES UNTIL EXPLICITLY APPROVED BY USER**

## Objective

Finalize V5 by removing any legacy code, documenting the reset procedure, and verifying E2E tests pass.

## Prerequisites

- Phase 1 complete (all 4 tools implemented and tested)

## Scope

### In Scope
- Delete any remaining legacy code
- Create reset script (`scripts/reset_v5.py`)
- Run E2E acceptance tests
- Update README with V5 interface
- Update version to "5.0.0"

### Out of Scope
- Migration scripts (clean slate - not applicable)
- Backward compatibility (clean slate - not applicable)

## Implementation

### 1. Legacy Code Cleanup

Delete any remaining V4 code if present:

```python
# Delete from server.py (if any remain):
# - memory_store, memory_search, memory_list, memory_delete
# - history_append, history_get
# - artifact_ingest, artifact_search, artifact_get, artifact_delete
# - embedding_health, job_status, event_reextract

# Delete from collections.py (if any remain):
# - get_memory_collection
# - get_history_collection
# - get_artifacts_collection
# - get_artifact_chunks_collection
```

### 2. Reset Script

Create `scripts/reset_v5.py`:

```python
"""
V5 Reset Script

Completely wipes all V5 data (ChromaDB, PostgreSQL tables).
Use this for clean slate restarts.

Usage:
    python scripts/reset_v5.py --confirm
"""

import os
import sys
import argparse
import logging
from chromadb import HttpClient

CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8001"))
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_DATABASE = os.getenv("PG_DATABASE", "memory")
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def reset_chromadb(client: HttpClient):
    """Delete V5 ChromaDB collections."""
    logger.info("Resetting ChromaDB collections...")

    for name in ["content", "chunks"]:
        try:
            client.delete_collection(name)
            logger.info(f"  Deleted collection: {name}")
        except Exception as e:
            logger.info(f"  Collection '{name}' not found: {e}")

    logger.info("ChromaDB reset complete")


def reset_postgres():
    """Truncate PostgreSQL tables."""
    import psycopg2

    logger.info("Resetting PostgreSQL tables...")

    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DATABASE,
        user=PG_USER,
        password=PG_PASSWORD,
    )

    try:
        with conn.cursor() as cur:
            # Truncate in dependency order (FKs require this order)
            # V4 entity tables first
            tables = [
                "event_actor",
                "event_subject",
                "entity_mention",
                "entity_alias",
                "entity",
                # V3 tables
                "event_evidence",
                "semantic_event",
                "event_jobs",
                "artifact_revision"
            ]

            for table in tables:
                try:
                    cur.execute(f"TRUNCATE TABLE {table} CASCADE")
                    logger.info(f"  Truncated table: {table}")
                except Exception as e:
                    logger.warning(f"  Could not truncate {table}: {e}")

            conn.commit()
    finally:
        conn.close()

    logger.info("PostgreSQL reset complete")


def main():
    parser = argparse.ArgumentParser(description="V5 Reset Script")
    parser.add_argument("--confirm", action="store_true", required=True,
                       help="Confirm you want to delete all data")
    parser.add_argument("--chromadb-only", action="store_true",
                       help="Only reset ChromaDB")
    parser.add_argument("--postgres-only", action="store_true",
                       help="Only reset PostgreSQL")
    args = parser.parse_args()

    if not args.confirm:
        print("ERROR: Must pass --confirm to proceed")
        sys.exit(1)

    print("\n" + "="*50)
    print("V5 RESET - This will DELETE ALL DATA")
    print("="*50 + "\n")

    # Connect to ChromaDB
    chroma_client = HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)

    if args.chromadb_only:
        reset_chromadb(chroma_client)
    elif args.postgres_only:
        reset_postgres()
    else:
        # Reset everything
        reset_chromadb(chroma_client)
        reset_postgres()

    print("\n" + "="*50)
    print("RESET COMPLETE")
    print("="*50 + "\n")


if __name__ == "__main__":
    main()
```

### 3. E2E Acceptance Tests

Run all E2E tests from the spec (Section 5.2):

```bash
pytest tests/e2e/test_v5_e2e.py -v
```

Required tests:
- [ ] `test_e2e_store_retrieve` - remember() → recall(query) works
- [ ] `test_e2e_event_extraction` - events are extracted and returned
- [ ] `test_e2e_graph_expansion` - related_context returned via graph
- [ ] `test_e2e_cascade_delete` - forget() cascades properly
- [ ] `test_e2e_status` - status() reports V5 collections

### 4. README Update

Update main README with V5 interface:

```markdown
## V5 Interface

### remember() - Store Content
```python
result = await remember(
    content="Meeting notes from Q4 planning",
    context="meeting",
    source="slack",
    importance=0.8
)
# Returns: {id: "art_xxx", summary: "...", events_queued: True}
```

### recall() - Find Content
```python
# Semantic search
results = await recall(query="Q4 planning decisions")

# Direct lookup
result = await recall(id="art_xxx")

# Conversation history
history = await recall(conversation_id="conv_123")

# With graph expansion
results = await recall(query="Alice project", expand=True)
```

### forget() - Delete Content
```python
result = await forget(id="art_xxx", confirm=True)
# Returns: {deleted: True, cascade: {chunks: 3, events: 2, entities: 1}}
```

### status() - System Health
```python
s = await status()
# Returns: {version, healthy, services: {...}, counts: {...}}
```
```

### 5. Version Update

Update `__version__` in server.py:

```python
__version__ = "5.0.0"
```

## Success Criteria

- [ ] No legacy tool code remains
- [ ] Reset script works (`scripts/reset_v5.py --confirm`)
- [ ] All E2E tests pass
- [ ] Graph expansion verified in E2E
- [ ] README updated with V5 interface
- [ ] Version is "5.0.0"

## Verification Runbook

After Phase 2 is complete, run this verification:

```bash
# 1. Reset to clean slate
python scripts/reset_v5.py --confirm

# 2. Verify empty state
python -c "from server import status; import asyncio; print(asyncio.run(status()))"
# Should show counts all at 0

# 3. Run E2E tests
pytest tests/e2e/test_v5_e2e.py -v

# 4. Verify graph expansion specifically
pytest tests/e2e/test_v5_e2e.py::test_e2e_graph_expansion -v

# 5. Check version
python -c "from server import __version__; print(__version__)"
# Should print: 5.0.0
```

## Checklist

- [ ] Legacy code deleted
- [ ] Reset script created and tested
- [ ] E2E tests all pass
- [ ] Graph expansion verified
- [ ] README updated
- [ ] Version updated to "5.0.0"
- [ ] Code reviewed
- [ ] User approved
- [ ] Committed (after approval)
