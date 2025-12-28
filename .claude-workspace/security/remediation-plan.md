# V4 Security Remediation Plan

**Created**: 2025-12-28
**Based On**: V4 Security Audit Report
**Target Completion**: Sprint +2

---

## Priority 1: Critical - Cypher Query Injection (C-01)

### Issue
The `_substitute_params` method in `graph_service.py` has insufficient escaping for string values in Cypher queries, allowing injection attacks.

### Root Cause
Apache AGE does not support native parameterized queries, requiring manual string substitution with inadequate escaping.

### Fix

**File**: `/Users/roland/Library/Mobile Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/implementation/mcp-server/src/services/graph_service.py`

**Replace lines 231-265** with:

```python
def _escape_cypher_string(self, value: str) -> str:
    """
    Safely escape a string for Cypher query inclusion.

    Handles:
    - Backslashes (must be escaped first)
    - Single quotes
    - Double quotes
    - Newlines and carriage returns
    - Tab characters
    - Unicode escape sequences
    """
    if value is None:
        return "null"

    # Escape backslashes first (order matters!)
    escaped = value.replace("\\", "\\\\")
    # Escape single quotes (used for string delimiters in Cypher)
    escaped = escaped.replace("'", "\\'")
    # Escape double quotes
    escaped = escaped.replace('"', '\\"')
    # Escape newlines
    escaped = escaped.replace("\n", "\\n")
    escaped = escaped.replace("\r", "\\r")
    # Escape tabs
    escaped = escaped.replace("\t", "\\t")

    return escaped

def _validate_identifier(self, value: str, max_length: int = 256) -> str:
    """
    Validate and sanitize identifiers (entity names, categories, etc.)

    Raises ValueError if validation fails.
    """
    if not value:
        raise ValueError("Identifier cannot be empty")

    if len(value) > max_length:
        raise ValueError(f"Identifier exceeds maximum length of {max_length}")

    # Remove any Cypher metacharacters that shouldn't appear in identifiers
    # Allow alphanumeric, spaces, common punctuation
    import re
    if not re.match(r'^[\w\s\.\-\'\",@#$%&*()!?:;]+$', value, re.UNICODE):
        raise ValueError(f"Identifier contains invalid characters: {value[:50]}")

    return value

def _substitute_params(self, query: str, params: Dict[str, Any]) -> str:
    """
    Substitute parameters into Cypher query with proper escaping.

    AGE doesn't support parameterized queries in the standard way,
    so we need to safely substitute values with comprehensive escaping.
    """
    result = query

    for key, value in params.items():
        placeholder = f"${key}"
        if placeholder not in result:
            continue

        if value is None:
            result = result.replace(placeholder, "null")
        elif isinstance(value, bool):
            result = result.replace(placeholder, str(value).lower())
        elif isinstance(value, int):
            # Validate integer is within safe bounds
            if not (-2147483648 <= value <= 2147483647):
                raise ValueError(f"Integer value out of bounds: {value}")
            result = result.replace(placeholder, str(value))
        elif isinstance(value, float):
            # Validate float is finite
            import math
            if math.isnan(value) or math.isinf(value):
                raise ValueError(f"Invalid float value: {value}")
            result = result.replace(placeholder, str(value))
        elif isinstance(value, str):
            escaped = self._escape_cypher_string(value)
            result = result.replace(placeholder, f"'{escaped}'")
        elif isinstance(value, (list, tuple)):
            # Format as array with proper escaping for each element
            escaped_items = []
            for v in value:
                if isinstance(v, str):
                    escaped_items.append(f"'{self._escape_cypher_string(v)}'")
                elif isinstance(v, (int, float)):
                    escaped_items.append(str(v))
                elif v is None:
                    escaped_items.append("null")
                else:
                    escaped_items.append(f"'{self._escape_cypher_string(str(v))}'")
            result = result.replace(placeholder, f"[{', '.join(escaped_items)}]")
        elif isinstance(value, UUID):
            # UUIDs are safe alphanumeric
            result = result.replace(placeholder, f"'{str(value)}'")
        else:
            # Fallback: convert to string and escape
            escaped = self._escape_cypher_string(str(value))
            result = result.replace(placeholder, f"'{escaped}'")

    return result
```

