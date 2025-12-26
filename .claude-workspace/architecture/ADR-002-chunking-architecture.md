# ADR-002: Token-Window Chunking Architecture

**Status:** Accepted
**Date:** 2025-12-25
**Author:** Senior Architect
**Relates to:** v2.0 Artifact Ingestion

---

## Context

### Problem Statement

v2.0 introduces **artifact ingestion** for storing large documents (emails, PDFs, chat logs) that may exceed reasonable embedding sizes. Challenges:

1. **Token Limits**: OpenAI embeddings work best on focused text (≤512 tokens recommended)
2. **Context Window**: Large docs (10MB+) may contain 100K+ tokens
3. **Retrieval Quality**: Embedding an entire document loses specificity
4. **Search Precision**: Relevant content may be buried in a 50-page doc

### Requirements

1. **Threshold-based chunking**: Small docs (≤1200 tokens) stored whole, large docs chunked
2. **Deterministic IDs**: Same input produces same chunk IDs (idempotency)
3. **Overlap for continuity**: Chunks overlap to preserve context across boundaries
4. **Character offsets**: Track where chunks appear in original document
5. **Neighbor expansion**: Retrieve ±1 adjacent chunks for broader context
6. **Two-phase atomic writes**: Generate all embeddings first, then write to DB

### Key Constraints

- **Token counting**: Use tiktoken `cl100k_base` (same as GPT-4)
- **Chunk size**: Target 900 tokens per chunk (sweet spot for embedding quality)
- **Overlap**: 100 tokens (balances context vs redundancy)
- **Storage efficiency**: Minimize duplicate content from overlap
- **Query latency**: Fast chunk lookup by artifact_id + chunk_index

---

## Decision

We will implement a **token-window chunking strategy** with the following design:

### Chunking Thresholds

| Artifact Size | Strategy | Storage |
|---------------|----------|---------|
| ≤1200 tokens | No chunking | `artifacts` collection (full content + embedding) |
| >1200 tokens | Token-window chunking | `artifacts` (metadata only) + `artifact_chunks` (chunks + embeddings) |

**Rationale for 1200 token threshold:**
- Typical email/note: 300-1000 tokens (no chunking needed)
- Typical doc/meeting minutes: 2000-5000 tokens (needs chunking)
- Sweet spot: Avoids overhead for most small artifacts

### Token-Window Algorithm

```
Input: text (string), artifact_id (string)
Output: List[Chunk]

1. Tokenize text using tiktoken cl100k_base encoding
2. If tokens ≤ SINGLE_PIECE_MAX (1200):
     Return empty list (no chunking needed)
3. Else:
     chunks = []
     pos = 0
     chunk_index = 0

     while pos < len(tokens):
         # Extract chunk window
         chunk_tokens = tokens[pos : pos + CHUNK_TARGET (900)]
         chunk_text = decode(chunk_tokens)

         # Compute character offsets
         start_char = len(decode(tokens[:pos]))
         end_char = start_char + len(chunk_text)

         # Generate stable chunk ID
         content_hash = sha256(chunk_text).hexdigest()
         chunk_id = f"{artifact_id}::chunk::{chunk_index:03d}::{content_hash[:8]}"

         # Create chunk
         chunks.append(Chunk(
             chunk_id=chunk_id,
             artifact_id=artifact_id,
             chunk_index=chunk_index,
             content=chunk_text,
             start_char=start_char,
             end_char=end_char,
             token_count=len(chunk_tokens),
             content_hash=content_hash
         ))

         # Advance with overlap
         pos += CHUNK_TARGET - CHUNK_OVERLAP (900 - 100 = 800)
         chunk_index += 1

     return chunks
```

### Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  artifact_ingest Tool                                   │
└───────────────────┬─────────────────────────────────────┘
                    │ calls
                    ▼
┌─────────────────────────────────────────────────────────┐
│  ChunkingService                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │  should_chunk(text) -> (bool, token_count)       │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  chunk_text(text, artifact_id) -> List[Chunk]   │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  expand_chunk_neighbors(...) -> str              │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                    │ uses
                    ▼
┌─────────────────────────────────────────────────────────┐
│  tiktoken (cl100k_base encoding)                        │
└─────────────────────────────────────────────────────────┘
```

### Service Interface

```python
from dataclasses import dataclass
import tiktoken
import hashlib

@dataclass
class Chunk:
    """Represents a single chunk of an artifact."""
    chunk_id: str                # art_xxx::chunk::003::c0ffee12
    artifact_id: str             # art_xxx
    chunk_index: int             # 0, 1, 2, ...
    content: str                 # Chunk text
    start_char: int              # Character offset in original text
    end_char: int                # End character offset
    token_count: int             # Number of tokens in chunk
    content_hash: str            # SHA256 of content


