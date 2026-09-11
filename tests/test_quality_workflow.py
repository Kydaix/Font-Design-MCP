"""Observable regressions from the UniSlaw audit, including previously passing false positives."""

import copy

import pytest
from PIL import Image, ImageDraw
from test_design import execute, project
from test_quality import K, contract, font_with, polygon, proofs, ready_source, review
from test_variable import VARIATION

from font_design_mcp import models as m
from font_design_mcp.design import analyze_font
from font_design_mcp.domain import FontError
from font_design_mcp.geometry import FlattenPen
from font_design_mcp.interpolation import analyze_sources, sample_locations
from font_design_mcp.quality import measure_profile


@pytest.mark.parametrize("text", [" ", "   ", "H", "H H"])
def test_usage_evidence_requires_adjacent_visible_glyphs(tmp_path, text):
    service, pid, revision = ready_source(tmp_path)
    result, _ = execute(service, "render_text", project_id=pid, text=text, sizes=[24, 72])
    uri = result.data["images"][0]["report_uri"]
    with pytest.raises(FontError, match="visible shaped glyphs"):
        review(service, pid, revision, [uri])
    revised, _ = execute(
        service,
        "proof_review",
        project_id=pid,
        revision=revision,
        proof_uris=[uri],
        verdict="revise",
        observation="Negative fixture: this text does not demonstrate spacing in words.",
    )
    assert revised.data["verdict"] == "revise"


def test_region_coverage_cannot_be_satisfied_by_renaming_a_stem_probe():
    f = font_with("K", polygon(K, 75, 774))
    spec = m.DesignSpec(
        stroke_probes=[m.StrokeProbe(id="all-K-branches", glyph_id="K", position=100, target=137.2)]
    )
    report = analyze_font(f, spec)
    assert {"K.upper_branch", "K.lower_branch", "K.junction"} <= set(
        report["design_coverage"]["unmeasured_regions"]
    )
    rect = polygon([(40, 0), (140, 0), (140, 700), (40, 700)], 89)
    report = analyze_font(font_with("Y", rect), m.DesignSpec())
    assert any(r["kind"] == "latin_structure_unexpected" for r in report["review_candidates"])


def test_distinct_samples_are_required_for_regional_measurement():
    f = font_with("K", polygon(K, 75, 774))
    spec = m.DesignSpec(
        stroke_probes=[
            m.StrokeProbe(id=f"copy{i}", glyph_id="K", position=200, target=137.2) for i in range(4)
        ]
    )
    report = analyze_font(f, spec)
    stem = next(r for r in report["design_coverage"]["regions"] if r["id"] == "K.stem")
    assert stem["sample_count"] == 1 and not stem["covered"]
    plan = report["evidence_plan"]
    assert plan["status"] == "proposed_not_measured_or_reviewed"
    assert all(r["target"] is None for r in plan["regions"])
    assert next(r for r in plan["regions"] if r["region_id"] == "K.lower_branch")["font_bounds"][1] > 0


def test_release_tracks_requested_word_sequences(tmp_path):
    service, pid, revision = ready_source(tmp_path)
    spec = contract()
    spec["usage_texts"] = ["HHHH"]
    edited, _ = execute(
        service, "project_update", project_id=pid, expected_revision=revision, design_spec=spec
    )
    revision = edited.revision
    accepted = review(service, pid, revision, proofs(service, pid, revision))
    check, _ = execute(service, "font_release_check", project_id=pid, review_uris=[accepted])
    assert any(r["kind"] == "usage_sequences_missing" for r in check.data["reasons"])


NETWORK = {
    "parameters": {"stem": 100},
    "strokes": [{"id": "diagonal", "path": "M 100 100 L 500 600", "width_parameter": "stem"}],
    "advance": 900,
}


def test_linked_centerlines_keep_normal_width_when_widened(tmp_path):
    service, pid, revision = project(tmp_path)
    edited, _ = execute(
        service,
        "glyph_edit",
        project_id=pid,
        expected_revision=revision,
        glyph_id="branch",
        create=True,
        operations=[{"op": "stroke_network", "network": NETWORK}],
    )
    first = edited.revision
    edited, _ = execute(
        service,
        "glyph_edit",
        project_id=pid,
        expected_revision=first,
        glyph_id="branch",
        operations=[{"op": "update_stroke_network", "horizontal_scale": 1.5, "parameters": {"stem": 160}}],
    )
    font, manifest, _ = service.store.load(pid)
    assert manifest["schema"] == 5
    pen = FlattenPen(font)
    font["branch"].draw(pen)
    profile = m.StrokeProfile(
        id="width", glyph_id="branch", start=(330, 250), end=(510, 400), minimum=159.9, maximum=160.1
    )
    measured = measure_profile(pen.contours, profile, 0.25)
    assert measured["checks_passed"]
    point = font["branch"].contours[0].points[0]
    with pytest.raises(FontError, match="detach"):
        execute(
            service,
            "glyph_edit",
            project_id=pid,
            expected_revision=edited.revision,
            glyph_id="branch",
            operations=[{"op": "move_point", "point_id": point.identifier, "x": 20, "y": 20}],
        )
    assert service.store.head(pid)["revision"] == edited.revision
    execute(
        service,
        "glyph_edit",
        project_id=pid,
        expected_revision=edited.revision,
        glyph_id="branch",
        operations=[
            {"op": "detach_stroke_network"},
            {"op": "move_point", "point_id": point.identifier, "x": 20, "y": 20},
        ],
    )
    old, _, _ = service.store.load(pid, first)
    assert old["branch"].lib["io.font-design-mcp.stroke-network"]["parameters"]["stem"] == 100