### Testing
Add test cases in test file:
```python
def test_cypher_injection_prevention():
    service = GraphService(mock_pg_client)

    # Test single quote injection
    result = service._substitute_params(
        "MATCH (n {name: $name})",
        {"name": "Alice'; MATCH (n) DELETE n; //"}
    )
    assert "DELETE" not in result or "\\'" in result

    # Test backslash injection
    result = service._substitute_params(
        "MATCH (n {name: $name})",
        {"name": "test\\'; DELETE n; //"}
    )
    assert result.count("\\\\") >= 1

    # Test newline injection
    result = service._substitute_params(
        "MATCH (n {name: $name})",
        {"name": "test\nDELETE n"}
    )
    assert "\\n" in result
```

### Verification
- [ ] Unit tests pass
- [ ] Integration test with AGE confirms queries execute correctly
- [ ] Security test with injection payloads fails safely

---

## Priority 2: High - Unbounded Graph Expansion (H-01)

### Issue
`expand_from_events` accepts unbounded `budget` parameter that could cause resource exhaustion.

### Fix

**File**: `/Users/roland/Library/Mobile Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/implementation/mcp-server/src/services/graph_service.py`

**Replace lines 502-510** with:

```python
async def expand_from_events(
    self,
    seed_event_ids: List[UUID],
    budget: int = 10,
    category_filter: Optional[List[str]] = None
) -> List[RelatedContext]:
    """
    Perform 1-hop graph expansion from seed events.

    Args:
        seed_event_ids: Event IDs to expand from (max 50)
        budget: Maximum related items to return (1-100, default 10)
        category_filter: List of categories to include (None = all)
    """
    # Input validation
    if not seed_event_ids:
        return []

    # Enforce limits
    MAX_SEED_EVENTS = 50
    MAX_BUDGET = 100

    seed_event_ids = seed_event_ids[:MAX_SEED_EVENTS]
    budget = max(1, min(budget, MAX_BUDGET))

    # Validate category filter if provided
    VALID_CATEGORIES = {"Commitment", "Execution", "Decision", "Collaboration",
                        "QualityRisk", "Feedback", "Change", "Stakeholder"}
    if category_filter:
        category_filter = [c for c in category_filter if c in VALID_CATEGORIES]
        if not category_filter:
            category_filter = None  # Empty filter means no valid categories

    if not await self.check_age_available():
        logger.warning("AGE not available, returning empty expansion")
        return []
```

### Verification
- [ ] Test with budget=1000 gets capped to 100
- [ ] Test with 100 seed events gets capped to 50
- [ ] Test with invalid categories filters them out

---

## Priority 3: High - Input Validation on Graph API (H-02)

### Issue
V4 API parameters passed without validation bounds.

### Fix

**File**: `/Users/roland/Library/Mobile Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/implementation/mcp-server/src/services/retrieval_service.py`

**Add after line 497** (at start of `hybrid_search_v4`):

```python
async def hybrid_search_v4(
    self,
    query: str,
    limit: int = 5,
    include_memory: bool = False,
    expand_neighbors: bool = False,
    filters: Optional[Dict] = None,
    # V4 parameters
    graph_expand: bool = False,
    graph_depth: int = 1,
    graph_budget: int = 10,
    graph_seed_limit: int = 5,
    graph_filters: Optional[Dict] = None,
    include_entities: bool = False
) -> V4SearchResult:
    """V4 hybrid search with optional graph expansion."""

    # ===== INPUT VALIDATION =====
    # Validate and bound all numeric parameters
    limit = max(1, min(limit, 50))
    graph_depth = max(1, min(graph_depth, 2))  # Only 1-2 supported
    graph_budget = max(1, min(graph_budget, 100))
    graph_seed_limit = max(1, min(graph_seed_limit, 20))

    # Validate query
    if not query or not isinstance(query, str):
        raise RetrievalError("Query must be a non-empty string")
    if len(query) > 1000:
        query = query[:1000]  # Truncate long queries

    # Validate graph_filters structure
    if graph_filters is not None and not isinstance(graph_filters, dict):
        graph_filters = None

    # ===== END INPUT VALIDATION =====

    try:
        # ... rest of method
```

### Verification
- [ ] Test boundary values (0, negative, very large)
- [ ] Test type coercion (string "10" should fail or convert)
- [ ] API documentation updated with limits

---

## Priority 4: Medium - LLM Prompt Injection (M-01)

### Issue
User content interpolated directly into LLM prompts.

### Fix

**File**: `/Users/roland/Library/Mobile Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/implementation/mcp-server/src/services/entity_resolution_service.py`

**Add helper function before `confirm_merge_with_llm`**:

