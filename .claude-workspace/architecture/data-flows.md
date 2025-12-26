# Data Flow Diagrams: Chroma MCP Memory V1

**Date:** 2025-12-25
**Version:** 1.0

---

## Flow 1: History Append Flow

**Trigger**: Every user or assistant message
**Frequency**: High (every message turn)
**Latency target**: <100ms (p95)

### Sequence Diagram

```
┌─────────┐    ┌─────────┐    ┌───────────────┐    ┌──────────┐    ┌─────────┐
│  User   │    │ app.py  │    │memory_gateway │    │chroma-mcp│    │ChromaDB │
└────┬────┘    └────┬────┘    └───────┬───────┘    └────┬─────┘    └────┬────┘
     │              │                 │                  │               │
     │ "Hi there"   │                 │                  │               │
     ├─────────────>│                 │                  │               │
     │              │                 │                  │               │
     │              │ 1. Parse message│                  │               │
     │              │    Extract metadata                │               │
     │              │                 │                  │               │
     │              │ 2. append_history(                 │               │
     │              │    conversation_id="conv_123",     │               │
     │              │    role="user",                    │               │
     │              │    text="Hi there",                │               │
     │              │    turn_index=1,                   │               │
     │              │    ts="2025-12-25T12:00:00Z")      │               │
     │              ├────────────────>│                  │               │
     │              │                 │                  │               │
     │              │                 │ 3. Build MCP payload             │
     │              │                 │    tool: "add_documents"         │
     │              │                 │    collection: "history"         │
     │              │                 │                  │               │
     │              │                 │ 4. MCP call      │               │
     │              │                 │   (stdio)        │               │
     │              │                 ├─────────────────>│               │
     │              │                 │                  │               │
     │              │                 │                  │ 5. HTTP POST  │
     │              │                 │                  │ /collections/ │
     │              │                 │                  │ history/add   │
     │              │                 │                  ├──────────────>│
     │              │                 │                  │               │
     │              │                 │                  │               │ 6. Generate
     │              │                 │                  │               │    embedding
     │              │                 │                  │               │
     │              │                 │                  │               │ 7. Store doc
     │              │                 │                  │               │    + vector
     │              │                 │                  │               │    + metadata
     │              │                 │                  │               │
     │              │                 │                  │               │ 8. Persist
     │              │                 │                  │               │    to volume
     │              │                 │                  │               │
     │              │                 │                  │ 9. doc_id     │
     │              │                 │                  │<──────────────┤
     │              │                 │                  │               │
     │              │                 │ 10. MCP response │               │
     │              │                 │    {success, id} │               │
     │              │                 │<─────────────────┤               │
     │              │                 │                  │               │
     │              │ 11. doc_id      │                  │               │
     │              │<────────────────┤                  │               │
     │              │                 │                  │               │
     │              │ 12. Log success │                  │               │
     │              │                 │                  │               │
     │              │ 13. Continue processing            │               │
     │              │     (build context...)             │               │
     │              │                 │                  │               │
```

### Data Transformations

**Input (app.py)**:
```python
{
    "conversation_id": "conv_123",
    "role": "user",
    "text": "Hi there",
    "turn_index": 1,
    "ts": "2025-12-25T12:00:00Z",
    "message_id": "msg_abc123",  # optional
    "channel": "web"  # optional
}
```

**MCP Payload (memory_gateway → chroma-mcp)**:
```json
{
    "tool": "add_documents",
    "arguments": {
        "collection_name": "history",
        "documents": ["Hi there"],
        "metadatas": [{
            "conversation_id": "conv_123",
            "role": "user",
            "ts": "2025-12-25T12:00:00Z",
            "turn_index": 1,
            "message_id": "msg_abc123",
            "channel": "web"
        }],
        "ids": ["msg_abc123"]  # if provided, else auto-generated
    }
}
```

