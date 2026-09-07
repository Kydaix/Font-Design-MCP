"""Reproducible public SDK client; only MCP calls perform font operations."""

import argparse
import asyncio
import html
import json
import sys
from pathlib import Path

from fixture import fixture
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def demo(workspace):
    workspace = workspace.absolute()
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "font_design_mcp", "serve", "--workspace", str(workspace)]
    )
    calls = []
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name, **arguments):
                response = await session.call_tool(name, arguments)
                data = response.structuredContent
                if response.isError:
                    raise RuntimeError(data or response.content)
                calls.append({"tool": name, "arguments": arguments, "result": data})
                return data

            created = await call(
                "project_create",
                metadata={"family": "MCP Geometry Study"},
                brief="Original geometric fixture to exercise tools; not a finished typeface.",
            )
            pid, revision = created["project_id"], created["revision"]
            for name, data in fixture().items():
                result = await call(
                    "glyph_edit",
                    project_id=pid,
                    expected_revision=revision,
                    glyph_id=name,
                    create=True,
                    operations=[{"op": "replace_glyph", "glyph": data}],
                )
                revision = result["revision"]
            result = await call(
                "spacing_edit",
                project_id=pid,
                expected_revision=revision,
                operations=[{"op": "kern_pair", "left": "A", "right": "V", "value": -80}],
            )
            before = result["revision"]
            changed = await call(
                "glyph_edit",
                project_id=pid,
                expected_revision=before,
                glyph_id="A",
                operations=[{"op": "move_point", "point_id": "Aouter_1", "x": 340, "y": 720}],
                summary="Observed variant: move apex +40,+20",
            )
            revision = changed["revision"]
            glyph = await call(
                "render_glyph", project_id=pid, revision=revision, glyph_id="A", compare_revision=before
            )
            curves = await call("render_glyph", project_id=pid, revision=revision, glyph_id="O")
            accent = await call("render_glyph", project_id=pid, revision=revision, glyph_id="Aacute")
            text = await call(
                "render_text",
                project_id=pid,
                revision=revision,
                compare_revision=before,
                text="AV VA OQ ÁV ?",
                sizes=[24, 64, 120],
            )
            validation = await call("font_validate", project_id=pid, revision=revision, corpus="AV OQ Á?")
            build = await call("font_build", project_id=pid, revision=revision)
            state = await call("project_inspect", project_id=pid)
    # Read-only local HTML, no JS, server, network, system font installation or model required.
    cards = []
    for label, result in [
        ("A — edited then previous", glyph),
        ("O — cubic curves and counter", curves),
        ("Á — transformed components", accent),
        ("Text — edited then previous", text),
    ]:
        cards.append(f"<h2>{html.escape(label)}</h2>")
        for image in result["data"]["images"]:
            relative = image["path"].removeprefix(pid + "/")
            cards.append(
                f'<figure><img src="{html.escape(relative, quote=True)}" alt="{html.escape(label, quote=True)}">'
                f"<figcaption>Revision {html.escape(image['revision'])} · "
                f"{image['width']}×{image['height']}</figcaption></figure>"
            )
    downloads = " ".join(
        f'<a href="{html.escape(v["path"].removeprefix(pid + "/"), quote=True)}">{fmt.upper()}</a>'
        for fmt, v in build["data"]["files"].items()
    )
    page = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        "<title>MCP Geometry Study — technical specimen</title><style>body{font:16px system-ui;margin:2rem;max-width:1100px}"
        "img{max-width:100%;height:auto;border:1px solid #ddd}figure{margin:1rem 0}figcaption{font-size:12px}"
        "a{margin-right:1rem}</style><h1>MCP Geometry Study</h1><p>Original technical fixture. "
    )
    page += "FreeType unhinted rendering; no artistic or human approval. “?” demonstrates the missing-glyph fallback.</p>"
    page += f"<p>{downloads}</p>" + "".join(cards) + "</html>"
    folder = workspace / pid
    (folder / "specimen.html").write_text(page, "utf-8")
    (folder / "demo-calls.json").write_text(json.dumps(calls, ensure_ascii=False, indent=2), "utf-8")
    report = {
        "project_id": pid,
        "revision": revision,
        "source": state["data"]["source_path"],
        "specimen": str(folder / "specimen.html"),
        "build": build["data"],
        "validation": validation["data"],
    }
    (folder / "demo-report.json").write_text(json.dumps(report, indent=2), "utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    asyncio.run(demo(parser.parse_args().workspace))
