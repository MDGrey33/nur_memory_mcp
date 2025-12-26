# ADR-001: OpenAI Embedding Strategy

**Status:** Accepted
**Date:** 2025-12-25
**Author:** Senior Architect
**Relates to:** v2.0 Clean Slate Rewrite

---

## Context

### Current State (v1)

The existing MCP Memory Server (v1) relies on ChromaDB's automatic embedding generation:
- Uses ChromaDB's built-in `all-MiniLM-L6-v2` model (384 dimensions)
- No explicit embedding generation in server code
- Simple `collection.add(documents=[...])` API
- Limited control over embedding quality and consistency

### Requirements for v2

v2.0 requires:
1. **Higher quality embeddings**: OpenAI's `text-embedding-3-large` (3072 dimensions)
2. **BYO embeddings**: Server generates embeddings, ChromaDB stores them
3. **Batch efficiency**: Generate embeddings for multiple chunks in single API call
4. **Retry resilience**: Handle rate limits, timeouts, and transient failures
5. **Cost awareness**: OpenAI charges per token, need to optimize batch sizes
6. **Observability**: Track latency, error rates, token usage

### Key Constraints

- **OpenAI API limits**: 2048 texts per batch, 8191 tokens per text
- **Token budget**: Large artifacts (10MB+) may require 100+ chunks
- **Network reliability**: Must handle transient failures gracefully
- **Cold start**: API latency varies (50-500ms per request)

---

## Decision

We will implement a **centralized EmbeddingService** that:

1. **Encapsulates OpenAI client** with configuration management
2. **Implements retry logic** with exponential backoff for transient failures
3. **Provides batch generation** for efficient multi-chunk embedding
4. **Tracks observability metrics** (latency, token count, error rates)
5. **Validates inputs** before making API calls

### Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  Tool Layer (memory_store, artifact_ingest, etc.)      │
└───────────────────┬─────────────────────────────────────┘
                    │ calls
                    ▼
┌─────────────────────────────────────────────────────────┐
│  EmbeddingService                                       │
│  ┌──────────────────────────────────────────────────┐  │
│  │  OpenAI Client (openai>=1.12.0)                  │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Retry Logic (3 attempts, exp backoff)          │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Batch Coordinator (up to 100 texts/batch)      │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Observability (structured logging, metrics)     │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                    │ HTTPS
                    ▼
