# V4 Service Interfaces

## Overview

V4 introduces two new services and enhances one existing service:

| Service | Status | Purpose |
|---------|--------|---------|
| `EntityResolutionService` | NEW | Resolve entity mentions to canonical entities |
| `GraphService` | NEW | Manage Apache AGE graph operations |
| `RetrievalService` | ENHANCED | hybrid_search with graph expansion |

---

## 1. EntityResolutionService

### Purpose

Resolves entity mentions extracted from documents to canonical entities in the database. Handles deduplication using a two-phase approach: embedding similarity for candidate generation, then LLM confirmation for merge decisions.

### Interface Definition

```python
from dataclasses import dataclass
from typing import Optional, List
from uuid import UUID

@dataclass
class ContextClues:
    """Context clues for entity disambiguation."""
    role: Optional[str] = None        # Job title, e.g., "Engineering Manager"
    organization: Optional[str] = None # Company, e.g., "Acme Corp"
    email: Optional[str] = None        # Email address

@dataclass
class EntityResolutionResult:
    """Result of resolving an entity mention."""
    entity_id: UUID              # Resolved entity ID
    is_new: bool                 # True if new entity created
    merged_from: Optional[UUID]  # ID of existing entity if merged
    uncertain_match: Optional[UUID]  # ID if POSSIBLY_SAME edge created
    canonical_name: str          # Final canonical name used

@dataclass
class MergeDecision:
    """LLM's decision on whether two entities are the same."""
    decision: str       # "same" | "different" | "uncertain"
    canonical_name: str # Best name to use (if "same")
    reason: str         # Explanation for the decision

class EntityResolutionService:
    """
    Service for resolving entity mentions to canonical entities.

    Uses a two-phase approach:
    1. Embedding similarity for candidate generation
    2. LLM confirmation for merge decisions
    """

    def __init__(
        self,
        postgres_pool: asyncpg.Pool,
        embedding_service: EmbeddingService,
        openai_client: OpenAI,
        similarity_threshold: float = 0.85,
        max_candidates: int = 5,
        model: str = "gpt-4o-mini"
    ):
        """
        Initialize entity resolution service.

        Args:
            postgres_pool: Asyncpg connection pool
            embedding_service: Service for generating embeddings
            openai_client: OpenAI client for LLM confirmation
            similarity_threshold: Minimum similarity for candidates (default: 0.85)
            max_candidates: Maximum candidates to consider (default: 5)
            model: LLM model for confirmation (default: gpt-4o-mini)
        """
        pass

    async def resolve_entity(
        self,
        surface_form: str,
        canonical_suggestion: str,
        entity_type: str,
        context_clues: ContextClues,
        artifact_uid: str,
        revision_id: str,
        aliases_in_doc: Optional[List[str]] = None,
        start_char: Optional[int] = None,
        end_char: Optional[int] = None
    ) -> EntityResolutionResult:
        """
        Resolve an entity mention to a canonical entity.

        This is the main entry point. It will:
        1. Check for exact name match in existing entities
        2. If no exact match, generate embedding and find candidates
        3. If candidates found, call LLM for confirmation
        4. Create or merge entity based on decision
        5. Record mention and aliases

        Args:
            surface_form: Exact text as it appeared in document
            canonical_suggestion: LLM's suggested canonical name
            entity_type: person|org|project|object|place|other
            context_clues: Role, organization, email for disambiguation
            artifact_uid: Document identifier
            revision_id: Document version identifier
            aliases_in_doc: Other surface forms in the same document
            start_char: Character offset start (optional)
            end_char: Character offset end (optional)

        Returns:
            EntityResolutionResult with resolved entity_id and status

        Raises:
            EntityResolutionError: If resolution fails
        """
        pass

    async def generate_context_embedding(
        self,
        canonical_name: str,
        entity_type: str,
        role: Optional[str] = None,
        organization: Optional[str] = None
    ) -> List[float]:
        """
        Generate embedding for entity context string.

        Context string format: "{name}, {type}, {role}, {org}"
        Example: "Alice Chen, person, Engineering Manager, Acme Corp"

        Args:
            canonical_name: Entity's canonical name
            entity_type: Entity type
            role: Job title (optional)
            organization: Company (optional)

        Returns:
            Embedding vector (3072 dimensions for text-embedding-3-large)
        """
        pass

    async def find_dedup_candidates(
        self,
        entity_type: str,
        context_embedding: List[float],
        threshold: Optional[float] = None
    ) -> List['Entity']:
        """
        Find candidate entities for deduplication using embedding similarity.

        Args:
            entity_type: Only match entities of same type
            context_embedding: Query embedding vector
            threshold: Similarity threshold (default: self.similarity_threshold)

        Returns:
            List of candidate Entity objects, ordered by similarity

        SQL Query:
            SELECT * FROM entity
            WHERE entity_type = $type
              AND context_embedding <=> $embedding < (1 - $threshold)
            ORDER BY context_embedding <=> $embedding
            LIMIT $max_candidates
        """
        pass

    async def confirm_merge_with_llm(
        self,
        entity_a: 'Entity',
        entity_b: 'Entity',
        context_a: ContextClues,
        context_b: ContextClues,
        doc_title_a: str,
        doc_title_b: str
    ) -> MergeDecision:
        """
        Call LLM to confirm whether two entities are the same.

        Args:
            entity_a: New entity (from current extraction)
            entity_b: Existing entity (candidate)
            context_a: Context clues for entity A
            context_b: Context clues for entity B
            doc_title_a: Document title for A
            doc_title_b: Document title for B

        Returns:
            MergeDecision with decision, canonical_name, and reason
        """
        pass

    async def create_entity(
        self,
        canonical_name: str,
        normalized_name: str,
        entity_type: str,
        context_clues: ContextClues,
        context_embedding: List[float],
        artifact_uid: str,
        revision_id: str,
        needs_review: bool = False
    ) -> UUID:
        """
        Create a new entity in the database.

        Args:
            canonical_name: Display name
            normalized_name: Lowercase, stripped for matching
            entity_type: Entity type
            context_clues: Role, org, email
            context_embedding: Vector embedding
            artifact_uid: First seen document
            revision_id: First seen version
            needs_review: Flag for uncertain merges

        Returns:
            New entity_id
        """
        pass

    async def merge_entity(
        self,
        new_surface_form: str,
        existing_entity_id: UUID,
        new_canonical_name: Optional[str] = None
    ) -> UUID:
        """
        Merge a mention into an existing entity.

        If new_canonical_name provided and different from existing,
        may update the entity's canonical name (if more complete).

        Args:
            new_surface_form: Surface form being merged
            existing_entity_id: Target entity
            new_canonical_name: Optional updated canonical name

        Returns:
            existing_entity_id (unchanged)
        """
        pass

    async def add_alias(
        self,
        entity_id: UUID,
        alias: str
    ) -> None:
        """
        Add an alias to an entity.

        Args:
            entity_id: Entity to add alias to
            alias: New alias text
        """
        pass

    async def record_mention(
        self,
        entity_id: UUID,
        artifact_uid: str,
        revision_id: str,
        surface_form: str,
        start_char: Optional[int] = None,
        end_char: Optional[int] = None
    ) -> UUID:
        """
        Record an entity mention.

        Args:
            entity_id: Resolved entity
            artifact_uid: Document identifier
            revision_id: Document version
            surface_form: Exact text
            start_char: Character offset start
            end_char: Character offset end

        Returns:
            mention_id
        """
        pass
```

