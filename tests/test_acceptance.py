"""All font edits are real SDK MCP calls to a separate STDIO server process."""

import asyncio
import base64
import hashlib
import io
import json
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import uharfbuzz as hb
from fontTools.pens.freetypePen import FreeTypePen
from fontTools.ttLib import TTFont
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import MCPError
from PIL import Image
from ufoLib2 import Font

sys.path.insert(0, str(Path(__file__).parents[1] / "examples"))
from fixture import fixture


@asynccontextmanager
async def client(root, fault=None):
    root.mkdir(exist_ok=True, parents=True)
    args = [str(Path(__file__).with_name("stdio_proxy.py")), str(root), str(root / "protocol.jsonl")]
    if fault:
        args.append(fault)
    params = StdioServerParameters(command=sys.executable, args=args)
    with (root / "server.stderr.log").open("a", encoding="utf-8") as err:
        async with stdio_client(params, errlog=err) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


async def call(session, name, error=None, **args):
    # This scenario inspects complete evidence; compact defaults have separate coverage.
    if name in {"project_inspect", "glyph_get", "glyph_edit", "render_glyph", "render_text", "font_validate"}:
        args.setdefault("detail", "full")
    if name == "history_list":
        args.setdefault("include_total", True)
    response = await session.call_tool(name, args)
    data = response.structured_content
    assert data is not None, response
    if error:
        assert response.is_error and data["error"]["code"] == error, data
    else:
        assert not response.is_error and data["ok"], data
    return data, response


def shape_file(path, text, kern):
    face = hb.Face(path.read_bytes())
    font = hb.Font(face)
    font.scale = (face.upem, face.upem)
    hb.ot_font_set_funcs(font)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, {"kern": kern})
    return sum(p.x_advance for p in buf.glyph_positions)


def assert_protocol(root):
    lines = (root / "protocol.jsonl").read_text("utf-8").splitlines()
    assert lines
    for line in lines:
        obj = json.loads(line)
        assert obj["jsonrpc"] == "2.0" and ("result" in obj or "method" in obj or "error" in obj)


