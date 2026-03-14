"""MCP Server for skill retrieval."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from skill_mcp.config import load_config
from skill_mcp.embeddings import EmbeddingModel
from skill_mcp.index import SkillIndex
from skill_mcp.retriever import retrieve
from skill_mcp.store import SkillStore

logger = logging.getLogger("skill_mcp")

server = Server(
    "skill-retrieval",
    instructions=(
        "A knowledge base of 89K+ skills is available — covering virtually every "
        "technical domain: programming, DevOps, cloud, ML, databases, security, "
        "documentation, API design, testing, project management, and more. "
        "Each skill is a structured best-practice guide. "
        "Workflow: search_skills (semantic) or keyword_search (exact terms) → "
        "review summaries → get_skill to fetch full instructions. "
        "Search is < 5ms with zero API calls — when in doubt, search."
    ),
)

# Module-level state, loaded at startup
_store: SkillStore | None = None
_index: SkillIndex | None = None
_embedding: EmbeddingModel | None = None


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_skills",
            description=(
                "Search 89K+ skills covering virtually every technical domain — "
                "programming, DevOps, cloud, ML, databases, security, documentation, "
                "API design, testing, project management, and more. "
                "Each skill is a structured best-practice guide. "
                "Search is < 5ms with zero API calls — when in doubt, search. "
                "Returns summaries only — call get_skill for full instructions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language task description to search for",
                    },
                    "k": {
                        "type": "integer",
                        "description": "Number of results to return (default: 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_skill",
            description=(
                "Fetch full step-by-step instructions for a skill by ID. "
                "Always call this after search_skills or keyword_search "
                "when you find a relevant skill — the search results contain "
                "summaries only, this returns the complete guide with code examples "
                "and best practices."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "skill_id": {
                        "type": "string",
                        "description": "The skill ID from search results",
                    },
                },
                "required": ["skill_id"],
            },
        ),
        Tool(
            name="keyword_search",
            description=(
                "Search skills by exact keyword matching. "
                "Prefer this over search_skills when you have specific terms — "
                "tool names (pytest, webpack, terraform), error messages, CLI commands, "
                "or technology names. Works without a vector index. "
                "Returns summaries — call get_skill for full instructions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords to search for",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default: 10)",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="list_categories",
            description=(
                "List all skill categories with counts. "
                "Use to discover what domains are covered or when the user asks "
                "'what skills do you have', 'what can you help with', "
                "or wants to browse available knowledge areas."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    logger.debug("tool_call: %s args=%s", name, arguments)
    t0 = time.perf_counter()

    if name == "search_skills":
        result = _handle_search_skills(arguments)
    elif name == "get_skill":
        result = _handle_get_skill(arguments)
    elif name == "keyword_search":
        result = _handle_keyword_search(arguments)
    elif name == "list_categories":
        result = _handle_list_categories()
    else:
        result = [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    elapsed = (time.perf_counter() - t0) * 1000
    logger.info("tool_call: %s %.1fms", name, elapsed)
    return result


def _handle_search_skills(arguments: dict) -> list[TextContent]:
    if _store is None or _index is None or _embedding is None:
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "error": "Vector index not available. Run `skill-mcp build-index` first.",
                    }
                ),
            )
        ]

    query = arguments["query"]
    k = arguments.get("k", 5)

    results = retrieve(query, _store, _index, _embedding, k=k)
    logger.debug("search: query=%r k=%d results=%d", query, k, len(results))
    output = [
        {
            "id": r.skill.id,
            "name": r.skill.name,
            "description": r.skill.description,
            "score": round(r.score, 4),
            "category": r.skill.category,
            "tags": r.skill.tags,
        }
        for r in results
    ]
    return [TextContent(type="text", text=json.dumps(output, ensure_ascii=False))]


def _handle_get_skill(arguments: dict) -> list[TextContent]:
    if _store is None:
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {"error": "Skill store not available. Run `skill-mcp init` first."}
                ),
            )
        ]
    skill_id = arguments["skill_id"]
    skill = _store.get_skill(skill_id)
    if skill is None:
        logger.warning("get_skill: not found id=%s", skill_id)
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "Skill not found", "skill_id": skill_id}),
            )
        ]

    output = {
        "id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "instructions": skill.instructions,
        "category": skill.category,
        "tags": skill.tags,
        "source": skill.source.value,
    }
    return [TextContent(type="text", text=json.dumps(output, ensure_ascii=False))]


def _handle_keyword_search(arguments: dict) -> list[TextContent]:
    if _store is None:
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {"error": "Skill store not available. Run `skill-mcp init` first."}
                ),
            )
        ]
    query = arguments["query"]
    limit = arguments.get("limit", 10)

    results = _store.search_keyword(query, limit=limit)
    logger.debug("keyword_search: query=%r limit=%d results=%d", query, limit, len(results))
    output = [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "category": s.category,
            "tags": s.tags,
        }
        for s in results
    ]
    return [TextContent(type="text", text=json.dumps(output, ensure_ascii=False))]


def _handle_list_categories() -> list[TextContent]:
    if _store is None:
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {"error": "Skill store not available. Run `skill-mcp init` first."}
                ),
            )
        ]
    counts = _store.category_counts()
    return [TextContent(type="text", text=json.dumps(counts, ensure_ascii=False))]


async def run_server(config_path: Path | None = None, transport: str = "stdio") -> None:
    """Start the MCP server."""
    global _store, _index, _embedding

    config = load_config(config_path)

    # Load store in read-only mode
    db_path = config.db_path
    if db_path.exists():
        _store = SkillStore(db_path, readonly=True)
        logger.info("store: loaded %d skills from %s", _store.count(), db_path)
    else:
        _store = SkillStore()  # in-memory fallback
        logger.warning("store: database not found at %s, using in-memory fallback", db_path)

    # Load index if available
    index_dir = config.index_dir
    if (index_dir / "index.faiss").exists():
        _index = SkillIndex.load(index_dir)
        emb_info = _index.embedding_info
        backend = emb_info.get("backend", config.embedding.backend)
        model = emb_info.get("model", config.embedding.model)
        _embedding = EmbeddingModel(model_name=model, backend=backend)
        logger.info(
            "index: loaded %d vectors (%s/%s)",
            len(_index.skill_ids),
            backend,
            model,
        )
    else:
        logger.warning("index: not found at %s, semantic search disabled", index_dir)

    logger.info("server: starting transport=%s", transport)

    if transport == "sse":
        try:
            from starlette.applications import Starlette
            from starlette.routing import Route
            from mcp.server.sse import SseServerTransport
            import uvicorn
        except ImportError:
            raise SystemExit(
                "SSE transport requires extra dependencies. Install with:\n"
                "  pip install skill-retrieval-mcp[sse]"
            )

        sse = SseServerTransport("/messages")

        async def handle_sse(request):
            async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
                await server.run(streams[0], streams[1], server.create_initialization_options())

        app = Starlette(
            routes=[
                Route("/sse", endpoint=handle_sse),
                Route("/messages", endpoint=sse.handle_post_message, methods=["POST"]),
            ]
        )
        uvicorn.run(app, host="127.0.0.1", port=8000)
    else:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