### Usage Example

```python
# In EventExtractionService.process_job()

entity_resolution = EntityResolutionService(
    postgres_pool=pool,
    embedding_service=embedding_svc,
    openai_client=openai_client
)

# For each entity extracted from the document
for entity_mention in extracted_entities:
    result = await entity_resolution.resolve_entity(
        surface_form=entity_mention.surface_form,
        canonical_suggestion=entity_mention.canonical_suggestion,
        entity_type=entity_mention.type,
        context_clues=ContextClues(
            role=entity_mention.context_clues.get("role"),
            organization=entity_mention.context_clues.get("org"),
            email=entity_mention.context_clues.get("email")
        ),
        artifact_uid=job.artifact_uid,
        revision_id=job.revision_id,
        aliases_in_doc=entity_mention.aliases_in_doc,
        start_char=entity_mention.start_char,
        end_char=entity_mention.end_char
    )

    # Map surface form to resolved entity_id for event linking
    entity_map[entity_mention.surface_form] = result.entity_id
```

---

## 2. GraphService

### Purpose

Manages Apache AGE graph operations including node/edge upserts and graph traversal queries for context expansion.

### Interface Definition

```python
from dataclasses import dataclass
from typing import List, Optional
from uuid import UUID

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
        postgres_pool: asyncpg.Pool,
        graph_name: str = "nur",
        query_timeout_ms: int = 500
    ):
        """
        Initialize graph service.

        Args:
            postgres_pool: Asyncpg connection pool
            graph_name: AGE graph name (default: "nur")
            query_timeout_ms: Timeout for graph queries (default: 500ms)
        """
        pass

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

        Cypher:
            MERGE (e:Entity {entity_id: $entity_id})
            ON CREATE SET
                e.canonical_name = $name,
                e.type = $type,
                e.role = $role,
                e.organization = $org
            ON MATCH SET
                e.canonical_name = $name,
                e.role = COALESCE($role, e.role),
                e.organization = COALESCE($org, e.organization)

        Args:
            entity_id: Entity UUID
            canonical_name: Display name
            entity_type: Entity type
            role: Job title (optional)
            organization: Company (optional)
        """
        pass

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
        pass

    async def upsert_acted_in_edge(
        self,
        entity_id: UUID,
        event_id: UUID,
        role: str
    ) -> None:
        """
        MERGE an ACTED_IN edge between entity and event.

        Cypher:
            MATCH (e:Entity {entity_id: $entity_id})
            MATCH (ev:Event {event_id: $event_id})
            MERGE (e)-[r:ACTED_IN]->(ev)
            ON CREATE SET r.role = $role
            ON MATCH SET r.role = $role

        Args:
            entity_id: Actor entity UUID
            event_id: Event UUID
            role: Actor role (owner, contributor, etc.)
        """
        pass

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
        pass

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
        pass

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
        pass

    async def get_health(self) -> GraphHealthStats:
        """
        Get graph health statistics.

        Returns:
            GraphHealthStats with node/edge counts
        """
        pass

    async def execute_cypher(
        self,
        query: str,
        params: dict
    ) -> List[dict]:
        """
        Execute a raw Cypher query.

        Internal method for graph operations.

        Args:
            query: Cypher query string
            params: Query parameters

        Returns:
            List of result rows as dicts
        """
        pass
```

