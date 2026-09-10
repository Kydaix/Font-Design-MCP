"""Seeded typographic faults, normal measurements and proof-to-release evidence contracts."""

import asyncio
import json
import math

import pytest
from pydantic import ValidationError
from test_acceptance import call, client
from test_design import execute, project
from test_variable import VARIATION

from font_design_mcp import models as m
from font_design_mcp.design import analyze_font
from font_design_mcp.domain import FontError, new_font, replace_glyph
from font_design_mcp.geometry import FlattenPen
from font_design_mcp.quality import expects_ink, measure_profile, outline_key

H = [
    (40, 0),
    (140, 0),
    (140, 300),
    (460, 300),
    (460, 0),
    (560, 0),
    (560, 700),
    (460, 700),
    (460, 400),
    (140, 400),
    (140, 700),
    (40, 700),
]
# Real defect from the UniSlaw Semibold investigation: the lower K branch tapers.
K = [
    (32, 0),
    (169.2, 0),
    (169.2, 216),
    (296, 303),
    (606.172, 0),
    (742, 0),
    (437, 414),
    (726, 700),
    (540.78, 700),
    (169.2, 367),
    (169.2, 700),
    (32, 700),
]


def polygon(points, code=72, width=600):
    return {
        "advance": width,
        "unicodes": [code],
        "contours": [
            {
                "id": "c0",
                "points": [
                    {"id": f"p{i}", "x": x, "y": y, "type": "line"} for i, (x, y) in enumerate(points)
                ],
            }
        ],
    }


def font_with(name="H", data=None):
    f = new_font(m.Metadata(family="Quality fixture"), m.Metrics())
    replace_glyph(f.newGlyph(name), m.Glyph.model_validate(data or polygon(H)))
    return f


def contract():
    return {
        "required_characters": "H",
        "reference_glyphs": ["H"],
        "stroke_probes": [{"id": "H-stem", "glyph_id": "H", "position": 200, "target": 100, "tolerance": 1}],
    }


def ready_source(tmp_path):
    service, pid, revision = project(tmp_path, contract())
    state, _ = execute(
        service,
        "glyph_edit",
        project_id=pid,
        expected_revision=revision,
        glyph_id="H",
        create=True,
        operations=[{"op": "replace_glyph", "glyph": polygon(H)}],
    )
    return service, pid, state.revision


def proofs(service, pid, revision, names=None, master_id="default", location=None):
    sheet, _ = execute(
        service,
        "render_proof",
        project_id=pid,
        revision=revision,
        glyph_ids=names or ["H"],
        master_id=master_id,
    )
    uris = [sheet.data["images"][0]["report_uri"]]
    for kern in [True, False]:
        result, _ = execute(
            service,
            "render_text",
            project_id=pid,
            revision=revision,
            text="HHH HHH",
            sizes=[24, 72],
            kern=kern,
            location=location or {},
        )
        uris.append(result.data["images"][0]["report_uri"])
    return uris


def review(service, pid, revision, uris, **extra):
    result, _ = execute(
        service,
        "proof_review",
        project_id=pid,
        revision=revision,
        proof_uris=uris,
        verdict="accept",
        observation="Fixture review: examined stems, junctions and spacing at both sizes.",
        **extra,
    )
    return result.data["report_uri"]


@pytest.mark.parametrize("code", [32, 0x00A0, 0x034F, 0x200B, 0x2060, 0xFEFF, 0xFE0F, 0xE0100])
def test_expected_invisible_characters_remain_valid(code):
    assert not expects_ink(code)
    f = font_with("invisible", {"advance": 0, "unicodes": [code]})
    assert analyze_font(f, m.DesignSpec())["outline_integrity_passed"]


