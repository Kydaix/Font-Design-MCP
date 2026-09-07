"""Reproduce Miette using real MCP calls; no direct edits to server-owned UFOs."""

import argparse
import asyncio
import json
import shutil
import sys
from datetime import timedelta
from pathlib import Path

from drawings import FAMILY, LETTERS, METRICS, glyphs, spacing_operations
from fontTools.ttLib import TTFont
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def build(workspace, output, project_id=None, proof_text=None, only=None):
    workspace = workspace.absolute()
    output.mkdir(parents=True, exist_ok=True)
    all_drawings = glyphs()
    drawings = all_drawings
    if only:
        drawings = {name: drawings[name] for name in only}
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "font_design_mcp", "serve", "--workspace", str(workspace)],
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=180)) as session:
            await session.initialize()

            async def call(name, **arguments):
                result = await session.call_tool(name, arguments)
                data = result.structuredContent
                if result.isError or not data or not data["ok"]:
                    raise RuntimeError(data or result.content)
                if project_id:
                    with (workspace / project_id / "miette-calls.jsonl").open("a", encoding="utf-8") as log:
                        log.write(json.dumps({"tool": name, "arguments": arguments, "result": data},
                                             ensure_ascii=False) + "\n")
                return data

            if project_id:
                state = await call("project_open", project_id=project_id)
            else:
                state = await call("project_create", metadata={"family": FAMILY}, metrics=METRICS,
                                   brief="Original soft rounded French typeface example; agent review, not human approval.")
                project_id = state["project_id"]
            revision = state["revision"]
            state = await call("project_update", project_id=project_id, expected_revision=revision,
                               metrics=METRICS, summary="Miette: line metrics and embedding defaults")
            revision = state["revision"]
            (output / "project.json").write_text(json.dumps({"project_id": project_id}, indent=2), "utf-8")
            existing = set()
            offset = 0
            while True:
                inventory = await call("project_inspect", project_id=project_id, offset=offset, limit=100)
                existing.update(inventory["data"]["glyphs"])
                offset = inventory["data"]["next_offset"]
                if offset is None:
                    break
            for name, drawing in drawings.items():
                state = await call("glyph_edit", project_id=project_id, expected_revision=revision,
                                   glyph_id=name, create=name not in existing,
                                   operations=[{"op": "replace_glyph", "glyph": drawing}],
                                   summary=f"Miette: original drawing for {name}")
                revision = state["revision"]
                print(f"Drawn {name}", flush=True)
            operations = spacing_operations()
            for offset in range(0, len(operations), 128):
                state = await call("spacing_edit", project_id=project_id, expected_revision=revision,
                                   operations=operations[offset:offset + 128],
                                   summary="Miette: optical kerning with accent inheritance")
                revision = state["revision"]
            proof = proof_text or "Miette aime les belles lettres"
            preview = await call("render_text", project_id=project_id, revision=revision,
                                 text=proof, sizes=[16, 24, 48, 96], width=1600)
            assert all(not image["missing_codepoints"] for image in preview["data"]["images"])
            shutil.copyfile(workspace / preview["data"]["images"][0]["path"], output / "proof.png")
            coverage = "".join(chr(cp) for g in all_drawings.values() for cp in g.get("unicodes", []))
            validation = await call("font_validate", project_id=project_id, revision=revision, corpus=coverage)
            assert validation["data"]["valid"] and not validation["data"]["missing_codepoints"]
            exported = await call("font_build", project_id=project_id, revision=revision)
            for extension, info in exported["data"]["files"].items():
                shutil.copyfile(workspace / info["path"], output / f"Miette-Regular.{extension}")
            with TTFont(output / "Miette-Regular.ttf") as font:
                cmap = font.getBestCmap()
                assert set(map(ord, coverage)).issubset(cmap)
                if not proof_text:
                    assert set(map(ord, LETTERS)).issubset(cmap)
            report = {"project_id": project_id, "revision": revision, "validation": validation["data"],
                      "build": exported["data"], "codepoints": len(cmap), "proof": proof}
            (output / "project.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
            print(json.dumps({"project_id": project_id, "revision": revision, "output": str(output.absolute())}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent)
    parser.add_argument("--project-id")
    parser.add_argument("--proof-text")
    parser.add_argument("--only", nargs="+", help="Redraw only these glyph IDs in an existing project")
    args = parser.parse_args()
    if args.only and not args.project_id:
        parser.error("--only requires --project-id")
    asyncio.run(build(args.workspace, args.output, args.project_id, args.proof_text, args.only))
