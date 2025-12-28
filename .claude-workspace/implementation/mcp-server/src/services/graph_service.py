"""
V4 Graph Service for Apache AGE operations.

Manages the 'nur' graph containing:
- Entity nodes (person, org, project, etc.)
- Event nodes (Decision, Commitment, etc.)
- ACTED_IN edges (Entity -> Event)
- ABOUT edges (Event -> Entity)
- POSSIBLY_SAME edges (Entity -> Entity)

All operations are idempotent using Cypher MERGE semantics.
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID

logger = logging.getLogger("graph_service")


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class RelatedContext:
    """A related event found via graph expansion."""
    event_id: UUID
    category: str
    narrative: str
    reason: str           # e.g., "same_actor:Alice Chen"
    event_time: Optional[str]
    confidence: float
    entity_name: str      # Entity that connected this event
    artifact_uid: str
    revision_id: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "event",
            "id": str(self.event_id),
            "category": self.category,
            "reason": self.reason,
            "summary": self.narrative,
            "event_time": self.event_time,
            "artifact_uid": self.artifact_uid,
            "revision_id": self.revision_id
        }


@dataclass
class GraphHealthStats:
    """Health statistics for the graph."""
    age_enabled: bool
    graph_exists: bool
    entity_node_count: int
    event_node_count: int
    acted_in_edge_count: int
    about_edge_count: int
    possibly_same_edge_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "age_enabled": self.age_enabled,
            "graph_exists": self.graph_exists,
            "entity_node_count": self.entity_node_count,
            "event_node_count": self.event_node_count,
            "acted_in_edge_count": self.acted_in_edge_count,
            "about_edge_count": self.about_edge_count,
            "possibly_same_edge_count": self.possibly_same_edge_count
        }


# ============================================================================
# Exceptions
# ============================================================================

class GraphServiceError(Exception):
    """Base error for graph operations."""
    pass


class AGENotAvailableError(GraphServiceError):
    """Apache AGE extension not available."""
    pass


class GraphQueryTimeoutError(GraphServiceError):
    """Graph query timed out."""
    pass


class CypherSyntaxError(GraphServiceError):
    """Invalid Cypher query."""
    pass


# ============================================================================
# Graph Service
# ============================================================================

class GraphService:
    """
    Service for Apache AGE graph operations.

    Handles:
    - Node upserts (Entity, Event)
    - Edge upserts (ACTED_IN, ABOUT, POSSIBLY_SAME)
    - Graph traversal queries for context expansion
    """

    def __init__(
        self,
        pg_client,
        graph_name: str = "nur",
        query_timeout_ms: int = 500
    ):
        """
        Initialize graph service.

        Args:
            pg_client: Asyncpg-based Postgres client
            graph_name: AGE graph name (default: "nur")
            query_timeout_ms: Timeout for graph queries (default: 500ms)
        """
        self.pg = pg_client
        self.graph_name = graph_name
        self.query_timeout_ms = query_timeout_ms
        self._age_available: Optional[bool] = None

    async def check_age_available(self) -> bool:
        """Check if Apache AGE is available and properly configured."""
        if self._age_available is not None:
            return self._age_available

        try:
            # Check extension exists
            ext_check = await self.pg.fetch_one(
                "SELECT 1 FROM pg_extension WHERE extname = 'age'"
            )

            if not ext_check:
                self._age_available = False
                logger.warning("Apache AGE extension not installed")
                return False

            # Check graph exists
            graph_check = await self.pg.fetch_one(
                "SELECT 1 FROM ag_catalog.ag_graph WHERE name = $1",
                self.graph_name
            )

            if not graph_check:
                self._age_available = False
                logger.warning(f"Graph '{self.graph_name}' does not exist")
                return False

            self._age_available = True
            return True

        except Exception as e:
            logger.error(f"Failed to check AGE availability: {e}")
            self._age_available = False
            return False

    async def health_check(self) -> GraphHealthStats:
        """
        Check graph service health and return statistics.

        Returns:
            GraphHealthStats with AGE status and node/edge counts
        """
        age_enabled = await self.check_age_available()

        if not age_enabled:
            return GraphHealthStats(
                age_enabled=False,
                graph_exists=False,
                entity_node_count=0,
                event_node_count=0,
                acted_in_edge_count=0,
                about_edge_count=0,
                possibly_same_edge_count=0
            )

        try:
            # Count nodes and edges
            entity_count = 0
            event_count = 0
            acted_in_count = 0
            about_count = 0
            possibly_same_count = 0

            async with self.pg.pool.acquire() as conn:
                await self._ensure_age_session(conn)

                # Count Entity nodes
                result = await conn.fetchrow(
                    f"SELECT count(*) as cnt FROM cypher('{self.graph_name}', $$ MATCH (e:Entity) RETURN count(e) $$) as (cnt agtype)"
                )
                if result:
                    entity_count = int(str(result['cnt']).strip('"'))

                # Count Event nodes
                result = await conn.fetchrow(
                    f"SELECT count(*) as cnt FROM cypher('{self.graph_name}', $$ MATCH (e:Event) RETURN count(e) $$) as (cnt agtype)"
                )
                if result:
                    event_count = int(str(result['cnt']).strip('"'))

                # Count edges
                result = await conn.fetchrow(
                    f"SELECT count(*) as cnt FROM cypher('{self.graph_name}', $$ MATCH ()-[r:ACTED_IN]->() RETURN count(r) $$) as (cnt agtype)"
                )
                if result:
                    acted_in_count = int(str(result['cnt']).strip('"'))

                result = await conn.fetchrow(
                    f"SELECT count(*) as cnt FROM cypher('{self.graph_name}', $$ MATCH ()-[r:ABOUT]->() RETURN count(r) $$) as (cnt agtype)"
                )
                if result:
                    about_count = int(str(result['cnt']).strip('"'))

                result = await conn.fetchrow(
                    f"SELECT count(*) as cnt FROM cypher('{self.graph_name}', $$ MATCH ()-[r:POSSIBLY_SAME]->() RETURN count(r) $$) as (cnt agtype)"
                )
                if result:
                    possibly_same_count = int(str(result['cnt']).strip('"'))

            return GraphHealthStats(
                age_enabled=True,
                graph_exists=True,
                entity_node_count=entity_count,
                event_node_count=event_count,
                acted_in_edge_count=acted_in_count,
                about_edge_count=about_count,
                possibly_same_edge_count=possibly_same_count
            )

        except Exception as e:
            logger.error(f"Failed to get graph health stats: {e}")
            return GraphHealthStats(
                age_enabled=age_enabled,
                graph_exists=True,
                entity_node_count=0,
                event_node_count=0,
                acted_in_edge_count=0,
                about_edge_count=0,
                possibly_same_edge_count=0
            )

    async def _ensure_age_session(self, conn) -> None:
        """Ensure AGE is loaded in the current session."""
        await conn.execute("LOAD 'age'")
        await conn.execute("SET search_path = ag_catalog, \"$user\", public")

    async def execute_cypher(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute a Cypher query against the graph.

        Args:
            query: Cypher query string
            params: Query parameters (optional)

        Returns:
            List of result rows as dicts
        """
        if not await self.check_age_available():
            raise AGENotAvailableError("Apache AGE is not available")

        params = params or {}

        # Build the parameter injection for AGE
        # AGE doesn't support $1, $2 style params in Cypher, so we substitute directly
        substituted_query = self._substitute_params(query, params)

        # Wrap in cypher() function call
        sql = f"""
        SELECT * FROM cypher('{self.graph_name}', $$
            {substituted_query}
        $$) AS (result agtype)
        """

        try:
            async with self.pg.acquire() as conn:
                await self._ensure_age_session(conn)

                rows = await conn.fetch(
                    sql,
                    timeout=self.query_timeout_ms / 1000.0
                )

                results = []
                for row in rows:
                    # Parse AGE result (agtype)
                    result = self._parse_agtype(row["result"])
                    results.append(result)

                return results

        except Exception as e:
            error_str = str(e)
            if "timeout" in error_str.lower():
                raise GraphQueryTimeoutError(f"Query timed out after {self.query_timeout_ms}ms")
            elif "syntax" in error_str.lower():
                raise CypherSyntaxError(f"Invalid Cypher query: {e}")
            else:
                raise GraphServiceError(f"Graph query failed: {e}")

    def _substitute_params(self, query: str, params: Dict[str, Any]) -> str:
        """
        Substitute parameters into Cypher query.

        AGE doesn't support parameterized queries in the standard way,
        so we need to safely substitute values.
        """
        result = query

        for key, value in params.items():
            placeholder = f"${key}"
            if placeholder in result:
                if value is None:
                    result = result.replace(placeholder, "null")
                elif isinstance(value, bool):
                    result = result.replace(placeholder, str(value).lower())
                elif isinstance(value, (int, float)):
                    result = result.replace(placeholder, str(value))
                elif isinstance(value, str):
                    # Escape single quotes
                    escaped = value.replace("'", "\\'")
                    result = result.replace(placeholder, f"'{escaped}'")
                elif isinstance(value, (list, tuple)):
                    # Format as array
                    if all(isinstance(v, str) for v in value):
                        items = [f"'{v.replace(chr(39), chr(92)+chr(39))}'" for v in value]
                    else:
                        items = [str(v) for v in value]
                    result = result.replace(placeholder, f"[{', '.join(items)}]")
                elif isinstance(value, UUID):
                    result = result.replace(placeholder, f"'{str(value)}'")
                else:
                    result = result.replace(placeholder, f"'{str(value)}'")

        return result

    def _parse_agtype(self, value) -> Any:
        """Parse AGE agtype value to Python type."""
        if value is None:
            return None

        # AGE returns results as JSON strings
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value

        return value

    async def upsert_entity_node(
        self,
        entity_id: UUID,
        canonical_name: str,
        entity_type: str,
        role: Optional[str] = None,
        organization: Optional[str] = None
    ) -> None:
        """
        MERGE an entity node into the graph.

        Args:
            entity_id: Entity UUID
            canonical_name: Display name
            entity_type: Entity type (person, org, etc.)
            role: Job title (optional)
            organization: Company (optional)
        """
        # Build SET clause for optional properties
        set_parts = [
            "e.canonical_name = $canonical_name",
            "e.type = $entity_type"
        ]

        params = {
            "entity_id": str(entity_id),
            "canonical_name": canonical_name,
            "entity_type": entity_type
        }

        if role:
            set_parts.append("e.role = $role")
            params["role"] = role

        if organization:
            set_parts.append("e.organization = $organization")
            params["organization"] = organization

        set_clause = ", ".join(set_parts)

        # NOTE: Apache AGE Cypher support does not reliably accept `ON CREATE SET` / `ON MATCH SET`
        # across versions. For idempotent upserts, we `MERGE` the identity and then `SET` properties
        # unconditionally.
        query = f"""
        MERGE (e:Entity {{entity_id: $entity_id}})
        SET {set_clause}
        RETURN e
        """

        try:
            await self.execute_cypher(query, params)
            logger.debug(f"Upserted Entity node: {entity_id}")
        except GraphServiceError as e:
            logger.error(f"Failed to upsert Entity node {entity_id}: {e}")
            raise

    async def upsert_event_node(
        self,
        event_id: UUID,
        category: str,
        narrative: str,
        artifact_uid: str,
        revision_id: str,
        event_time: Optional[str] = None,
        confidence: float = 1.0
    ) -> None:
        """
        MERGE an event node into the graph.

        Args:
            event_id: Event UUID
            category: Event category (Decision, Commitment, etc.)
            narrative: Event summary
            artifact_uid: Document identifier
            revision_id: Document version
            event_time: ISO timestamp (optional)
            confidence: Extraction confidence
        """
        set_parts = [
            "ev.category = $category",
            "ev.narrative = $narrative",
            "ev.artifact_uid = $artifact_uid",
            "ev.revision_id = $revision_id",
            "ev.confidence = $confidence"
        ]

        params = {
            "event_id": str(event_id),
            "category": category,
            "narrative": narrative[:500],  # Truncate for graph storage
            "artifact_uid": artifact_uid,
            "revision_id": revision_id,
            "confidence": confidence
        }

        if event_time:
            set_parts.append("ev.event_time = $event_time")
            params["event_time"] = event_time

        set_clause = ", ".join(set_parts)

        query = f"""
        MERGE (ev:Event {{event_id: $event_id}})
        SET {set_clause}
        RETURN ev
        """

        try:
            await self.execute_cypher(query, params)
            logger.debug(f"Upserted Event node: {event_id}")
        except GraphServiceError as e:
            logger.error(f"Failed to upsert Event node {event_id}: {e}")
            raise

    async def upsert_acted_in_edge(
        self,
        entity_id: UUID,
        event_id: UUID,
        role: str
    ) -> None:
        """
        MERGE an ACTED_IN edge between entity and event.

        Args:
            entity_id: Actor entity UUID
            event_id: Event UUID
            role: Actor role (owner, contributor, etc.)
        """
        query = """
        MATCH (e:Entity {entity_id: $entity_id})
        MATCH (ev:Event {event_id: $event_id})
        MERGE (e)-[r:ACTED_IN]->(ev)
        SET r.role = $role
        RETURN r
        """

        params = {
            "entity_id": str(entity_id),
            "event_id": str(event_id),
            "role": role
        }

        try:
            await self.execute_cypher(query, params)
            logger.debug(f"Upserted ACTED_IN edge: {entity_id} -> {event_id}")
        except GraphServiceError as e:
            logger.error(f"Failed to upsert ACTED_IN edge: {e}")
            raise

    async def upsert_about_edge(
        self,
        event_id: UUID,
        entity_id: UUID
    ) -> None:
        """
        MERGE an ABOUT edge between event and entity.

        Args:
            event_id: Event UUID
            entity_id: Subject entity UUID
        """
        query = """
        MATCH (ev:Event {event_id: $event_id})
        MATCH (e:Entity {entity_id: $entity_id})
        MERGE (ev)-[r:ABOUT]->(e)
        RETURN r
        """

        params = {
            "event_id": str(event_id),
            "entity_id": str(entity_id)
        }

        try:
            await self.execute_cypher(query, params)
            logger.debug(f"Upserted ABOUT edge: {event_id} -> {entity_id}")
        except GraphServiceError as e:
            logger.error(f"Failed to upsert ABOUT edge: {e}")
            raise

    async def upsert_possibly_same_edge(
        self,
        entity_a_id: UUID,
        entity_b_id: UUID,
        confidence: float,
        reason: str
    ) -> None:
        """
        MERGE a POSSIBLY_SAME edge between two entities.

        Used when entity resolution is uncertain.

        Args:
            entity_a_id: First entity UUID
            entity_b_id: Second entity UUID
            confidence: Similarity confidence
            reason: Explanation from LLM
        """
        query = """
        MATCH (a:Entity {entity_id: $entity_a_id})
        MATCH (b:Entity {entity_id: $entity_b_id})
        MERGE (a)-[r:POSSIBLY_SAME]->(b)
        SET r.confidence = $confidence, r.reason = $reason
        RETURN r
        """

        params = {
            "entity_a_id": str(entity_a_id),
            "entity_b_id": str(entity_b_id),
            "confidence": confidence,
            "reason": reason[:200]  # Truncate reason
        }

        try:
            await self.execute_cypher(query, params)
            logger.debug(f"Upserted POSSIBLY_SAME edge: {entity_a_id} <-> {entity_b_id}")
        except GraphServiceError as e:
            logger.error(f"Failed to upsert POSSIBLY_SAME edge: {e}")
            raise

    async def expand_from_events(
        self,
        seed_event_ids: List[UUID],
        budget: int = 10,
        category_filter: Optional[List[str]] = None
    ) -> List[RelatedContext]:
        """
        Perform 1-hop graph expansion from seed events.

        Algorithm:
        1. Find entities connected to seed events (actors and subjects)
        2. Find other events connected to those entities
        3. Exclude seed events from results
        4. Apply category filter if provided
        5. Order by event_time DESC, confidence DESC
        6. Limit to budget

        Args:
            seed_event_ids: Event IDs to expand from
            budget: Maximum related items to return
            category_filter: List of categories to include (None = all)

        Returns:
            List of RelatedContext objects with reason labels
        """
        if not seed_event_ids:
            return []

        if not await self.check_age_available():
            logger.warning("AGE not available, returning empty expansion")
            return []

        # Build seed IDs array
        seed_ids_str = [str(sid) for sid in seed_event_ids]

        # Build category filter clause
        category_clause = ""
        if category_filter:
            categories_str = ", ".join([f"'{c}'" for c in category_filter])
            category_clause = f"AND related.category IN [{categories_str}]"

        # NOTE: Apache AGE Cypher has a few sharp edges around variable reuse and
        # relationship-type unions. This query is written to avoid:
        # - `[:A|B]` union syntax
        # - `UNWIND ... AS var` followed by `MATCH (var)...` (AGE can error "var already exists")
        #
        # Strategy: expand from seed events via two explicit paths (actors and subjects) and UNION.
        query = f"""
        MATCH (seed:Event)
        WHERE seed.event_id IN $seed_ids
        MATCH (seed)<-[:ACTED_IN]-(ent:Entity)
        MATCH (ent)-[rel]-(related:Event)
        WHERE type(rel) IN ['ACTED_IN', 'ABOUT']
          AND NOT related.event_id IN $seed_ids
        {category_clause}
        RETURN DISTINCT
               related.event_id AS event_id,
               related.category AS category,
               related.narrative AS narrative,
               related.event_time AS event_time,
               related.confidence AS confidence,
               related.artifact_uid AS artifact_uid,
               related.revision_id AS revision_id,
               ent.canonical_name AS entity_name,
               CASE
                 WHEN type(rel) = 'ACTED_IN' THEN 'same_actor:' + ent.canonical_name
                 ELSE 'same_subject:' + ent.canonical_name
               END AS reason

        UNION

        MATCH (seed:Event)
        WHERE seed.event_id IN $seed_ids
        MATCH (seed)-[:ABOUT]->(ent:Entity)
        MATCH (ent)-[rel]-(related:Event)
        WHERE type(rel) IN ['ACTED_IN', 'ABOUT']
          AND NOT related.event_id IN $seed_ids
        {category_clause}
        RETURN DISTINCT
               related.event_id AS event_id,
               related.category AS category,
               related.narrative AS narrative,
               related.event_time AS event_time,
               related.confidence AS confidence,
               related.artifact_uid AS artifact_uid,
               related.revision_id AS revision_id,
               ent.canonical_name AS entity_name,
               CASE
                 WHEN type(rel) = 'ACTED_IN' THEN 'same_actor:' + ent.canonical_name
                 ELSE 'same_subject:' + ent.canonical_name
               END AS reason

        LIMIT $budget
        """

        params = {
            "seed_ids": seed_ids_str,
            "budget": budget
        }

        try:
            # Execute with a more complex result parser
            async with self.pg.acquire() as conn:
                await self._ensure_age_session(conn)

                sql = f"""
                SELECT * FROM cypher('{self.graph_name}', $$
                    {self._substitute_params(query, params)}
                $$) AS (
                    event_id agtype,
                    category agtype,
                    narrative agtype,
                    event_time agtype,
                    confidence agtype,
                    artifact_uid agtype,
                    revision_id agtype,
                    entity_name agtype,
                    reason agtype
                )
                """

                rows = await conn.fetch(sql, timeout=self.query_timeout_ms / 1000.0)

                results = []
                for row in rows:
                    event_id_str = self._parse_agtype(row["event_id"])
                    if not event_id_str:
                        continue

                    results.append(RelatedContext(
                        event_id=UUID(event_id_str),
                        category=self._parse_agtype(row["category"]) or "",
                        narrative=self._parse_agtype(row["narrative"]) or "",
                        event_time=self._parse_agtype(row["event_time"]),
                        confidence=float(self._parse_agtype(row["confidence"]) or 1.0),
                        artifact_uid=self._parse_agtype(row["artifact_uid"]) or "",
                        revision_id=self._parse_agtype(row["revision_id"]) or "",
                        entity_name=self._parse_agtype(row["entity_name"]) or "",
                        reason=self._parse_agtype(row["reason"]) or ""
                    ))

                logger.info(f"Graph expansion returned {len(results)} related events")
                # Sort in Python for portability across AGE versions (some struggle with
                # ORDER BY on UNION queries / agtype columns).
                def _sort_key(rc: RelatedContext):
                    # ISO8601 sorts lexicographically for same format; None goes last.
                    return (rc.event_time or "", rc.confidence)

                results.sort(key=_sort_key, reverse=True)
                return results[:budget]

        except GraphQueryTimeoutError:
            logger.warning("Graph expansion timed out, returning empty results")
            return []
        except Exception as e:
            logger.error(f"Graph expansion failed: {e}")
            return []

    async def get_health(self) -> GraphHealthStats:
        """
        Get graph health statistics.

        Returns:
            GraphHealthStats with node/edge counts
        """
        if not await self.check_age_available():
            return GraphHealthStats(
                age_enabled=False,
                graph_exists=False,
                entity_node_count=0,
                event_node_count=0,
                acted_in_edge_count=0,
                about_edge_count=0,
                possibly_same_edge_count=0
            )

        try:
            # Count Entity nodes
            entity_count = 0
            try:
                result = await self.execute_cypher("MATCH (e:Entity) RETURN count(e) AS cnt")
                if result:
                    entity_count = int(self._parse_agtype(result[0]) if result else 0)
            except Exception:
                pass

            # Count Event nodes
            event_count = 0
            try:
                result = await self.execute_cypher("MATCH (ev:Event) RETURN count(ev) AS cnt")
                if result:
                    event_count = int(self._parse_agtype(result[0]) if result else 0)
            except Exception:
                pass

            # Count ACTED_IN edges
            acted_in_count = 0
            try:
                result = await self.execute_cypher("MATCH ()-[r:ACTED_IN]->() RETURN count(r) AS cnt")
                if result:
                    acted_in_count = int(self._parse_agtype(result[0]) if result else 0)
            except Exception:
                pass

            # Count ABOUT edges
            about_count = 0
            try:
                result = await self.execute_cypher("MATCH ()-[r:ABOUT]->() RETURN count(r) AS cnt")
                if result:
                    about_count = int(self._parse_agtype(result[0]) if result else 0)
            except Exception:
                pass

            # Count POSSIBLY_SAME edges
            possibly_same_count = 0
            try:
                result = await self.execute_cypher("MATCH ()-[r:POSSIBLY_SAME]->() RETURN count(r) AS cnt")
                if result:
                    possibly_same_count = int(self._parse_agtype(result[0]) if result else 0)
            except Exception:
                pass

            return GraphHealthStats(
                age_enabled=True,
                graph_exists=True,
                entity_node_count=entity_count,
                event_node_count=event_count,
                acted_in_edge_count=acted_in_count,
                about_edge_count=about_count,
                possibly_same_edge_count=possibly_same_count
            )

        except Exception as e:
            logger.error(f"Failed to get graph health: {e}")
            return GraphHealthStats(
                age_enabled=True,
                graph_exists=True,
                entity_node_count=-1,
                event_node_count=-1,
                acted_in_edge_count=-1,
                about_edge_count=-1,
                possibly_same_edge_count=-1
            )

    async def get_entities_for_events(
        self,
        event_ids: List[UUID]
    ) -> List[Dict[str, Any]]:
        """
        Get all entities related to a set of events.

        Args:
            event_ids: Event IDs to get entities for

        Returns:
            List of entity dicts with mention counts
        """
        if not event_ids:
            return []

        if not await self.check_age_available():
            return []

        event_ids_str = [str(eid) for eid in event_ids]

        # NOTE: Avoid relationship-type union syntax for AGE compatibility.
        query = """
        MATCH (ev:Event)
        WHERE ev.event_id IN $event_ids
        MATCH (e:Entity)-[rel]-(ev)
        WHERE type(rel) IN ['ACTED_IN', 'ABOUT']
        WITH e, count(DISTINCT ev) AS mention_count
        RETURN e.entity_id AS entity_id,
               e.canonical_name AS name,
               e.type AS type,
               e.role AS role,
               e.organization AS organization,
               mention_count
        ORDER BY mention_count DESC
        """

        try:
            async with self.pg.acquire() as conn:
                await self._ensure_age_session(conn)

                sql = f"""
                SELECT * FROM cypher('{self.graph_name}', $$
                    {self._substitute_params(query, {"event_ids": event_ids_str})}
                $$) AS (
                    entity_id agtype,
                    name agtype,
                    type agtype,
                    role agtype,
                    organization agtype,
                    mention_count agtype
                )
                """

                rows = await conn.fetch(sql, timeout=self.query_timeout_ms / 1000.0)

                entities = []
                for row in rows:
                    entity_id = self._parse_agtype(row["entity_id"])
                    if not entity_id:
                        continue

                    entities.append({
                        "entity_id": entity_id,
                        "name": self._parse_agtype(row["name"]) or "",
                        "type": self._parse_agtype(row["type"]) or "other",
                        "role": self._parse_agtype(row["role"]),
                        "organization": self._parse_agtype(row["organization"]),
                        "mention_count": int(self._parse_agtype(row["mention_count"]) or 1)
                    })

                return entities

        except Exception as e:
            logger.error(f"Failed to get entities for events: {e}")
            return []
