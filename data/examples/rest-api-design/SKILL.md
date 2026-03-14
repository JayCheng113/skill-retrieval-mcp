---
name: "rest-api-design"
description: "Principles and conventions for designing intuitive, consistent REST APIs"
tags: ["api-design", "rest", "http", "backend"]
---

## Instructions

A well-designed REST API is predictable, consistent, and makes the right thing easy to do.

**Resource Naming**
- Use nouns, not verbs: `/orders` not `/getOrders`.
- Use plural nouns for collections: `/users`, `/products`.
- Nest resources to express ownership, but limit depth to two levels: `/users/{id}/orders` is fine; `/users/{id}/orders/{oid}/items/{iid}/reviews` is too deep — flatten it.
- Use kebab-case for multi-word segments: `/order-items`.

**HTTP Methods**
- `GET` — read, safe and idempotent, no body.
- `POST` — create a new resource; returns 201 with a `Location` header.
- `PUT` — full replacement of a resource; idempotent.
- `PATCH` — partial update; use JSON Merge Patch (RFC 7396) or JSON Patch (RFC 6902).
- `DELETE` — remove a resource; idempotent; returns 204 on success.

**Status Codes**
Use meaningful status codes: `200 OK`, `201 Created`, `204 No Content`, `400 Bad Request`, `401 Unauthorized`, `403 Forbidden`, `404 Not Found`, `409 Conflict`, `422 Unprocessable Entity`, `429 Too Many Requests`, `500 Internal Server Error`.

**Versioning**
Version via the URL path: `/v1/users`. Increment the version on breaking changes only. Maintain at least one prior version for a deprecation window.

**Pagination, Filtering, Sorting**
- Pagination: use cursor-based pagination for large or fast-changing datasets; offset pagination for simple cases.
- Filter via query params: `GET /orders?status=shipped&created_after=2024-01-01`.
- Sort: `GET /products?sort=price&order=asc`.

**Error Responses**
Return a consistent error body on all 4xx/5xx responses:
```json
{"error": {"code": "RESOURCE_NOT_FOUND", "message": "Order 123 does not exist."}}
```