class ChunkingService:
    """Token-window chunking for large artifacts."""

    def __init__(
        self,
        single_piece_max: int = 1200,
        chunk_target: int = 900,
        chunk_overlap: int = 100
    ):
        """
        Initialize chunking service.

        Args:
            single_piece_max: Threshold for chunking (tokens)
            chunk_target: Target chunk size (tokens)
            chunk_overlap: Overlap between chunks (tokens)
        """
        self.single_piece_max = single_piece_max
        self.chunk_target = chunk_target
        self.chunk_overlap = chunk_overlap
        self.encoding = tiktoken.get_encoding("cl100k_base")
        self.logger = logging.getLogger("ChunkingService")

    def should_chunk(self, text: str) -> tuple[bool, int]:
        """
        Determine if text needs chunking.

        Args:
            text: Text to evaluate

        Returns:
            (should_chunk, token_count)
        """
        tokens = self.encoding.encode(text)
        token_count = len(tokens)
        should_chunk = token_count > self.single_piece_max

        self.logger.debug(
            "chunk_decision",
            extra={
                "token_count": token_count,
                "threshold": self.single_piece_max,
                "will_chunk": should_chunk
            }
        )

        return should_chunk, token_count

    def chunk_text(self, text: str, artifact_id: str) -> list[Chunk]:
        """
        Chunk text using token-window strategy.

        Args:
            text: Text to chunk
            artifact_id: Parent artifact ID

        Returns:
            List of Chunk objects (empty if text ≤ threshold)
        """
        # Check if chunking needed
        should_chunk, token_count = self.should_chunk(text)
        if not should_chunk:
            return []

        # Tokenize
        tokens = self.encoding.encode(text)
        chunks = []
        pos = 0
        chunk_index = 0

        while pos < len(tokens):
            # Extract chunk tokens
            chunk_tokens = tokens[pos : pos + self.chunk_target]
            chunk_text = self.encoding.decode(chunk_tokens)

            # Compute character offsets
            start_char = len(self.encoding.decode(tokens[:pos]))
            end_char = start_char + len(chunk_text)

            # Generate stable chunk ID
            content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()
            chunk_id = f"{artifact_id}::chunk::{chunk_index:03d}::{content_hash[:8]}"

            # Create chunk
            chunk = Chunk(
                chunk_id=chunk_id,
                artifact_id=artifact_id,
                chunk_index=chunk_index,
                content=chunk_text,
                start_char=start_char,
                end_char=end_char,
                token_count=len(chunk_tokens),
                content_hash=content_hash
            )
            chunks.append(chunk)

            # Advance with overlap
            pos += self.chunk_target - self.chunk_overlap
            chunk_index += 1

        self.logger.info(
            "text_chunked",
            extra={
                "artifact_id": artifact_id,
                "total_tokens": token_count,
                "num_chunks": len(chunks),
                "avg_chunk_size": sum(c.token_count for c in chunks) / len(chunks),
                "overlap_tokens": self.chunk_overlap
            }
        )

        return chunks

    def expand_chunk_neighbors(
        self,
        artifact_id: str,
        chunk_index: int,
        all_chunks: list[Chunk]
    ) -> str:
        """
        Get chunk with ±1 neighbors and [CHUNK BOUNDARY] markers.

        Args:
            artifact_id: Artifact ID
            chunk_index: Index of target chunk
            all_chunks: All chunks for artifact (sorted by chunk_index)

        Returns:
            Combined text with [CHUNK BOUNDARY] markers
        """
        if not all_chunks:
            return ""

        # Find target chunk
        target = None
        for chunk in all_chunks:
            if chunk.chunk_index == chunk_index:
                target = chunk
                break

        if target is None:
            self.logger.warning(f"Chunk index {chunk_index} not found")
            return ""

        # Find neighbors
        prev_chunk = None
        next_chunk = None

        if chunk_index > 0:
            prev_chunk = all_chunks[chunk_index - 1]

        if chunk_index < len(all_chunks) - 1:
            next_chunk = all_chunks[chunk_index + 1]

        # Build combined text
        parts = []

        if prev_chunk:
            parts.append(prev_chunk.content)
            parts.append("[CHUNK BOUNDARY]")

        parts.append(target.content)

        if next_chunk:
            parts.append("[CHUNK BOUNDARY]")
            parts.append(next_chunk.content)

        return "\n".join(parts)
