"""Design intent, reference provenance, geometry and dependency regressions."""

import asyncio
import io
import math
import os

import pytest
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw
from pydantic import ValidationError
from test_acceptance import client
from ufoLib2.objects import Glyph

from font_design_mcp import models as m
from font_design_mcp.domain import FontError
from font_design_mcp.geometry import FlattenPen, filled_spans, join_issues, move_handle, move_node
from font_design_mcp.references import reference_layer
from font_design_mcp.service import TOOLS, Service


def execute(service, tool, **kwargs):
    return service.execute(tool, TOOLS[tool][0].model_validate(kwargs))


def project(tmp_path, spec=None):
    service = Service(tmp_path)
    state, _ = execute(service, "project_create", metadata={"family": "Design test"}, design_spec=spec)
    return service, state.project_id, state.revision


def rectangle(name="A", advance=400, x=40, width=80, unicode=None):
    operations = [
        {
            "op": "primitive",
            "shape": "rectangle",
            "x": x,
            "y": 0,
            "width": width,
            "height": 700,
            "advance": advance,
        }
    ]
    if unicode is not None:
        operations.append({"op": "set_unicodes", "unicodes": [unicode]})
    return {"glyph_id": name, "create": True, "operations": operations}


def oval_data():
    coordinates = [
        (300, 0),
        (500, 0),
        (600, 150),
        (600, 350),
        (600, 550),
        (500, 700),
        (300, 700),
        (100, 700),
        (0, 550),
        (0, 350),
        (0, 150),
        (100, 0),
    ]
    return {
        "advance": 680,
        "unicodes": [79],
        "contours": [
            {
                "id": "oval",
                "points": [
                    {
                        "id": f"p{i}",
                        "x": x,
                        "y": y,
                        "type": "curve" if i % 3 == 0 else "offcurve",
                        "smooth": i % 3 == 0,
                    }
                    for i, (x, y) in enumerate(coordinates)
                ],
            }
        ],
    }


def draw_oval(service, pid, revision):
    state, _ = execute(
        service,
        "glyph_edit",
        project_id=pid,
        expected_revision=revision,
        glyph_id="O",
        create=True,
        operations=[{"op": "replace_glyph", "glyph": oval_data()}],
    )
    return state.revision


def read_font(service, pid):
    return service.store.load(pid)[0]


def point(font, identifier):
    return next(p for p in font["O"].contours[0].points if p.identifier == identifier)


def test_preserve_handles_and_raw_move_are_distinct(tmp_path):
    service, pid, revision = project(tmp_path)
    revision = draw_oval(service, pid, revision)
    before = read_font(service, pid)
    moved, _ = execute(
        service,
        "glyph_edit",
        project_id=pid,
        expected_revision=revision,
        glyph_id="O",
        detail="full",
        operations=[{"op": "move_point", "point_id": "p6", "x": 320, "y": 710, "preserve_handles": True}],
    )
    after = read_font(service, pid)
    for identifier in ("p5", "p6", "p7"):
        assert point(after, identifier).x == point(before, identifier).x + 20
        assert point(after, identifier).y == point(before, identifier).y + 10
    assert set(moved.data["touched_ids"]) == {"p5", "p6", "p7"}
    assert not list(join_issues(after["O"], 3))
    execute(
        service,
        "glyph_edit",
        project_id=pid,
        expected_revision=moved.revision,
        glyph_id="O",
        operations=[{"op": "move_point", "point_id": "p6", "x": 320, "y": 800}],
    )
    assert any(i["point_id"] == "p6" for i in list(join_issues(read_font(service, pid)["O"], 3)))