**HTTP Request (chroma-mcp → ChromaDB)**:
```http
POST /api/v1/collections/history/add HTTP/1.1
Host: chroma:8000
Content-Type: application/json

{
    "documents": ["Hi there"],
    "metadatas": [{
        "conversation_id": "conv_123",
        "role": "user",
        "ts": "2025-12-25T12:00:00Z",
        "turn_index": 1,
        "message_id": "msg_abc123",
        "channel": "web"
    }],
    "ids": ["msg_abc123"]
}
```

**ChromaDB Response**:
```json
{
    "ids": ["msg_abc123"]
}
```

### Error Handling

| Error | Layer | Handling |
|-------|-------|----------|
| Invalid role | gateway | ValueError raised, logged |
| MCP connection failure | gateway | ConnectionError, retry once |
| ChromaDB timeout | chroma-mcp | Timeout error, propagate to gateway |
| Duplicate ID | ChromaDB | Update existing (upsert behavior) |
| Volume full | ChromaDB | Storage error, propagate, alert |

---

## Flow 2: Memory Write Flow

**Trigger**: Agent decides information is worth remembering
**Frequency**: Low (1-3 per conversation window)
**Latency target**: <150ms (p95)

### Sequence Diagram

```
┌─────────┐  ┌─────────┐  ┌──────────────┐  ┌───────────────┐  ┌──────────┐  ┌─────────┐
│ app.py  │  │ memory_ │  │memory_gateway│  │  chroma-mcp   │  │ChromaDB  │  │  volume │
│         │  │ policy  │  │              │  │               │  │          │  │         │
└────┬────┘  └────┬────┘  └──────┬───────┘  └───────┬───────┘  └────┬─────┘  └────┬────┘
     │            │               │                  │               │             │
     │ 1. Extract memory candidate                   │               │             │
     │    {text: "User prefers dark mode",           │               │             │
     │     type: "preference",                       │               │             │
     │     confidence: 0.85}                         │               │             │
     │            │               │                  │               │             │
     │ 2. should_store(type, confidence)             │               │             │
     ├───────────>│               │                  │               │             │
     │            │               │                  │               │             │
     │            │ 3. Check confidence >= min (0.7) │               │             │
     │            │    ✓ Pass                        │               │             │
     │            │               │                  │               │             │
     │ 4. True    │               │                  │               │             │
     │<───────────┤               │                  │               │             │
     │            │               │                  │               │             │
     │ 5. enforce_rate_limit("conv_123_window_1")    │               │             │
     ├───────────>│               │                  │               │             │
     │            │               │                  │               │             │
     │            │ 6. Check count < max_per_window  │               │             │
     │            │    ✓ Pass (1 < 3)                │               │             │
     │            │               │                  │               │             │
     │ 7. True    │               │                  │               │             │
     │<───────────┤               │                  │               │             │
     │            │               │                  │               │             │
     │ 8. write_memory(                              │               │             │
     │    text="User prefers dark mode",             │               │             │
     │    memory_type="preference",                  │               │             │
     │    confidence=0.85,                           │               │             │
     │    ts="2025-12-25T12:01:00Z",                 │               │             │
     │    conversation_id="conv_123")                │               │             │
     ├──────────────────────────>│                  │               │             │
     │            │               │                  │               │             │
     │            │               │ 9. Build MCP payload            │             │
     │            │               │    tool: "add_documents"         │             │
     │            │               │    collection: "memory"          │             │
     │            │               │                  │               │             │
     │            │               │ 10. MCP call     │               │             │
     │            │               ├─────────────────>│               │             │
     │            │               │                  │               │             │
     │            │               │                  │ 11. HTTP POST │             │
     │            │               │                  │ /collections/ │             │
     │            │               │                  │ memory/add    │             │
     │            │               │                  ├──────────────>│             │
     │            │               │                  │               │             │
     │            │               │                  │               │ 12. Embed   │
     │            │               │                  │               │     Store   │
     │            │               │                  │               │     Persist │
     │            │               │                  │               ├────────────>│
     │            │               │                  │               │             │
     │            │               │                  │ 13. doc_id    │             │
     │            │               │                  │<──────────────┤             │
     │            │               │                  │               │             │
     │            │               │ 14. MCP response │               │             │
     │            │               │<─────────────────┤               │             │
     │            │               │                  │               │             │
     │ 15. doc_id │               │                  │               │             │
     │<──────────────────────────┤                  │               │             │
     │            │               │                  │               │             │
     │ 16. Log memory stored      │                  │               │             │
     │            │               │                  │               │             │
```