@pytest.mark.parametrize("code", [65, 0x00C9, 0x0218, 0x0301, 0x20AC, 0x1E9E])
def test_visible_letters_marks_and_symbols_cannot_be_empty(code):
    f = font_with("missingInk", {"advance": 600, "unicodes": [code]})
    report = analyze_font(f, m.DesignSpec())
    assert not report["checks_passed"]
    assert any(r["kind"] == "empty_visible_glyph" for r in report["issues"])


def test_cancelled_winding_and_collapsed_components_are_not_ink():
    f = font_with()
    data = polygon(H)
    second = {
        "id": "c1",
        "points": [dict(p, id=f"q{i}") for i, p in enumerate(reversed(data["contours"][0]["points"]))],
    }
    data["contours"].append(second)
    replace_glyph(f["H"], m.Glyph.model_validate(data))
    assert not analyze_font(f, m.DesignSpec())["outline_integrity_passed"]
    f = font_with()
    replace_glyph(
        f.newGlyph("M"),
        m.Glyph(unicodes=[77], components=[m.Component(id="base", base="H", transform=(0, 0, 0, 1, 0, 0))]),
    )
    report = analyze_font(f, m.DesignSpec())
    assert any(r["kind"] == "empty_visible_glyph" and r["glyph"] == "M" for r in report["issues"])


def test_crossing_has_ink_and_degenerate_extra_contour_is_localized():
    f = font_with("X", polygon([(0, 0), (200, 200), (0, 200), (200, 0)], 88))
    report = analyze_font(f, m.DesignSpec())
    assert report["outline_integrity_passed"]
    assert any(r["kind"] == "self_intersection" for r in report["review_candidates"])
    data = polygon(H)
    data["contours"].append(
        {"id": "flat", "points": [{"id": "q0", "x": 0, "y": 0}, {"id": "q1", "x": 10, "y": 10}]}
    )
    report = analyze_font(font_with(data=data), m.DesignSpec())
    assert any(
        r["kind"] == "degenerate_contour" and r["contour_index"] == 1 for r in report["review_candidates"]
    )


def test_duplicate_detection_preserves_counters_and_canonical_unicode_aliases():
    outer = [(0, 0), (200, 0), (200, 200), (0, 200), (0, 0)]
    inner = [(50, 50), (50, 150), (150, 150), (150, 50), (50, 50)]
    assert outline_key([outer, inner]) != outline_key([outer, inner[::-1]])
    assert outline_key([outer, inner]) == outline_key([inner[::-1], outer[::-1]])
    f = font_with()
    replace_glyph(f.newGlyph("K"), m.Glyph.model_validate(polygon(H, 75)))
    row = next(
        r for r in analyze_font(f, m.DesignSpec())["review_candidates"] if r["kind"] == "matching_outlines"
    )
    assert row["glyphs"] == ["H", "K"] and len(row["finding_id"]) == 64
    replace_glyph(f["H"], m.Glyph.model_validate(polygon(H, 0x00C5)))
    replace_glyph(f["K"], m.Glyph.model_validate(polygon(H, 0x212B)))
    assert not any(
        r["kind"] == "matching_outlines" for r in analyze_font(f, m.DesignSpec())["review_candidates"]
    )


def test_real_unislaw_k_is_caught_by_normal_profile():
    def midpoint(y):
        a = 606.172 + (296 - 606.172) * y / 303
        b = 742 + (437 - 742) * y / 414
        return [(a + b) / 2, y]

    profile = m.StrokeProfile(
        id="K-leg",
        glyph_id="K",
        start=midpoint(80),
        end=midpoint(200),
        minimum=100,
        maximum=160,
        max_ratio=1.1,
    )
    report = analyze_font(font_with("K", polygon(K, 75, 774)), m.DesignSpec(stroke_profiles=[profile]))
    row = next(r for r in report["issues"] if r["kind"] == "stroke_profile_mismatch")
    assert row["actual_ratio"] == pytest.approx(1.217, abs=0.002)
    assert row["samples"][0]["actual"] == pytest.approx(119.8, abs=0.2)
    assert row["samples"][-1]["actual"] == pytest.approx(145.8, abs=0.2)


