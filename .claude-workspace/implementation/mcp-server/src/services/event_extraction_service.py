"""
Event extraction service using OpenAI LLM with two-phase extraction:
- Prompt A: Extract events AND entities from each chunk (V4 extended)
- Prompt B: Canonicalize and deduplicate events across chunks

V4 additions:
- entities_mentioned extraction with context clues (role, org, email)
- Character offsets for entity mentions
- Aliases within document
"""

import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from openai import OpenAI

logger = logging.getLogger("event_extraction")


# V7.3: Dynamic categories - common examples for prompt guidance only
# These are NOT enforced - LLM can suggest any category
EVENT_CATEGORY_EXAMPLES = [
    "Commitment",
    "Execution",
    "Decision",
    "Collaboration",
    "QualityRisk",
    "Feedback",
    "Change",
    "Stakeholder",
    # Additional categories the LLM may suggest:
    "Meeting",
    "Insight",
    "Goal",
    "Milestone",
    "Risk",
    "Learning",
    "Question",
    "Transaction"
]

# Entity types (V4)
ENTITY_TYPES = [
    "person",
    "org",
    "project",
    "object",
    "place",
    "other"
]


# Prompt A: Extract events AND entities from a single chunk (V4 extended, V7.3 dynamic categories)
PROMPT_A_SYSTEM = """You are an expert at extracting structured semantic events and entities from text artifacts.

Your task is to identify and extract key events AND entities from the provided text chunk.

## EVENTS

Suggest an appropriate category for each event that best describes its type. Use concise, singular nouns.

Common categories include (but are not limited to):
- **Commitment**: Promises, deadlines, deliverables (e.g., "Alice will deliver MVP by Q1")
- **Execution**: Actions taken, completions (e.g., "Deployed v2.3 to production")
- **Decision**: Choices made, directions set (e.g., "Decided to use Postgres over Kafka")
- **Collaboration**: Meetings, discussions, handoffs (e.g., "Engineering and design synced on UI")
- **QualityRisk**: Issues, blockers, concerns (e.g., "Security audit found XSS vulnerability")
- **Feedback**: User input, reviews, critiques (e.g., "Users reported login flow is confusing")
- **Change**: Modifications, pivots, updates (e.g., "Changed pricing from $99 to $149")
- **Stakeholder**: Who's involved, roles (e.g., "Added Bob as security reviewer")
- **Meeting**: Scheduled gatherings, syncs, standups
- **Insight**: Discoveries, learnings, realizations
- **Goal**: Objectives, targets, desired outcomes
- **Milestone**: Project markers, completions, achievements
- **Risk**: Concerns, potential issues, warnings
- **Transaction**: Purchases, payments, contracts
- **Question**: Open queries, unknowns to investigate

You may suggest new categories if none of the above fit well. Use singular nouns (e.g., "Decision" not "Decisions").

For each event, extract:
- **category**: A concise singular noun describing the event type (see examples above, or suggest your own)
- **narrative**: 1-2 sentence summary of what happened
- **event_time**: ISO8601 timestamp if mentioned, otherwise null
- **subject**: What the event is about ({"type": "person|project|object|other", "ref": "name"})
- **actors**: Who was involved ([{"ref": "name", "role": "owner|contributor|stakeholder"}])
- **confidence**: 0.0-1.0 confidence score
- **evidence**: List of exact quotes from the text (max 25 words each) with character offsets

## ENTITIES (V4)

Also extract all named entities mentioned in the text:
- **People**: Names of individuals mentioned
- **Organizations**: Companies, teams, departments
- **Projects**: Named projects, products, initiatives
- **Objects**: Specific tools, systems, technologies
- **Places**: Locations mentioned
- **Other**: Any other significant named entities

For each entity, extract:
- **surface_form**: Exact text as it appeared in the document
- **canonical_suggestion**: Your best guess at the full/formal name
- **type**: One of [person, org, project, object, place, other]
- **context_clues**: Any disambiguating information found:
  - **role**: Job title or role if mentioned (e.g., "Engineering Manager")
  - **org**: Organization affiliation if mentioned (e.g., "Acme Corp")
  - **email**: Email address if mentioned
- **aliases_in_doc**: Other ways this entity is referred to in this chunk (e.g., ["Alice", "A.C."])
- **confidence**: 0.0-1.0
- **start_char**: Starting character offset in this chunk
- **end_char**: Ending character offset in this chunk

Return JSON with this structure:
{
  "events": [
    {
      "category": "Decision",
      "narrative": "Team decided to adopt freemium pricing model",
      "event_time": "2024-03-15T14:30:00Z",
      "subject": {"type": "project", "ref": "pricing-model"},
      "actors": [{"ref": "Alice Chen", "role": "owner"}],
      "confidence": 0.95,
      "evidence": [
        {
          "quote": "we're going with freemium for launch",
          "start_char": 1250,
          "end_char": 1290
        }
      ]
    }
  ],
  "entities_mentioned": [
    {
      "surface_form": "Alice Chen",
      "canonical_suggestion": "Alice Chen",
      "type": "person",
      "context_clues": {
        "role": "Engineering Manager",
        "org": "Acme Corp",
        "email": "achen@acme.com"
      },
      "aliases_in_doc": ["Alice", "A. Chen"],
      "confidence": 0.95,
      "start_char": 150,
      "end_char": 160
    }
  ]
}
"""