┌─────────────────────────────────────────────────────────┐
│  OpenAI API (text-embedding-3-large)                    │
└─────────────────────────────────────────────────────────┘
```

### Service Interface

```python
class EmbeddingService:
    """Centralized OpenAI embedding generation service."""

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-large",
        dimensions: int = 3072,
        timeout: int = 30,
        max_retries: int = 3,
        batch_size: int = 100
    ):
        """
        Initialize embedding service.

        Args:
            api_key: OpenAI API key
            model: Embedding model name
            dimensions: Embedding dimensions
            timeout: Request timeout (seconds)
            max_retries: Max retry attempts
            batch_size: Max texts per batch (≤2048 per OpenAI limit)
        """
        self.client = openai.OpenAI(api_key=api_key, timeout=timeout)
        self.model = model
        self.dimensions = dimensions
        self.max_retries = max_retries
        self.batch_size = min(batch_size, 2048)
        self.logger = logging.getLogger("EmbeddingService")

    def generate_embedding(self, text: str) -> list[float]:
        """
        Generate single embedding with retry logic.

        Args:
            text: Text to embed (≤8191 tokens)

        Returns:
            Embedding vector (3072 dimensions)

        Raises:
            ValidationError: Invalid input (too long, empty)
            ConfigurationError: Invalid API key
            EmbeddingError: Generation failed after retries
        """
        pass

    def generate_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts efficiently.

        Automatically splits into batches if texts > batch_size.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors (same order as input)

        Raises:
            ValidationError: Invalid input
            EmbeddingError: Generation failed after retries
        """
        pass

    def get_model_info(self) -> dict:
        """
        Return model configuration.

        Returns:
            {
                "provider": "openai",
                "model": "text-embedding-3-large",
                "dimensions": 3072,
                "batch_size": 100
            }
        """
        pass

    def health_check(self) -> dict:
        """
        Test API connectivity with small embedding.

        Returns:
            {
                "status": "healthy" | "unhealthy",
                "latency_ms": 234,
                "error": "..." (if unhealthy)
            }
        """
        pass
```

### Retry Strategy

We implement **exponential backoff** with the following rules:

| Error Type | Retry? | Backoff Schedule | Max Attempts |
|------------|--------|------------------|--------------|
| 401 (Unauthorized) | No | N/A | 1 |
| 429 (Rate Limit) | Yes | 1s, 2s, 4s | 3 |
| 500/502/503 (Server Error) | Yes | 1s, 2s, 4s | 3 |
| Timeout | Yes | 1s, 2s, 4s | 3 |
| 400 (Invalid Input) | No | N/A | 1 |

**Implementation:**
```python
def _call_with_retry(self, func, *args, **kwargs):
    """Execute function with exponential backoff."""
    attempts = 0
    backoff = 1.0  # seconds

    while attempts < self.max_retries:
        try:
            return func(*args, **kwargs)
        except openai.RateLimitError as e:
            attempts += 1
            if attempts >= self.max_retries:
                raise EmbeddingError(f"Rate limit after {attempts} attempts") from e
            self.logger.warning(f"Rate limit (attempt {attempts}), retry in {backoff}s")
            time.sleep(backoff)
            backoff *= 2
        except (openai.APITimeoutError, openai.APIConnectionError) as e:
            attempts += 1
            if attempts >= self.max_retries:
                raise EmbeddingError(f"Timeout after {attempts} attempts") from e
            self.logger.warning(f"Timeout (attempt {attempts}), retry in {backoff}s")
            time.sleep(backoff)
            backoff *= 2
        except openai.AuthenticationError as e:
            raise ConfigurationError("Invalid OpenAI API key") from e
        except openai.BadRequestError as e:
            raise ValidationError(f"Invalid input: {e}") from e
```

### Batch Coordination

For large artifacts requiring 100+ chunks:

```python
def generate_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
    """Generate embeddings with automatic batching."""
    if not texts:
        return []

    all_embeddings = []

    # Split into batches
    for i in range(0, len(texts), self.batch_size):
        batch = texts[i:i + self.batch_size]

        # Generate batch embeddings with retry
        response = self._call_with_retry(
            self.client.embeddings.create,
            input=batch,
            model=self.model,
            dimensions=self.dimensions
        )

        # Extract embeddings in order
        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)

        self.logger.info(
            "batch_embeddings_generated",
            extra={
                "batch_size": len(batch),
                "batch_index": i // self.batch_size,
                "total_batches": (len(texts) + self.batch_size - 1) // self.batch_size
            }
        )

    return all_embeddings
```

### Observability

Every embedding request logs structured data:

```python
self.logger.info("embedding_generated", extra={
    "model": self.model,
    "dimensions": self.dimensions,
    "input_length": len(text),
    "token_count": token_count,
    "latency_ms": latency,
    "batch_size": 1,
    "trace_id": trace_id
})
```

Key metrics to track:
- `embeddings_total` (counter) - by model, dimensions
- `embedding_latency_seconds` (histogram) - p50, p95, p99
- `embedding_errors_total` (counter) - by error type
- `embedding_tokens_total` (counter) - cost tracking

---

## Consequences

### Positive

1. **Quality Improvement**: 3072-dim embeddings capture more semantic nuance than 384-dim
2. **Full Control**: Can switch providers (Cohere, Anthropic) without changing storage layer
3. **Resilience**: Retry logic handles transient failures gracefully
4. **Efficiency**: Batch API calls reduce latency for multi-chunk ingestion
5. **Observability**: Clear visibility into embedding performance and costs
6. **Testability**: Service can be mocked for unit tests without API calls

### Negative

1. **Complexity**: More code than v1's `collection.add(documents=...)` approach
2. **Cost**: OpenAI charges per token (~$0.13 per 1M tokens for text-embedding-3-large)
3. **Latency**: Network round-trip adds 100-500ms per batch
4. **Dependency**: Service downtime if OpenAI API unavailable (mitigated by retry)
5. **State Management**: Must track API key, handle rotation

### Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| OpenAI rate limits | Exponential backoff + batch coordination |
| API key leakage | Store in env vars, never log key |
| High costs | Log token counts, set budget alerts |
| Model deprecation | Abstract behind interface, easy to swap |
| Inconsistent dimensions | Validate dimensions on startup, fail fast |

---

## Implementation Notes

### Configuration

Use environment variables for flexibility:

```bash
OPENAI_API_KEY=sk-proj-...
OPENAI_EMBED_MODEL=text-embedding-3-large
OPENAI_EMBED_DIMS=3072
OPENAI_TIMEOUT=30
OPENAI_MAX_RETRIES=3
OPENAI_BATCH_SIZE=100
```

### Initialization

Service initialized at server startup:

```python
# In server.py lifespan
embedding_service = EmbeddingService(
    api_key=os.getenv("OPENAI_API_KEY"),
    model=os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-large"),
    dimensions=int(os.getenv("OPENAI_EMBED_DIMS", "3072")),
    timeout=int(os.getenv("OPENAI_TIMEOUT", "30")),
    max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "3")),
    batch_size=int(os.getenv("OPENAI_BATCH_SIZE", "100"))
)

# Health check on startup
health = embedding_service.health_check()
if health["status"] != "healthy":
    logger.error(f"Embedding service unhealthy: {health}")
    raise RuntimeError("Cannot start without healthy embedding service")
```

### Integration with Tools

Tools call the service instead of ChromaDB auto-embed:

```python
# OLD v1 approach
collection.add(
    ids=[memory_id],
    documents=[content],  # ChromaDB auto-generates embedding
    metadatas=[metadata]
)

# NEW v2 approach
embedding = embedding_service.generate_embedding(content)
collection.add(
    ids=[memory_id],
    documents=[content],
    embeddings=[embedding],  # Explicit embedding
    metadatas=[{
        **metadata,
        "embedding_provider": "openai",
        "embedding_model": "text-embedding-3-large",
        "embedding_dimensions": 3072,
        "token_count": len(tiktoken.get_encoding("cl100k_base").encode(content))
    }]
)
```

### Testing Strategy

1. **Unit Tests**: Mock OpenAI client, test retry logic, batch splitting
2. **Integration Tests**: Real API calls (with test API key), measure latency
3. **Error Injection**: Simulate 429, timeout, 401 to verify error handling
4. **Performance Tests**: Measure batch efficiency (sequential vs batch)

---

## Alternatives Considered

### Alternative 1: Keep ChromaDB Auto-Embed

**Pros:**
- Simpler code (no service layer)
- No OpenAI costs
- Works offline

**Cons:**
- Lower quality (384 dims vs 3072)
- Cannot switch providers
- No control over retry logic
- No observability into embedding generation

**Decision:** Rejected - quality improvement justifies complexity

### Alternative 2: Use Anthropic Embeddings

**Pros:**
- Native to Claude ecosystem
- May have better semantic alignment with Claude's understanding

**Cons:**
- Not yet GA (as of 2025-12-25)
- Unknown dimensions/quality
- Risk of early API changes

**Decision:** Deferred - OpenAI is proven, can revisit in v2.1

### Alternative 3: Local Embeddings (Ollama, Sentence Transformers)

**Pros:**
- No API costs
- Full control
- Works offline

**Cons:**
- Lower quality than OpenAI (typically 768-1024 dims)
- Requires GPU for reasonable latency
- Complex deployment (model files, CUDA setup)

**Decision:** Rejected - cloud API simplifies deployment, quality > cost

---

## References

- [OpenAI Embeddings API Documentation](https://platform.openai.com/docs/guides/embeddings)
- [text-embedding-3-large Model Card](https://platform.openai.com/docs/models/embeddings)
- Technical Specification: Section 5.1 (EmbeddingService)
- ChromaDB BYO Embeddings: [Docs](https://docs.trychroma.com/guides#bring-your-own-embeddings)

---

## Approval

**Approved by:** Senior Architect
**Date:** 2025-12-25
**Next ADR:** ADR-002 (Chunking Architecture)
