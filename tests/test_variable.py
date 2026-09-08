"""Real MCP variable export, interpolation, revision isolation and invalid inputs."""

import asyncio
from copy import deepcopy

import pytest
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from pydantic import ValidationError
from test_acceptance import call, client
from ufoLib2 import Font

from font_design_mcp import models as m
from font_design_mcp.domain import FontError
from font_design_mcp.service import Service

VARIATION = {
    "axes": [{"tag": "wght", "name": "Weight", "minimum": 300, "default": 300, "maximum": 700}],
    "masters": [
        {"id": "default", "name": "Light", "location": {"wght": 300}},
        {"id": "bold", "name": "Bold", "location": {"wght": 700}},
    ],
}


def test_variable_mcp_end_to_end(tmp_path):
    async def run():
        async with client(tmp_path) as session:
            created, _ = await call(session, "project_create", metadata={"family": "Variable Study"})
            pid, revision = created["project_id"], created["revision"]
            drawn, _ = await call(
                session,
                "font_edit",
                project_id=pid,
                expected_revision=revision,
                glyphs=[
                    {
                        "glyph_id": "A",
                        "create": True,
                        "operations": [
                            {
                                "op": "primitive",
                                "shape": "rectangle",
                                "x": 40,
                                "y": 0,
                                "width": 100,
                                "height": 700,
                                "advance": 400,
                            },
                            {"op": "set_unicodes", "unicodes": [65]},
                        ],
                    }
                ],
                spacing=[{"op": "kern_pair", "left": "A", "right": "A", "value": -20}],
            )
            static_revision = drawn["revision"]
            configured, _ = await call(
                session,
                "variable_configure",
                project_id=pid,
                expected_revision=static_revision,
                variation=VARIATION,
            )
            configured_revision = configured["revision"]
            changed, _ = await call(
                session,
                "glyph_edit",
                project_id=pid,
                expected_revision=configured_revision,
                master_id="bold",
                glyph_id="A",
                operations=[
                    {
                        "op": "primitive",
                        "shape": "rectangle",
                        "x": 40,
                        "y": 0,
                        "width": 300,
                        "height": 700,
                        "advance": 600,
                        "replace": True,
                    },
                ],
            )
            changed, _ = await call(
                session,
                "spacing_edit",
                project_id=pid,
                expected_revision=changed["revision"],
                master_id="bold",
                operations=[
                    {"op": "kern_pair", "left": "A", "right": "A", "value": -100},
                ],
            )
            variable_revision = changed["revision"]
            for master, advance in [("default", 400), ("bold", 600)]:
                glyph, _ = await call(session, "glyph_get", project_id=pid, master_id=master, glyph_id="A")
                assert glyph["data"]["advance"] == advance
            old, _ = await call(
                session,
                "glyph_get",
                project_id=pid,
                revision=configured_revision,
                master_id="bold",
                glyph_id="A",
            )
            assert old["data"]["advance"] == 400
            await call(
                session,
                "glyph_get",
                error="missing_reference",
                project_id=pid,
                master_id="absent",
                glyph_id="A",
            )
            built, _ = await call(session, "font_build", project_id=pid)
            assert built["data"]["variable"]
            for fmt in ("ttf", "woff2"):
                path = tmp_path / built["data"]["files"][fmt]["path"]
                with TTFont(path) as font:
                    assert {"fvar", "gvar", "GPOS"} <= set(font.keys())
                    axis = font["fvar"].axes[0]
                    assert (axis.axisTag, axis.minValue, axis.defaultValue, axis.maxValue) == (
                        "wght",
                        300,
                        300,
                        700,
                    )
                    assert len(font["fvar"].instances) == 2
                    for weight, width, advance in [(300, 100, 400), (500, 200, 500), (700, 300, 600)]:
                        instance = instantiateVariableFont(font, {"wght": weight})
                        glyph = instance["glyf"]["A"]
                        assert glyph.xMax - glyph.xMin == width
                        assert instance["hmtx"]["A"][0] == advance
                resource = await session.read_resource(built["data"]["files"][fmt]["uri"])
                assert resource.contents
            renders = []
            for weight, advance in [(300, 780), (500, 940), (700, 1100)]:
                rendered, response = await call(
                    session,
                    "render_text",
                    project_id=pid,
                    text="AA",
                    location={"wght": weight},
                )
                info = rendered["data"]["images"][0]
                assert info["advance_units"][0] == advance
                assert info["location"] == {"wght": weight}
                assert info["build"]["cache_hit"]
                renders.append(next(c.data for c in response.content if c.type == "image"))
            assert len(set(renders)) == 3
            glyph_render, _ = await call(
                session,
                "render_glyph",
                project_id=pid,
                master_id="bold",
                glyph_id="A",
                compare_revision=configured_revision,
            )
            assert len(glyph_render["data"]["images"]) == 2
            for location in ({"wght": 900}, {"wdth": 100}):
                await call(
                    session, "render_text", error="invalid_input", project_id=pid, text="A", location=location
                )
            valid, _ = await call(session, "font_validate", project_id=pid)
            assert valid["data"]["valid"] and valid["data"]["build"]["cache_hit"]
            # A legitimate intermediate edit may be incompatible; never silently export it.
            broken, _ = await call(
                session,
                "glyph_edit",
                project_id=pid,
                expected_revision=variable_revision,
                master_id="bold",
                glyph_id="A",
                operations=[
                    {
                        "op": "primitive",
                        "id": "extra",
                        "shape": "rectangle",
                        "x": 0,
                        "y": 0,
                        "width": 20,
                        "height": 20,
                    },
                ],
            )
            invalid, _ = await call(session, "font_validate", project_id=pid)
            assert not invalid["data"]["valid"]
            assert invalid["data"]["errors"][0]["code"] == "incompatible_masters"
            await call(session, "font_build", error="incompatible_masters", project_id=pid)
            restored, _ = await call(
                session,
                "history_restore",
                project_id=pid,
                expected_revision=broken["revision"],
                target_revision=static_revision,
            )
            static, _ = await call(session, "font_build", project_id=pid)
            assert not static["data"]["variable"]
            await call(
                session,
                "render_text",
                error="invalid_input",
                project_id=pid,
                text="A",
                location={"wght": 500},
            )
            restored, _ = await call(
                session,
                "history_restore",
                project_id=pid,
                expected_revision=restored["revision"],
                target_revision=variable_revision,
            )
            reopened, _ = await call(session, "project_open", project_id=pid)
            assert reopened["data"]["variation"] == VARIATION
            # Reconfiguration keeps drawings; metadata updates apply to all masters.
            updated, _ = await call(
                session,
                "variable_configure",
                project_id=pid,
                expected_revision=restored["revision"],
                variation=VARIATION,
            )
            updated, _ = await call(
                session,
                "project_update",
                project_id=pid,
                expected_revision=updated["revision"],
                metadata={"family": "Renamed Variable"},
            )
            rebuilt, _ = await call(session, "font_build", project_id=pid)
            assert rebuilt["data"]["build_key"] != built["data"]["build_key"]
            with TTFont(tmp_path / rebuilt["data"]["files"]["ttf"]["path"]) as font:
                assert instantiateVariableFont(font, {"wght": 700})["hmtx"]["A"][0] == 600
            # Every master is integrity checked even when only opening the default source.
            source = (
                tmp_path
                / pid
                / "revisions"
                / updated["revision"]
                / "masters"
                / "master-bold.ufo"
                / "fontinfo.plist"
            )
            with source.open("ab") as stream:
                stream.write(b" ")
            await call(session, "project_open", error="external_modification", project_id=pid)

    asyncio.run(run())