async def scenario(root):
    async with client(root) as session:
        discovery = await session.list_tools()
        assert len(discovery.tools) == 20
        assert all(tool.input_schema and tool.output_schema for tool in discovery.tools)
        assert next(t for t in discovery.tools if t.name == "glyph_get").annotations.read_only_hint
        assert not next(t for t in discovery.tools if t.name == "render_glyph").annotations.read_only_hint
        (root / "tool-schemas.json").write_text(
            json.dumps(discovery.model_dump(mode="json", by_alias=True), indent=2), "utf-8"
        )
        created, _ = await call(
            session,
            "project_create",
            metadata={"family": "MCP Geometry Study"},
            brief="Original technical fixture; no artistic approval",
        )
        pid, rev = created["project_id"], created["revision"]
        first = rev
        for name, data in fixture().items():
            result, _ = await call(
                session,
                "glyph_edit",
                project_id=pid,
                expected_revision=rev,
                glyph_id=name,
                create=True,
                operations=[{"op": "replace_glyph", "glyph": data}],
            )
            rev = result["revision"]
        result, _ = await call(
            session,
            "spacing_edit",
            project_id=pid,
            expected_revision=rev,
            operations=[
                {"op": "kern_group", "name": "public.kern1.A", "glyphs": ["A", "Aacute"]},
                {"op": "kern_group", "name": "public.kern2.V", "glyphs": ["V"]},
                {"op": "kern_pair", "left": "public.kern1.A", "right": "public.kern2.V", "value": -80},
                {"op": "kern_pair", "left": "O", "right": "V", "value": -35},
            ],
        )
        rev = result["revision"]
        before = rev
        oldglyph, _ = await call(session, "glyph_get", project_id=pid, glyph_id="A")
        other, _ = await call(session, "glyph_get", project_id=pid, glyph_id="V")
        oldrender, _ = await call(
            session, "render_glyph", project_id=pid, glyph_id="A", guides=False, points=False
        )
        oldbuild, _ = await call(session, "font_build", project_id=pid)
        point = {"op": "move_point", "point_id": "Aouter_1", "x": 340, "y": 720}
        edited, _ = await call(
            session,
            "glyph_edit",
            project_id=pid,
            expected_revision=rev,
            glyph_id="A",
            operations=[point],
            summary="Move apex by +40,+20",
        )
        rev = edited["revision"]
        assert edited["data"]["removed_ids"] == []
        newglyph, _ = await call(session, "glyph_get", project_id=pid, glyph_id="A")
        assert newglyph["data"]["contours"][0]["points"][1]["x"] == 340
        unchanged, _ = await call(session, "glyph_get", project_id=pid, glyph_id="V")
        assert unchanged["data"] == other["data"]
        inspect, _ = await call(session, "project_inspect", project_id=pid, limit=2)
        assert inspect["data"]["next_offset"] == 2
        source = root / inspect["data"]["source_path"]
        ufo = Font.open(source, lazy=False)
        assert ufo["A"].contours[0].points[1].x == 340
        rendered, content = await call(
            session,
            "render_glyph",
            project_id=pid,
            glyph_id="A",
            compare_revision=before,
            guides=False,
            points=False,
        )
        assert len([c for c in content.content if c.type == "image"]) == 2
        for info, block in zip(rendered["data"]["images"], [c for c in content.content if c.type == "image"]):
            png = base64.b64decode(block.data)
            assert png == (root / info["path"]).read_bytes()
            assert hashlib.sha256(png).hexdigest() == info["sha256"]
            assert Image.open(io.BytesIO(png)).size == (640, 640)
        assert rendered["data"]["images"][0]["sha256"] != rendered["data"]["images"][1]["sha256"]
        assert rendered["data"]["images"][1]["sha256"] == oldrender["data"]["images"][0]["sha256"]
        newbuild, _ = await call(session, "font_build", project_id=pid)
        repeated, _ = await call(session, "font_build", project_id=pid)
        for fmt in ("ttf", "woff2"):
            assert repeated["data"]["files"][fmt]["sha256"] == newbuild["data"]["files"][fmt]["sha256"]
        oldttf = root / oldbuild["data"]["files"]["ttf"]["path"]
        newttf = root / newbuild["data"]["files"]["ttf"]["path"]
        with TTFont(oldttf) as old, TTFont(newttf) as new:
            assert new["OS/2"].fsType == 0
            assert old["glyf"]["A"].coordinates != new["glyf"]["A"].coordinates
            assert old["glyf"]["V"].coordinates == new["glyf"]["V"].coordinates
            assert new["glyf"]["Aacute"].isComposite()
            assert new.getBestCmap()[193] == "Aacute"
            outline = FreeTypePen(new.getGlyphSet())
            new.getGlyphSet()["O"].draw(outline)
            mask = outline.image(600, 800).getchannel("A")
            assert mask.getpixel((300, 450)) == 0  # Real compiled cubic -> quadratic counter.
            assert mask.getpixel((90, 450)) == 255
        assert shape_file(newttf, "AV", False) - shape_file(newttf, "AV", True) == 80
        assert shape_file(newttf, "ÁV", False) - shape_file(newttf, "ÁV", True) == 80
        assert shape_file(newttf, "OV", False) - shape_file(newttf, "OV", True) == 35
        with TTFont(root / newbuild["data"]["files"]["woff2"]["path"]) as web:
            assert web["head"].unitsPerEm == 1000 and "GPOS" in web
        text, _ = await call(
            session,
            "render_text",
            project_id=pid,
            text="AV ÁV OQ?",
            sizes=[24, 64, 120],
            compare_revision=before,
        )
        assert text["data"]["images"][0]["missing_codepoints"] == [63]
        assert any(p["gid"] == 0 for p in text["data"]["images"][0]["positions"])
        assert text["data"]["images"][0]["sha256"] != text["data"]["images"][1]["sha256"]
        text_off, _ = await call(session, "render_text", project_id=pid, text="AV", kern=False)
        text_on, _ = await call(session, "render_text", project_id=pid, text="AV", kern=True)
        invisible, _ = await call(session, "render_text", project_id=pid, text="A\u200d", sizes=[32])
        assert invisible["data"]["images"][0]["missing_codepoints"] == [0x200D]
        assert any(p["gid"] == 0 for p in invisible["data"]["images"][0]["positions"])
        assert (
            text_off["data"]["images"][0]["advance_units"][0]
            - text_on["data"]["images"][0]["advance_units"][0]
            == 80
        )
        guides, _ = await call(session, "render_glyph", project_id=pid, glyph_id="O")
        counter, _ = await call(
            session, "render_glyph", project_id=pid, glyph_id="O", points=False, guides=False
        )
        im = Image.open(root / counter["data"]["images"][0]["path"])
        info = counter["data"]["images"][0]
        ox, oy = info["origin_pixel"]
        scale = info["scale"]
        assert im.getpixel((round(ox + 300 * scale), round(oy - 350 * scale))) == (255, 255, 255)
        assert im.getpixel((round(ox + 90 * scale), round(oy - 350 * scale))) == (0, 0, 0)
        validation, _ = await call(session, "font_validate", project_id=pid, corpus="AVOQ Á?")
        assert validation["data"]["valid"] and validation["data"]["missing_codepoints"] == [63]
        await call(
            session,
            "glyph_edit",
            error="stale_revision",
            project_id=pid,
            expected_revision=before,
            glyph_id="A",
            operations=[point],
        )
        await call(
            session,
            "glyph_edit",
            error="missing_reference",
            project_id=pid,
            expected_revision=rev,
            glyph_id="A",
            operations=[
                {"op": "move_point", "point_id": "Aouter_1", "x": 400, "y": 700},
                {"op": "move_point", "point_id": "absent", "x": 0, "y": 0},
            ],
        )
        state, _ = await call(session, "glyph_get", project_id=pid, glyph_id="A")
        assert state["revision"] == rev and state["data"] == newglyph["data"]
        await call(
            session,
            "glyph_edit",
            error="component_cycle",
            project_id=pid,
            expected_revision=rev,
            glyph_id="A",
            operations=[{"op": "put_component", "component": {"id": "cycle", "base": "Aacute"}}],
        )
        await call(
            session,
            "glyph_edit",
            error="invalid_input",
            project_id=pid,
            expected_revision=rev,
            glyph_id="A",
            operations=[{"op": "move_point", "point_id": "Aouter_1", "x": "NaN", "y": 700}],
        )
        await call(session, "project_open", error="invalid_input", project_id="../outside")
        await call(session, "glyph_get", error="missing_reference", project_id=pid, glyph_id="Missing")
        await call(session, "font_build", error="invalid_input", project_id=pid, formats=["otf"])
        await call(
            session,
            "project_update",
            error="capability_unavailable",
            project_id=pid,
            expected_revision=rev,
            metrics={"units_per_em": 2000},
        )
        journal, _ = await call(
            session,
            "project_update",
            project_id=pid,
            expected_revision=rev,
            decision={"hypothesis": "Shift apex", "observation": "apex +40,+20", "review": "agent"},
        )
        rev = journal["revision"]
        await call(
            session,
            "project_update",
            error="invalid_input",
            project_id=pid,
            expected_revision=rev,
            decision={"hypothesis": "No fabricated approval", "review": "human"},
        )
        report = {
            "project_id": pid,
            "initial_revision": first,
            "before_revision": before,
            "edited_revision": newglyph["revision"],
            "latest_revision": rev,
            "source": str(source),
            "build": newbuild["data"],
            "glyph_comparison": rendered["data"],
            "text_comparison": text["data"],
            "guides": guides["data"],
            "validation": validation["data"],
        }
    # New OS process, same on-disk project.
    async with client(root) as session:
        reopened, _ = await call(session, "project_open", project_id=pid)
        assert reopened["revision"] == rev
        history, _ = await call(session, "history_list", project_id=pid, limit=2)
        assert history["data"]["total"] >= 10 and history["data"]["next_offset"] == 2
        restored, _ = await call(
            session, "history_restore", project_id=pid, expected_revision=rev, target_revision=before
        )
        assert restored["revision"] not in (rev, before)
        state, _ = await call(session, "glyph_get", project_id=pid, glyph_id="A")
        assert state["data"] == oldglyph["data"]
        report["restored_revision"] = restored["revision"]
    async with client(root, "compiler") as session:
        await call(session, "font_build", error="build_failed", project_id=pid)
    # Real abrupt exit during a multi-file UFO write; no internal function is called by this client.
    try:
        async with client(root, "interrupt") as session:
            await session.call_tool(
                "glyph_edit",
                {
                    "project_id": pid,
                    "expected_revision": restored["revision"],
                    "glyph_id": "A",
                    "operations": [point],
                },
            )
        pytest.fail("Interrupted server unexpectedly returned normally")
    except BaseExceptionGroup as exc:

        def leaves(error):
            if isinstance(error, BaseExceptionGroup):
                return [leaf for child in error.exceptions for leaf in leaves(child)]
            return [error]

        assert any(isinstance(e, MCPError) and "Connection closed" in str(e) for e in leaves(exc)), exc
    async with client(root) as session:
        state, _ = await call(session, "glyph_get", project_id=pid, glyph_id="A")
        assert state["revision"] == restored["revision"] and state["data"] == oldglyph["data"]
        # Recovery includes a successful next write; OS file lock must have been released.
        recovered, _ = await call(
            session,
            "glyph_edit",
            project_id=pid,
            expected_revision=state["revision"],
            glyph_id="A",
            operations=[point],
        )
        report["recovered_revision"] = recovered["revision"]
    assert_protocol(root)
    assert not (root / "server.stderr.log").read_text("utf-8").strip()
    (root / "report.json").write_text(json.dumps(report, indent=2), "utf-8")
    return report


def test_stdio_acceptance(tmp_path):
    report = asyncio.run(scenario(tmp_path))
    assert report["build"]["files"]["ttf"]["bytes"] > 0


def test_external_modification(tmp_path):
    async def run():
        async with client(tmp_path) as session:
            created, _ = await call(session, "project_create", metadata={"family": "External Edit Test"})
            pid, rev = created["project_id"], created["revision"]
            inspect, _ = await call(session, "project_inspect", project_id=pid)
            ufo = tmp_path / inspect["data"]["source_path"]
            with (ufo / "fontinfo.plist").open("ab") as stream:
                stream.write(b"\n<!-- external edit -->")
            await call(
                session,
                "project_update",
                error="external_modification",
                project_id=pid,
                expected_revision=rev,
                brief="Must not overwrite",
            )
            assert (tmp_path / pid / "HEAD.json").read_text().find(rev) >= 0

    asyncio.run(run())


if __name__ == "__main__":
    output = Path(__file__).parents[1] / "test-output" / ("acceptance-" + uuid.uuid4().hex[:8])
    result = asyncio.run(scenario(output))
    print(
        json.dumps({"output": str(output), "project_id": result["project_id"], "status": "passed"}, indent=2)
    )