@pytest.mark.parametrize("angle", [0, 30, 90, 135])
def test_normal_measurements_are_rotation_invariant(angle):
    r = math.radians(angle)

    def rotate(x, y):
        return [x * math.cos(r) - y * math.sin(r), x * math.sin(r) + y * math.cos(r)]

    contour = [rotate(x, y) for x, y in [(-50, 0), (50, 0), (50, 700), (-50, 700), (-50, 0)]]
    p = m.StrokeProfile(
        id="stem",
        glyph_id="I",
        start=rotate(0, 100),
        end=rotate(0, 600),
        minimum=100,
        maximum=100,
        max_ratio=1,
    )
    row = measure_profile([contour], p, 0.25)
    assert row["checks_passed"]
    assert all(s["actual"] == pytest.approx(100) for s in row["samples"])


def test_counter_profiles_require_a_bounded_white_interval():
    f = font_with()
    pen = FlattenPen(f)
    f["H"].draw(pen)
    p = m.StrokeProfile(
        id="white", glyph_id="H", start=(300, 450), end=(300, 650), region="counter", minimum=319, maximum=321
    )
    assert measure_profile(pen.contours, p, 0.25)["checks_passed"]
    p = p.model_copy(update={"start": (800, 450), "end": (800, 650)})
    assert not measure_profile(pen.contours, p, 0.25)["checks_passed"]


def test_profile_contract_rejects_ambiguous_or_unbounded_input():
    data = dict(id="stem", glyph_id="H", start=[90, 100], end=[90, 600], minimum=90, maximum=110)
    for extra in [
        {"end": [90, 100]},
        {"minimum": 120},
        {"samples": 1000},
        {"master_id": "default", "location": {}},
    ]:
        with pytest.raises(ValidationError):
            m.StrokeProfile.model_validate({**data, **extra})


def test_release_requires_evidence_and_persists_exact_binary_provenance(tmp_path):
    service, pid, revision = ready_source(tmp_path)
    check, _ = execute(service, "font_release_check", project_id=pid)
    assert not check.data["ready"]
    assert check.data["masters"]["default"]["unreviewed_glyphs"] == ["H"]
    uri = review(service, pid, revision, proofs(service, pid, revision))
    assert service.store.head(pid)["revision"] == revision
    check, _ = execute(service, "font_release_check", project_id=pid, review_uris=[uri])
    assert check.data["ready"], check.data
    built, _ = execute(service, "font_build", project_id=pid, purpose="release", review_uris=[uri])
    assert built.data["release_status"] == "contract_satisfied" and not built.data["artistic_approval"]
    raw, _ = service.store.read_resource(built.data["report_uri"])
    delivered = json.loads(raw)
    assert delivered["kind"] == "font_delivery"
    assert delivered["files"]["ttf"]["sha256"] == built.data["files"]["ttf"]["sha256"]
    draft, _ = execute(service, "font_build", project_id=pid, formats=["ttf"])
    assert draft.data["release_status"] == "not_reviewed"
    assert draft.data["cache_hit"]


def test_stale_cross_project_and_tampered_proof_evidence_are_rejected(tmp_path):
    service, pid, revision = ready_source(tmp_path)
    evidence = proofs(service, pid, revision)
    uri = review(service, pid, revision, evidence)
    changed, _ = execute(
        service,
        "spacing_edit",
        project_id=pid,
        expected_revision=revision,
        operations=[{"op": "advance", "glyph_id": "H", "value": 650}],
    )
    with pytest.raises(FontError, match="exact revision"):
        execute(service, "font_release_check", project_id=pid, review_uris=[uri])
    with pytest.raises(FontError, match="exact revision"):
        review(service, pid, changed.revision, evidence)
    other, _ = execute(service, "project_create", metadata={"family": "Other"})
    with pytest.raises(FontError, match="exact revision"):
        review(service, other.project_id, other.revision, evidence)
    data, _ = service.store.read_resource(evidence[0])
    image_path = service.store.root / json.loads(data)["path"]
    image_path.write_bytes(image_path.read_bytes() + b"tampered")
    with pytest.raises(FontError, match="Resource changed"):
        execute(service, "font_release_check", project_id=pid, revision=revision, review_uris=[uri])