@pytest.mark.parametrize(
    "case", ["range", "tag", "duplicate", "case", "default", "unknown", "outside", "coverage", "nan", "path"]
)
def test_invalid_designspace(case):
    value = deepcopy(VARIATION)
    axis, master = value["axes"][0], value["masters"][1]
    if case == "range":
        axis["minimum"] = axis["maximum"]
    elif case == "tag":
        axis["tag"] = "weight"
    elif case == "duplicate":
        master["id"] = "default"
    elif case == "case":
        master["id"] = "DEFAULT"
    elif case == "default":
        axis["default"] = 400
    elif case == "unknown":
        master["location"]["wdth"] = 100
    elif case == "outside":
        master["location"]["wght"] = 800
    elif case == "coverage":
        master["location"]["wght"] = 600
    elif case == "nan":
        master["location"]["wght"] = float("nan")
    else:
        master["id"] = "../outside"
    with pytest.raises(ValidationError):
        m.Variation.model_validate(value)


def test_multiple_axes_components_and_atomic_master_save(tmp_path, monkeypatch):
    service = Service(tmp_path)
    created, _ = service.execute("project_create", m.ProjectCreate(metadata=m.Metadata(family="Two Axes")))
    pid = created.project_id
    drawn, _ = service.execute(
        "font_edit",
        m.FontEdit(
            project_id=pid,
            expected_revision=created.revision,
            glyphs=[
                {
                    "glyph_id": "A",
                    "create": True,
                    "operations": [
                        {
                            "op": "primitive",
                            "shape": "rectangle",
                            "x": 0,
                            "y": 0,
                            "width": 100,
                            "height": 700,
                            "advance": 400,
                        },
                        {"op": "set_unicodes", "unicodes": [65]},
                    ],
                },
                {
                    "glyph_id": "B",
                    "create": True,
                    "operations": [
                        {"op": "put_component", "component": {"id": "base", "base": "A"}},
                        {"op": "set_unicodes", "unicodes": [66]},
                    ],
                },
            ],
            spacing=[{"op": "advance", "glyph_id": "B", "value": 400}],
        ),
    )
    variation = {
        "axes": [
            {"tag": "wght", "name": "Weight", "minimum": 300, "default": 400, "maximum": 700},
            {"tag": "wdth", "name": "Width", "minimum": 75, "default": 100, "maximum": 125},
        ],
        "masters": [
            {"id": "default", "name": "Regular", "location": {"wght": 400, "wdth": 100}},
            {"id": "light", "name": "Light", "location": {"wght": 300, "wdth": 100}},
            {"id": "bold", "name": "Bold", "location": {"wght": 700, "wdth": 100}},
            {"id": "narrow", "name": "Narrow", "location": {"wght": 400, "wdth": 75}},
            {"id": "wide", "name": "Wide", "location": {"wght": 400, "wdth": 125}},
        ],
    }
    request = m.VariableConfigure(project_id=pid, expected_revision=drawn.revision, variation=variation)
    original = Font.save

    def interrupted(font, path, *args, **kwargs):
        if path.name == "master-bold.ufo":
            raise OSError("Interrupted master write")
        return original(font, path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Font, "save", interrupted)
        with pytest.raises(OSError, match="Interrupted"):
            service.execute("variable_configure", request)
    assert service.store.head(pid)["revision"] == drawn.revision
    current, _ = service.execute("variable_configure", request)
    with pytest.raises(FontError, match="Expected"):
        service.execute("variable_configure", request)
    for master, width in [("light", 80), ("bold", 200), ("narrow", 50), ("wide", 150)]:
        current, _ = service.execute(
            "font_edit",
            m.FontEdit(
                project_id=pid,
                expected_revision=current.revision,
                master_id=master,
                glyphs=[
                    {
                        "glyph_id": "A",
                        "operations": [
                            {
                                "op": "primitive",
                                "shape": "rectangle",
                                "x": 0,
                                "y": 0,
                                "replace": True,
                                "width": width,
                                "height": 700,
                                "advance": 300 + width,
                            },
                        ],
                    }
                ],
                spacing=[{"op": "advance", "glyph_id": "B", "value": 300 + width}],
            ),
        )
    built, _ = service.execute("font_build", m.Build(project_id=pid))
    with TTFont(tmp_path / built.data["files"]["ttf"]["path"]) as font:
        assert len(font["fvar"].axes) == 2
        instance = instantiateVariableFont(font, {"wght": 550, "wdth": 112.5})
        for name in ("A", "B"):
            glyph = instance["glyf"][name]
            assert glyph.xMax - glyph.xMin == 175
            assert instance["hmtx"][name][0] == 475
    rendered, _ = service.execute(
        "render_text",
        m.RenderText(
            project_id=pid,
            text="AB",
            location={"wght": 550},
            detail="full",
        ),
    )
    assert rendered.data["images"][0]["location"] == {"wght": 550, "wdth": 100}
    assert rendered.data["images"][0]["advance_units"][0] == 900
