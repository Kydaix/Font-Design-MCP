"""Regressions from the UniSlaw audit: feature reachability and misleading design checks."""

import io
from copy import deepcopy

import pytest
import uharfbuzz as hb
from fontTools.ttLib import TTFont
from pydantic import ValidationError
from test_design import draw_oval, execute, project, rectangle
from test_variable import VARIATION

from font_design_mcp import models as m
from font_design_mcp.domain import FontError
from font_design_mcp.layout import compiler_font, validate_latin_marks


def anchor(name, x, y):
    return {"op": "put_anchor", "anchor": {"id": name, "name": name, "x": x, "y": y}}


def shape(binary, text, weight=None):
    binary.flavor = None
    stream = io.BytesIO()
    binary.save(stream)
    font = hb.Font(hb.Face(stream.getvalue()))
    font.scale = (1000, 1000)
    if weight is not None:
        font.set_variations({"wght": weight})
    buffer = hb.Buffer()
    buffer.add_str(text)
    buffer.guess_segment_properties()
    hb.shape(font, buffer)
    return buffer.glyph_infos, buffer.glyph_positions


@pytest.mark.parametrize("variable", [False, True])
def test_latin_marks_and_kerning_reach_harfbuzz_in_both_formats(tmp_path, variable):
    service, pid, revision = project(tmp_path)
    glyphs = []
    for name, code, x, y in [("q", 113, 180, 710), ("x", 120, 220, 730)]:
        glyph = rectangle(name, unicode=code)
        glyph["operations"].append(anchor("top", x, y))
        glyphs.append(glyph)
    for name, code, x, y in [("acutecomb", 769, 10, 20), ("dieresiscomb", 776, 20, 10)]:
        glyph = rectangle(name, advance=0, x=-30, width=60, unicode=code)
        glyph["operations"][0]["height"] = 60
        glyph["operations"].append(anchor("_top", x, y))
        glyphs.append(glyph)
    edited, _ = execute(
        service,
        "font_edit",
        project_id=pid,
        expected_revision=revision,
        glyphs=glyphs,
        spacing=[{"op": "kern_pair", "left": "q", "right": "q", "value": -30}],
    )
    if variable:
        edited, _ = execute(
            service,
            "variable_configure",
            project_id=pid,
            expected_revision=edited.revision,
            variation=VARIATION,
        )
        edited, _ = execute(
            service,
            "font_edit",
            project_id=pid,
            expected_revision=edited.revision,
            master_id="bold",
            glyphs=[
                {"glyph_id": name, "operations": [{**anchor("top", x + 100, y + 60), "replace": True}]}
                for name, x, y in [("q", 180, 710), ("x", 220, 730)]
            ],
            spacing=[
                {"op": "advance", "glyph_id": "q", "value": 600},
                {"op": "advance", "glyph_id": "x", "value": 600},
                {"op": "kern_pair", "left": "q", "right": "q", "value": -70},
            ],
        )
    source, manifest, _ = service.store.load(pid)
    original = manifest["source_sha256"]
    assert not source.features.text
    prepared = compiler_font(source)
    assert "languagesystem latn dflt;" in prepared.features.text
    assert not source.features.text
    built, _ = execute(service, "font_build", project_id=pid)
    assert built.data["layout"]["status"] == "passed"
    assert built.data["layout"]["expected_pairs"] == 4
    for fmt in ("ttf", "woff2"):
        with TTFont(tmp_path / built.data["files"][fmt]["path"]) as binary:
            for weight, shift in [(300, 0), (500, 0.5), (700, 1)] if variable else [(None, 0)]:
                for text, expected_x, expected_y in [("q\u0301", -230, 690), ("x\u0308", -200, 720)]:
                    infos, positions = shape(binary, text, weight)
                    assert len(infos) == 2
                    assert positions[1].x_advance == 0
                    assert positions[1].x_offset == pytest.approx(expected_x - 100 * shift, abs=1)
                    assert positions[1].y_offset == pytest.approx(expected_y + 60 * shift, abs=1)
                _, kerned = shape(binary, "qq", weight)
                assert sum(p.x_advance for p in kerned) == pytest.approx(770 + 360 * shift, abs=1)
            # A GPOS table and a mark feature alone are insufficient: they must be active in latn.
            latin = next(
                r.Script for r in binary["GPOS"].table.ScriptList.ScriptRecord if r.ScriptTag == "latn"
            )
            records = binary["GPOS"].table.FeatureList.FeatureRecord
            latin.DefaultLangSys.FeatureIndex = [
                i for i in latin.DefaultLangSys.FeatureIndex if records[i].FeatureTag != "mark"
            ]
            with pytest.raises(FontError, match="unreachable"):
                validate_latin_marks(binary, source)
    cached, _ = execute(service, "font_build", project_id=pid)
    assert cached.data["cache_hit"]
    service.store.verify(pid, edited.revision)
    after, after_manifest, _ = service.store.load(pid)
    assert after_manifest["source_sha256"] == original and not after.features.text