@pytest.mark.parametrize("handle", ["p1", "p11", "p5", "p7"])
@pytest.mark.parametrize("mode", ["aligned", "symmetric"])
def test_cubic_handle_edit_wraparound_and_modes(tmp_path, handle, mode):
    service, pid, revision = project(tmp_path)
    revision = draw_oval(service, pid, revision)
    glyph = read_font(service, pid)["O"]
    node = glyph.contours[0].points[0 if handle in {"p1", "p11"} else 6]
    opposite = glyph.contours[0].points[{"p1": 11, "p11": 1, "p5": 7, "p7": 5}[handle]]
    old_length = math.hypot(opposite.x - node.x, opposite.y - node.y)
    x, y = node.x + 120, node.y + 25
    result, _ = execute(
        service,
        "glyph_edit",
        project_id=pid,
        expected_revision=revision,
        glyph_id="O",
        detail="full",
        operations=[{"op": "move_handle", "point_id": handle, "x": x, "y": y, "mode": mode}],
    )
    glyph = read_font(service, pid)["O"]
    by_id = {p.identifier: p for p in glyph.contours[0].points}
    other = by_id[opposite.identifier]
    length = math.hypot(other.x - node.x, other.y - node.y)
    assert length == pytest.approx(math.hypot(120, 25) if mode == "symmetric" else old_length)
    assert not any(i["point_id"] == node.identifier for i in join_issues(glyph, 0.01))
    assert set(result.data["touched_ids"]) == {handle, node.identifier, opposite.identifier}


def test_bad_handle_edit_rolls_back_and_corners_are_explicit(tmp_path):
    service, pid, revision = project(tmp_path)
    revision = draw_oval(service, pid, revision)
    for op in [
        {"op": "move_handle", "point_id": "p1", "x": 300, "y": 0},
        {"op": "move_handle", "point_id": "p0", "x": 200, "y": 0},
        {"op": "move_point", "point_id": "p1", "x": 200, "y": 0, "preserve_handles": True},
    ]:
        with pytest.raises(FontError):
            execute(
                service,
                "glyph_edit",
                project_id=pid,
                expected_revision=revision,
                glyph_id="O",
                operations=[op],
            )
        assert service.store.head(pid)["revision"] == revision
    state, _ = execute(
        service,
        "glyph_edit",
        project_id=pid,
        expected_revision=revision,
        glyph_id="O",
        operations=[{"op": "move_point", "point_id": "p6", "x": 350, "y": 800}],
    )
    report, _ = execute(service, "font_analyze", project_id=pid)
    assert not report.data["checks_passed"]
    execute(
        service,
        "glyph_edit",
        project_id=pid,
        expected_revision=state.revision,
        glyph_id="O",
        operations=[{"op": "set_smooth", "point_id": "p6", "smooth": False}],
    )
    report, _ = execute(service, "font_analyze", project_id=pid)
    assert report.data["checks_passed"]
    assert report.data["artistic_approval"] is False


def test_quadratic_controls_are_not_silently_treated_as_cubic():
    from ufoLib2.objects import Contour, Point

    glyph = Glyph("quad")
    glyph.contours.append(
        Contour(
            [
                Point(0, 0, "qcurve", identifier="a", smooth=True),
                Point(100, 0, None, identifier="b"),
                Point(100, 100, "qcurve", identifier="c", smooth=True),
                Point(0, 100, None, identifier="d"),
            ]
        )
    )
    with pytest.raises(ValueError, match="cubic"):
        move_handle(glyph, "b", 80, 0, "aligned")
    assert move_node(glyph, "a", 5, 5) == ["a", "d", "b"]
    glyph.contours[0].points[-1].x = 5
    glyph.contours[0].points[-1].y = 5
    assert any(i["kind"] == "degenerate_tangent" for i in join_issues(glyph, 3))


def test_nonzero_scanlines_holes_overlaps_and_vertices():
    outer = [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]
    inner = [(20, 20), (20, 80), (80, 80), (80, 20), (20, 20)]
    assert filled_spans([outer, inner], "horizontal", 50) == [(0, 20), (80, 100)]
    assert filled_spans([outer, inner], "vertical", 50) == [(0, 20), (80, 100)]
    assert filled_spans([outer, outer], "horizontal", 0) == [(0, 100)]
    assert filled_spans([outer], "horizontal", 100) == []
    assert filled_spans([outer, list(reversed(outer))], "horizontal", 50) == []


def test_flattening_preserves_sources_and_bounds_cost():
    glyph = Glyph("curve")
    pen = glyph.getPen()
    pen.moveTo((0, 0))
    pen.curveTo((0, 100), (100, 100), (100, 0))
    pen.closePath()
    flat = FlattenPen(None)
    glyph.draw(flat)
    spans = filled_spans(flat.contours, "horizontal", 50)
    assert len(spans) == 1 and 70 < spans[0][1] - spans[0][0] < 80
    assert len(glyph.contours[0].points) == 4
    with pytest.raises(ValueError, match="20000"):
        glyph.draw(FlattenPen(None, budget=4))
    loop = FlattenPen(None)
    loop.moveTo((0, 0))
    loop.curveTo((100, 0), (-100, 0), (0, 0))
    loop.closePath()
    assert loop.count > 4  # Do not collapse collinear reversals to a point.


