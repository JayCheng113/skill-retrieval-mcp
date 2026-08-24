"""MCP Server for skill retrieval."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Annotated

from pydantic import Field

try:  # mcp >= 2.0
    from mcp.server import MCPServer as _FastServer
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _FastServer

from mcp.types import TextContent

from skill_mcp.config import Config
from skill_mcp.embeddings import EmbeddingModel
from skill_mcp.index import SkillIndex
from skill_mcp.retriever import retrieve
from skill_mcp.store import SkillStore

logger = logging.getLogger("skill_mcp")

server = _FastServer(
    "skill-retrieval",
    instructions=(
        "A local library of curated skills — each one a procedural guide written "
        "by the tool's own maintainers, not a generated summary. "
        "Coverage is deep but narrow. It is strongest on Google Cloud "
        "(GKE, BigQuery, Cloud Run, IAM, Vertex/Agent Platform, Google Ads and "
        "Mobile Ads APIs) and on computational science (single-cell and bulk "
        "RNA-seq, cheminformatics, structural biology, statistics, scientific "
        "writing and figures), with smaller sets on agent engineering practice, "
        "frontend and API design, Obsidian, and one deep guide to draw.io "
        "diagramming. It covers little else: AWS, Azure, "
        "Rust, iOS, self-hosted databases and most web infrastructure are absent. "
        "Workflow: search_skills (semantic) or keyword_search (exact terms) → "
        "read the returned descriptions → get_skill for the full guide. "
        "Search is < 5ms with zero API calls, so searching costs you nothing. "
        "Similarity scores are NOT calibrated confidence: a query the library "
        "cannot answer still returns five results, and its top score can exceed "
        "that of a genuine hit. Decide from the description, never the score. "
        "If nothing returned actually matches the task, say so and use web search "
        "or your own knowledge instead."
    ),
)

# Module-level state, loaded at startup
_store: SkillStore | None = None
_index: SkillIndex | None = None
_embedding: EmbeddingModel | None = None
_embedding_spec: tuple[str, str] | None = None
_embedding_lock = threading.Lock()


def _get_embedding() -> EmbeddingModel | None:
    """Build the embedding model on first use, at most once.

    Importing sentence-transformers costs ~6s and HuggingFace cache validation
    another ~5s. Paying that inside ``run_server`` stalled the MCP handshake for
    fourteen seconds, which most clients cannot distinguish from a hung server.
    """
    global _embedding
    if _embedding is not None:
        return _embedding
    if _embedding_spec is None:
        return None
    with _embedding_lock:
        if _embedding is None:
            backend, model = _embedding_spec
            t0 = time.perf_counter()
            _embedding = EmbeddingModel(model_name=model, backend=backend)
            logger.info(
                "embedding: loaded %s/%s in %.0fms",
                backend,
                model,
                (time.perf_counter() - t0) * 1000,
            )
    return _embedding


def _dispatch(name: str, handler, arguments: dict) -> str:
    """Run a handler, log timing, and unwrap it to the JSON text payload.

    The tool functions below are ``async`` on purpose: mcp 2.x dispatches sync
    tool callables to a worker thread, and the SQLite connection in SkillStore
    is bound to the thread that opened it. Staying on the event loop keeps every
    handler on the startup thread under both mcp 1.x and 2.x.
    """
    logger.debug("tool_call: %s args=%s", name, arguments)
    t0 = time.perf_counter()
    result = handler(arguments)
    elapsed = (time.perf_counter() - t0) * 1000
    logger.info("tool_call: %s %.1fms", name, elapsed)
    return result[0].text


@server.tool(
    name="search_skills",
    description=(
        "Semantic search over a curated skill library. Deep but narrow: "
        "strongest on Google Cloud and computational science, with smaller sets "
        "on agent engineering practice, frontend and API design, and Obsidian. "
        "Phrase the query as the task you are doing, not as a keyword. "
        "Search is < 5ms with zero API calls. "
        "Scores are relative, not confidence — an unanswerable query still "
        "returns results, so judge each hit by its description. "
        "Returns summaries only — call get_skill for the full guide."
    ),
    structured_output=False,
)
async def search_skills(
    query: Annotated[str, Field(description="Natural language task description to search for")],
    k: Annotated[int, Field(description="Number of results to return (default: 5)")] = 5,
) -> str:
    return _dispatch("search_skills", _handle_search_skills, {"query": query, "k": k})


@server.tool(
    name="get_skill",
    description=(
        "Fetch full step-by-step instructions for a skill by ID. "
        "Always call this after search_skills or keyword_search "
        "when you find a relevant skill — the search results contain "
        "summaries only, this returns the complete guide with code examples "
        "and best practices. The `upstream` field gives the licence and the "
        "source file on GitHub: fetch that repository when a guide refers to "
        "scripts or reference files it ships alongside, which are not stored here."
    ),
    structured_output=False,
)
async def get_skill(
    skill_id: Annotated[str, Field(description="The skill ID from search results")],
) -> str:
    return _dispatch("get_skill", _handle_get_skill, {"skill_id": skill_id})


@server.tool(
    name="keyword_search",
    description=(
        "Search skills by exact keyword matching. "
        "Prefer this over search_skills when you have specific terms — "
        "tool names (pytest, webpack, terraform), error messages, CLI commands, "
        "or technology names. Works without a vector index. "
        "Returns summaries — call get_skill for full instructions."
    ),
    structured_output=False,
)
async def keyword_search(
    query: Annotated[str, Field(description="Keywords to search for")],
    limit: Annotated[int, Field(description="Maximum number of results (default: 10)")] = 10,
) -> str:
    return _dispatch("keyword_search", _handle_keyword_search, {"query": query, "limit": limit})


@server.tool(
    name="list_categories",
    description=(
        "List the skill categories that carry one, with counts. "
        "Categories come from the upstream repository layout, so most skills "
        "have none and the counts here cover well under half the library — "
        "an absent category means unlabelled, not uncovered. "
        "Use search_skills to find out what is actually there."
    ),
    structured_output=False,
)
async def list_categories() -> str:
    return _dispatch("list_categories", lambda _: _handle_list_categories(), {})


def _handle_search_skills(arguments: dict) -> list[TextContent]:
    embedding = _get_embedding()
    if _store is None or _index is None or embedding is None:
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

    results = retrieve(query, _store, _index, embedding, k=k)
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
    # Every row was licence-vetted at import time; the guide is a redistributed
    # copy, so the attribution has to travel with it. It is also the only way an
    # agent can reach files a skill references but that we do not ship.
    provenance = {
        key: skill.metadata[key]
        for key in ("repo", "repo_url", "url", "license", "declared_license")
        if skill.metadata.get(key)
    }
    if provenance:
        output["upstream"] = provenance
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


async def run_server(config: Config, transport: str = "stdio") -> None:
    """Start the MCP server.

    Takes a resolved ``Config`` rather than a path: ``--data-dir`` is an
    in-memory override that no config file necessarily records, so re-loading
    from disk here would drop it and serve an empty store instead.
    """
    global _store, _index, _embedding_spec

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
        _embedding_spec = (backend, model)
        logger.info(
            "index: loaded %d vectors (%s/%s)",
            len(_index.skill_ids),
            backend,
            model,
        )
        # Warm the model off the event loop so the handshake does not wait on it.
        asyncio.get_running_loop().run_in_executor(None, _get_embedding)
    else:
        logger.warning("index: not found at %s, semantic search disabled", index_dir)

    logger.info("server: starting transport=%s", transport)

    if transport == "sse":
        try:
            import starlette  # noqa: F401
            import uvicorn  # noqa: F401
        except ImportError:
            raise SystemExit(
                "SSE transport requires extra dependencies. Install with:\n"
                "  pip install skill-retrieval-mcp[sse]"
            )
        await server.run_sse_async()
    else:
        await server.run_stdio_async()
