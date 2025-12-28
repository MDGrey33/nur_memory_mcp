# ADR-002: Graph Database Choice

**Status:** Accepted
**Date:** 2025-12-28
**Deciders:** Senior Architect, Technical PM, DevOps Engineer
**Context Level:** V4 Graph-backed Context Expansion

---

## Context

V4 requires a graph data structure to enable 1-hop traversal for context expansion in `hybrid_search`. When a user searches for "Alice's decisions", we need to traverse:

```
(Query Result Events) -> (Entities: Alice) -> (Other Events involving Alice)
```

This requires:
1. Node storage (Entity, Event)
2. Edge storage (ACTED_IN, ABOUT, POSSIBLY_SAME)
3. Traversal queries (1-hop expansion)
4. MERGE semantics for idempotent updates

### Requirements

| Requirement | Priority | Notes |
|-------------|----------|-------|
| 1-hop traversal | Must | Core graph expansion feature |
| Cypher or similar query language | Should | Developer productivity |
| Runs with existing infrastructure | Must | No new containers/services |
| ACID compliance | Must | Consistent with relational data |
| Idempotent MERGE | Must | Re-run safety |
| < 100ms traversal latency | Should | P95 for typical queries |

### Options Considered

#### Option A: Neo4j (Dedicated Graph Database)

Industry-leading native graph database with Cypher query language.

**Pros:**
- Native graph storage (optimal traversal)
- Full Cypher support
- Excellent tooling (Neo4j Browser, Bloom)
- Mature and battle-tested

**Cons:**
- **New container**: Adds complexity to deployment
- **Separate data store**: Events/entities duplicated across Postgres and Neo4j
- **Consistency challenges**: Must keep Postgres and Neo4j in sync
- **Operational overhead**: Additional monitoring, backups, upgrades
- **License**: Enterprise features require paid license

**Infrastructure Impact:**
```yaml
# docker-compose.yml changes
services:
  neo4j:
    image: neo4j:5.15
    ports:
      - "7474:7474"  # HTTP
      - "7687:7687"  # Bolt
    volumes:
      - neo4j_data:/data
```

#### Option B: Apache AGE (Postgres Extension)

Graph extension for PostgreSQL that adds Cypher support.

**Pros:**
- **No new container**: Runs inside existing Postgres
- **Same connection pool**: Uses existing asyncpg connections
- **ACID with Postgres**: Graph and relational data in same transaction
- **Cypher queries**: Standard graph query language
- **Open source**: Apache 2.0 license
- **Data locality**: No cross-database sync needed

**Cons:**
- Less mature than Neo4j
- Some Cypher features not supported (no CALL procedures)
- Performance not as optimized for very large graphs (millions of edges)
- Requires AGE extension installation in Postgres

**Infrastructure Impact:**
```sql
-- Enable in existing Postgres
CREATE EXTENSION IF NOT EXISTS age;
SELECT create_graph('nur');
```

#### Option C: Property Graph via Relational Tables (No Graph DB)

Model graph as relational tables with foreign keys.

**Pros:**
- No new dependencies
- Pure SQL queries
- Full ACID compliance
- Well-understood patterns

**Cons:**
- **Traversal complexity**: Recursive CTEs for 1-hop expansion
- **Query verbosity**: Simple traversals require complex SQL
- **No Cypher**: Graph queries not intuitive
- **Performance**: Recursive queries slower than native graph traversal

**Example 1-hop query (SQL recursive CTE):**
```sql
WITH RECURSIVE related AS (
  SELECT event_id FROM semantic_event WHERE event_id = ANY($seed_ids)
  UNION
  SELECT ea2.event_id
  FROM event_actor ea1
  JOIN event_actor ea2 ON ea1.entity_id = ea2.entity_id
  WHERE ea1.event_id = ANY($seed_ids)
)
SELECT * FROM semantic_event WHERE event_id IN (SELECT event_id FROM related);
```

#### Option D: EdgeDB (Graph-Relational Database)

Modern database combining relational and graph features.

**Pros:**
- Native graph traversal
- Type-safe queries
- Built-in migrations

**Cons:**
- **New service**: Another container to manage
- **Learning curve**: New query language (EdgeQL)
- **Ecosystem**: Smaller community than Postgres
- **Migration risk**: Moving from Postgres

---

## Decision

**We will implement Option B: Apache AGE (Postgres Extension)**

### Rationale

1. **Infrastructure Simplicity**: AGE runs inside our existing Postgres container. No new services, no new ports, no new backups. This aligns with our principle of minimal infrastructure changes for V4.

2. **Transactional Consistency**: With AGE, we can write relational data (entity tables) and graph data (nodes/edges) in the same transaction. This eliminates sync issues between separate databases.