def test_unreviewed_candidate_cannot_be_waived_by_an_unrelated_proof(tmp_path):
    service, pid, revision = ready_source(tmp_path)
    edited, _ = execute(
        service,
        "glyph_edit",
        project_id=pid,
        expected_revision=revision,
        glyph_id="K",
        create=True,
        operations=[{"op": "replace_glyph", "glyph": polygon(H, 75)}],
    )
    revision = edited.revision
    report, _ = execute(service, "font_analyze", project_id=pid, detail="full")
    finding = next(r for r in report.data["review_candidates"] if r["kind"] == "matching_outlines")
    uri = review(
        service,
        pid,
        revision,
        proofs(service, pid, revision),
        resolutions=[
            {
                "finding_id": finding["finding_id"],
                "reason": "This fixture tests a waiver with insufficient glyph coverage.",
            }
        ],
    )
    check, _ = execute(service, "font_release_check", project_id=pid, review_uris=[uri])
    assert check.data["masters"]["default"]["unreviewed_glyphs"] == ["K"]
    assert finding["finding_id"] in check.data["masters"]["default"]["unresolved_findings"]
    all_uri = review(service, pid, revision, proofs(service, pid, revision, ["H", "K"]))
    with pytest.raises(FontError, match="release requirements"):
        execute(service, "font_build", project_id=pid, purpose="release", review_uris=[all_uri])


def test_variable_profile_is_evaluated_on_exported_location(tmp_path):
    service, pid, revision = ready_source(tmp_path)
    state, _ = execute(
        service, "variable_configure", project_id=pid, expected_revision=revision, variation=VARIATION
    )
    spec = contract()
    spec["stroke_profiles"] = [
        {
            "id": "middle",
            "glyph_id": "H",
            "start": [90, 100],
            "end": [90, 250],
            "minimum": 120,
            "maximum": 140,
            "location": {"wght": 500},
        }
    ]
    execute(service, "project_update", project_id=pid, expected_revision=state.revision, design_spec=spec)
    report, _ = execute(service, "font_analyze", project_id=pid, detail="full")
    row = next(r for r in report.data["variation"]["issues"] if r["kind"] == "stroke_profile_mismatch")
    assert row["location"] == {"wght": 500}
    assert row["samples"][0]["actual"] == pytest.approx(100)
    with pytest.raises(FontError, match="issues"):
        execute(service, "font_build", project_id=pid, require_design_checks=True)


def test_original_empty_M_and_K_as_H_counterexample_over_real_mcp(tmp_path):
    async def run():
        async with client(tmp_path) as session:
            created, _ = await call(
                session, "project_create", metadata={"family": "Seeded faults"}, design_spec=contract()
            )
            pid, revision = created["project_id"], created["revision"]
            changes = [
                {"glyph_id": name, "create": True, "operations": [{"op": "replace_glyph", "glyph": data}]}
                for name, data in [
                    ("H", polygon(H)),
                    ("K", polygon(H, 75)),
                    ("M", {"advance": 600, "unicodes": [77]}),
                ]
            ]
            await call(session, "font_edit", project_id=pid, expected_revision=revision, glyphs=changes)
            report, _ = await call(session, "font_analyze", project_id=pid, detail="full")
            assert any(r["kind"] == "empty_visible_glyph" for r in report["data"]["issues"])
            assert any(r["kind"] == "matching_outlines" for r in report["data"]["review_candidates"])
            await call(
                session,
                "font_build",
                error="design_checks_failed",
                project_id=pid,
                require_design_checks=True,
            )
            proof, _ = await call(session, "font_build", project_id=pid, formats=["ttf"])
            assert proof["data"]["purpose"] == "proof" and proof["data"]["release_status"] == "not_reviewed"

    asyncio.run(run())


