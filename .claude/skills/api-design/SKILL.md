---
name: api-design
description: Design RESTful APIs with proper resource modeling, error handling, pagination, and documentation
allowed-tools: Read, Write, Edit, Glob, Grep
---

# API Design Skill

Design clean, consistent, and developer-friendly APIs.

## When to Use

- Designing new API endpoints
- Refactoring existing APIs
- Creating API documentation
- Reviewing API contracts
- Planning API versioning

## RESTful Principles

1. **Resource-based URLs** - `/users`, `/orders`
2. **HTTP methods for actions** - GET, POST, PUT, DELETE
3. **Stateless** - No server-side sessions
4. **Consistent responses** - Same format everywhere
5. **Proper status codes** - 2xx, 4xx, 5xx

## URL Patterns

```
GET    /api/v1/users           # List users
POST   /api/v1/users           # Create user
GET    /api/v1/users/:id       # Get user
PUT    /api/v1/users/:id       # Update user
DELETE /api/v1/users/:id       # Delete user

GET    /api/v1/users/:id/orders  # Nested resource
```

## Response Format

### Success Response
```json
{
  "data": { ... },
  "meta": {
    "timestamp": "2025-01-01T00:00:00Z"
  }
}
```

### List Response (with pagination)
```json
{
  "data": [ ... ],
  "meta": {
    "page": 1,
    "per_page": 20,
    "total": 100,
    "total_pages": 5
  }
}
```

### Error Response
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Validation failed",
    "details": [
      { "field": "email", "message": "Invalid email format" }
    ]
  }
}
```

## Status Codes

| Code | Use Case |
|------|----------|
| 200 | Success |
| 201 | Created |
| 204 | No Content (DELETE) |
| 400 | Bad Request (validation) |
| 401 | Unauthorized |
| 403 | Forbidden |
| 404 | Not Found |
| 409 | Conflict |
| 429 | Rate Limited |
| 500 | Internal Error |

## Pagination

Always paginate list endpoints:

```
GET /api/v1/users?page=1&per_page=20
GET /api/v1/users?cursor=abc123&limit=20
```

## Filtering & Sorting

```
GET /api/v1/users?status=active
GET /api/v1/users?sort=created_at&order=desc
GET /api/v1/users?search=john
```

## Rate Limiting

Include headers:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1609459200
```

## Versioning

Use URL versioning: `/api/v1/`, `/api/v2/`

## API Documentation Template

```markdown
## [METHOD] /api/v1/[resource]

**Description**: [What it does]
**Auth**: Bearer token required

### Request
**Headers**:
- Authorization: Bearer {token}
- Content-Type: application/json

**Body**:
```json
{ "field": "value" }
```

### Response
**200 OK**:
```json
{ "data": { ... } }
```

### Errors
- 400: Invalid input
- 401: Missing/invalid token
- 404: Resource not found
```
