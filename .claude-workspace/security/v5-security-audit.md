# V5 Security Audit Report

**Date:** 2025-12-31
**Auditor:** Security Engineer
**Version:** 5.0.0-alpha
**Files Reviewed:**
- `/Users/roland/Library/Mobile Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/implementation/mcp-server/src/server.py`
- `/Users/roland/Library/Mobile Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/implementation/mcp-server/src/storage/collections.py`
- `/Users/roland/Library/Mobile Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/implementation/mcp-server/src/storage/postgres_client.py`
- `/Users/roland/Library/Mobile Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/implementation/mcp-server/src/tools/event_tools.py`
- `/Users/roland/Library/Mobile Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/implementation/mcp-server/src/services/graph_service.py`
- `/Users/roland/Library/Mobile Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/implementation/mcp-server/src/services/retrieval_service.py`
- `/Users/roland/Library/Mobile Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/implementation/mcp-server/src/config.py`

---

## Executive Summary

The V5 implementation introduces a simplified interface with four new tools (`remember()`, `recall()`, `forget()`, `status()`) that unify content storage with content-based ID generation. The overall security posture is **GOOD** with no critical vulnerabilities identified. The codebase demonstrates proper use of parameterized queries, input validation, and secure defaults.

**Key Findings:**
- **0 Critical** issues
- **1 High** severity issue (Cypher injection risk in graph_service.py)
- **3 Medium** severity issues
- **4 Low** severity issues
- **5 Informational** recommendations

---

## Findings

### Critical
*None identified.*

---

### High

#### H1: Potential Cypher Injection in Graph Service Parameter Substitution

**Location:** `/services/graph_service.py`, lines 317-351 (`_substitute_params` method)

**Description:** The `_substitute_params` method performs direct string substitution for Cypher query parameters because Apache AGE does not support standard parameterized queries. While the code attempts to escape single quotes for strings, this approach is inherently risky.

**Current mitigation:**
```python
elif isinstance(value, str):
    # Escape single quotes
    escaped = value.replace("'", "\\'")
    result = result.replace(placeholder, f"'{escaped}'")
```

**Risk:** An attacker who can control entity names, narratives, or other string values stored in the database could potentially craft input that breaks out of the string context. For example, if a value contains `\'` followed by Cypher syntax, the escaping may be insufficient.

**Recommendation:**
1. Implement a more robust escaping function that handles all edge cases including backslash sequences
2. Consider using AGE's `agtype` conversion functions where possible
3. Implement input validation to reject or sanitize suspicious character sequences in entity names and narratives
4. Add a whitelist of allowed characters for critical fields

---

### Medium

#### M1: ID Collision Risk with SHA256[:12]

**Location:** `server.py`, lines 1668-1670 (V5 `remember()`)

**Description:** V5 generates artifact IDs using `art_` + `SHA256(content)[:12]`. This creates 48-bit identifiers (12 hex characters), giving approximately 281 trillion possible values.

**Risk Analysis:**
- Birthday paradox suggests 50% collision probability at ~16.7 million documents
- Content-based deduplication means same content always gets same ID (intentional)
- However, if two different contents hash to same prefix, one will silently overwrite the other in ChromaDB

**Current behavior:** The code checks for existing content before insert:
```python
existing = get_content_by_id(client, artifact_id)
if existing:
    # Same content already exists - upsert metadata
```

**Gap:** This only checks if an ID exists, not if the existing content matches. If there's a collision with different content, the original content is preserved but metadata is overwritten.

**Recommendation:**
1. Increase ID length to SHA256[:16] (64 bits) or SHA256[:20] (80 bits)
2. Add content hash comparison when ID exists to detect true collisions
3. Log and alert on hash collisions for monitoring

#### M2: Sensitive Data Exposure in Error Messages

**Location:** Multiple locations in `server.py`

**Description:** Error messages sometimes include internal details:
```python
return {"error": f"Internal server error: {str(e)}"}
```

**Risk:** Stack traces and exception details may leak:
- Database connection strings
- File paths
- Internal state information

**Recommendation:**
1. Implement an error sanitization layer
2. Log full errors server-side, return generic messages to clients
3. Use error codes for client-facing errors

#### M3: Sensitivity Metadata Not Enforced in Queries

**Location:** `server.py`, recall() function and throughout

**Description:** The `sensitivity` field ("normal", "sensitive", "highly_sensitive") is stored as metadata but not enforced during retrieval. Anyone who can call `recall()` can retrieve "highly_sensitive" content.

