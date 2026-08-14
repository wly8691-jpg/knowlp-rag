#!/usr/bin/env python
"""MCP protocol smoke test — spawns knowlp-mcp.exe over stdio (the same
JSON-RPC path dsh uses) and exercises initialize / list_tools / call_tool.

Usage: .venv/Scripts/python proto_smoke.py
  环境变量: KNOWLP_MCP_EXE (必须, 指向 knowlp-mcp 可执行文件)
"""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXE = os.environ.get("KNOWLP_MCP_EXE", "")


def _content_text(result) -> str:
    try:
        return result.content[0].text
    except Exception:
        return str(result)


async def main():
    if not EXE:
        print("❌ 需要设置 KNOWLP_MCP_EXE 指向 knowlp-mcp 可执行文件")
        sys.exit(1)
    params = StdioServerParameters(
        command=EXE,
        args=[],
        env=os.environ.copy(),
    )
    failures = []
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            print("tools:", names)
            expected = {"knowlp_get_note", "knowlp_record_feedback",
                        "knowlp_search", "knowlp_stats", "skill_search"}
            if not expected.issubset(set(names)):
                failures.append(f"missing tools: {expected - set(names)}")

            r = await session.call_tool("knowlp_stats", {})
            stats = json.loads(_content_text(r))
            print("stats:", json.dumps(stats, ensure_ascii=False)[:200])
            if stats["engines"]["knowlp"] is not True:
                failures.append("knowlp engine not ready")

            r = await session.call_tool("knowlp_search",
                                        {"query": "RAG architecture", "limit": 5})
            search = json.loads(_content_text(r))
            print("search total:", search["total"],
                  "engines:", search["engines_used"])
            if search["total"] < 1:
                failures.append("search returned no hits")

            r = await session.call_tool("skill_search",
                                        {"query": "做PPT红金版", "top_k": 3})
            skill = json.loads(_content_text(r))
            print("skill_search available:", skill.get("available"),
                  "hits:", len(skill.get("hits", [])))

    print("\nFAILURES:", failures if failures else "none")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())