def test_contract_probes_digits_and_missing_coverage(tmp_path):
    spec = {
        "required_characters": "A0123456789",
        "digit_spacing": "tabular",
        "metric_rules": [{"id": "width", "glyphs": ["A"], "metric": "advance", "target": 400}],
        "stroke_probes": [{"id": "stem", "glyph_id": "A", "position": 350, "target": 80}],
    }
    service, pid, revision = project(tmp_path, spec)
    glyphs = [rectangle(unicode=65)] + [
        rectangle(f"digit{i}", advance=610 if i == 3 else 600, unicode=48 + i) for i in range(9)
    ]
    state, _ = execute(service, "font_edit", project_id=pid, expected_revision=revision, glyphs=glyphs)
    report, _ = execute(service, "font_analyze", project_id=pid, detail="full")
    assert report.data["missing_codepoints"] == [57]
    assert any(i["kind"] == "tabular_advance_mismatch" for i in report.data["issues"])
    probe = next(row for row in report.data["measurements"] if row.get("rule_id") == "stem")
    assert probe["actual"] == 80
    assert probe["spans"] == [[40, 120]]
    valid, _ = execute(service, "font_validate", project_id=pid, detail="full")
    assert valid.data["valid"] and valid.data["technical_valid"]
    assert not valid.data["coverage_complete"] and not valid.data["design"]["checks_passed"]
    assert service.store.head(pid)["revision"] == state.revision
    with pytest.raises(FontError) as exc:
        execute(service, "font_build", project_id=pid, require_design_checks=True)
    assert exc.value.code == "design_checks_failed"


def test_export_gate_requires_contract_and_compiles_when_satisfied(tmp_path):
    service, pid, revision = project(tmp_path)
    with pytest.raises(FontError) as exc:
        execute(service, "font_build", project_id=pid, require_design_checks=True)
    assert exc.value.code == "design_contract_missing"
    state, _ = execute(
        service, "font_edit", project_id=pid, expected_revision=revision, glyphs=[rectangle(unicode=65)]
    )
    state, _ = execute(
        service,
        "project_update",
        project_id=pid,
        expected_revision=state.revision,
        design_spec={"required_characters": "A"},
    )
    built, _ = execute(service, "font_build", project_id=pid, require_design_checks=True)
    with TTFont(tmp_path / built.data["files"]["ttf"]["path"]) as font:
        assert 65 in font.getBestCmap()


def test_design_summary_bounded_full_evidence_and_restore(tmp_path):
    service, pid, revision = project(tmp_path)
    state, _ = execute(
        service,
        "project_update",
        project_id=pid,
        expected_revision=revision,
        brief="Preserve my asymmetric bowls",
        design_spec={"required_characters": "abcdefghijklmnopqrstuvwxyz", "protected_features": "square o"},
    )
    summary, _ = execute(service, "font_analyze", project_id=pid)
    assert len(summary.data["issues"]) == 10 and summary.data["truncated"]
    data, _ = service.store.read_resource(summary.data["report_uri"])
    import json

    assert len(json.loads(data)["issues"]) == 26
    info, _ = execute(service, "project_inspect", project_id=pid)
    assert info.data["design_context"]["protected_features"] == "square o"
    assert info.data["design_context"]["brief"] == "Preserve my asymmetric bowls"
    state, _ = execute(
        service,
        "spacing_edit",
        project_id=pid,
        expected_revision=state.revision,
        operations=[{"op": "advance", "glyph_id": "space", "value": 300}],
    )
    assert service.store.load(pid)[1]["schema"] == 3
    execute(
        service, "history_restore", project_id=pid, expected_revision=state.revision, target_revision=revision
    )
    assert "design" not in service.store.load(pid)[1]
    assert service.store.load(pid)[1]["schema"] == 1