```

### Storage Schema

#### artifacts Collection (Chunked Documents)

For chunked documents, store metadata only (no embedding):

```json
{
  "id": "art_9f2ca8b1",
  "content": "",
  "metadata": {
    "artifact_type": "doc",
    "source_system": "drive",
    "source_id": "1a2b3c4d",
    "title": "Q4 Release Plan",
    "token_count": 5400,
    "is_chunked": true,
    "num_chunks": 6,
    "content_hash": "sha256_of_full_content",
    "ts": "2025-12-25T10:30:00Z"
  }
}
```

#### artifact_chunks Collection

```json
{
  "id": "art_9f2ca8b1::chunk::003::c0ffee12",
  "content": "chunk text content...",
  "embedding": [0.123, -0.456, ...],  // 3072 dimensions
  "metadata": {
    "artifact_id": "art_9f2ca8b1",
    "chunk_index": 3,
    "start_char": 8421,
    "end_char": 11290,
    "token_count": 910,
    "content_hash": "sha256_of_chunk",
    "sensitivity": "normal",
    "ts": "2025-12-25T10:30:00Z"
  }
}
```

### Neighbor Expansion Example

Given a 6-chunk document, when chunk 3 is retrieved:

```
User request: expand_neighbors=True for chunk 3

ChunkingService.expand_chunk_neighbors(
    artifact_id="art_9f2ca8b1",
    chunk_index=3,
    all_chunks=[chunk_0, chunk_1, ..., chunk_5]
)

Returns:
"""
...end of chunk 2 discussing project timeline...
[CHUNK BOUNDARY]
The Q4 release milestones include: feature freeze on Oct 15,
code complete on Nov 1, and launch on Dec 1. Each milestone has
specific acceptance criteria...
[CHUNK BOUNDARY]
...start of chunk 4 discussing testing requirements...
"""
```

---

## Consequences

### Positive

1. **Retrieval Precision**: Search finds specific relevant sections, not entire documents
2. **Embedding Quality**: 900-token chunks are optimal size for semantic embeddings
3. **Scalability**: Can handle arbitrarily large documents (10MB+)
4. **Idempotency**: Deterministic chunk IDs enable safe re-ingestion
5. **Context Preservation**: 100-token overlap ensures continuity across boundaries
6. **Neighbor Expansion**: Can retrieve broader context when needed

### Negative

1. **Storage Overhead**: 100-token overlap means 11% redundancy (100/900)
2. **Complexity**: More code than storing whole documents
3. **Reconstruction Cost**: Getting full content requires fetching all chunks
4. **Index Growth**: Large corpus creates many chunk records
5. **Query Complexity**: Search must span both artifacts and artifact_chunks collections

### Trade-offs

| Aspect | Small Threshold (e.g., 600) | Large Threshold (e.g., 2000) | Chosen (1200) |
|--------|----------------------------|------------------------------|---------------|
| Chunking frequency | High (more overhead) | Low (simpler) | Balanced |
| Retrieval precision | Better (smaller pieces) | Worse (large docs) | Good |
| Storage efficiency | More redundancy | Less redundancy | Acceptable |
| Embedding quality | Excellent | Degraded | Good |

---

## Implementation Notes

### Configuration

```bash
SINGLE_PIECE_MAX_TOKENS=1200
CHUNK_TARGET_TOKENS=900
CHUNK_OVERLAP_TOKENS=100
```

### Integration with artifact_ingest

```python
@mcp.tool()
def artifact_ingest(artifact_type: str, source_system: str, content: str, ...) -> dict:
    """Ingest artifact with automatic chunking."""

    # 1. Compute content hash
    content_hash = hashlib.sha256(content.encode()).hexdigest()

    # 2. Generate artifact_id
    if source_id:
        artifact_id = "art_" + hashlib.sha256(
            f"{source_system}:{source_id}".encode()
        ).hexdigest()[:8]
    else:
        artifact_id = "art_" + content_hash[:8]

    # 3. Check for duplicate (implementation detail)
    # ...

    # 4. Decide: chunk or store whole
    should_chunk, token_count = chunking_service.should_chunk(content)

    if not should_chunk:
        # Store as single artifact
        embedding = embedding_service.generate_embedding(content)

        artifacts_collection.add(
            ids=[artifact_id],
            documents=[content],
            embeddings=[embedding],
            metadatas=[{
                "artifact_type": artifact_type,
                "source_system": source_system,
                "token_count": token_count,
                "is_chunked": False,
                "content_hash": content_hash,
                ...
            }]
        )

        return {
            "artifact_id": artifact_id,
            "is_chunked": False,
            "num_chunks": 0,
            "stored_ids": [artifact_id]
        }

    else:
        # Chunk and store
        chunks = chunking_service.chunk_text(content, artifact_id)

        # Two-phase atomic write (see ADR-004)
        # Phase 1: Generate ALL embeddings first
        embeddings = embedding_service.generate_embeddings_batch(
            [chunk.content for chunk in chunks]
        )

        # Phase 2: Write to DB (only if all embeddings succeeded)
        # Store artifact metadata (no embedding)
        artifacts_collection.add(
            ids=[artifact_id],
            documents=[""],  # Empty content
            metadatas=[{
                "artifact_type": artifact_type,
                "source_system": source_system,
                "token_count": token_count,
                "is_chunked": True,
                "num_chunks": len(chunks),
                "content_hash": content_hash,
                ...
            }]
        )

        # Store chunks with embeddings
        chunk_ids = []
        for chunk, embedding in zip(chunks, embeddings):
            artifact_chunks_collection.add(
                ids=[chunk.chunk_id],
                documents=[chunk.content],
                embeddings=[embedding],
                metadatas=[{
                    "artifact_id": artifact_id,
                    "chunk_index": chunk.chunk_index,
                    "start_char": chunk.start_char,
                    "end_char": chunk.end_char,
                    "token_count": chunk.token_count,
                    "content_hash": chunk.content_hash,
                    ...
                }]
            )
            chunk_ids.append(chunk.chunk_id)

        return {
            "artifact_id": artifact_id,
            "is_chunked": True,
            "num_chunks": len(chunks),
            "stored_ids": [artifact_id] + chunk_ids
        }
