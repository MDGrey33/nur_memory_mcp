"""
V4 Entity Resolution Service.

Resolves entity mentions to canonical entities using a two-phase approach:
1. Embedding similarity for candidate generation
2. LLM confirmation for merge decisions

Key features:
- Quality-first approach: conservative merges, uncertain cases flagged for review
- Embedding-based candidate search reduces LLM calls to O(candidates), not O(n^2)
- Full evidence trail preserved via entity_mention table
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID, uuid4

from openai import OpenAI

logger = logging.getLogger("entity_resolution")


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class ContextClues:
    """Context clues for entity disambiguation."""
    role: Optional[str] = None        # Job title, e.g., "Engineering Manager"
    organization: Optional[str] = None # Company, e.g., "Acme Corp"
    email: Optional[str] = None        # Email address

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "organization": self.organization,
            "email": self.email
        }

    def has_context(self) -> bool:
        """Check if any context clues are available."""
        return any([self.role, self.organization, self.email])


@dataclass
class EntityResolutionResult:
    """Result of resolving an entity mention."""
    entity_id: UUID              # Resolved entity ID
    is_new: bool                 # True if new entity created
    merged_from: Optional[UUID] = None  # ID of existing entity if merged
    uncertain_match: Optional[UUID] = None  # ID if POSSIBLY_SAME edge created
    canonical_name: str = ""     # Final canonical name used

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": str(self.entity_id),
            "is_new": self.is_new,
            "merged_from": str(self.merged_from) if self.merged_from else None,
            "uncertain_match": str(self.uncertain_match) if self.uncertain_match else None,
            "canonical_name": self.canonical_name
        }


@dataclass
class MergeDecision:
    """LLM's decision on whether two entities are the same."""
    decision: str       # "same" | "different" | "uncertain"
    canonical_name: str # Best name to use (if "same")
    reason: str         # Explanation for the decision


@dataclass
class Entity:
    """Represents an entity from the database."""
    entity_id: UUID
    entity_type: str
    canonical_name: str
    normalized_name: str
    role: Optional[str] = None
    organization: Optional[str] = None
    email: Optional[str] = None
    first_seen_artifact_uid: str = ""
    first_seen_revision_id: str = ""
    needs_review: bool = False


@dataclass
class ExtractedEntity:
    """Entity extracted from document by the LLM."""
    surface_form: str
    canonical_suggestion: str
    entity_type: str  # person|org|project|object|place|other
    context_clues: ContextClues
    aliases_in_doc: List[str] = field(default_factory=list)
    confidence: float = 0.9
    start_char: Optional[int] = None
    end_char: Optional[int] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'ExtractedEntity':
        """Create from LLM extraction output."""
        context = d.get("context_clues", {})
        return cls(
            surface_form=d.get("surface_form", ""),
            canonical_suggestion=d.get("canonical_suggestion", d.get("surface_form", "")),
            entity_type=d.get("type", "other"),
            context_clues=ContextClues(
                role=context.get("role"),
                organization=context.get("org") or context.get("organization"),
                email=context.get("email")
            ),
            aliases_in_doc=d.get("aliases_in_doc", []),
            confidence=d.get("confidence", 0.9),
            start_char=d.get("start_char"),
            end_char=d.get("end_char")
        )


# ============================================================================
# LLM Prompts
# ============================================================================

ENTITY_DEDUP_PROMPT = """You are determining if two entity mentions refer to the same real-world entity.

ENTITY A (from document "{title_a}"):
- Name: "{name_a}"
- Type: {type_a}
- Context: {context_a}

ENTITY B (from document "{title_b}"):
- Name: "{name_b}"
- Type: {type_b}
- Context: {context_b}

Rules:
- "same" = High confidence these refer to the same real-world entity
- "different" = High confidence these are different entities
- "uncertain" = Not enough information to decide confidently

Key considerations:
- Same name + same organization = likely same person
- Same name + different organizations = likely different people
- Nicknames/abbreviations with matching context = likely same
- Limited context = should be "uncertain"

If "same", provide the best canonical name to use (prefer the more complete form).

Return JSON:
{
  "decision": "same|different|uncertain",
  "canonical_name": "Full name to use if same, otherwise the name from entity A",
  "reason": "Brief explanation (1-2 sentences)"
}"""


# ============================================================================
# Entity Resolution Service
# ============================================================================

class EntityResolutionError(Exception):
    """Base error for entity resolution."""
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