### Usage Example

```python
# In graph_upsert worker job

graph_service = GraphService(postgres_pool=pool)

# Upsert entity nodes
for entity in entities:
    await graph_service.upsert_entity_node(
        entity_id=entity.entity_id,
        canonical_name=entity.canonical_name,
        entity_type=entity.entity_type,
        role=entity.role,
        organization=entity.organization
    )

# Upsert event nodes
for event in events:
    await graph_service.upsert_event_node(
        event_id=event.event_id,
        category=event.category,
        narrative=event.narrative,
        artifact_uid=event.artifact_uid,
        revision_id=event.revision_id,
        event_time=event.event_time,
        confidence=event.confidence
    )

# Upsert edges
for actor in event_actors:
    await graph_service.upsert_acted_in_edge(
        entity_id=actor.entity_id,
        event_id=actor.event_id,
        role=actor.role
    )
```

---

## 3. RetrievalService (Enhanced)

### Enhancement Summary

The existing `RetrievalService` is enhanced with graph expansion capabilities. The `hybrid_search` method gains new parameters for graph-based context expansion.

### New Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `graph_expand` | bool | False | Enable graph expansion |
| `graph_depth` | int | 1 | Expansion depth (only 1 in V4) |
| `graph_budget` | int | 10 | Max related items |
| `graph_seed_limit` | int | 5 | Max seeds from primary results |
| `graph_filters` | List[str] | None | Category filter |
| `include_entities` | bool | True | Include entities list |

### Enhanced Interface