def test_profile_schema_migration_and_rendered_measurement_evidence(tmp_path):
    service, pid, revision = ready_source(tmp_path)
    _, original, _ = service.store.load(pid)
    assert original["schema"] == 3 and "stroke_profiles" not in original["design"]["spec"]
    spec = contract()
    spec["stroke_profiles"] = [
        {
            "id": "H-normal",
            "glyph_id": "H",
            "start": [90, 100],
            "end": [90, 250],
            "minimum": 110,
            "maximum": 130,
        }
    ]
    edited, _ = execute(
        service, "project_update", project_id=pid, expected_revision=revision, design_spec=spec
    )
    _, manifest, _ = service.store.load(pid)
    assert manifest["schema"] == 4 and manifest["design"]["version"] == 2
    image, images = execute(
        service, "render_glyph", project_id=pid, glyph_id="H", measurements=True, detail="full"
    )
    row = image.data["images"][0]["profile_measurements"][0]
    assert row["samples"][0]["actual"] == pytest.approx(100) and not row["checks_passed"]
    assert images
    restored, _ = execute(
        service,
        "history_restore",
        project_id=pid,
        expected_revision=edited.revision,
        target_revision=revision,
    )
    _, old, _ = service.store.load(pid, restored.revision)
    assert old["schema"] == 3 and not old["design"]["spec"].get("stroke_profiles")


def test_intentional_duplicate_requires_a_localized_review_resolution(tmp_path):
    service, pid, revision = ready_source(tmp_path)
    rect = [(40, 0), (140, 0), (140, 700), (40, 700)]
    edited, _ = execute(
        service,
        "font_edit",
        project_id=pid,
        expected_revision=revision,
        glyphs=[
            {
                "glyph_id": name,
                "create": True,
                "operations": [{"op": "replace_glyph", "glyph": polygon(rect, cp)}],
            }
            for name, cp in [("I", 73), ("l", 108)]
        ],
    )
    revision = edited.revision
    report, _ = execute(service, "font_analyze", project_id=pid, detail="full")
    row = next(r for r in report.data["review_candidates"] if r["kind"] == "matching_outlines")
    evidence = proofs(service, pid, revision, ["H", "I", "l"])
    uri = review(
        service,
        pid,
        revision,
        evidence,
        resolutions=[
            {
                "finding_id": row["finding_id"],
                "reason": "Intentional shared sans-serif I/l outlines in this controlled fixture.",
            }
        ],
    )
    check, _ = execute(service, "font_release_check", project_id=pid, review_uris=[uri])
    assert check.data["ready"], check.data
    unknown = review(
        service,
        pid,
        revision,
        evidence,
        resolutions=[
            {
                "finding_id": "f" * 64,
                "reason": "An unrelated finding identifier must not clear this candidate.",
            }
        ],
    )
    check, _ = execute(service, "font_release_check", project_id=pid, review_uris=[unknown])
    assert any(r["kind"] == "unknown_finding_resolutions" for r in check.data["reasons"])


def test_missing_glyph_proofs_can_request_revision_but_never_acceptance(tmp_path):
    service, pid, revision = ready_source(tmp_path)
    proof, _ = execute(service, "render_proof", project_id=pid, glyph_ids=["H", "M"])
    uris = [proof.data["images"][0]["report_uri"]]
    with pytest.raises(FontError, match="missing glyphs"):
        review(service, pid, revision, uris)
    result, _ = execute(
        service,
        "proof_review",
        project_id=pid,
        revision=revision,
        proof_uris=uris,
        verdict="revise",
        observation="The M is absent from this proof and must be drawn before review.",
    )
    check, _ = execute(service, "font_release_check", project_id=pid, review_uris=[result.data["report_uri"]])
    assert any(r["kind"] == "revision_requested" for r in check.data["reasons"])


