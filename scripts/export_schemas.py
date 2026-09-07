"""Export the actual tools/list response from a live STDIO server using the official SDK."""

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    root = Path(__file__).parents[1]
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "font_design_mcp", "serve", "--workspace", str(root / "workspace")],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            (root / "docs" / "tool-schemas.json").write_text(
                json.dumps(result.model_dump(mode="json", exclude_none=True), indent=2), "utf-8"
            )
            print(f"Exported {len(result.tools)} live tool schemas")


asyncio.run(main())