```python
def _sanitize_for_prompt(self, text: str, max_length: int = 500) -> str:
    """
    Sanitize user-provided text for safe LLM prompt inclusion.

    - Truncates to max_length
    - Removes control characters
    - Escapes potential instruction-like patterns
    """
    if not text:
        return ""

    # Truncate
    text = text[:max_length]

    # Remove control characters (except newline, tab)
    import unicodedata
    text = ''.join(
        char for char in text
        if unicodedata.category(char) != 'Cc' or char in '\n\t'
    )

    # Remove common prompt injection patterns
    # This is defense-in-depth, not a complete solution
    injection_patterns = [
        r'ignore\s+(all\s+)?(previous|above)\s+instructions?',
        r'disregard\s+(all\s+)?(previous|above)',
        r'system\s*:\s*',
        r'assistant\s*:\s*',
        r'user\s*:\s*',
    ]

    import re
    for pattern in injection_patterns:
        text = re.sub(pattern, '[FILTERED]', text, flags=re.IGNORECASE)

    return text
```

**Update `confirm_merge_with_llm` (around line 604-625)**:

```python
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
    """Call LLM to confirm whether two entities are the same."""

    # Sanitize all user-provided content
    entity_a_name = self._sanitize_for_prompt(entity_a_name, max_length=200)
    entity_b_name = self._sanitize_for_prompt(entity_b_name, max_length=200)
    doc_title_a = self._sanitize_for_prompt(doc_title_a, max_length=200)
    doc_title_b = self._sanitize_for_prompt(doc_title_b, max_length=200)

    # Sanitize context
    def sanitize_context(ctx: ContextClues) -> ContextClues:
        return ContextClues(
            role=self._sanitize_for_prompt(ctx.role or "", max_length=100) or None,
            organization=self._sanitize_for_prompt(ctx.organization or "", max_length=100) or None,
            email=self._sanitize_for_prompt(ctx.email or "", max_length=100) or None
        )

    entity_a_context = sanitize_context(entity_a_context)
    entity_b_context = sanitize_context(entity_b_context)

    # ... rest of method unchanged
```

### Verification
- [ ] Test with injection payloads in entity names
- [ ] Verify filtering doesn't break legitimate content
- [ ] Test max length truncation

---

## Priority 5: Medium - ILIKE Pattern Escaping (M-03)

### Issue
ILIKE search patterns allow SQL pattern metacharacters.

### Fix

**File**: `/Users/roland/Library/Mobile Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/implementation/mcp-server/src/tools/event_tools.py`

**Replace lines 537-540** with:

```python
if query:
    # Escape ILIKE pattern metacharacters
    escaped_query = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    query_parts.append(f"AND canonical_name ILIKE ${param_idx}")
    params.append(f"%{escaped_query}%")
    param_idx += 1
```

### Verification
- [ ] Test search for literal "%" character
- [ ] Test search for literal "_" character
- [ ] Performance test with escaped patterns

---

## Priority 6: Medium - Category Filter Validation (M-05)

### Issue
Category filter built using f-string without validation.

### Fix

**File**: `/Users/roland/Library/Mobile Documents/com~apple~CloudDocs/code/mcp_memory/.claude-workspace/implementation/mcp-server/src/services/graph_service.py`

**Replace lines 537-541** with:

```python
# Build category filter clause with validation
category_clause = ""
if category_filter:
    VALID_CATEGORIES = {"Commitment", "Execution", "Decision", "Collaboration",
                        "QualityRisk", "Feedback", "Change", "Stakeholder"}
    # Filter to only valid categories
    valid_cats = [c for c in category_filter if c in VALID_CATEGORIES]
    if valid_cats:
        # Safe to interpolate since values are from allowlist
        categories_str = ", ".join([f"'{c}'" for c in valid_cats])
        category_clause = f"AND related.category IN [{categories_str}]"
```

### Verification
- [ ] Test with valid categories
- [ ] Test with invalid categories (should be filtered out)
- [ ] Test with injection attempt in category

---

## Verification Checklist

Before marking remediation complete:

- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] Security-specific tests added and pass
- [ ] Manual penetration testing performed
- [ ] Code review by second engineer
- [ ] Documentation updated
- [ ] CHANGELOG updated

---

## Timeline

| Week | Tasks |
|------|-------|
| 1 | C-01 (Cypher injection), H-01 (bounds) |
| 2 | H-02 (API validation), M-01 (prompt injection) |
| 3 | M-03, M-05, testing, documentation |
| 4 | Security regression testing, sign-off |

---

## Sign-off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Security Engineer | | | |
| Lead Developer | | | |
| Platform Architect | | | |