def accented(service, pid, revision):
    base = rectangle(unicode=65)
    base["operations"].append(
        {"op": "put_anchor", "anchor": {"id": "top", "name": "top", "x": 190, "y": 700}}
    )
    mark = rectangle("acute", advance=0, x=0, width=20)
    mark["operations"].append(
        {"op": "put_anchor", "anchor": {"id": "attach", "name": "_top", "x": 0, "y": 0}}
    )
    composite = {
        "glyph_id": "Aacute",
        "create": True,
        "operations": [
            {"op": "compose_accent", "base": "A", "mark": "acute", "auto_align": True},
            {"op": "set_unicodes", "unicodes": [193]},
        ],
    }
    state, _ = execute(
        service, "font_edit", project_id=pid, expected_revision=revision, glyphs=[base, mark, composite]
    )
    return state.revision


def test_linked_accent_follows_bearings_and_width_across_restart(tmp_path):
    service, pid, revision = project(tmp_path)
    revision = accented(service, pid, revision)
    service = Service(tmp_path)
    state, _ = execute(
        service,
        "spacing_edit",
        project_id=pid,
        expected_revision=revision,
        operations=[{"op": "bearings", "glyph_id": "A", "left": 80, "right": 90}],
    )
    font = read_font(service, pid)
    assert font["Aacute"].components[1].transformation.dx == 230
    assert font["Aacute"].width == font["A"].width == 250
    assert "Aacute" in state.changed
    assert font["Aacute"].unicodes == [193]


def test_linked_metrics_overrides_require_detach_and_broken_anchor_rolls_back(tmp_path):
    service, pid, revision = project(tmp_path)
    revision = accented(service, pid, revision)
    with pytest.raises(FontError, match="Detach"):
        execute(
            service,
            "spacing_edit",
            project_id=pid,
            expected_revision=revision,
            operations=[{"op": "advance", "glyph_id": "Aacute", "value": 700}],
        )
    with pytest.raises(FontError, match="anchor"):
        execute(
            service,
            "glyph_edit",
            project_id=pid,
            expected_revision=revision,
            glyph_id="A",
            operations=[{"op": "remove", "kind": "anchor", "id": "top"}],
        )
    assert service.store.head(pid)["revision"] == revision
    state, _ = execute(
        service,
        "font_edit",
        project_id=pid,
        expected_revision=revision,
        glyphs=[{"glyph_id": "Aacute", "operations": [{"op": "detach_composition"}]}],
        spacing=[{"op": "advance", "glyph_id": "Aacute", "value": 700}],
    )
    assert read_font(service, pid)["Aacute"].width == 700
    assert service.store.load(pid)[1]["design"]["composition_links"] == {}
    execute(
        service, "history_restore", project_id=pid, expected_revision=state.revision, target_revision=revision
    )
    assert service.store.load(pid)[1]["design"]["composition_links"]["default"]["Aacute"]


def test_linked_compositions_clone_independently_to_masters(tmp_path):
    service, pid, revision = project(tmp_path)
    revision = accented(service, pid, revision)
    variation = {
        "axes": [{"tag": "wght", "name": "Weight", "minimum": 400, "default": 400, "maximum": 700}],
        "masters": [
            {"id": "default", "name": "Regular", "location": {"wght": 400}},
            {"id": "bold", "name": "Bold", "location": {"wght": 700}},
        ],
    }
    state, _ = execute(
        service, "variable_configure", project_id=pid, expected_revision=revision, variation=variation
    )
    execute(
        service,
        "spacing_edit",
        project_id=pid,
        expected_revision=state.revision,
        master_id="bold",
        operations=[{"op": "advance", "glyph_id": "A", "value": 600}],
    )
    font, manifest, _ = service.store.load(pid)
    fonts = service.store.load_masters(pid, manifest, font)
    assert fonts["default"]["Aacute"].width == 400
    assert fonts["bold"]["Aacute"].width == 600


def make_reference(tmp_path, size=(100, 100)):
    inbox = tmp_path / "inbox"
    inbox.mkdir(exist_ok=True)
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).rectangle((10, 10, 40, min(90, size[1] - 1)), fill="black")
    image.save(inbox / "drawing.png")
    return inbox / "drawing.png"