### Policy Decision Tree

```
┌─────────────────────────────┐
│  Memory candidate arrives   │
└─────────────┬───────────────┘
              │
              ▼
    ┌──────────────────────────┐
    │ confidence >= min (0.7)? │
    └─────────┬──────────┬─────┘
              │          │
         YES  │          │ NO
              │          │
              ▼          ▼
    ┌──────────────┐  ┌──────────────────┐
    │ Continue     │  │ REJECT           │
    └──────┬───────┘  │ Log: Low confidence│
           │          └──────────────────┘
           ▼
    ┌──────────────────────────┐
    │ rate_limit < max (3)?    │
    └─────────┬──────────┬─────┘
              │          │
         YES  │          │ NO
              │          │
              ▼          ▼
    ┌──────────────┐  ┌──────────────────┐
    │ STORE        │  │ REJECT           │
    │ Call gateway │  │ Log: Rate limited│
    └──────────────┘  └──────────────────┘
```

### Data Transformations

**Input (app.py)**:
```python
{
    "text": "User prefers dark mode",
    "memory_type": "preference",
    "confidence": 0.85,
    "ts": "2025-12-25T12:01:00Z",
    "conversation_id": "conv_123",
    "entities": "user,ui",
    "source": "chat",
    "tags": "preference,ui"
}
```

**MCP Payload**:
```json
{
    "tool": "add_documents",
    "arguments": {
        "collection_name": "memory",
        "documents": ["User prefers dark mode"],
        "metadatas": [{
            "type": "preference",
            "confidence": 0.85,
            "ts": "2025-12-25T12:01:00Z",
            "conversation_id": "conv_123",
            "entities": "user,ui",
            "source": "chat",
            "tags": "preference,ui"
        }]
    }
}
```

---

## Flow 3: Context Build Flow

**Trigger**: Before generating assistant response
**Frequency**: High (every response generation)
**Latency target**: <500ms (p95)

### Sequence Diagram

