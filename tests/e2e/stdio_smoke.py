"""Drive the built wheel over real MCP stdio, the way an agent does.

Everything else in this repo tests the source tree in-process with a mock
embedding backend. That combination has now hidden two shipped defects: 0.2.0
went out with a server that could not start, and a declared `mcp>=1.14` floor
survived two releases even though loading the embedding model inside a 1.x stdio
server kills the process. Both were invisible because nothing ever spawned the
installed console script, and nothing ever loaded a real model.

So this script deliberately uses none of the shortcuts:

  - it launches the venv's own `skill-mcp` entry point, which only exists once
    the wheel is installed, and which is what every registration snippet tells
    an agent to run;
  - it speaks the real stdio protocol over a real subprocess;
  - it runs against a real sentence-transformers model, because the failure it
    exists to catch happens at model load and not before.

Run: python stdio_smoke.py <path-to-skill-mcp-executable> <data-dir>
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

TIMEOUT_SECONDS = 300

EXPECTED_TOOLS = {"search_skills", "get_skill", "keyword_search", "list_categories"}

# Counts, not just names: they are what proves the category came from the corpus
# directory layout rather than from each skill labelling itself.
EXPECTED_CATEGORIES = {
    "analysis": 1,
    "databases": 1,
    "documents": 1,
    "infrastructure": 2,
    "security": 1,
}


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def call_json(session: ClientSession, tool: str, args: dict | None = None):
    """Call a tool and decode its payload, refusing to treat an error as a result.

    MCP reports a server-side tool failure as a normal response carrying an error
    flag, not as an exception, so a caller that only reads `.content` sees a
    plausible-looking string and reports success.
    """
    result = await session.call_tool(tool, args or {})
    is_error = getattr(result, "is_error", None)
    if is_error is None:
        is_error = getattr(result, "isError", False)
    text = "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")
    check(not is_error, f"{tool} returned an error: {text[:400]}")
    check(bool(text), f"{tool} returned no text content")
    return json.loads(text)


async def run(exe: str, data_dir: str, errlog) -> None:
    env = dict(os.environ, SKILL_MCP_DATA_DIR=data_dir)
    params = StdioServerParameters(command=exe, args=["serve"], env=env)

    async with stdio_client(params, errlog=errlog) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            info = getattr(init, "server_info", None) or init.serverInfo
            print(f"handshake: {info.name} v{info.version}")
            check(info.name == "skill-retrieval", f"unexpected server name {info.name!r}")
            check(bool(info.version), "server advertised an empty version")
            check(
                info.version != "0.0.0.dev0",
                "server reports the source-tree fallback version, so it is not "
                "running from the installed distribution",
            )
            check(bool(init.instructions), "server advertised no instructions")

            tools = {t.name for t in (await session.list_tools()).tools}
            print(f"tools: {sorted(tools)}")
            check(EXPECTED_TOOLS <= tools, f"missing tools: {sorted(EXPECTED_TOOLS - tools)}")

            # The first search_skills is the load-bearing call: it is where the
            # server first loads the embedding model, and where a server that is
            # going to die does so. Everything after it also proves it survived.
            hits = await call_json(
                session,
                "search_skills",
                {"query": "change a database table without downtime", "k": 3},
            )
            print(f"search_skills #1: {[(h['name'], round(h['score'], 3)) for h in hits]}")
            check(len(hits) == 3, f"asked for 3 results, got {len(hits)}")
            scores = [h["score"] for h in hits]
            check(scores == sorted(scores, reverse=True), f"results not ranked: {scores}")
            check(
                hits[0]["name"] == "postgres-migrations",
                f"semantic search did not discriminate: top hit {hits[0]['name']!r}",
            )

            # A second query with a different right answer, so a server that
            # returns one fixed ordering cannot pass the check above by accident.
            other = await call_json(
                session, "search_skills", {"query": "read text off a scanned page", "k": 3}
            )
            print(f"search_skills #2: {[(h['name'], round(h['score'], 3)) for h in other]}")
            check(
                other[0]["name"] == "pdf-extraction",
                f"semantic search did not discriminate: top hit {other[0]['name']!r}",
            )

            full = await call_json(session, "get_skill", {"skill_id": hits[0]["id"]})
            print(f"get_skill: {len(full['instructions'])} chars")
            check(
                "lock_timeout" in full["instructions"],
                "get_skill returned instructions that are not the stored body",
            )

            # Keyword search goes through SQLite FTS5, a different path from the
            # vector index, and has its own way of being silently empty.
            kw = await call_json(session, "keyword_search", {"query": "PKCE"})
            print(f"keyword_search: {[h['name'] for h in kw]}")
            check(
                any(h["name"] == "oauth-pkce" for h in kw),
                f"keyword_search missed an exact term match: {[h['name'] for h in kw]}",
            )

            cats = {
                row["category"]: row["count"] for row in await call_json(session, "list_categories")
            }
            print(f"list_categories: {cats}")
            check(cats == EXPECTED_CATEGORIES, f"category counts are {cats}")


async def main() -> None:
    exe, data_dir = sys.argv[1], sys.argv[2]
    err_path = Path(tempfile.gettempdir()) / "skill_mcp_stdio_smoke.err"
    with open(err_path, "w+", encoding="utf-8") as errlog:
        try:
            await asyncio.wait_for(run(exe, data_dir, errlog), timeout=TIMEOUT_SECONDS)
        except BaseException:
            # A server that dies during model load leaves the client with nothing
            # but "Connection closed", so its stderr is the only evidence there is.
            errlog.flush()
            errlog.seek(0)
            captured = errlog.read()
            print("\n--- server stderr ---", file=sys.stderr)
            print(captured or "(empty — the server died without writing anything)", file=sys.stderr)
            raise


if __name__ == "__main__":
    asyncio.run(main())
    print("\nstdio smoke passed")