```python
@dataclass
class HybridSearchResult:
    """Result of hybrid search with optional graph expansion."""
    primary_results: List[MergedResult]
    related_context: Optional[List[RelatedContextItem]]
    entities: Optional[List[EntityInfo]]
    expand_options: List[ExpandOption]

@dataclass
class RelatedContextItem:
    """A related event from graph expansion."""
    type: str              # Always "event" in V4
    id: str                # Event UUID
    category: str          # Event category
    reason: str            # e.g., "same_actor:Alice Chen"
    summary: str           # Event narrative
    event_time: Optional[str]
    evidence: List[EvidenceItem]

@dataclass
class EntityInfo:
    """Entity information for response."""
    entity_id: str
    name: str
    type: str
    role: Optional[str]
    organization: Optional[str]
    aliases: List[str]
    mention_count: int

@dataclass
class ExpandOption:
    """Available expansion option."""
    name: str
    description: str

class RetrievalService:
    """RRF-based hybrid retrieval service (V4 enhanced)."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        chunking_service: ChunkingService,
        chroma_client: HttpClient,
        graph_service: GraphService,  # NEW
        postgres_pool: asyncpg.Pool,  # NEW
        k: int = 60
    ):
        pass

    def hybrid_search(
        self,
        query: str,
        limit: int = 5,
        include_memory: bool = False,
        expand_neighbors: bool = False,
        filters: Optional[Dict] = None,
        # V4 new parameters:
        graph_expand: bool = False,
        graph_depth: int = 1,
        graph_budget: int = 10,
        graph_seed_limit: int = 5,
        graph_filters: Optional[List[str]] = None,
        include_entities: bool = True
    ) -> HybridSearchResult:
        """
        Search across collections with optional graph expansion.

        V4 Behavior:
        - When graph_expand=False: Returns V3-compatible output
        - When graph_expand=True: Adds related_context and entities

        expand_options is ALWAYS returned for progressive disclosure.

        Args:
            query: Search query text
            limit: Max primary results
            include_memory: Include memory collection
            expand_neighbors: Include +-1 chunks
            filters: Metadata filters
            graph_expand: Enable graph expansion (V4)
            graph_depth: Expansion depth, only 1 supported (V4)
            graph_budget: Max related items (V4)
            graph_seed_limit: Max seeds from primary results (V4)
            graph_filters: Category filter for related items (V4)
            include_entities: Include entities list (V4)

        Returns:
            HybridSearchResult with all sections
        """
        pass

    async def expand_via_graph(
        self,
        primary_results: List[MergedResult],
        graph_seed_limit: int,
        graph_budget: int,
        graph_filters: Optional[List[str]]
    ) -> Tuple[List[RelatedContextItem], List[EntityInfo]]:
        """
        Perform graph expansion on primary results.

        Steps:
        1. Collect seed event IDs from primary results
        2. Map chunks/artifacts to revisions to get events
        3. Call GraphService.expand_from_events()
        4. Fetch full event data + evidence
        5. Fetch entities for all events

        Args:
            primary_results: Top search results
            graph_seed_limit: Max seeds to use
            graph_budget: Max related items
            graph_filters: Category filter

        Returns:
            Tuple of (related_context, entities)
        """
        pass

    async def map_chunk_to_revision(
        self,
        artifact_id: str
    ) -> Tuple[str, str]:
        """
        Map a chunk's artifact_id to its revision.

        Args:
            artifact_id: Artifact ID from chunk

        Returns:
            Tuple of (artifact_uid, revision_id)
        """
        pass

    def get_expand_options(self) -> List[ExpandOption]:
        """
        Get available expansion options.

        Always returns the same list for progressive disclosure.

        Returns:
            List of ExpandOption objects
        """
        return [
            ExpandOption(
                name="graph_expand",
                description="Add related events/entities (1 hop) for richer context"
            ),
            ExpandOption(
                name="include_memory",
                description="Include stored memories in search"
            ),
            ExpandOption(
                name="expand_neighbors",
                description="Include neighboring chunks for context"
            ),
            ExpandOption(
                name="graph_budget",
                description="Adjust max related items (current: 10)"
            ),
            ExpandOption(
                name="graph_filters",
                description="Filter by category: Decision, Commitment, QualityRisk, etc."
            )
        ]
```

### Response Format

```json
{
  "primary_results": [
    {
      "id": "art_abc123::chunk::002::xyz789",
      "content": "Alice Chen decided...",
      "type": "chunk",
      "metadata": {...},
      "rrf_score": 0.0154,
      "collections": ["artifact_chunks"]
    }
  ],
  "related_context": [
    {
      "type": "event",
      "id": "evt_def456",
      "category": "Commitment",
      "reason": "same_actor:Alice Chen",
      "summary": "Alice committed to delivering MVP by Q1",
      "event_time": "2024-03-10T09:00:00Z",
      "evidence": [
        {
          "quote": "I'll have the MVP ready by end of Q1",
          "artifact_uid": "uid_123",
          "start_char": 450,
          "end_char": 495
        }
      ]
    }
  ],
  "entities": [
    {
      "entity_id": "ent_789",
      "name": "Alice Chen",
      "type": "person",
      "role": "Engineering Manager",
      "organization": "Acme Corp",
      "aliases": ["Alice", "A. Chen"],
      "mention_count": 12
    }
  ],
  "expand_options": [
    {"name": "graph_expand", "description": "..."},
    {"name": "include_memory", "description": "..."},
    {"name": "expand_neighbors", "description": "..."},
    {"name": "graph_budget", "description": "..."},
    {"name": "graph_filters", "description": "..."}
  ]
}
```

---

## Error Types

### EntityResolutionError

```python
class EntityResolutionError(Exception):
    """Error during entity resolution."""
    pass

class EmbeddingGenerationError(EntityResolutionError):
    """Failed to generate entity embedding."""
    pass

class DedupCandidateError(EntityResolutionError):
    """Failed to find dedup candidates."""
    pass

class LLMConfirmationError(EntityResolutionError):
    """Failed to get LLM confirmation."""
    pass
```

### GraphServiceError

```python
class GraphServiceError(Exception):
    """Error during graph operation."""
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
```

---

## Dependencies

### EntityResolutionService

- `asyncpg.Pool` - Postgres connection pool
- `EmbeddingService` - For context embeddings
- `OpenAI` - For LLM confirmation

### GraphService

- `asyncpg.Pool` - Postgres connection pool (with AGE)

### RetrievalService (Enhanced)

- `EmbeddingService` - Query embeddings
- `ChunkingService` - Neighbor expansion
- `HttpClient` - ChromaDB client
- `GraphService` - Graph expansion (NEW)
- `asyncpg.Pool` - Postgres client (NEW)