def test_variable_release_requires_each_master_and_an_interior_proof(tmp_path):
    service, pid, revision = ready_source(tmp_path)
    state, _ = execute(
        service, "variable_configure", project_id=pid, expected_revision=revision, variation=VARIATION
    )
    revision = state.revision
    uris = [
        review(
            service, pid, revision, proofs(service, pid, revision, master_id=mid, location={"wght": weight})
        )
        for mid, weight in [("default", 300), ("bold", 700)]
    ]
    check, _ = execute(service, "font_release_check", project_id=pid, review_uris=uris)
    assert [r["kind"] for r in check.data["reasons"]] == ["intermediate_axis_review_missing"]
    middle, _ = execute(service, "render_text", project_id=pid, text="HHH", location={"wght": 500})
    uris.append(review(service, pid, revision, [middle.data["images"][0]["report_uri"]]))
    check, _ = execute(service, "font_release_check", project_id=pid, review_uris=uris)
    assert check.data["ready"], check.data
    check, _ = execute(service, "font_release_check", project_id=pid, review_uris=uris[:1] + uris[2:])
    assert check.data["masters"]["bold"]["unreviewed_glyphs"] == ["H"]


def test_outline_budget_exhaustion_is_not_reported_as_success(monkeypatch):
    from font_design_mcp import quality

    original = quality.FlattenPen
    monkeypatch.setattr(quality, "FlattenPen", lambda font, **kwargs: original(font, budget=2))
    report = analyze_font(font_with(), m.DesignSpec())
    assert not report["checks_passed"] and not report["outline_integrity_passed"]
    assert not report["scope"]["outline_integrity"]["complete"]
    assert any(r["kind"] == "diagnostic_limit" for r in report["issues"])


def test_mapping_K_to_H_in_the_same_glyph_is_also_a_review_candidate():
    data = polygon(H)
    data["unicodes"] = [72, 75]
    report = analyze_font(font_with(data=data), m.DesignSpec(required_characters="HK"))
    assert report["coverage_complete"]
    assert any(r["kind"] == "shared_unicode_outline" for r in report["review_candidates"])


def test_proof_export_survives_an_unresolved_future_design_scope(tmp_path):
    service, pid, revision = ready_source(tmp_path)
    spec = contract()
    spec["stroke_probes"][0]["location"] = {"wght": 500}
    execute(service, "project_update", project_id=pid, expected_revision=revision, design_spec=spec)
    draft, _ = execute(service, "font_build", project_id=pid, formats=["ttf"])
    assert draft.data["purpose"] == "proof"
    assert not draft.data["analysis_reports"]["default"]["checks_passed"]
    with pytest.raises(FontError, match="require a variable font"):
        execute(service, "font_build", project_id=pid, require_design_checks=True)


def test_text_review_is_bound_to_the_compiler_binary_not_only_the_revision(tmp_path):
    from PIL import Image

    from font_design_mcp.render import save_render

    service, pid, revision = ready_source(tmp_path)
    evidence = proofs(service, pid, revision)
    raw, _ = service.store.read_resource(evidence[1])
    old = json.loads(raw)
    old["build"]["files"]["ttf"]["sha256"] = "0" * 64
    with Image.open(service.store.root / old["path"]) as source:
        stored, _ = save_render(
            service.store,
            pid,
            revision,
            source.convert("RGB"),
            old["parameters"],
            {"build": old["build"], "warnings": []},
        )
    evidence[1] = service.store.resource_uri(pid, revision, stored["artifact_id"], "artifact.json")
    uri = review(service, pid, revision, evidence)
    check, _ = execute(service, "font_release_check", project_id=pid, review_uris=[uri])
    assert not check.data["ready"]
    assert any(r["kind"] == "proof_binary_mismatch" for r in check.data["reasons"])