**Current state:** Sensitivity is stored but not filtered:
```python
# Build metadata
metadata = {
    "sensitivity": sensitivity,  # Stored but not enforced
    ...
}
```

**Recommendation:**
1. Implement sensitivity-based access controls
2. Add caller context/identity to MCP requests if available
3. Consider filtering highly_sensitive content from general searches by default

---

### Low

#### L1: Missing Rate Limiting

**Location:** Application-wide

**Description:** No rate limiting is implemented on tool invocations. A malicious or misconfigured client could:
- Exhaust OpenAI API quota via repeated embedding calls
- Overload ChromaDB with excessive queries
- Fill storage with spam content

**Recommendation:** Implement rate limiting middleware with configurable limits per tool.

#### L2: Default Postgres Credentials in Config

**Location:** `config.py`, line 90

**Description:**
```python
events_db_dsn=os.getenv("EVENTS_DB_DSN", "postgresql://events:events@localhost:5432/events")
```

Default credentials are included in the fallback DSN.

**Recommendation:**
1. Remove default credentials from code
2. Require explicit configuration in production
3. Use environment variable validation to ensure EVENTS_DB_DSN is set

#### L3: API Key Exposure Risk in Logs

**Location:** `config.py` and `server.py`

**Description:** While the API key is not directly logged, the configuration object contains it and could be inadvertently logged during debugging.

**Recommendation:**
1. Implement a `__repr__` method in Config that masks sensitive values
2. Add logging filters to redact API keys and DSN passwords

#### L4: Trusted Hosts Set to Wildcard

**Location:** `server.py`, lines 2621-2624

**Description:**
```python
Middleware(ProxyHeadersMiddleware, trusted_hosts="*"),
```

All hosts are trusted for proxy header processing.

**Recommendation:** Configure specific trusted proxy IPs in production environments.

---

### Informational

#### I1: Dependency Versions Should Be Pinned

**Location:** `requirements.txt`

**Description:** Most dependencies use `>=` version specifiers. For production deployments, consider pinning exact versions to ensure reproducible builds and protect against supply chain attacks.

#### I2: HTTPS Not Enforced

**Location:** Server configuration

**Description:** The server listens on HTTP by default. In production, HTTPS should be enforced either at the application level or via a reverse proxy.

#### I3: Cascade Delete Could Leave Orphaned Records

**Location:** `server.py`, `forget()` function, lines 2203-2265

**Description:** The cascade delete logic handles multiple tables but executes as separate queries without an atomic transaction wrapper at the top level. If the process crashes mid-deletion, orphaned records may remain.

**Current implementation:**
```python
# Delete events and entities from PostgreSQL
if pg_client:
    try:
        # Multiple separate DELETE statements...
```

**Recommendation:** Wrap all delete operations in a single transaction block.

#### I4: Consider Adding Audit Logging

**Description:** Currently, operations are logged at INFO level for debugging. For security compliance, consider implementing:
- Structured audit logs for all write operations
- User/session identification where available
- Timestamp, operation type, affected resource IDs

#### I5: Event Extraction LLM Prompt Injection Risk

**Location:** Not in reviewed files, but referenced (event extraction via OpenAI)

**Description:** Content ingested via `remember()` is processed by an LLM for event extraction. Malicious content could potentially include prompt injection attempts.

**Recommendation:**
- Sanitize or escape content before sending to LLM
- Use system prompts that clearly delineate user content
- Monitor for anomalous extraction patterns

---

## OWASP Top 10 Checklist

| Category | Status | Notes |
|----------|--------|-------|
| A01:2021 Broken Access Control | ⚠️ | Sensitivity metadata stored but not enforced |
| A02:2021 Cryptographic Failures | ✅ | SHA256 used correctly for hashing; API keys handled via env vars |
| A03:2021 Injection | ⚠️ | PostgreSQL uses parameterized queries; Cypher substitution is risky |
| A04:2021 Insecure Design | ✅ | Defense in depth present; validation at input boundaries |
| A05:2021 Security Misconfiguration | ⚠️ | Default credentials in fallback config; trusted_hosts="*" |
| A06:2021 Vulnerable Components | ✅ | Dependencies are recent; no known CVEs in specified versions |
| A07:2021 Identification/Auth Failures | N/A | MCP protocol handles this at transport layer |
| A08:2021 Software/Data Integrity | ✅ | Content hashing provides integrity checks |
| A09:2021 Security Logging/Monitoring | ⚠️ | Basic logging present; no structured audit trail |
| A10:2021 SSRF | ✅ | No user-controlled URL fetching in V5 tools |

---

