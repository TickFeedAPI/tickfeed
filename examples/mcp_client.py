"""Connect to the TickFeed MCP server with the official MCP Python SDK and call a few tools.

    pip install "mcp>=2"
    export TICKFEED_API_KEY=mdp_...
    python examples/mcp_client.py

MCP apps (Claude Code, Claude Desktop, Cursor, VS Code) do this for you; see the mcp/ folder.
"""

import asyncio
import json
import os
import sys

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = "https://api.tickfeed.pro/mcp"


async def main(key: str) -> None:
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {key}"}, timeout=30) as http:
        async with streamable_http_client(URL, http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                init = await session.initialize()
                print(f"Connected to {init.server_info.name} {init.server_info.version}")
                tools = await session.list_tools()
                print("Tools:", ", ".join(t.name for t in tools.tools))
                for name, args in [("get_prices", {"symbols": ["XAUUSD", "EURUSD"]}),
                                   ("get_candles", {"symbol": "XAUUSD", "timeframe": "H1", "limit": 3})]:
                    result = await session.call_tool(name, args)
                    print(f"\n{name}({args}) -> is_error={result.is_error}")
                    print(json.dumps(result.structured_content, indent=2)[:800])


if __name__ == "__main__":
    key = os.environ.get("TICKFEED_API_KEY")
    if not key:
        sys.exit("Set TICKFEED_API_KEY (create a key at https://tickfeed.pro/dashboard)")
    asyncio.run(main(key))
