"""MCP Server for skill retrieval."""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from skill_mcp.config import load_config
from skill_mcp.embeddings import EmbeddingModel
from skill_mcp.index import SkillIndex
from skill_mcp.retriever import retrieve
from skill_mcp.store import SkillStore

server = Server("skill-retrieval")

# Module-level state, loaded at startup
_store: SkillStore | None = None
_index: SkillIndex | None = None
_embedding: EmbeddingModel | None = None


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_skills",
            description="Search for relevant skills by semantic similarity. Returns top-k matching skills with scores. Requires a pre-built vector index (run `skill-mcp build-index` first).",
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
            description="Get the full details of a skill by its ID, including complete instructions.",
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
            description="Search for skills using keyword matching (FTS5). Works even without a vector index.",
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
            description="List all skill categories and their counts.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "search_skills":
        return _handle_search_skills(arguments)
    elif name == "get_skill":
        return _handle_get_skill(arguments)
    elif name == "keyword_search":
        return _handle_keyword_search(arguments)
    elif name == "list_categories":
        return _handle_list_categories()
    else:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


def _handle_search_skills(arguments: dict) -> list[TextContent]:
    if _index is None or _embedding is None:
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": "Vector index not available. Run `skill-mcp build-index` first.",
            }),
        )]

    query = arguments["query"]
    k = arguments.get("k", 5)

    results = retrieve(query, _store, _index, _embedding, k=k)
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
    skill_id = arguments["skill_id"]
    skill = _store.get_skill(skill_id)
    if skill is None:
        return [TextContent(
            type="text",
            text=json.dumps({"error": "Skill not found", "skill_id": skill_id}),
        )]

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
    query = arguments["query"]
    limit = arguments.get("limit", 10)

    results = _store.search_keyword(query, limit=limit)
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
    counts = _store.category_counts()
    return [TextContent(type="text", text=json.dumps(counts, ensure_ascii=False))]


async def run_server(config_path: Path | None = None) -> None:
    """Start the MCP server."""
    global _store, _index, _embedding

    config = load_config(config_path)

    # Load store in read-only mode
    db_path = config.db_path
    if db_path.exists():
        _store = SkillStore(db_path, readonly=True)
    else:
        _store = SkillStore()  # in-memory fallback

    # Load index if available
    index_dir = config.index_dir
    if (index_dir / "index.faiss").exists():
        _index = SkillIndex.load(index_dir)
        _embedding = EmbeddingModel(
            model_name=config.embedding.model,
            backend=config.embedding.backend,
        )

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