def import_reference(service, pid, revision, **kwargs):
    return execute(
        service,
        "reference_import",
        project_id=pid,
        expected_revision=revision,
        reference_id="sketch",
        glyph_id="A",
        source_path="inbox/drawing.png",
        image_to_font=[1, 0, 0, -1, 0, 100],
        **kwargs,
    )


def test_reference_is_immutable_calibrated_and_not_a_ufo_image(tmp_path):
    service, pid, revision = project(tmp_path)
    source = make_reference(tmp_path)
    state, images = import_reference(service, pid, revision)
    assert len(images) == 1
    reference = state.data["reference"]
    assert reference["image_to_font"] == [1, 0, 0, -1, 0, 100]
    data, _ = service.store.read_resource(reference["uri"])
    source.unlink()
    assert data == service.store.read_resource(reference["uri"])[0]
    state, _ = execute(
        service, "font_edit", project_id=pid, expected_revision=state.revision, glyphs=[rectangle(unicode=65)]
    )
    font, manifest, ufo = service.store.load(pid)
    assert manifest["design"]["references"][0]["id"] == "sketch"
    assert not font["A"].image.fileName and not (ufo / "images").exists()
    normal, normal_images = execute(
        service, "render_glyph", project_id=pid, glyph_id="A", points=False, guides=False
    )
    overlay, overlay_images = execute(
        service,
        "render_glyph",
        project_id=pid,
        glyph_id="A",
        reference_id="sketch",
        points=False,
        guides=False,
    )
    assert normal_images != overlay_images
    assert overlay.data["images"][0]["reference"]["source_sha256"] == reference["source_sha256"]
    assert overlay.data["images"][0]["frame"] == normal.data["images"][0]["frame"]
    artifact = reference["uri"].split("/")[4]
    (tmp_path / pid / "artifacts" / artifact / "image.png").write_bytes(b"changed")
    with pytest.raises(FontError) as exc:
        service.store.load(pid)
    assert exc.value.code == "external_modification"


def test_reference_layer_uses_top_left_down_to_baseline_up():
    source = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(source).rectangle((8, 18, 12, 22), fill="black")
    reference = m.DrawingReference(
        id="sketch",
        glyph_id="A",
        width=100,
        height=100,
        uri=f"font-design://{'0' * 32}/{'1' * 32}/{'2' * 32}/image.png?sha256={'3' * 64}",
        source_sha256="4" * 64,
        encoded_bytes=100,
        image_to_font=(2, 0, 0, -2, 40, 700),
    )
    layer = reference_layer(source, reference, 500, 500, 0.5, 10, 20)
    assert max(layer.getpixel((40, 150))) < 200
    assert layer.getpixel((0, 0)) == (255, 255, 255)


@pytest.mark.parametrize(
    "path",
    [
        "../drawing.png",
        "/tmp/drawing.png",
        "inbox/../../secret.png",
        "inbox\\drawing.png",
        "C:/inbox/drawing.png",
    ],
)
def test_reference_paths_cannot_escape_workspace(tmp_path, path):
    service, pid, revision = project(tmp_path)
    with pytest.raises(FontError) as exc:
        execute(
            service,
            "reference_import",
            project_id=pid,
            expected_revision=revision,
            reference_id="sketch",
            glyph_id="A",
            source_path=path,
            image_to_font=[1, 0, 0, -1, 0, 100],
        )
    assert exc.value.code == "path_denied"
    assert service.store.head(pid)["revision"] == revision


@pytest.mark.parametrize("kind", ["corrupt", "large", "animated", "singular"])
def test_invalid_references_do_not_commit(tmp_path, kind):
    service, pid, revision = project(tmp_path)
    source = make_reference(tmp_path)
    matrix = [1, 0, 0, -1, 0, 100]
    if kind == "corrupt":
        source.write_bytes(b"not a PNG")
    elif kind == "large":
        Image.new("RGB", (2049, 1)).save(source)
    elif kind == "animated":
        Image.new("RGB", (5, 5)).save(
            source, save_all=True, append_images=[Image.new("RGB", (5, 5), "white")]
        )
    else:
        matrix = [0, 0, 0, 0, 0, 0]
    with pytest.raises((FontError, ValidationError)):
        execute(
            service,
            "reference_import",
            project_id=pid,
            expected_revision=revision,
            reference_id="sketch",
            glyph_id="A",
            source_path="inbox/drawing.png",
            image_to_font=matrix,
        )
    assert service.store.head(pid)["revision"] == revision