```
┌─────────┐  ┌──────────────┐  ┌───────────────┐  ┌──────────┐  ┌─────────┐
│ app.py  │  │context_builder│ │memory_gateway │  │chroma-mcp│  │ChromaDB │
└────┬────┘  └──────┬───────┘  └───────┬───────┘  └────┬─────┘  └────┬────┘
     │              │                  │                │             │
     │ 1. User message arrives:         │                │             │
     │    "What are my preferences?"    │                │             │
     │              │                  │                │             │
     │ 2. build_context(               │                │             │
     │    conversation_id="conv_123",   │                │             │
     │    latest_user_text="What are my preferences?")   │             │
     ├─────────────>│                  │                │             │
     │              │                  │                │             │
     │              │ ╔════════════════════════════════════════════╗  │
     │              │ ║ PARALLEL FETCH (concurrent requests)       ║  │
     │              │ ╚════════════════════════════════════════════╝  │
     │              │                  │                │             │
     │              │ 3a. tail_history(conversation_id, n=16)         │
     │              ├─────────────────>│                │             │
     │              │                  │                │             │
     │              │                  │ 4a. MCP call   │             │
     │              │                  │ "get_documents"│             │
     │              │                  ├───────────────>│             │
     │              │                  │                │             │
     │              │                  │                │ 5a. HTTP GET│
     │              │                  │                │ /collections/
     │              │                  │                │ history/get │
     │              │                  │                │ ?where={    │
     │              │                  │                │   conversation_id│
     │              │                  │                │ }&limit=16  │
     │              │                  │                │ &sort=[     │
     │              │                  │                │   {field:turn_index,│
     │              │                  │                │    order:desc}]│
     │              │                  │                ├────────────>│
     │              │                  │                │             │
     │              │                  │                │             │ 6a. Query
     │              │                  │                │             │     metadata
     │              │                  │                │             │     index
     │              │                  │                │             │
     │              │ 3b. recall_memory(                │             │
     │              │     query_text="What are my preferences?",      │
     │              │     k=8,                          │             │
     │              │     min_confidence=0.7)           │             │
     │              ├─────────────────>│                │             │
     │              │                  │                │             │
     │              │                  │ 4b. MCP call   │             │
     │              │                  │ "query_collection"            │
     │              │                  ├───────────────>│             │
     │              │                  │                │             │
     │              │                  │                │ 5b. HTTP POST│
     │              │                  │                │ /collections/
     │              │                  │                │ memory/query│
     │              │                  │                │ {query_texts:[│
     │              │                  │                │   "What are my│
     │              │                  │                │    preferences?"],│
     │              │                  │                │  n_results:8,│
     │              │                  │                │  where:{    │
     │              │                  │                │   confidence:│
     │              │                  │                │   {$gte:0.7}│
     │              │                  │                │  }}         │
     │              │                  │                ├────────────>│
     │              │                  │                │             │
     │              │                  │                │             │ 6b. Vector
     │              │                  │                │             │     similarity
     │              │                  │                │             │     search
     │              │                  │                │             │     Filter by
     │              │                  │                │             │     metadata
     │              │                  │                │             │     Top-K
     │              │                  │                │             │
     │              │                  │                │ 7a. history │
     │              │                  │                │ documents   │
     │              │                  │                │<────────────┤
     │              │                  │                │             │
     │              │                  │ 8a. Parse MCP  │             │
     │              │                  │     response   │             │
     │              │                  │<───────────────┤             │
     │              │                  │                │             │
     │              │ 9a. list[dict]   │                │             │
     │              │<─────────────────┤                │             │
     │              │                  │                │             │
     │              │                  │                │ 7b. memory  │
     │              │                  │                │ results +   │
     │              │                  │                │ distances   │
     │              │                  │                │<────────────┤
     │              │                  │                │             │
     │              │                  │ 8b. Parse MCP  │             │
     │              │                  │     response   │             │
     │              │                  │<───────────────┤             │
     │              │                  │                │             │
     │              │ 9b. list[dict]   │                │             │
     │              │<─────────────────┤                │             │
     │              │                  │                │             │
     │              │ ╔════════════════════════════════════════════╗  │
     │              │ ║ ASSEMBLE CONTEXT                           ║  │
     │              │ ╚════════════════════════════════════════════╝  │
     │              │                  │                │             │
     │              │ 10. Build context dict:           │             │
     │              │     {                             │             │
     │              │       history: [turns...],        │             │
     │              │       memories: [(mem, score)...],│             │
     │              │       latest_message: "...",      │             │
     │              │       metadata: {tokens, truncated}│            │
     │              │     }                             │             │
     │              │                  │                │             │
     │              │ 11. Optionally truncate to budget │             │
     │              │     (if token_budget set)         │             │
     │              │                  │                │             │
     │ 12. context  │                  │                │             │
     │<─────────────┤                  │                │             │
     │              │                  │                │             │
     │ 13. format_for_prompt(context)  │                │             │
     ├─────────────>│                  │                │             │
     │              │                  │                │             │
     │              │ 14. Format as string:             │             │
     │              │     "Recent history:              │             │
     │              │      - User: ...                  │             │
     │              │      Relevant memories:           │             │
     │              │      - [preference] User prefers..│             │
     │              │      Current message: ..."        │             │
     │              │                  │                │             │
     │ 15. prompt   │                  │                │             │
     │<─────────────┤                  │                │             │
     │              │                  │                │             │
     │ 16. Inject into LLM prompt      │                │             │
     │     Generate response            │                │             │
     │              │                  │                │             │
```

### Context Assembly Logic

```python
def build_context(conversation_id, latest_user_text):
    # Parallel fetch
    history_future = async_fetch(gateway.tail_history(conversation_id, 16))
    memory_future = async_fetch(gateway.recall_memory(latest_user_text, 8, 0.7))

    # Wait for both
    history = await history_future  # List of last 16 turns
    memories = await memory_future  # List of top 8 memories with scores

    # Assemble
    context = {
        "history": history,
        "memories": memories,
        "latest_message": latest_user_text,
        "metadata": {
            "history_count": len(history),
            "memory_count": len(memories),
            "truncated": False
        }
    }

    # Token budget check
    if token_budget:
        context = _truncate_to_budget(context, token_budget)

    return context
```