def test_inspection_sections_and_each_collection_pagination(tmp_path):
    service, pid, revision = ready_source(tmp_path)
    glyphs = [
        {
            "glyph_id": f"helper{i}",
            "create": True,
            "operations": [{"op": "replace_glyph", "glyph": {"advance": 100}}],
        }
        for i in range(60)
    ]
    spacing = [{"op": "kern_pair", "left": "H", "right": f"helper{i}", "value": -i} for i in range(60)]
    execute(service, "font_edit", project_id=pid, expected_revision=revision, glyphs=glyphs, spacing=spacing)
    focused, _ = execute(
        service, "project_inspect", project_id=pid, detail="full", sections=["design"], limit=12
    )
    assert (
        "design_spec" in focused.data
        and "kerning" not in focused.data
        and "composition_links" not in focused.data
    )
    first, _ = execute(
        service, "project_inspect", project_id=pid, detail="full", sections=["spacing"], limit=12
    )
    second, _ = execute(
        service, "project_inspect", project_id=pid, detail="full", sections=["spacing"], limit=12, offset=12
    )
    assert len(first.data["kerning"]) == 12 and first.data["pagination"]["kerning"]["total"] == 60
    assert first.data["kerning"] != second.data["kerning"]
    local, _ = execute(
        service,
        "project_inspect",
        project_id=pid,
        detail="full",
        glyph_ids=["helper7"],
        sections=["spacing", "glyphs"],
    )
    assert len(local.data["kerning"]) == 1 and local.data["glyphs"] == ["helper7"]


def test_fonttools_detects_cyclic_point_start_mismatch():
    left = font_with("Y", polygon([(40, 0), (140, 0), (140, 700), (40, 700)], 89))
    right = copy.deepcopy(left)
    points = right["Y"].contours[0].points
    positions = [(p.x, p.y) for p in points[2:] + points[:2]]
    for point, position in zip(points, positions):
        point.x, point.y = position
    result = analyze_sources({"default": left, "bold": right})
    assert result["complete"]
    assert any(r["type"] == "wrong_start_point" for r in result["findings"])


def test_axis_grid_includes_corners_midpoints_and_master_locations():
    variation = {
        "axes": [{"tag": tag, "minimum": 0, "default": 0.2, "maximum": 1} for tag in ["wght", "wdth"]],
        "masters": [{"location": {"wght": 0.2, "wdth": 0.2}}],
    }
    grid = sample_locations(variation)
    assert len(grid) == 10
    assert {"wght": 0.5, "wdth": 0.5} in grid and {"wght": 1, "wdth": 0} in grid


def test_normal_variation_detects_local_reversal_in_compiled_font(tmp_path):
    service, pid, revision = project(tmp_path)
    changed, _ = execute(
        service,
        "glyph_edit",
        project_id=pid,
        expected_revision=revision,
        glyph_id="branch",
        create=True,
        operations=[{"op": "stroke_network", "network": NETWORK}],
    )
    configured, _ = execute(
        service, "variable_configure", project_id=pid, expected_revision=changed.revision, variation=VARIATION
    )
    changed, _ = execute(
        service,
        "glyph_edit",
        project_id=pid,
        expected_revision=configured.revision,
        master_id="bold",
        glyph_id="branch",
        operations=[{"op": "update_stroke_network", "parameters": {"stem": 60}}],
    )
    spec = {
        "variation_profiles": [
            {
                "id": "normal-weight",
                "glyph_id": "branch",
                "start": [220, 250],
                "end": [340, 400],
                "minimum": 40,
                "maximum": 120,
                "axis_tag": "wght",
                "values": [300, 500, 700],
                "direction": "nondecreasing",
            }
        ]
    }
    execute(service, "project_update", project_id=pid, expected_revision=changed.revision, design_spec=spec)
    report, _ = execute(service, "font_analyze", project_id=pid, detail="full")
    assert not report.data["checks_passed"]
    assert any(r["kind"] == "variation_direction_mismatch" for r in report.data["issues"])