```

### Testing Strategy

1. **Boundary Tests**:
   - 1199 tokens (no chunking)
   - 1200 tokens (no chunking)
   - 1201 tokens (chunking triggered)

2. **Overlap Verification**:
   - Verify last 100 tokens of chunk N appear in first 100 tokens of chunk N+1

3. **Character Offset Accuracy**:
   - Reconstruct original text from chunks using offsets
   - Verify exact match

4. **Deterministic ID Test**:
   - Chunk same text twice
   - Verify identical chunk IDs

5. **Neighbor Expansion Test**:
   - Chunk 6-chunk document
   - Expand chunk 3
   - Verify chunks 2, 3, 4 present with [CHUNK BOUNDARY] markers

---

## Alternatives Considered

### Alternative 1: Fixed Character Length Chunking

**Description:** Split by characters (e.g., 3000 chars per chunk)

**Pros:**
- Simpler implementation
- No tokenization overhead

**Cons:**
- Ignores token boundaries (may split mid-word)
- Unpredictable embedding quality
- No alignment with model's tokenization

**Decision:** Rejected - token-based is more semantically sound

### Alternative 2: Structure-Aware Chunking

**Description:** Split by document structure (headings, paragraphs, email blocks)

**Pros:**
- Respects semantic boundaries
- Better chunk coherence
- Natural context preservation

**Cons:**
- Requires format-specific parsers (Markdown, HTML, email)
- Complex implementation (many edge cases)
- May create highly variable chunk sizes

**Decision:** Deferred to v2.1 - token-window is simpler, universal baseline

### Alternative 3: Sliding Window with 50% Overlap

**Description:** 50% overlap instead of 100 tokens

**Pros:**
- Better context preservation
- More redundancy for edge hits

**Cons:**
- 2x storage overhead
- 2x embedding costs
- Diminishing returns on retrieval quality

**Decision:** Rejected - 100 tokens (11% overlap) is sweet spot

### Alternative 4: No Chunking (Store Whole Documents)

**Description:** Always embed entire document

**Pros:**
- Simplest implementation
- No overlap complexity

**Cons:**
- Poor retrieval precision (large docs)
- May exceed token limits (8191)
- Embedding quality degrades for long text

**Decision:** Rejected - chunking is essential for large docs

---

## References

- Technical Specification: Section 2.3.1 (Artifact Ingestion Flow)
- Technical Specification: Section 5.2 (ChunkingService)
- [tiktoken Documentation](https://github.com/openai/tiktoken)
- [OpenAI Embedding Best Practices](https://platform.openai.com/docs/guides/embeddings/embedding-models)

---

## Future Enhancements (v2.1)

### Structure-Aware Chunking

Add format-specific chunking strategies:

- **Email**: Split by reply blocks, quoted sections
- **Markdown**: Split by headings (h1, h2, h3)
- **Chat logs**: Split by speaker turns
- **Code**: Split by functions/classes
- **Fallback**: Token-window (current)

Implementation approach:
```python
class StructureAwareChunkingService(ChunkingService):
    def chunk_text(self, text: str, artifact_id: str, artifact_type: str) -> list[Chunk]:
        if artifact_type == "email":
            return self._chunk_email(text, artifact_id)
        elif artifact_type == "doc" and self._is_markdown(text):
            return self._chunk_markdown(text, artifact_id)
        else:
            return super().chunk_text(text, artifact_id)  # Fallback
```

---

## Approval

**Approved by:** Senior Architect
**Date:** 2025-12-25
**Next ADR:** ADR-003 (Hybrid Retrieval)