### Truncation Priority

When token budget is exceeded:

```
1. Keep full: latest_message (always included)
2. Truncate: history (keep most recent N that fit)
3. Truncate: memories (keep top-K that fit)
4. Set: metadata.truncated = True
```

### Context Format Example

**Context dict**:
```python
{
    "history": [
        {"role": "user", "text": "Hi", "turn_index": 1},
        {"role": "assistant", "text": "Hello!", "turn_index": 2},
        # ... up to 16 turns
    ],
    "memories": [
        ({"type": "preference", "text": "User prefers dark mode", "confidence": 0.85}, 0.92),
        # ... up to 8 memories with similarity scores
    ],
    "latest_message": "What are my preferences?",
    "metadata": {
        "history_count": 16,
        "memory_count": 3,
        "truncated": False,
        "total_tokens": 450
    }
}
```

**Formatted prompt string**:
```
=== Recent Conversation History ===
[1] User: Hi
[2] Assistant: Hello!
...
[16] User: Tell me more

=== Relevant Memories ===
- [preference, confidence: 0.85] User prefers dark mode
- [fact, confidence: 0.90] User is a software engineer
- [project, confidence: 0.75] User is building a memory system

=== Current Message ===
User: What are my preferences?
```

---

## Flow 4: Bootstrap Flow

**Trigger**: Application startup (`docker compose up`)
**Frequency**: Once per deployment
**Latency target**: <30 seconds (includes health checks)

### Sequence Diagram

