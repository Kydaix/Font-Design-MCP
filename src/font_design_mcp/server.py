"""Official MCP SDK 1.x STDIO transport; stdout contains JSON-RPC only."""

import base64
import json
import logging
import sys
from functools import partial

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from pydantic import ValidationError

from .domain import FontError
from .models import Result
from .service import TOOLS, Service

INSTRUCTIONS = """Create and edit Unicode UFO projects using explicit project IDs and expected revisions.
Coordinates are font units, baseline y=0, Y upwards; advance differs from visible width.
Read stable IDs before moving points. Use atomic edit batches, render, inspect and revise.
Define brief/coverage, explore structural glyphs, compare proportions and optical corrections,
set side bearings before kerning, test words before expanding coverage. Log decisions with project_update.
Technical validation is not artistic or human approval. Images are provided as MCP image content;
whether a model sees them depends on the client. No external models, system fonts or network are used."""


class BoundedStdin:
    """Bound a protocol line before the SDK JSON parser allocates its object graph."""

    def __aiter__(self):
        return self

    async def __anext__(self):
        line = await anyio.to_thread.run_sync(sys.stdin.buffer.readline, 2_000_001)
        if not line:
            raise StopAsyncIteration
        if len(line) > 2_000_000:
            raise ValueError("MCP input line exceeds 2 MB; transport closed")
        return line.decode("utf-8")


def create_server(root):
    service = Service(root)
    server = Server("font-design-mcp", version="0.1.0", instructions=INSTRUCTIONS)
    limiter = anyio.CapacityLimiter(2)

    @server.list_tools()
    async def list_tools():
        return [
            types.Tool(
                name=name,
                description=description,
                inputSchema=model.model_json_schema(),
                outputSchema=Result.model_json_schema(),
                annotations=types.ToolAnnotations(
                    readOnlyHint=readonly, destructiveHint=False, idempotentHint=readonly, openWorldHint=False
                ),
            )
            for name, (model, readonly, description) in TOOLS.items()
        ]

    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        images = []
        try:
            if name not in TOOLS:
                raise FontError("unknown_tool", f"Unknown tool {name}")
            if len(json.dumps(arguments, ensure_ascii=True)) > 2_000_000:
                raise FontError("limit_exceeded", "Tool input exceeds 2 MB")
            request = TOOLS[name][0].model_validate(arguments)
            result, images = await anyio.to_thread.run_sync(
                partial(service.execute, name, request), limiter=limiter
            )
        except ValidationError as exc:
            result = Result(
                ok=False,
                summary="Input or geometry validation failed",
                error={
                    "code": "invalid_input",
                    "details": json.loads(
                        exc.json(include_url=False, include_input=False, include_context=False)
                    ),
                },
            )
        except FontError as exc:
            result = Result(ok=False, summary=str(exc), error={"code": exc.code, "message": str(exc)})
        except Exception:
            logging.exception("Tool failed")
            result = Result(
                ok=False,
                summary="Operation failed; see server stderr",
                error={"code": "operation_failed", "message": "No successful result was produced"},
            )
        structured = result.model_dump(mode="json")
        content = [types.TextContent(type="text", text=json.dumps(structured, ensure_ascii=False))]
        content.extend(
            types.ImageContent(type="image", mimeType="image/png", data=base64.b64encode(p).decode())
            for p in images
        )
        return types.CallToolResult(isError=not result.ok, structuredContent=structured, content=content)

    return server


async def serve(root):
    server = create_server(root)
    async with stdio_server(stdin=BoundedStdin()) as (read, write):
        await server.run(read, write, server.create_initialization_options())