@pytest.mark.skipif(os.name == "nt", reason="symlink creation requires privileges on Windows")
def test_reference_symlink_and_hardlink_rejected(tmp_path):
    service, pid, revision = project(tmp_path)
    original = make_reference(tmp_path)
    target = tmp_path / "target.png"
    original.rename(target)
    original.symlink_to(target)
    with pytest.raises(FontError) as exc:
        import_reference(service, pid, revision)
    assert exc.value.code == "path_denied"
    original.unlink()
    os.link(target, original)
    with pytest.raises(FontError) as exc:
        import_reference(service, pid, revision)
    assert exc.value.code == "path_denied"


def test_proof_common_scale_missing_glyphs_and_revision_comparison(tmp_path):
    service, pid, revision = project(tmp_path)
    state, _ = execute(
        service,
        "font_edit",
        project_id=pid,
        expected_revision=revision,
        glyphs=[rectangle(), rectangle("B", advance=900, width=750)],
    )
    old = state.revision
    state, _ = execute(
        service,
        "glyph_edit",
        project_id=pid,
        expected_revision=old,
        glyph_id="B",
        operations=[{"op": "transform", "matrix": [1.2, 0, 0, 1, 0, 0]}],
    )
    proof, images = execute(
        service,
        "render_proof",
        project_id=pid,
        glyph_ids=["A", "B", "zero"],
        compare_revision=old,
        detail="full",
    )
    assert len(images) == 2
    current, previous = proof.data["images"]
    assert current["frame"] == previous["frame"]
    assert current["scale"] == previous["scale"]
    assert current["glyphs"][0]["scale"] == current["glyphs"][1]["scale"]
    assert current["missing_glyphs"] == ["zero"]
    assert Image.open(io.BytesIO(images[0])).size == (1024, 256)
    assert service.store.head(pid)["revision"] == state.revision


def test_schema_rejects_unbounded_and_invalid_design_contracts():
    with pytest.raises(ValidationError):
        m.DesignSpec(
            metric_rules=[{"id": "duplicate", "glyphs": ["A"], "metric": "advance", "target": 500}] * 2
        )
    with pytest.raises(ValidationError):
        m.DesignSpec(tangent_tolerance_degrees=float("nan"))
    with pytest.raises(ValidationError):
        m.RenderProof(project_id="0" * 32, glyph_ids=["A"] * 32, columns=8, cell_width=512)


def test_design_reference_and_proof_over_real_mcp(tmp_path):
    make_reference(tmp_path)

    async def run():
        async with client(tmp_path) as session:
            response = await session.call_tool(
                "project_create",
                {"metadata": {"family": "MCP design"}, "design_spec": {"required_characters": "A"}},
            )
            created = response.structured_content
            pid, revision = created["project_id"], created["revision"]
            imported = await session.call_tool(
                "reference_import",
                {
                    "project_id": pid,
                    "expected_revision": revision,
                    "reference_id": "sketch",
                    "glyph_id": "A",
                    "source_path": "inbox/drawing.png",
                    "image_to_font": [1, 0, 0, -1, 0, 100],
                },
            )
            assert not imported.is_error
            assert any(c.type == "image" for c in imported.content)
            revision = imported.structured_content["revision"]
            drawn = await session.call_tool(
                "font_edit",
                {"project_id": pid, "expected_revision": revision, "glyphs": [rectangle(unicode=65)]},
            )
            assert not drawn.is_error
            analyzed = await session.call_tool("font_analyze", {"project_id": pid})
            assert analyzed.structured_content["data"]["checks_passed"]
            proof = await session.call_tool(
                "render_proof", {"project_id": pid, "glyph_ids": ["A", "zero"], "image_mode": "resource"}
            )
            assert not proof.is_error
            assert any(c.type == "resource_link" for c in proof.content)
            uri = proof.structured_content["data"]["images"][0]["uri"]
            contents = await session.read_resource(uri)
            assert contents.contents[0].mime_type == "image/png"
            overlay = await session.call_tool(
                "render_glyph", {"project_id": pid, "glyph_id": "A", "reference_id": "sketch"}
            )
            assert not overlay.is_error and any(c.type == "image" for c in overlay.content)

    asyncio.run(run())


