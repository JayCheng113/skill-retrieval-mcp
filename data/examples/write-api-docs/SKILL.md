---
name: "write-api-docs"
description: "Write clear, complete API documentation that developers can use without external help"
tags: ["documentation", "api", "openapi", "developer-experience"]
---

## Instructions

Good API documentation lets a developer integrate your API in under an hour without ever needing to contact support.

**What Every Endpoint Document Must Include**
1. **Summary**: One sentence describing what the endpoint does and when to use it.
2. **HTTP method and URL**: `POST /v1/users/{id}/orders`
3. **Authentication**: Which auth scheme is required (Bearer token, API key, OAuth scope).
4. **Path, query, and header parameters**: Name, type, required/optional, default value, and constraints.
5. **Request body**: Full schema with field descriptions, types, and example values.
6. **Response schemas**: One section per status code (200, 201, 400, 401, 404, 429, 500).
7. **Example request and response**: Show a real, copy-pasteable `curl` command and a realistic JSON response.
8. **Error codes**: List all application-level error codes your API can return in the error body, with meaning and remediation.

**Writing Style**
- Write for a developer who is new to your API but experienced in general.
- Use active voice: "Returns a list of orders" not "A list of orders is returned".
- Describe *what* fields mean in business terms, not just their type.
- Highlight gotchas explicitly: rate limits, eventual consistency delays, side effects (emails sent, charges made).

**Tooling**
- Maintain an OpenAPI 3.x (`openapi.yaml`) spec as the source of truth; generate HTML docs from it using Redoc or Swagger UI.
- Keep code examples synchronized with the spec using automated snapshot tests.
- Version your docs alongside your API — breaking changes require a new version section.
