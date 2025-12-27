# ADR-001: Postgres Job Queue Over Kafka

**Status:** Accepted
**Date:** 2025-12-27
**Author:** Senior Architect
**Deciders:** Technical PM, Senior Architect, Lead Backend Engineer

---

## Context

V3 requires an **async job queue** for event extraction:

- Ingestion must remain fast (< 1s) while extraction is slow (5-60s)
- Extraction must be reliable with retry logic
- Jobs must be durable (survive worker crashes)
- System must support horizontal worker scaling

We evaluated two options:

1. **Kafka**: Industry-standard message broker with high throughput
2. **Postgres**: Relational database with table-based job queue

---

## Decision

**We will use Postgres as a lightweight job queue** instead of Kafka.

Implementation:
- `event_jobs` table with status column (PENDING, PROCESSING, DONE, FAILED)
- Workers claim jobs using `SELECT ... FOR UPDATE SKIP LOCKED`
- Retry logic via `next_run_at` timestamp and exponential backoff
- Atomic job enqueue with artifact revision writes (ACID transactions)

---

## Consequences

### Positive

1. **Simplicity**: One database instead of separate message broker
   - Fewer containers to deploy and manage
   - No ZooKeeper dependency
   - Simpler operational model

2. **ACID Guarantees**: Transactional integrity for artifact revision + job enqueue
   ```sql
   BEGIN;
     INSERT INTO artifact_revision (...);
     INSERT INTO event_jobs (...);
   COMMIT;
   ```
   - Either both succeed or both fail (no partial states)

3. **Query Flexibility**: SQL queries on job history and status
   ```sql
   SELECT status, count(*) FROM event_jobs GROUP BY status;
   SELECT * FROM event_jobs WHERE status = 'FAILED';
   ```

4. **Sufficient Scale**: Our workload is < 1000 docs/day
   - Postgres handles 1000+ TPS easily on commodity hardware
   - `FOR UPDATE SKIP LOCKED` prevents contention between workers

5. **Cost**: No additional infrastructure cost
   - Already running Postgres for event storage
   - Reuse connection pools and monitoring

### Negative

1. **Throughput Ceiling**: Postgres job queue tops out at ~10K jobs/sec
   - **Accepted**: Our scale is 1000 docs/day = ~0.01 jobs/sec
   - If we hit 10K jobs/sec, we have bigger problems to solve

2. **No Native Pub/Sub**: Workers poll for jobs instead of push notifications
   - **Mitigated**: Poll interval = 1s, negligible overhead
   - Database load: 1 query/sec/worker = trivial

3. **Job Table Bloat**: Completed jobs accumulate over time
   - **Mitigated**: Periodic cleanup via retention policy (future)
   - Archive old jobs to S3 if needed

4. **Not Industry Standard**: Kafka is more recognizable to engineers
   - **Accepted**: Simplicity > familiarity at our scale
   - Document pattern clearly in ADRs

### Neutral

1. **Horizontal Scaling**: Both Postgres and Kafka support multiple workers
   - Postgres: `FOR UPDATE SKIP LOCKED` (row-level locking)
   - Kafka: Consumer groups (partition assignment)

2. **Dead Letter Queue**: Both require manual implementation
   - Postgres: `status = 'FAILED'` with `max_attempts`
   - Kafka: DLQ topic

---

## Alternatives Considered

### Option 1: Kafka + Zookeeper

**Pros**:
- Industry standard for job queues
- Built-in pub/sub (no polling)
- Higher theoretical throughput (100K+ msgs/sec)
- Natural fit for event streaming architecture

**Cons**:
- **Complexity**: 2 additional containers (Kafka + ZooKeeper)
- **Operational Overhead**: Partition management, rebalancing, logs
- **Overkill**: We don't need 100K msgs/sec for 1K docs/day
- **Two-Phase Commit**: Cannot atomically write artifact + enqueue job
  - Would need distributed transaction (Saga pattern) or eventual consistency
- **Cost**: More infrastructure to monitor and maintain

**Verdict**: Rejected due to complexity vs. benefit trade-off

### Option 2: Redis Streams

**Pros**:
- Simpler than Kafka, lighter than Postgres
- Built-in pub/sub with consumer groups
- Fast in-memory operations