PROMPT_A_USER_TEMPLATE = """Extract semantic events AND named entities from the following text chunk:

Chunk Index: {chunk_index}
Chunk ID: {chunk_id}
Start Character: {start_char}

Text:
---
{text}
---

Return events as JSON with the structure described in the system prompt.
"""


# Prompt B: Canonicalize events across all chunks
PROMPT_B_SYSTEM = """You are an expert at deduplicating and merging semantic events extracted from multiple text chunks.

Your task is to take events extracted from individual chunks and:
1. **Deduplicate**: Merge events that refer to the same real-world event
2. **Merge evidence**: Combine evidence spans from multiple chunks
3. **Resolve entities**: Map entity aliases to canonical names (e.g., "Alice" and "Alice Chen" → "Alice Chen")
4. **Preserve precision**: Keep character offsets and chunk IDs accurate

Return the canonical list of events with merged evidence in the same JSON structure as the input.

Rules:
- Events are the same if they have identical category, subject, and narrative (modulo minor wording)
- When merging, prefer the highest confidence score
- Preserve all evidence spans from all chunks
- If event_time differs between chunks, prefer the more specific timestamp
"""


PROMPT_B_USER_TEMPLATE = """Here are events extracted from {num_chunks} chunks of the same artifact:

{events_json}

Deduplicate and merge these events, returning the canonical list with all evidence preserved.
"""