def variable_strokes(tmp_path, widths=(100, 300), spec=None):
    service, pid, revision = project(tmp_path, spec)
    edited, _ = execute(
        service,
        "font_edit",
        project_id=pid,
        expected_revision=revision,
        glyphs=[rectangle("N", width=widths[0], unicode=78)],
    )
    configuration = deepcopy(VARIATION)
    if len(widths) == 3:
        configuration["masters"].insert(1, {"id": "middle", "name": "Middle", "location": {"wght": 500}})
    edited, _ = execute(
        service,
        "variable_configure",
        project_id=pid,
        expected_revision=edited.revision,
        variation=configuration,
    )
    for master, width in zip(configuration["masters"][1:], widths[1:]):
        operation = rectangle("N", width=width)["operations"][0]
        operation["replace"] = True
        edited, _ = execute(
            service,
            "glyph_edit",
            project_id=pid,
            expected_revision=edited.revision,
            master_id=master["id"],
            glyph_id="N",
            operations=[operation],
        )
    return service, pid, edited.revision


def trend(**extra):
    return {
        "id": "N-weight",
        "glyph_id": "N",
        "axis": "horizontal",
        "position": 400,
        "axis_tag": "wght",
        "values": [300, 500, 700],
        "minimum_change": 50,
        **extra,
    }


@pytest.mark.parametrize(
    "widths,kind",
    [
        ((240, 160), "variation_direction_mismatch"),
        ((200, 200), "variation_change_insufficient"),
        ((100, 400, 300), "variation_direction_mismatch"),
    ],
)
def test_inverted_frozen_and_interior_weight_fail_export_gate(tmp_path, widths, kind):
    service, pid, _ = variable_strokes(
        tmp_path,
        widths,
        {"required_characters": "N", "variation_probes": [trend()]},
    )
    for master in ("default", "bold"):
        report, _ = execute(service, "font_analyze", project_id=pid, master_id=master, detail="full")
        assert not report.data["checks_passed"]
        assert any(i["kind"] == kind for i in report.data["issues"])
        samples = report.data["variation"]["measurements"][0]["samples"]
        expected = list(widths) if len(widths) == 3 else [widths[0], sum(widths) / 2, widths[1]]
        assert [s["actual"] for s in samples] == pytest.approx(expected)
        assert report.data["scope"]["variation"] == "checked"
    validation, _ = execute(service, "font_validate", project_id=pid)
    assert validation.data["technical_valid"] and not validation.data["design"]["checks_passed"]
    with pytest.raises(FontError, match="Variation:"):
        execute(service, "font_build", project_id=pid, require_design_checks=True)
    assert not list((tmp_path / pid / "artifacts").rglob("font.ttf"))
    ungated, _ = execute(service, "font_build", project_id=pid)
    assert ungated.data["design_gate"] == "not_requested"


def test_dense_samples_cannot_hide_cumulative_reversal(tmp_path):
    service, pid, _ = variable_strokes(
        tmp_path,
        (100, 120, 116),
        {"variation_probes": [trend(values=list(range(300, 701, 50)), minimum_change=0)]},
    )
    report, _ = execute(service, "font_analyze", project_id=pid, detail="full")
    assert not report.data["checks_passed"]
    issue = next(i for i in report.data["issues"] if i["kind"] == "variation_direction_mismatch")
    assert issue["from"]["location"]["wght"] == 500
    assert issue["to"]["actual"] < 118


def test_decreasing_direction_and_unmeasurable_samples(tmp_path):
    spec = {"required_characters": "N", "variation_probes": [trend(direction="nonincreasing")]}
    service, pid, revision = variable_strokes(tmp_path, (300, 100), spec)
    result, _ = execute(service, "font_analyze", project_id=pid)
    assert result.data["checks_passed"]
    spec["variation_probes"][0]["position"] = 800
    execute(service, "project_update", project_id=pid, expected_revision=revision, design_spec=spec)
    result, _ = execute(service, "font_analyze", project_id=pid, detail="full")
    assert not result.data["checks_passed"]
    assert any(i["kind"] == "unmeasurable" for i in result.data["issues"])
    with pytest.raises(FontError, match="Variation:"):
        execute(service, "font_build", project_id=pid, require_design_checks=True)