class EntityResolutionService:
    """
    Service for resolving entity mentions to canonical entities.

    Uses a two-phase approach:
    1. Embedding similarity for candidate generation
    2. LLM confirmation for merge decisions
    """

    def __init__(
        self,
        pg_client,
        embedding_service,
        openai_client: Optional[OpenAI] = None,
        openai_api_key: Optional[str] = None,
        similarity_threshold: float = 0.85,
        max_candidates: int = 5,
        model: str = "gpt-4o-mini"
    ):
        """
        Initialize entity resolution service.

        Args:
            pg_client: Postgres client instance (async)
            embedding_service: Service for generating embeddings
            openai_client: OpenAI client for LLM confirmation (optional if api_key provided)
            openai_api_key: OpenAI API key (used if openai_client not provided)
            similarity_threshold: Minimum similarity for candidates (default: 0.85)
            max_candidates: Maximum candidates to consider (default: 5)
            model: LLM model for confirmation (default: gpt-4o-mini)
        """
        self.pg = pg_client
        self.embedding_service = embedding_service
        self.openai_client = openai_client or OpenAI(api_key=openai_api_key, timeout=30)
        self.similarity_threshold = similarity_threshold
        self.max_candidates = max_candidates
        self.model = model

        # Track uncertain pairs to create POSSIBLY_SAME edges
        self._uncertain_pairs: List[Tuple[UUID, UUID, float, str]] = []

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
        end_char: Optional[int] = None,
        doc_title: Optional[str] = None
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
            doc_title: Document title for LLM context

        Returns:
            EntityResolutionResult with resolved entity_id and status

        Raises:
            EntityResolutionError: If resolution fails critically
        """
        aliases_in_doc = aliases_in_doc or []
        normalized_name = self._normalize_name(canonical_suggestion)

        logger.info(f"Resolving entity: '{surface_form}' -> '{canonical_suggestion}' ({entity_type})")

        try:
            # Step 1: Check for exact normalized name match
            existing = await self._find_exact_match(entity_type, normalized_name)

            if existing:
                logger.info(f"Found exact match: {existing.entity_id}")
                # Record mention and return
                await self.record_mention(
                    entity_id=existing.entity_id,
                    artifact_uid=artifact_uid,
                    revision_id=revision_id,
                    surface_form=surface_form,
                    start_char=start_char,
                    end_char=end_char
                )
                return EntityResolutionResult(
                    entity_id=existing.entity_id,
                    is_new=False,
                    merged_from=existing.entity_id,
                    canonical_name=existing.canonical_name
                )

            # Step 2: Generate context embedding
            context_embedding = await self.generate_context_embedding(
                canonical_name=canonical_suggestion,
                entity_type=entity_type,
                role=context_clues.role,
                organization=context_clues.organization
            )

            # Step 3: Find dedup candidates
            candidates = await self.find_dedup_candidates(
                entity_type=entity_type,
                context_embedding=context_embedding
            )

            result: EntityResolutionResult

            if not candidates:
                # No candidates - create new entity
                entity_id = await self.create_entity(
                    canonical_name=canonical_suggestion,
                    normalized_name=normalized_name,
                    entity_type=entity_type,
                    context_clues=context_clues,
                    context_embedding=context_embedding,
                    artifact_uid=artifact_uid,
                    revision_id=revision_id
                )

                result = EntityResolutionResult(
                    entity_id=entity_id,
                    is_new=True,
                    canonical_name=canonical_suggestion
                )

            else:
                # Step 4: LLM confirmation for each candidate
                merge_decision = await self._evaluate_candidates(
                    new_name=canonical_suggestion,
                    new_type=entity_type,
                    new_context=context_clues,
                    candidates=candidates,
                    doc_title=doc_title or artifact_uid
                )

                if merge_decision and merge_decision.decision == "same":
                    # Merge with existing entity
                    best_candidate = candidates[0]
                    await self.merge_entity(
                        new_surface_form=surface_form,
                        existing_entity_id=best_candidate.entity_id,
                        new_canonical_name=merge_decision.canonical_name
                    )

                    # Add alias if surface form differs from canonical
                    if self._normalize_name(surface_form) != best_candidate.normalized_name:
                        await self.add_alias(best_candidate.entity_id, surface_form)

                    result = EntityResolutionResult(
                        entity_id=best_candidate.entity_id,
                        is_new=False,
                        merged_from=best_candidate.entity_id,
                        canonical_name=merge_decision.canonical_name
                    )

                elif merge_decision and merge_decision.decision == "uncertain":
                    # Create new entity but flag for review
                    entity_id = await self.create_entity(
                        canonical_name=canonical_suggestion,
                        normalized_name=normalized_name,
                        entity_type=entity_type,
                        context_clues=context_clues,
                        context_embedding=context_embedding,
                        artifact_uid=artifact_uid,
                        revision_id=revision_id,
                        needs_review=True
                    )

                    # Track uncertain pair for POSSIBLY_SAME edge
                    best_candidate = candidates[0]
                    self._uncertain_pairs.append((
                        entity_id,
                        best_candidate.entity_id,
                        self.similarity_threshold,  # Use threshold as confidence
                        merge_decision.reason
                    ))

                    result = EntityResolutionResult(
                        entity_id=entity_id,
                        is_new=True,
                        uncertain_match=best_candidate.entity_id,
                        canonical_name=canonical_suggestion
                    )

                else:
                    # Different - create new entity
                    entity_id = await self.create_entity(
                        canonical_name=canonical_suggestion,
                        normalized_name=normalized_name,
                        entity_type=entity_type,
                        context_clues=context_clues,
                        context_embedding=context_embedding,
                        artifact_uid=artifact_uid,
                        revision_id=revision_id
                    )

                    result = EntityResolutionResult(
                        entity_id=entity_id,
                        is_new=True,
                        canonical_name=canonical_suggestion
                    )

            # Record mention
            await self.record_mention(
                entity_id=result.entity_id,
                artifact_uid=artifact_uid,
                revision_id=revision_id,
                surface_form=surface_form,
                start_char=start_char,
                end_char=end_char
            )

            # Add aliases from document
            for alias in aliases_in_doc:
                if self._normalize_name(alias) != self._normalize_name(result.canonical_name):
                    await self.add_alias(result.entity_id, alias)

            logger.info(f"Entity resolved: {result.entity_id} (new={result.is_new})")
            return result

        except Exception as e:
            logger.error(f"Entity resolution failed: {e}", exc_info=True)
            raise EntityResolutionError(f"Failed to resolve entity '{surface_form}': {e}")

    async def resolve_extracted_entity(
        self,
        extracted: ExtractedEntity,
        artifact_uid: str,
        revision_id: str,
        doc_title: Optional[str] = None
    ) -> EntityResolutionResult:
        """
        Convenience method to resolve an ExtractedEntity.

        Args:
            extracted: Entity extracted from LLM
            artifact_uid: Document identifier
            revision_id: Document version
            doc_title: Document title for context

        Returns:
            EntityResolutionResult
        """
        return await self.resolve_entity(
            surface_form=extracted.surface_form,
            canonical_suggestion=extracted.canonical_suggestion,
            entity_type=extracted.entity_type,
            context_clues=extracted.context_clues,
            artifact_uid=artifact_uid,
            revision_id=revision_id,
            aliases_in_doc=extracted.aliases_in_doc,
            start_char=extracted.start_char,
            end_char=extracted.end_char,
            doc_title=doc_title
        )

    def get_uncertain_pairs(self) -> List[Tuple[UUID, UUID, float, str]]:
        """
        Get uncertain entity pairs for POSSIBLY_SAME edges.

        Returns:
            List of (entity_id_a, entity_id_b, confidence, reason) tuples
        """
        pairs = self._uncertain_pairs.copy()
        self._uncertain_pairs.clear()
        return pairs

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
        # Build context string
        parts = [canonical_name, entity_type]
        if role:
            parts.append(role)
        if organization:
            parts.append(organization)

        context_text = ", ".join(parts)

        try:
            embedding = self.embedding_service.generate_embedding(context_text)
            return embedding
        except Exception as e:
            logger.error(f"Failed to generate context embedding: {e}")
            raise EmbeddingGenerationError(f"Embedding generation failed: {e}")

    async def find_dedup_candidates(
        self,
        entity_type: str,
        context_embedding: List[float],
        threshold: Optional[float] = None
    ) -> List[Entity]:
        """
        Find candidate entities for deduplication using embedding similarity.

        Uses cosine distance: 1 - cosine_similarity
        So threshold of 0.85 means distance < 0.15

        Args:
            entity_type: Only match entities of same type
            context_embedding: Query embedding vector
            threshold: Similarity threshold (default: self.similarity_threshold)

        Returns:
            List of candidate Entity objects, ordered by similarity
        """
        threshold = threshold or self.similarity_threshold
        distance_threshold = 1 - threshold  # Convert similarity to distance

        try:
            # pgvector uses <=> for cosine distance
            query = """
            SELECT entity_id, entity_type, canonical_name, normalized_name,
                   role, organization, email,
                   first_seen_artifact_uid, first_seen_revision_id, needs_review,
                   (context_embedding <=> $1::vector) AS distance
            FROM entity
            WHERE entity_type = $2
              AND context_embedding IS NOT NULL
              AND (context_embedding <=> $1::vector) < $3
            ORDER BY context_embedding <=> $1::vector
            LIMIT $4
            """

            # Convert embedding to string format for pgvector
            embedding_str = "[" + ",".join(str(x) for x in context_embedding) + "]"

            rows = await self.pg.fetch_all(
                query,
                embedding_str,
                entity_type,
                distance_threshold,
                self.max_candidates
            )

            candidates = []
            for row in rows:
                candidates.append(Entity(
                    entity_id=row["entity_id"],
                    entity_type=row["entity_type"],
                    canonical_name=row["canonical_name"],
                    normalized_name=row["normalized_name"],
                    role=row.get("role"),
                    organization=row.get("organization"),
                    email=row.get("email"),
                    first_seen_artifact_uid=row["first_seen_artifact_uid"],
                    first_seen_revision_id=row["first_seen_revision_id"],
                    needs_review=row.get("needs_review", False)
                ))

            logger.info(f"Found {len(candidates)} dedup candidates for {entity_type}")
            return candidates

        except Exception as e:
            logger.error(f"Failed to find dedup candidates: {e}")
            raise DedupCandidateError(f"Candidate search failed: {e}")

    async def confirm_merge_with_llm(
        self,
        entity_a_name: str,
        entity_a_type: str,
        entity_a_context: ContextClues,
        entity_b_name: str,
        entity_b_type: str,
        entity_b_context: ContextClues,
        doc_title_a: str,
        doc_title_b: str
    ) -> MergeDecision:
        """
        Call LLM to confirm whether two entities are the same.

        Args:
            entity_a_name: New entity name
            entity_a_type: New entity type
            entity_a_context: Context clues for entity A
            entity_b_name: Existing entity name
            entity_b_type: Existing entity type
            entity_b_context: Context clues for entity B
            doc_title_a: Document title for A
            doc_title_b: Document title for B

        Returns:
            MergeDecision with decision, canonical_name, and reason
        """
        # Format context strings
        def format_context(ctx: ContextClues) -> str:
            parts = []
            if ctx.role:
                parts.append(f"Role: {ctx.role}")
            if ctx.organization:
                parts.append(f"Organization: {ctx.organization}")
            if ctx.email:
                parts.append(f"Email: {ctx.email}")
            return ", ".join(parts) if parts else "No additional context available"

        prompt = ENTITY_DEDUP_PROMPT.format(
            title_a=doc_title_a,
            name_a=entity_a_name,
            type_a=entity_a_type,
            context_a=format_context(entity_a_context),
            title_b=doc_title_b,
            name_b=entity_b_name,
            type_b=entity_b_type,
            context_b=format_context(entity_b_context)
        )

        try:
            response = self.openai_client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                response_format={"type": "json_object"},
                timeout=30
            )

            content = response.choices[0].message.content
            result = json.loads(content)

            decision = result.get("decision", "uncertain")
            if decision not in ["same", "different", "uncertain"]:
                decision = "uncertain"

            return MergeDecision(
                decision=decision,
                canonical_name=result.get("canonical_name", entity_a_name),
                reason=result.get("reason", "No reason provided")
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response: {e}")
            return MergeDecision(
                decision="uncertain",
                canonical_name=entity_a_name,
                reason="Failed to parse LLM response"
            )
        except Exception as e:
            logger.error(f"LLM confirmation failed: {e}")
            raise LLMConfirmationError(f"LLM confirmation failed: {e}")

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
        entity_id = uuid4()
        embedding_str = "[" + ",".join(str(x) for x in context_embedding) + "]"

        query = """
        INSERT INTO entity (
            entity_id, entity_type, canonical_name, normalized_name,
            role, organization, email, context_embedding,
            first_seen_artifact_uid, first_seen_revision_id, needs_review
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector, $9, $10, $11)
        RETURNING entity_id
        """

        result = await self.pg.fetch_val(
            query,
            entity_id,
            entity_type,
            canonical_name,
            normalized_name,
            context_clues.role,
            context_clues.organization,
            context_clues.email,
            embedding_str,
            artifact_uid,
            revision_id,
            needs_review
        )

        logger.info(f"Created entity: {entity_id} ({canonical_name})")
        return result or entity_id

    async def merge_entity(
        self,
        new_surface_form: str,
        existing_entity_id: UUID,
        new_canonical_name: Optional[str] = None
    ) -> UUID:
        """
        Merge a mention into an existing entity.

        If new_canonical_name provided and more complete, updates the entity.

        Args:
            new_surface_form: Surface form being merged
            existing_entity_id: Target entity
            new_canonical_name: Optional updated canonical name

        Returns:
            existing_entity_id (unchanged)
        """
        if new_canonical_name:
            # Check if new name is more complete (longer)
            current = await self.pg.fetch_one(
                "SELECT canonical_name FROM entity WHERE entity_id = $1",
                existing_entity_id
            )

            if current and len(new_canonical_name) > len(current["canonical_name"]):
                await self.pg.execute(
                    """
                    UPDATE entity
                    SET canonical_name = $1, normalized_name = $2
                    WHERE entity_id = $3
                    """,
                    new_canonical_name,
                    self._normalize_name(new_canonical_name),
                    existing_entity_id
                )
                logger.info(f"Updated entity {existing_entity_id} canonical name to '{new_canonical_name}'")

        return existing_entity_id

    async def add_alias(
        self,
        entity_id: UUID,
        alias: str
    ) -> None:
        """
        Add an alias to an entity (idempotent).

        Args:
            entity_id: Entity to add alias to
            alias: New alias text
        """
        normalized_alias = self._normalize_name(alias)

        query = """
        INSERT INTO entity_alias (entity_id, alias, normalized_alias)
        VALUES ($1, $2, $3)
        ON CONFLICT (entity_id, normalized_alias) DO NOTHING
        """

        await self.pg.execute(query, entity_id, alias, normalized_alias)
        logger.debug(f"Added alias '{alias}' to entity {entity_id}")

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
        mention_id = uuid4()

        query = """
        INSERT INTO entity_mention (
            mention_id, entity_id, artifact_uid, revision_id,
            surface_form, start_char, end_char
        ) VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING mention_id
        """

        await self.pg.execute(
            query,
            mention_id,
            entity_id,
            artifact_uid,
            revision_id,
            surface_form,
            start_char,
            end_char
        )

        return mention_id

    async def _find_exact_match(self, entity_type: str, normalized_name: str) -> Optional[Entity]:
        """Find entity by exact normalized name match."""
        query = """
        SELECT entity_id, entity_type, canonical_name, normalized_name,
               role, organization, email,
               first_seen_artifact_uid, first_seen_revision_id, needs_review
        FROM entity
        WHERE entity_type = $1 AND normalized_name = $2
        LIMIT 1
        """

        row = await self.pg.fetch_one(query, entity_type, normalized_name)

        if row:
            return Entity(
                entity_id=row["entity_id"],
                entity_type=row["entity_type"],
                canonical_name=row["canonical_name"],
                normalized_name=row["normalized_name"],
                role=row.get("role"),
                organization=row.get("organization"),
                email=row.get("email"),
                first_seen_artifact_uid=row["first_seen_artifact_uid"],
                first_seen_revision_id=row["first_seen_revision_id"],
                needs_review=row.get("needs_review", False)
            )
        return None

    async def _evaluate_candidates(
        self,
        new_name: str,
        new_type: str,
        new_context: ContextClues,
        candidates: List[Entity],
        doc_title: str
    ) -> Optional[MergeDecision]:
        """
        Evaluate candidates using LLM confirmation.

        Returns the best merge decision, or None if no good match.
        """
        if not candidates:
            return None

        # For now, just check the top candidate
        # Could be extended to check multiple candidates
        best_candidate = candidates[0]

        existing_context = ContextClues(
            role=best_candidate.role,
            organization=best_candidate.organization,
            email=best_candidate.email
        )

        try:
            decision = await self.confirm_merge_with_llm(
                entity_a_name=new_name,
                entity_a_type=new_type,
                entity_a_context=new_context,
                entity_b_name=best_candidate.canonical_name,
                entity_b_type=best_candidate.entity_type,
                entity_b_context=existing_context,
                doc_title_a=doc_title,
                doc_title_b=best_candidate.first_seen_artifact_uid
            )

            return decision

        except LLMConfirmationError:
            # On LLM failure, be conservative and create separate entity
            return MergeDecision(
                decision="uncertain",
                canonical_name=new_name,
                reason="LLM confirmation failed, creating separate entity for safety"
            )

    def _normalize_name(self, name: str) -> str:
        """Normalize entity name for matching."""
        # Lowercase
        normalized = name.lower()
        # Remove extra whitespace
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return normalized