def test_crop_preserves_page_and_calibration_and_detects_page_tampering(tmp_path):
    service, pid, revision = ready_source(tmp_path)
    inbox = service.store.root / "inbox"
    inbox.mkdir()
    img = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(img).rectangle((20, 20, 39, 79), fill="black")
    img.save(inbox / "page.png")
    imported, _ = execute(
        service,
        "reference_import",
        project_id=pid,
        expected_revision=revision,
        reference_id="H-page",
        glyph_id="H",
        source_path="inbox/page.png",
        image_to_font=[1, 0, 0, -1, 0, 100],
        crop=[10, 10, 60, 90],
    )
    ref = imported.data["reference"]
    assert ref["image_to_font"] == (1.0, 0.0, 0.0, -1.0, 10.0, 90.0) or ref["image_to_font"] == [
        1.0,
        0.0,
        0.0,
        -1.0,
        10.0,
        90.0,
    ]
    assert ref["width"] == 50 and ref["source_page_uri"]
    rendered, _ = execute(
        service,
        "render_glyph",
        project_id=pid,
        glyph_id="H",
        reference_id="H-page",
        comparison_mode="difference",
        detail="full",
    )
    assert rendered.data["images"][0]["reference_comparison"]["intersection_over_union"] is not None
    page_id = ref["source_page_uri"].split("/")[4]
    page = service.store.project(pid) / "artifacts" / page_id / "image.png"
    page.write_bytes(b"changed")
    with pytest.raises(FontError):
        service.store.load(pid)


def test_arbitrary_glyph_lib_is_still_rejected():
    from font_design_mcp.domain import validate_font

    font = font_with("H", polygon(K, 72, 774))
    font["H"].lib["public.skipExportGlyphs"] = ["H"]
    with pytest.raises(FontError, match="Arbitrary glyph lib"):
        validate_font(font)


def test_variable_export_has_stat_values_and_ordered_instances(tmp_path):
    from fontTools.ttLib import TTFont

    service, pid, revision = ready_source(tmp_path)
    # Put the heaviest source first: serialization order must not become presentation order.
    variation = copy.deepcopy(VARIATION)
    variation["axes"][0]["default"] = 700
    variation["masters"][0]["location"]["wght"] = 700
    variation["masters"][1]["location"]["wght"] = 300
    execute(service, "variable_configure", project_id=pid, expected_revision=revision, variation=variation)
    exported, _ = execute(service, "font_build", project_id=pid, formats=["ttf", "woff2"])
    for artifact in exported.data["files"].values():
        with TTFont(service.store.root / artifact["path"]) as binary:
            assert [instance.coordinates["wght"] for instance in binary["fvar"].instances] == [300, 700]
            values = binary["STAT"].table.AxisValueArray.AxisValue
            assert {value.Value for value in values} == {300, 700}
            assert next(v for v in values if v.Value == 700).Flags & 2
            assert not any(name.platformID == 1 for name in binary["name"].names)


def test_interpolation_evidence_rejects_a_different_binary(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from font_design_mcp.interpolation import inspect_interpolation

    service, pid, revision = ready_source(tmp_path)
    monkeypatch.setattr(
        "font_design_mcp.interpolation.subprocess.run",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {"status": "checked", "checks_passed": True, "binary_sha256": "0" * 64}
            ).encode(),
        ),
    )
    with pytest.raises(FontError, match="differs from the verified compiler output"):
        inspect_interpolation(
            service.store,
            pid,
            {"revision": revision, "variation": VARIATION},
            tmp_path / "font.ttf",
            "1" * 64,
        )


def test_source_correspondence_is_gated_through_real_worker(tmp_path):
    service, pid, revision = ready_source(tmp_path)
    configured, _ = execute(
        service, "variable_configure", project_id=pid, expected_revision=revision, variation=VARIATION
    )
    font, manifest, _ = service.store.load(pid)
    masters = service.store.load_masters(pid, manifest, font)
    # H's 12 line nodes retain types but rotate semantic correspondence by half a contour.
    points = masters["bold"]["H"].contours[0].points
    coords = [(p.x, p.y) for p in points[len(points) // 2 :] + points[: len(points) // 2]]
    for point, (x, y) in zip(points, coords):
        point.x, point.y = x, y
    extra = {k: manifest[k] for k in ["brief", "decisions", "variation", "design"]}
    with service.store.lock(pid):
        service.store.commit(
            pid,
            font,
            extra,
            "Synthetic point-order regression",
            expected=configured.revision,
            masters=masters,
        )
    result, _ = execute(service, "font_analyze", project_id=pid, interpolation=True)
    assert not result.data["checks_passed"]
    assert not result.data["interpolation"]["checks_passed"]
    with pytest.raises(FontError, match="Interpolation checks failed"):
        execute(service, "font_build", project_id=pid, require_design_checks=True)