**Cons**:
- **Durability**: Requires careful AOF/RDB configuration
- **Additional Dependency**: Would need 3rd database (Postgres + ChromaDB + Redis)
- **No ACID with Postgres**: Cannot atomically enqueue job with revision write
- **Overkill**: Still more complex than Postgres table

**Verdict**: Rejected due to additional dependency and no transactional guarantee

### Option 3: Celery + Redis/RabbitMQ

**Pros**:
- Python-native task queue (Celery)
- Mature ecosystem with retry logic built-in
- Good monitoring tools (Flower)

**Cons**:
- **Complexity**: Celery broker (Redis/RabbitMQ) + worker management
- **Two-Phase Commit**: Same issue as Kafka (cannot atomically enqueue with Postgres write)
- **Dependency**: Another database/broker to manage

**Verdict**: Rejected due to complexity and lack of transactional guarantee

---

## Implementation Details

### Job Table Schema

```sql
CREATE TABLE event_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type TEXT NOT NULL DEFAULT 'extract_events',
    artifact_uid TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 5,
    next_run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at TIMESTAMPTZ NULL,
    locked_by TEXT NULL,
    last_error_code TEXT NULL,
    last_error_message TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (artifact_uid, revision_id, job_type)
);

CREATE INDEX idx_event_jobs_claimable
    ON event_jobs (status, next_run_at)
    WHERE status = 'PENDING';
```

### Job Claiming Logic

```sql
BEGIN;

-- Claim one job atomically
SELECT job_id, artifact_uid, revision_id
FROM event_jobs
WHERE status = 'PENDING'
  AND next_run_at <= now()
ORDER BY created_at ASC
FOR UPDATE SKIP LOCKED
LIMIT 1;

-- Update to PROCESSING
UPDATE event_jobs
SET status = 'PROCESSING',
    locked_at = now(),
    locked_by = :worker_id,
    attempts = attempts + 1,
    updated_at = now()
WHERE job_id = :claimed_job_id;

COMMIT;
```

### Retry Logic

```python
# On transient failure (OpenAI 429, network timeout)
backoff_seconds = min(30 * (2 ** attempts), 600)  # Max 10 minutes
next_run_at = now() + timedelta(seconds=backoff_seconds)

UPDATE event_jobs
SET status = 'PENDING',
    next_run_at = :next_run_at,
    last_error_code = :error_code,
    last_error_message = :error_message,
    updated_at = now()
WHERE job_id = :job_id;

# On terminal failure (attempts >= max_attempts)
UPDATE event_jobs
SET status = 'FAILED',
    last_error_code = :error_code,
    last_error_message = :error_message,
    updated_at = now()
WHERE job_id = :job_id;
```

---

## Performance Characteristics

| Operation | Latency | Notes |
|-----------|---------|-------|
| Enqueue job | < 10ms | Single INSERT |
| Claim job | < 50ms | SELECT ... FOR UPDATE SKIP LOCKED |
| Poll for jobs | < 10ms | Index scan on (status, next_run_at) |
| Update job status | < 10ms | Single UPDATE by PK |

**Concurrency**: Postgres supports 100+ concurrent workers claiming jobs without contention (row-level locking).

**Throughput**: At 1 job/sec ingestion rate:
- Database load: ~4 queries/sec (enqueue, claim, update, mark done)
- Postgres can handle 10K+ queries/sec on commodity hardware
- **Headroom**: 2500x our expected load

---

## Migration Path (If Needed)

If we outgrow Postgres job queue (> 10K jobs/sec):

1. **Intermediate Step**: PgBouncer connection pooling + read replicas
2. **Final Step**: Migrate to Kafka with minimal code changes
   - Worker interface remains the same (claim, process, mark done)
   - Swap Postgres queries for Kafka consumer API
   - Estimated effort: 2-3 days

---

## References

- [Postgres as a Job Queue](https://webapp.io/blog/postgres-is-the-answer/)
- [FOR UPDATE SKIP LOCKED](https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE)
- [Kafka vs. Postgres for Job Queues](https://news.ycombinator.com/item?id=23802824)

---

## Revision History

| Date | Author | Changes |
|------|--------|---------|
| 2025-12-27 | Senior Architect | Initial ADR |

---

**Status: Accepted**
