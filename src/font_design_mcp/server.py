"""Official MCP SDK 2.x STDIO transport, including legacy protocol clients."""

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

from . import __version__
from .domain import FontError
from .models import Result
from .service import TOOLS, Service

INSTRUCTIONS = """Create and edit Unicode UFO projects using explicit project IDs and expected revisions.
Coordinates are font units, baseline y=0, Y upwards; advance differs from visible width.
Read stable IDs with glyph_get(detail=full) before moving points. Prefer font_edit for several glyphs;
use stroke_path/filled_path/primitive for drawings and point operations for optical corrections.
Responses default to summaries; request full details or read returned immutable report URIs when needed.
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
    limiter = anyio.CapacityLimiter(2)
    compute_limiter = anyio.CapacityLimiter(1)

    def compact_schema(value):
        if isinstance(value, list):
            return [compact_schema(item) for item in value]
        if isinstance(value, dict):
            return {
                key: (
                    {name: compact_schema(schema) for name, schema in item.items()}
                    if key in ("properties", "$defs")
                    else compact_schema(item)
                )
                for key, item in value.items()
                if key != "title"
            }
        return value

    catalogue = [
        types.Tool(
            name=name,
            description=description,
            input_schema=compact_schema(model.model_json_schema()),
            output_schema=compact_schema(Result.model_json_schema()),
            annotations=types.ToolAnnotations(
                read_only_hint=readonly,
                destructive_hint=False,
                idempotent_hint=readonly,
                open_world_hint=False,
            ),
        )
        for name, (model, readonly, description) in TOOLS.items()
    ]

    async def list_tools(ctx, params):
        return types.ListToolsResult(tools=catalogue)

    async def read_resource(ctx, params):
        data, mime = await anyio.to_thread.run_sync(service.store.read_resource, params.uri)
        content = (
            types.TextResourceContents(uri=params.uri, text=data, mime_type=mime)
            if isinstance(data, str)
            else types.BlobResourceContents(
                uri=params.uri, blob=base64.b64encode(data).decode(), mime_type=mime
            )
        )
        return types.ReadResourceResult(contents=[content])

    async def resource_templates(ctx, params):
        return types.ListResourceTemplatesResult(
            resource_templates=[
                types.ResourceTemplate(
                    uri_template="font-design://{project_id}/{revision}/{artifact_id}/{filename}?sha256={sha256}",
                    name="Immutable font artifacts",
                    description="Read the exact report/image URI returned by a tool.",
                )
            ]
        )

    async def call_tool(ctx, params):
        name, arguments = params.name, params.arguments or {}
        images = []
        try:
            if name not in TOOLS:
                raise FontError("unknown_tool", f"Unknown tool {name}")
            if len(json.dumps(arguments, ensure_ascii=True)) > 2_000_000:
                raise FontError("limit_exceeded", "Tool input exceeds 2 MB")
            request = TOOLS[name][0].model_validate(arguments)
            compute = name in {"font_build", "font_validate", "render_text", "render_glyph"}
            result, images = await anyio.to_thread.run_sync(
                partial(service.execute, name, request),
                limiter=compute_limiter if compute else limiter,
                abandon_on_cancel=compute,
            )
        except ValidationError as exc:
            result = Result(
                ok=False,
                summary="Input or geometry validation failed",
                error={
                    "code": "invalid_input",
                    "total": exc.error_count(),
                    "truncated": exc.error_count() > 5,
                    "details": exc.errors(include_url=False, include_input=False, include_context=False)[:5],
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
            types.ImageContent(type="image", mime_type="image/png", data=base64.b64encode(p).decode())
            for p in images
        )
        if result.ok and getattr(request, "image_mode", "inline") == "resource":
            content.extend(
                types.ResourceLink(
                    type="resource_link",
                    uri=info["uri"],
                    name=f"render-{info['artifact_id']}",
                    mime_type="image/png",
                )
                for info in result.data["images"]
            )
        return types.CallToolResult(is_error=not result.ok, structured_content=structured, content=content)

    return Server(
        "font-design-mcp",
        version=__version__,
        instructions=INSTRUCTIONS,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_read_resource=read_resource,
        on_list_resource_templates=resource_templates,
    )


async def serve(root):
    server = create_server(root)
    async with stdio_server(stdin=BoundedStdin()) as (read, write):
        await server.run(read, write, server.create_initialization_options())