3. **Cypher Support**: AGE provides the Cypher query language, making graph traversals intuitive:
   ```cypher
   MATCH (e:Entity)-[:ACTED_IN]->(ev:Event)
   WHERE e.canonical_name = 'Alice Chen'
   RETURN ev
   ```

4. **Scale Appropriateness**: Our expected graph size (10K-100K nodes) is well within AGE's capabilities. We're not building a social network with billions of edges.

5. **Fallback Path**: If AGE proves problematic, we can implement Option C (relational tables) without changing the data model - the entity and event_actor tables already exist.

---

## Implementation Details

### Extension Setup

```sql
-- Migration: 009_v4_age_graph.sql
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT create_graph('nur');
```

### Graph Schema

```cypher
-- Node labels
(:Entity {entity_id, canonical_name, type, role, organization})
(:Event {event_id, category, narrative, artifact_uid, revision_id, event_time, confidence})

-- Edge types
(:Entity)-[:ACTED_IN {role}]->(:Event)
(:Event)-[:ABOUT]->(:Entity)
(:Entity)-[:POSSIBLY_SAME {confidence, reason}]->(:Entity)
```

### Key Cypher Queries

**MERGE Entity Node:**
```cypher
SELECT * FROM cypher('nur', $$
    MERGE (e:Entity {entity_id: $entity_id})
    ON CREATE SET
        e.canonical_name = $canonical_name,
        e.type = $entity_type,
        e.role = $role,
        e.organization = $organization
    RETURN e
$$, $params) AS (e agtype);
```

**1-Hop Graph Expansion:**
```cypher
SELECT * FROM cypher('nur', $$
    MATCH (seed:Event) WHERE seed.event_id IN $seed_ids
    OPTIONAL MATCH (seed)<-[:ACTED_IN]-(actor:Entity)
    OPTIONAL MATCH (seed)-[:ABOUT]->(subject:Entity)
    WITH seed, collect(DISTINCT actor) + collect(DISTINCT subject) AS entities
    UNWIND entities AS entity
    MATCH (entity)-[:ACTED_IN|ABOUT]-(related:Event)
    WHERE NOT related.event_id IN $seed_ids
    RETURN DISTINCT related, entity
    LIMIT $budget
$$, $params) AS (related agtype, entity agtype);
```

### Python Integration

```python
import asyncpg

class GraphService:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def execute_cypher(self, query: str, params: dict) -> list:
        """Execute a Cypher query via AGE."""
        async with self.pool.acquire() as conn:
            # Set AGE search path
            await conn.execute("SET search_path = ag_catalog, public;")
            await conn.execute("LOAD 'age';")

            # Execute Cypher
            result = await conn.fetch(query, params)
            return result
```

---

## Consequences

### Positive

1. **No Infrastructure Changes**: Same Docker Compose, same Postgres container
2. **Transactional Safety**: Graph updates in same transaction as entity tables
3. **Developer Experience**: Cypher is intuitive for graph queries
4. **Cost Neutral**: No additional hosting costs
5. **Simpler Operations**: One database to monitor, backup, and maintain

### Negative

1. **AGE Maturity**: Less battle-tested than Neo4j
2. **Feature Limitations**: Some advanced Cypher features unavailable
3. **Performance Ceiling**: Not suitable for very large graphs (100M+ edges)
4. **Extension Management**: Must ensure AGE is installed in Postgres image

### Mitigations

| Risk | Mitigation |
|------|------------|
| AGE unavailable | Graceful degradation: return primary results without graph expansion |
| Query timeout | 500ms timeout on graph queries, return partial results |
| Extension installation | Custom Postgres Docker image with AGE pre-installed |
| Performance issues | Monitor query times, optimize indexes, consider partitioning |

---

## Comparison with Neo4j

| Aspect | Apache AGE | Neo4j |
|--------|-----------|-------|
| Deployment | Same container | New container |
| Transactions | With Postgres | Separate |
| Query Language | Cypher (subset) | Full Cypher |
| Max Graph Size | ~10M nodes | ~100M nodes |
| Tooling | Basic | Excellent |
| License | Apache 2.0 | AGPL/Commercial |
| Our Complexity | Low | High |

**Decision: AGE wins on operational simplicity for our scale.**

---

## Related ADRs

- **ADR-001**: Entity Resolution Strategy
- **ADR-003**: Entity Resolution Timing
- **ADR-004**: Graph Model Simplification

---

## References

- Apache AGE: https://age.apache.org/
- AGE Cypher Support: https://age.apache.org/age-manual/cypher.html
- V4 Brief: `/v4.md`