## V5-Specific Findings

### ID Generation (SHA256[:12])

**Design Decision:** Using content-based IDs enables idempotent deduplication - storing the same content twice returns the same ID.

**Security Analysis:**
- **Pros:** Deterministic IDs prevent duplicates; shorter IDs are user-friendly
- **Cons:** 48-bit collision space; truncation reduces entropy

**Collision Probability Table:**
| Documents | Collision Probability |
|-----------|----------------------|
| 1,000 | ~0.0000002% |
| 100,000 | ~0.002% |
| 1,000,000 | ~0.18% |
| 10,000,000 | ~16% |

**Verdict:** Acceptable for most use cases. Monitor growth and consider longer IDs if approaching millions of documents.

### Deduplication (Upsert Behavior)

**Current behavior in `remember()`:**
1. Check if `artifact_id` exists
2. If exists, update metadata only (content unchanged)
3. If not exists, insert new content

**Potential exploit:** An attacker cannot overwrite existing content, but can modify metadata (importance, title, author) on content they don't own if they can produce the same hash.

**Verdict:** Low risk. Content is immutable once stored. Metadata updates are logged.

### Cascade Delete

**Analysis of `forget()` deletion order:**
1. Check content exists
2. Delete from V5 content collection
3. Delete associated chunks
4. Delete event_evidence (by event_ids)
5. Delete event_actor (by event_ids)
6. Delete event_subject (by event_ids)
7. Delete semantic_event (by event_ids)
8. Delete entity_mention (by artifact_uid)
9. Delete artifact_revision (by artifact_uid)
10. Delete event_jobs (by artifact_uid)

**Gap:** No atomic transaction wrapper. Partial failures could leave orphaned:
- entity_mention records without parent artifact
- event_jobs without corresponding revision

**Recommendation:** Use `pg_client.transaction()` to wrap all Postgres deletes.

### Content Sensitivity

**Implementation status:**
- `sensitivity` field: ✅ Stored in metadata
- `visibility_scope` field: ✅ Stored in metadata
- `retention_policy` field: ✅ Stored in metadata

**Enforcement status:**
- Query-time filtering: ❌ Not implemented
- Access control: ❌ Not implemented
- Retention enforcement: ❌ Not implemented

**Verdict:** These are currently informational metadata only. Future work needed for enforcement.

### Event Extraction Safety

**Token gating:** Short content (<100 tokens for conversations) skips extraction, reducing attack surface.

**Risk mitigations:**
- Content is passed to OpenAI, not executed locally
- Extracted events are stored as structured data, not code
- No dynamic code generation from content

### Graph Expansion Information Disclosure

**Concern:** Graph expansion via `recall()` with `expand=True` could reveal related content the caller might not otherwise discover.

**Analysis:**
- Graph connects entities across documents
- A user who can access Document A may discover related Document B through shared entities
- This is intended behavior for "portable memory"

**Verdict:** By design. If access control is implemented, graph expansion should respect it.

---

## Recommendations

### Priority 1 (Address Before Production)

1. **Fix Cypher injection risk** in `graph_service._substitute_params()`:
   - Implement comprehensive string escaping
   - Add character whitelist validation for entity names
   - Consider using AGE's native type conversion where possible

2. **Increase ID length** from SHA256[:12] to SHA256[:16] or longer

3. **Remove default credentials** from config.py fallbacks

### Priority 2 (Address Soon)

4. **Sanitize error messages** to avoid leaking internal details

5. **Implement transaction wrapper** for cascade delete operations

6. **Add rate limiting** to prevent API abuse

### Priority 3 (Best Practice Improvements)

7. **Implement structured audit logging** for security compliance

8. **Add sensitivity-based query filtering** when access control is implemented

9. **Pin dependency versions** in requirements.txt for production

10. **Configure specific trusted proxy hosts** instead of wildcard

---

## Conclusion

The V5 implementation demonstrates solid security fundamentals with proper parameterized queries for PostgreSQL, input validation at tool boundaries, and secure handling of sensitive configuration. The primary concern is the Cypher parameter substitution in the graph service, which should be hardened before production deployment.

The content-based ID generation is a reasonable trade-off between usability and security, though the collision space should be monitored as the system scales. The sensitivity metadata framework is in place but not yet enforced, representing future work rather than a current vulnerability.

**Overall Security Posture: GOOD (7/10)**

The system is suitable for development and internal use. Before production deployment, address the Priority 1 recommendations above.

---

*Security audit completed: 2025-12-31*
*Next review recommended: Upon V5 GA release*