class EventExtractionService:
    """Service for extracting semantic events from artifact text using OpenAI."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        temperature: float = 0.0,
        timeout: int = 60
    ):
        """
        Initialize event extraction service.

        Args:
            api_key: OpenAI API key
            model: Model to use (gpt-4o-mini, gpt-4-turbo-preview, etc.)
            temperature: Temperature for generation (0.0 = deterministic)
            timeout: Request timeout in seconds
        """
        self.client = OpenAI(api_key=api_key, timeout=timeout)
        self.model = model
        self.temperature = temperature
        self.timeout = timeout  # Store for per-request override if needed

    def extract_from_chunk(
        self,
        chunk_text: str,
        chunk_index: int,
        chunk_id: str,
        start_char: int
    ) -> List[Dict[str, Any]]:
        """
        Extract events from a single chunk using Prompt A (V3 compatible).

        Args:
            chunk_text: Text content of the chunk
            chunk_index: Index of this chunk
            chunk_id: Chunk ID (for evidence tracking)
            start_char: Starting character offset in original artifact

        Returns:
            List of extracted events
        """
        events, _ = self.extract_from_chunk_v4(chunk_text, chunk_index, chunk_id, start_char)
        return events

    def extract_from_chunk_v4(
        self,
        chunk_text: str,
        chunk_index: int,
        chunk_id: str,
        start_char: int
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Extract events AND entities from a single chunk using Prompt A (V4 extended).

        Args:
            chunk_text: Text content of the chunk
            chunk_index: Index of this chunk
            chunk_id: Chunk ID (for evidence tracking)
            start_char: Starting character offset in original artifact

        Returns:
            Tuple of (events, entities_mentioned)
        """
        user_prompt = PROMPT_A_USER_TEMPLATE.format(
            chunk_index=chunk_index,
            chunk_id=chunk_id,
            start_char=start_char,
            text=chunk_text
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": PROMPT_A_SYSTEM},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=self.temperature,
                response_format={"type": "json_object"},
                timeout=self.timeout
            )

            content = response.choices[0].message.content
            result = json.loads(content)

            events = result.get("events", [])
            entities = result.get("entities_mentioned", [])

            # Adjust character offsets to be relative to full artifact
            for event in events:
                if "evidence" in event:
                    for ev in event["evidence"]:
                        ev["start_char"] += start_char
                        ev["end_char"] += start_char
                        ev["chunk_id"] = chunk_id

            # Adjust entity character offsets
            for entity in entities:
                if entity.get("start_char") is not None:
                    entity["start_char"] += start_char
                if entity.get("end_char") is not None:
                    entity["end_char"] += start_char
                entity["chunk_id"] = chunk_id

            logger.info(f"Extracted {len(events)} events and {len(entities)} entities from chunk {chunk_index}")
            return events, entities

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from Prompt A: {e}")
            logger.error(f"Raw response: {content}")
            return [], []
        except Exception as e:
            logger.error(f"Error in extract_from_chunk_v4: {e}")
            raise

    def canonicalize_events(
        self,
        chunk_events: List[List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """
        Canonicalize events across chunks using Prompt B.

        Args:
            chunk_events: List of event lists (one per chunk)

        Returns:
            Canonical list of deduplicated events with merged evidence
        """
        # Flatten all events
        all_events = []
        for chunk_idx, events in enumerate(chunk_events):
            for event in events:
                all_events.append(event)

        if not all_events:
            return []

        events_json = json.dumps(all_events, indent=2)
        user_prompt = PROMPT_B_USER_TEMPLATE.format(
            num_chunks=len(chunk_events),
            events_json=events_json
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": PROMPT_B_SYSTEM},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=self.temperature,
                response_format={"type": "json_object"},
                timeout=self.timeout
            )

            content = response.choices[0].message.content
            result = json.loads(content)

            canonical_events = result.get("events", [])

            logger.info(f"Canonicalized {len(all_events)} events → {len(canonical_events)} unique events")
            return canonical_events

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from Prompt B: {e}")
            logger.error(f"Raw response: {content}")
            # Fallback: return all events without deduplication
            return all_events
        except Exception as e:
            logger.error(f"Error in canonicalize_events: {e}")
            raise

    def validate_event(self, event: Dict[str, Any]) -> bool:
        """
        Validate extracted event structure.

        Args:
            event: Event dict to validate

        Returns:
            True if valid, False otherwise
        """
        required_fields = ["category", "narrative", "subject", "actors", "confidence", "evidence"]

        for field in required_fields:
            if field not in event:
                logger.warning(f"Event missing required field: {field}")
                return False

        # V7.3: Accept any category (dynamic categories)
        # Just validate it's a non-empty string
        category = event.get("category", "")
        if not category or not isinstance(category, str) or len(category.strip()) == 0:
            logger.warning(f"Invalid or empty category: {category}")
            return False
        # Normalize to singular form and capitalize
        event["category"] = category.strip().rstrip("s").capitalize() if category.endswith("s") and len(category) > 3 else category.strip().capitalize()

        # Validate confidence
        if not (0.0 <= event["confidence"] <= 1.0):
            logger.warning(f"Invalid confidence: {event['confidence']}")
            return False

        # Validate subject structure
        subject = event.get("subject", {})
        if not isinstance(subject, dict) or "type" not in subject or "ref" not in subject:
            logger.warning(f"Invalid subject structure: {subject}")
            return False

        # Validate actors structure
        actors = event.get("actors", [])
        if not isinstance(actors, list):
            logger.warning(f"Invalid actors structure: {actors}")
            return False

        for actor in actors:
            if not isinstance(actor, dict) or "ref" not in actor or "role" not in actor:
                logger.warning(f"Invalid actor structure: {actor}")
                return False

        # Validate evidence
        evidence = event.get("evidence", [])
        if not isinstance(evidence, list) or len(evidence) == 0:
            logger.warning(f"Invalid or empty evidence: {evidence}")
            return False

        for ev in evidence:
            if not isinstance(ev, dict):
                return False
            if "quote" not in ev or "start_char" not in ev or "end_char" not in ev:
                return False
            if ev["end_char"] <= ev["start_char"]:
                return False

        return True

    def validate_entity(self, entity: Dict[str, Any]) -> bool:
        """
        Validate extracted entity structure (V4).

        Args:
            entity: Entity dict to validate

        Returns:
            True if valid, False otherwise
        """
        required_fields = ["surface_form", "type"]

        for field in required_fields:
            if field not in entity:
                logger.warning(f"Entity missing required field: {field}")
                return False

        # Validate entity type
        entity_type = entity.get("type", "other")
        if entity_type not in ENTITY_TYPES:
            logger.warning(f"Invalid entity type: {entity_type}, defaulting to 'other'")
            entity["type"] = "other"

        # Validate confidence if present
        if "confidence" in entity:
            try:
                conf = float(entity["confidence"])
                if not (0.0 <= conf <= 1.0):
                    entity["confidence"] = 0.9
            except (ValueError, TypeError):
                entity["confidence"] = 0.9

        # Ensure canonical_suggestion exists
        if not entity.get("canonical_suggestion"):
            entity["canonical_suggestion"] = entity["surface_form"]

        # Validate context_clues structure
        context = entity.get("context_clues", {})
        if not isinstance(context, dict):
            entity["context_clues"] = {}

        return True

    def deduplicate_entities(
        self,
        chunk_entities: List[List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """
        Deduplicate entities across chunks (V4).

        Entities are considered duplicates if they have the same
        normalized canonical_suggestion and type.

        Args:
            chunk_entities: List of entity lists (one per chunk)

        Returns:
            Deduplicated list of entities with merged aliases
        """
        # Build a map of canonical_key -> merged entity
        entity_map: Dict[str, Dict[str, Any]] = {}

        for entities in chunk_entities:
            for entity in entities:
                if not self.validate_entity(entity):
                    continue

                # Create canonical key from normalized name + type
                canonical = entity.get("canonical_suggestion", entity["surface_form"])
                entity_type = entity.get("type", "other")
                key = f"{canonical.lower().strip()}:{entity_type}"

                if key not in entity_map:
                    # First occurrence - use as base
                    entity_map[key] = {
                        "surface_form": entity["surface_form"],
                        "canonical_suggestion": canonical,
                        "type": entity_type,
                        "context_clues": entity.get("context_clues", {}),
                        "aliases_in_doc": list(entity.get("aliases_in_doc", [])),
                        "confidence": entity.get("confidence", 0.9),
                        "start_char": entity.get("start_char"),
                        "end_char": entity.get("end_char"),
                        "mentions": [entity]  # Track all mentions
                    }
                else:
                    # Merge with existing
                    existing = entity_map[key]

                    # Merge aliases
                    new_aliases = entity.get("aliases_in_doc", [])
                    for alias in new_aliases:
                        if alias not in existing["aliases_in_doc"]:
                            existing["aliases_in_doc"].append(alias)

                    # Add surface form as alias if different
                    if entity["surface_form"] != existing["surface_form"]:
                        if entity["surface_form"] not in existing["aliases_in_doc"]:
                            existing["aliases_in_doc"].append(entity["surface_form"])

                    # Merge context clues (keep non-null values)
                    new_context = entity.get("context_clues", {})
                    for ctx_key in ["role", "org", "organization", "email"]:
                        if new_context.get(ctx_key) and not existing["context_clues"].get(ctx_key):
                            existing["context_clues"][ctx_key] = new_context[ctx_key]

                    # Keep highest confidence
                    new_conf = entity.get("confidence", 0.9)
                    if new_conf > existing["confidence"]:
                        existing["confidence"] = new_conf

                    # Track mention
                    existing["mentions"].append(entity)

        # Return deduplicated list
        result = []
        for entity in entity_map.values():
            # Remove internal mentions tracking
            entity.pop("mentions", None)
            result.append(entity)

        logger.info(f"Deduplicated entities: {sum(len(e) for e in chunk_entities)} -> {len(result)}")
        return result