def test_issue_budget_keeps_counts_and_does_not_hide_failure(tmp_path):
    service, pid, revision = project(
        tmp_path, {"required_characters": "".join(chr(i) for i in range(1000, 4000))}
    )
    result, _ = execute(service, "font_analyze", project_id=pid, detail="full")
    assert not result.data["checks_passed"]
    assert result.data["counts"]["issues"] == 3000
    assert len(result.data["issues"]) == 2000 and result.data["issues_truncated"]
    data, _ = service.store.read_resource(result.data["report_uri"])
    assert len(data.encode()) < 4_000_000


def test_font_edit_reports_indirect_accent_changes(tmp_path):
    service, pid, revision = project(tmp_path)
    revision = accented(service, pid, revision)
    state, _ = execute(
        service,
        "font_edit",
        project_id=pid,
        expected_revision=revision,
        glyphs=[
            {
                "glyph_id": "A",
                "operations": [
                    {
                        "op": "put_anchor",
                        "replace": True,
                        "anchor": {"id": "top", "name": "top", "x": 220, "y": 710},
                    }
                ],
            }
        ],
    )
    assert "Aacute" in state.changed
    assert read_font(service, pid)["Aacute"].components[1].transformation.dx == 220


def test_reference_replace_remove_and_restore_keep_original_evidence(tmp_path):
    service, pid, revision = project(tmp_path)
    source = make_reference(tmp_path)
    first, _ = import_reference(service, pid, revision)
    old_uri = first.data["reference"]["uri"]
    Image.new("RGB", (10, 10), "black").save(source)
    with pytest.raises(FontError):
        import_reference(service, pid, first.revision)
    replaced, _ = import_reference(service, pid, first.revision, replace=True)
    assert replaced.data["reference"]["uri"] != old_uri
    removed, _ = execute(
        service,
        "project_update",
        project_id=pid,
        expected_revision=replaced.revision,
        remove_reference_ids=["sketch"],
    )
    assert service.store.load(pid)[1]["design"]["references"] == []
    assert service.store.read_resource(old_uri)[0]
    execute(
        service,
        "history_restore",
        project_id=pid,
        expected_revision=removed.revision,
        target_revision=first.revision,
    )
    assert service.store.load(pid)[1]["design"]["references"][0]["uri"] == old_uri


def test_reference_cannot_borrow_another_projects_asset(tmp_path):
    service, first_pid, revision = project(tmp_path)
    make_reference(tmp_path)
    first, _ = import_reference(service, first_pid, revision)
    other, _ = execute(service, "project_create", metadata={"family": "Other"})
    font, _, _ = service.store.load(other.project_id)
    state = m.DesignState(references=[m.DrawingReference.model_validate(first.data["reference"])])
    with service.store.lock(other.project_id), pytest.raises(FontError) as exc:
        service.store.commit(
            other.project_id,
            font,
            {"brief": "", "decisions": [], "design": state.model_dump()},
            "cross-project reference",
            other.revision,
        )
    assert exc.value.code == "path_denied"


def test_reference_count_and_project_byte_budget():
    ref = {
        "id": "r0",
        "glyph_id": "A",
        "width": 10,
        "height": 10,
        "image_to_font": [1, 0, 0, -1, 0, 100],
        "encoded_bytes": 100,
        "source_sha256": "3" * 64,
        "uri": f"font-design://{'0' * 32}/{'1' * 32}/{'2' * 32}/image.png?sha256={'3' * 64}",
    }
    references = [dict(ref, id=f"r{i}") for i in range(64)]
    assert len(m.DesignState(references=references).references) == 64
    with pytest.raises(ValidationError):
        m.DesignState(references=[dict(r, encoded_bytes=2_000_000) for r in references])
    with pytest.raises(ValidationError):
        m.DesignState(references=references + [dict(ref, id="r64")])


def test_report_size_limit_is_enforced_before_publication(tmp_path):
    service, pid, revision = project(tmp_path)
    with pytest.raises(FontError) as exc:
        service.store.save_report(pid, revision, {"oversized": "x" * 4_000_001})
    assert exc.value.code == "limit_exceeded"
    assert not (tmp_path / pid / "artifacts").exists()