```
┌─────────────┐  ┌─────────┐  ┌──────────┐  ┌─────────────┐  ┌─────────┐
│Docker Compose│ │ChromaDB │  │chroma-mcp│  │ agent-app   │  │  volume │
└──────┬──────┘  └────┬────┘  └────┬─────┘  └──────┬──────┘  └────┬────┘
       │              │             │               │              │
       │ 1. docker compose up        │               │              │
       │              │             │               │              │
       │ 2. Start chroma container   │               │              │
       ├─────────────>│             │               │              │
       │              │             │               │              │
       │              │ 3. Mount volume              │              │
       │              │<─────────────────────────────────────────────┤
       │              │             │               │              │
       │              │ 4. Initialize ChromaDB      │              │
       │              │    Check for existing data  │              │
       │              ├────────────────────────────────────────────>│
       │              │             │               │              │
       │              │ 5. Start HTTP server (port 8000)            │
       │              │             │               │              │
       │ 6. Health check loop (every 10s)            │              │
       ├─────────────>│             │               │              │
       │              │             │               │              │
       │              │ 7. GET /api/v1/heartbeat    │              │
       │              │<────────────┤               │              │
       │              │             │               │              │
       │              │ 8. 200 OK   │               │              │
       │              ├────────────>│               │              │
       │              │             │               │              │
       │ 9. Health check PASSED      │               │              │
       │<─────────────┤             │               │              │
       │              │             │               │              │
       │ 10. Start chroma-mcp (depends_on: chroma healthy)          │
       ├────────────────────────────>│               │              │
       │              │             │               │              │
       │              │             │ 11. Connect to ChromaDB      │
       │              │             │     CHROMA_HTTP_HOST=chroma  │
       │              │             │     CHROMA_HTTP_PORT=8000    │
       │              │             │               │              │
       │              │             │ 12. Test connection           │
       │              │             ├──────────────>│              │
       │              │             │               │              │
       │              │             │ 13. 200 OK    │              │
       │              │             │<──────────────┤              │
       │              │             │               │              │
       │              │             │ 14. MCP server ready (stdio) │
       │              │             │               │              │
       │ 15. Start agent-app (depends_on: chroma-mcp started)      │
       ├───────────────────────────────────────────>│              │
       │              │             │               │              │
       │              │             │               │ 16. Initialize│
       │              │             │               │     MemoryGateway│
       │              │             │               │     (MCP_ENDPOINT=│
       │              │             │               │      chroma-mcp)│
       │              │             │               │              │
       │              │             │               │ 17. ensure_collections│
       │              │             │               │     (["history",│
       │              │             │               │       "memory"])│
       │              │             │               │              │
       │              │             │ 18. MCP call: │              │
       │              │             │     list_collections          │
       │              │             │<──────────────┤              │
       │              │             │               │              │
       │              │ 19. GET /api/v1/collections │              │
       │              │<────────────┤               │              │
       │              │             │               │              │
       │              │ 20. [existing collections]  │              │
       │              ├────────────>│               │              │
       │              │             │               │              │
       │              │             │ 21. MCP response:             │
       │              │             │     ["existing_col"]          │
       │              │             ├──────────────>│              │
       │              │             │               │              │
       │              │             │               │ 22. Check if │
       │              │             │               │     "history"│
       │              │             │               │     exists   │
       │              │             │               │              │
       │              │             │ 23. MCP call: │              │
       │              │             │     create_collection         │
       │              │             │     name="history"            │
       │              │             │<──────────────┤              │
       │              │             │               │              │
       │              │ 24. POST /api/v1/collections│              │
       │              │     {name: "history"}       │              │
       │              │<────────────┤               │              │
       │              │             │               │              │
       │              │ 25. Create collection       │              │
       │              ├────────────────────────────────────────────>│
       │              │             │               │              │
       │              │ 26. 200 OK  │               │              │
       │              ├────────────>│               │              │
       │              │             │               │              │
       │              │             │ 27. MCP response: success    │
       │              │             ├──────────────>│              │
       │              │             │               │              │
       │              │             │ 28. MCP call: │              │
       │              │             │     create_collection         │
       │              │             │     name="memory"             │
       │              │             │<──────────────┤              │
       │              │             │               │              │
       │              │ 29. POST /api/v1/collections│              │
       │              │     {name: "memory"}        │              │
       │              │<────────────┤               │              │
       │              │             │               │              │
       │              │ 30. Create collection       │              │
       │              ├────────────────────────────────────────────>│
       │              │             │               │              │
       │              │ 31. 200 OK  │               │              │
       │              ├────────────>│               │              │
       │              │             │               │              │
       │              │             │ 32. MCP response: success    │
       │              │             ├──────────────>│              │
       │              │             │               │              │
       │              │             │               │ 33. Initialize│
       │              │             │               │     ContextBuilder│
       │              │             │               │     MemoryPolicy│
       │              │             │               │              │
       │              │             │               │ 34. Log: Application│
       │              │             │               │     ready    │
       │              │             │               │              │
       │ 35. All services healthy    │               │              │
       │<───────────────────────────────────────────┤              │
       │              │             │               │              │
       │ 36. docker compose up COMPLETE              │              │
       │              │             │               │              │
```

### Bootstrap Error Handling

| Error | Retry Strategy | Fallback |
|-------|----------------|----------|
| ChromaDB health check timeout | Retry 10 times (10s interval) | Fail deployment |
| chroma-mcp connection failure | Retry 5 times (exponential backoff) | Fail deployment |
| Collection already exists | Ignore (idempotent) | Continue |
| Collection creation failure | Retry once | Fail deployment |
| Volume mount failure | No retry (infrastructure issue) | Fail deployment |

### Verification Steps

After bootstrap completes, verify:

```bash
# 1. All containers running
docker compose ps
# Expected: chroma (healthy), chroma-mcp (running), agent-app (running)

# 2. ChromaDB accessible
curl http://localhost:8000/api/v1/heartbeat
# Expected: {"nanosecond heartbeat": ...}

# 3. Collections exist
curl http://localhost:8000/api/v1/collections
# Expected: ["history", "memory"]

# 4. Volume mounted
docker volume inspect chroma_data
# Expected: Mountpoint exists, created recently

# 5. Agent-app logs
docker compose logs agent-app
# Expected: "Application ready", no errors
```

---

