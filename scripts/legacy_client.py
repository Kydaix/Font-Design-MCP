"""Run with mcp==1.30.0; pass the installed v2 server interpreter as argv[1]."""

import asyncio
import json
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    with tempfile.TemporaryDirectory(prefix="font-legacy-") as folder:
        params = StdioServerParameters(
            command=sys.argv[1],
            args=["-m", "font_design_mcp", "serve", "--workspace", str(Path(folder).resolve())],
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            assert len((await session.list_tools()).tools) == 20
            result = await session.call_tool("project_create", {"metadata": {"family": "Legacy"}})
            # Deliberately use only the JSON text block: old hosts may ignore structuredContent.
            data = json.loads(result.content[0].text)
            assert not result.isError and data["ok"]
            rendered = await session.call_tool("render_text", {"project_id": data["project_id"], "text": " "})
            assert not rendered.isError and any(c.type == "image" for c in rendered.content)
            uri = json.loads(rendered.content[0].text)["data"]["images"][0]["report_uri"]
            assert (await session.read_resource(uri)).contents[0].mimeType == "application/json"
    print("Legacy MCP 1.30 client: discovery, JSON text, image and resource passed")


asyncio.run(main())