def test_location_rule_on_static_font_requires_configuration(tmp_path):
    service, pid, _ = project(
        tmp_path,
        {
            "metric_rules": [
                {"id": "width", "glyphs": ["space"], "metric": "advance", "target": 250, "location": {}}
            ],
        },
    )
    with pytest.raises(FontError, match="require a variable font"):
        execute(service, "font_analyze", project_id=pid)


def test_master_targets_and_compiled_intermediate_targets(tmp_path):
    spec = {
        "required_characters": "N",
        "stroke_probes": [
            {"id": "light", "glyph_id": "N", "position": 400, "target": 100, "master_id": "default"},
            {"id": "heavy", "glyph_id": "N", "position": 400, "target": 300, "master_id": "bold"},
            {"id": "halfway", "glyph_id": "N", "position": 400, "target": 200, "location": {"wght": 500}},
            {"id": "origin", "glyph_id": "N", "position": 400, "target": 100, "location": {}},
        ],
        "metric_rules": [
            {
                "id": "intermediate-width",
                "glyphs": ["N"],
                "metric": "visible_width",
                "target": 200,
                "location": {"wght": 500},
            },
        ],
        "variation_probes": [trend()],
    }
    service, pid, revision = variable_strokes(tmp_path, spec=spec)
    for master, rule in [("default", "light"), ("bold", "heavy")]:
        result, _ = execute(service, "font_analyze", project_id=pid, master_id=master, detail="full")
        assert result.data["checks_passed"]
        assert [row["rule_id"] for row in result.data["measurements"]] == [rule]
        assert result.data["scope"]["rules_for_other_masters"] == 1
        assert result.data["variation"]["checks_passed"]
    built, _ = execute(service, "font_build", project_id=pid, require_design_checks=True)
    assert built.data["design_gate"] == "passed"
    spec["stroke_probes"][2]["target"] = 240
    execute(service, "project_update", project_id=pid, expected_revision=revision, design_spec=spec)
    with pytest.raises(FontError, match="Variation:"):
        execute(service, "font_build", project_id=pid, require_design_checks=True)


@pytest.mark.parametrize(
    "rule",
    [
        {"master_id": "typo"},
        {"location": {"wdth": 100}},
        {"location": {"wght": 800}},
    ],
)
def test_invalid_scopes_are_never_silently_skipped(tmp_path, rule):
    spec = {"stroke_probes": [{"id": "probe", "glyph_id": "N", "position": 400, "target": 100, **rule}]}
    service, pid, _ = variable_strokes(tmp_path, spec=spec)
    with pytest.raises(FontError, match="(master|location)"):
        execute(service, "font_analyze", project_id=pid)


def test_scope_and_sample_schema_reject_ambiguous_requests():
    with pytest.raises(ValidationError):
        m.StrokeProbe(id="x", glyph_id="N", position=400, target=100, master_id="default", location={})
    for override in [
        {"values": [700, 300]},
        {"values": [300, 300]},
        {"values": [300, float("nan")]},
        {"location": {"wght": 300}},
    ]:
        with pytest.raises(ValidationError):
            m.VariationProbe(**trend(**override))


def test_unmarked_curve_cusps_are_visible_but_not_assumed_errors(tmp_path):
    service, pid, revision = project(tmp_path)
    revision = draw_oval(service, pid, revision)
    execute(
        service,
        "glyph_edit",
        project_id=pid,
        expected_revision=revision,
        glyph_id="O",
        operations=[
            {"op": "set_smooth", "point_id": "p0", "smooth": False},
            {"op": "move_point", "point_id": "p1", "x": 500, "y": 100},
        ],
    )
    report, _ = execute(service, "font_analyze", project_id=pid, detail="full")
    assert report.data["checks_passed"]
    assert report.data["scope"]["smooth_joins_checked"] == 3
    assert report.data["scope"]["stroke_probes_checked"] == 0
    assert report.data["scope"]["variation"] == "not_requested"
    assert report.data["counts"]["review_candidates"] == 1
    assert report.data["review_candidates"][0]["point_id"] == "p0"
    assert not report.data["artistic_approval"]
    assert "visual quality not assessed" in report.summary