## Flow 5: Persistence Verification Flow

**Trigger**: Container restart (`docker compose restart` or `docker compose down && up`)
**Purpose**: Verify data survives container lifecycle

### Sequence Diagram

```
┌──────────┐  ┌─────────┐  ┌────────────┐
│  User    │  │ChromaDB │  │   volume   │
└────┬─────┘  └────┬────┘  └─────┬──────┘
     │             │              │
     │ 1. docker compose down      │
     ├────────────>│              │
     │             │              │
     │             │ 2. Shutdown  │
     │             │    Flush WAL │
     │             │    Close DB  │
     │             ├─────────────>│
     │             │              │
     │             │ 3. Stop container
     │             X              │
     │                            │
     │ 4. docker compose up       │
     ├───────────>┌─────────┐    │
     │            │ChromaDB │    │
     │            │ (new)   │    │
     │            └────┬────┘    │
     │                 │         │
     │                 │ 5. Mount volume
     │                 │<────────┤
     │                 │         │
     │                 │ 6. Read existing data
     │                 │    - chroma.sqlite3
     │                 │    - index/ files
     │                 │<────────┤
     │                 │         │
     │                 │ 7. Initialize with
     │                 │    existing collections
     │                 │         │
     │ 8. Query old data         │
     │    (should succeed)       │
     ├────────────────>│         │
     │                 │         │
     │                 │ 9. Read from volume
     │                 │<────────┤
     │                 │         │
     │ 10. Results     │         │
     │<────────────────┤         │
     │                 │         │
```

### Persistence Test Script

```bash
#!/bin/bash

# Test persistence across restarts

echo "1. Starting services..."
docker compose up -d

echo "2. Waiting for ready..."
sleep 10

echo "3. Writing test data..."
# Store a message via agent-app API
curl -X POST http://localhost:8080/message \
  -d '{"conversation_id": "test_persist", "text": "Test message", "role": "user"}'

echo "4. Verifying write..."
# Query ChromaDB directly
docker exec chroma curl -X POST http://localhost:8000/api/v1/collections/history/get \
  -H "Content-Type: application/json" \
  -d '{"where": {"conversation_id": "test_persist"}}'

echo "5. Restarting containers..."
docker compose restart

echo "6. Waiting for restart..."
sleep 10

echo "7. Querying after restart..."
# Should return the same data
docker exec chroma curl -X POST http://localhost:8000/api/v1/collections/history/get \
  -H "Content-Type: application/json" \
  -d '{"where": {"conversation_id": "test_persist"}}'

echo "8. Full teardown..."
docker compose down

echo "9. Full restart..."
docker compose up -d

echo "10. Waiting for full restart..."
sleep 10

echo "11. Final verification..."
# Should STILL return the same data
docker exec chroma curl -X POST http://localhost:8000/api/v1/collections/history/get \
  -H "Content-Type: application/json" \
  -d '{"where": {"conversation_id": "test_persist"}}'

echo "✓ Persistence test complete"
```

---

## Performance Characteristics

| Flow | Operation | Latency (p50) | Latency (p95) | Throughput |
|------|-----------|---------------|---------------|------------|
| History Append | Write | 50ms | 100ms | 200 writes/sec |
| Memory Write | Write | 75ms | 150ms | 50 writes/sec |
| Context Build | Read (parallel) | 200ms | 500ms | 50 builds/sec |
| Bootstrap | One-time | 10s | 30s | N/A |

**Bottlenecks**:
- Vector similarity search (memory recall) is slowest operation
- Parallel history + memory fetch improves context build time
- Network latency (Docker internal network): ~1-5ms
- Embedding generation: ~50-100ms per document

**Optimization opportunities (V2)**:
- Cache recent history in memory
- Pre-compute embeddings for common queries
- Batch write operations
- Connection pooling
- Read replicas for ChromaDB

---

## Related Documents

- ADR-001: Docker-First Deployment
- ADR-002: ChromaDB as Vector Store
- ADR-003: Separation of Concerns
- ADR-004: Two-Collection Model
- component-diagram.md: Component architecture
- directory-structure.md: Code organization
