"""Application boundary shared by MCP and domain tests."""

import hashlib
import io
import uuid
from contextlib import ExitStack
from copy import deepcopy
from itertools import dropwhile, islice

from PIL import Image

from . import models as m
from .build import compile_font
from .construction import NETWORK_KEY
from .design import (
    analyze_font,
    applies_to_master,
    coverage,
    design_state,
    needs_variation,
    refresh_compositions,
    validate_rule_scopes,
)
from .domain import (
    FontError,
    edit_glyph,
    edit_spacing,
    glyph_data,
    metrics,
    new_font,
    require,
    set_info,
    validate_font,
)
from .inspection import select_inspection
from .interpolation import inspect_interpolation
from .planning import compact_coverage
from .proof import proof_frame, proof_view
from .references import import_png, reference_frame
from .render import glyph_frame, glyph_view, save_render, text_view
from .review import record_review, release_check
from .storage import Store
from .telemetry import phase, profiled
from .variation_design import analyze_variation, attach_variation

CAPABILITIES = {
    "source": "UFO 3",
    "formats": ["ttf", "woff2"],
    "transport": "stdio",
    "static_single_master": True,
    "variable_fonts": True,
    "variable_limits": {"axes": 4, "masters": 8},
    "curves": ["line", "cubic", "quadratic"],
    "fill_rule": "nonzero",
    "precomposed_components": True,
    "combining_mark_positioning": "Latin mark-to-base GPOS checked on export; stacked marks not certified",
    "svg_import": False,
    "reference_png_import": True,
    "design_diagnostics": True,
    "default_outline_checks": True,
    "normal_stroke_profiles": True,
    "regional_measurement_coverage": True,
    "normal_variation_profiles": True,
    "stroke_networks": True,
    "calibrated_reference_crops": True,
    "interpolation_diagnostics": True,
    "usage_glyph_and_sequence_coverage": True,
    "revision_bound_reviews": True,
    "release_contract": True,
    "linked_accent_composition": True,
    "automatic_tracing": False,
    "otf": False,
    "human_approval_via_tools": False,
    "limits": {"glyphs": 512, "source_points": 50000, "text_characters": 256, "png_bytes": 2000000},
}

# Input schemas are produced directly from the same Pydantic models used at runtime.
TOOLS = {
    "project_create": (
        m.ProjectCreate,
        False,
        "Create a project in the launch workspace with Unicode UFO sources and technical glyphs.",
    ),
    "project_open": (
        m.ProjectRef,
        True,
        "Reopen a server-created project by ID; verifies committed sources and returns its revision.",
    ),
    "project_inspect": (
        m.Inspect,
        True,
        "Inspect a master with optional sections and glyph_ids focus. Full collections are paginated; pagination lists each continuation. Use sections=['design'] for the complete design contract without spacing/compositions.",
    ),
    "project_update": (
        m.ProjectUpdate,
        False,
        "Atomically update metadata, brief or decision journal. Requires expected_revision. UPM changes on nonempty fonts fail.",
    ),
    "variable_configure": (
        m.VariableConfigure,
        False,
        "Configure continuous axes and masters in this project. Master 'default' is the existing source at the default location. New IDs clone it; existing IDs keep their drawings; omitted IDs are removed in a new revision. Edit masters with master_id. Compatibility is checked at build/validation time.",
    ),
    "glyph_get": (
        m.GlyphGet,
        True,
        "Read a master's glyph metrics in font units, Y upwards. master_id defaults to 'default'. Use detail=full for contour/point/component/anchor IDs and geometry.",
    ),
    "glyph_edit": (
        m.GlyphEdit,
        False,
        "Apply typed vector operations or drawing primitives atomically to one glyph in master_id (default: 'default'). Use detail=full for added/removed/touched IDs. Replacements are explicit.",
    ),
    "spacing_edit": (
        m.SpacingEdit,
        False,
        "Atomically set advances, side bearings, kerning groups or pairs in master_id (default: 'default'). Bearings move outlines; advances do not.",
    ),
    "font_edit": (
        m.FontEdit,
        False,
        "Edit up to 128 glyphs atomically in master_id (default: 'default'), then apply spacing. Forward component references resolve at final validation; any failure rolls back the batch.",
    ),
    "render_glyph": (
        m.RenderGlyph,
        False,
        "Persist and return PNG image content from the selected UFO revision, with optional guides/handles. Comparison uses the same frame.",
    ),
    "render_text": (
        m.RenderText,
        False,
        "Compile the revision, shape with HarfBuzz and return FreeType PNGs. For variable fonts, location maps axis tags to values; omitted axes use defaults. Missing Unicode is reported. Optional same-conditions revision comparison.",
    ),
    "font_validate": (
        m.Validate,
        False,
        "Run technical checks, compile a TTF, inspect tables and corpus coverage. Reports errors, warnings and observations; does not assess artistic merit.",
    ),
    "font_build": (
        m.Build,
        False,
        "Build real TTF and/or WOFF2 from a frozen revision, automatically variable when axes/masters are configured. Returns persistent relative paths and hashes. Does not alter sources.",
    ),
    "font_analyze": (
        m.Analyze,
        False,
        "Check visible ink, matching outlines and self crossings by default; measure declared design rules, "
        "normal stroke/counter profiles, smooth joins, digit spacing and required coverage. "
        "Rules accept master_id or a variable location; variation_profiles measure normal-width progression. "
        "interpolation=true adds timed source correspondence and compiled axis-grid checks. "
        "Returns regional coverage and localized candidates, not artistic approval. Full reports include measurements and evidence_plan.",
    ),
    "proof_review": (
        m.ProofReview,
        False,
        "Record an agent's visual review of immutable render report_uris from an exact revision. "
        "Use verdict=revise for defects; accepted intentional findings require their finding_id and a reason. "
        "Does not alter font sources or assert human approval. Inspect actual images before calling.",
    ),
    "font_release_check": (
        m.ReleaseCheck,
        False,
        "Evaluate all masters, structural measurements, glyph review coverage, localized findings, "
        "reference comparisons and shaped text reviews before release. Supply proof_review report_uris. "
        "Returns actionable missing requirements; never certifies aesthetic perfection.",
    ),
    "reference_import": (
        m.ReferenceImport,
        False,
        "Import a bounded single-frame PNG from workspace/inbox as an immutable drawing reference. "
        "image_to_font maps image pixels (top-left, Y down) to font units (baseline, Y up). "
        "Requires expected_revision. No tracing or automatic rescaling; use reference_id with render_glyph.",
    ),
    "render_proof": (
        m.RenderProof,
        False,
        "Render up to 32 glyphs at one common scale, optionally comparing revisions. "
        "Missing glyphs are explicit placeholders; use render_text separately for shaped words.",
    ),
    "history_list": (
        m.Page,
        True,
        "List committed revisions and summaries with pagination; interrupted uncommitted stages are excluded.",
    ),
    "history_restore": (
        m.Restore,
        False,
        "Restore a committed revision by creating a NEW revision; requires the current expected_revision and preserves history.",
    ),
}


class Service:
    def __init__(self, root):
        self.store = Store(root)

    @profiled
    @phase("execute")
    def execute(self, name, request):
        images = []
        if name == "project_create":
            project_id = uuid.uuid4().hex
            self.store.project(project_id).mkdir()
            with self.store.lock(project_id):
                font = new_font(request.metadata, request.metrics)
                extra = {"brief": request.brief, "decisions": []}
                if request.design_spec is not None:
                    extra["design"] = m.DesignState(spec=request.design_spec).model_dump()
                manifest = self.store.commit(project_id, font, extra, "Project created")
            return m.Result(
                ok=True,
                summary="Project created with .notdef and space",
                project_id=project_id,
                revision=manifest["revision"],
                changed=[".notdef", "space"],
                data=CAPABILITIES,
            ), images
        with ExitStack() as locks:
            locks.enter_context(self.store.lock(request.project_id))
            if name == "history_list":
                return self.history_page(request), images
            revision = getattr(request, "revision", None)
            font, manifest, source = self.store.load(request.project_id, revision)
            project_id, revision = request.project_id, manifest["revision"]
            master_id = getattr(request, "master_id", "default")
            fonts = (
                self.store.load_masters(project_id, manifest, font)
                if isinstance(request, m.WriteRef) or master_id != "default"
                else {"default": font}
            )
            require(master_id in fonts, "missing_reference", f"Unknown master {master_id}")
            font = fonts[master_id]
            state = design_state(manifest)
            result = m.Result(ok=True, summary=f"{name} completed", project_id=project_id, revision=revision)
            if isinstance(request, m.WriteRef):
                require(
                    request.expected_revision == revision,
                    "stale_revision",
                    f"Expected {request.expected_revision}; current revision is {revision}",
                )
                extra = {"brief": manifest["brief"], "decisions": list(manifest["decisions"])}
                if "variation" in manifest:
                    extra["variation"] = manifest["variation"]
                persist_design = "design" in manifest
                links = state.composition_links.setdefault(master_id, {})
                if name == "project_update":
                    require(
                        request.metrics is None or request.metrics.units_per_em == font.info.unitsPerEm,
                        "capability_unavailable",
                        "UPM is fixed after creation; no implicit rescaling",
                    )
                    for master_font in fonts.values():
                        set_info(master_font, request.metadata, request.metrics)
                    if request.brief is not None:
                        extra["brief"] = request.brief
                    if request.decision:
                        require(
                            len(extra["decisions"]) < 128, "limit_exceeded", "Maximum 128 decision entries"
                        )
                        extra["decisions"].append(request.decision.model_dump())
                    if request.design_spec is not None:
                        state.spec = request.design_spec
                        persist_design = True
                    if request.remove_reference_ids:
                        removed = set(request.remove_reference_ids)
                        require(
                            removed <= {r.id for r in state.references},
                            "missing_reference",
                            "A reference selected for removal does not exist",
                        )
                        state.references = [r for r in state.references if r.id not in removed]
                    result.changed = ["project"]
                elif name == "reference_import":
                    existing = next((r for r in state.references if r.id == request.reference_id), None)
                    require(
                        (existing is not None) == request.replace,
                        "missing_reference" if request.replace else "duplicate_id",
                        "Replacement needs an existing reference ID; addition needs a new ID",
                    )
                    require(
                        existing is not None or len(state.references) < 64,
                        "limit_exceeded",
                        "Maximum 64 drawing references",
                    )
                    image, original_hash = import_png(self.store, request.source_path)
                    source_page_uri = None
                    calibration = request.image_to_font
                    if request.crop:
                        x0, y0, x1, y1 = request.crop
                        require(
                            0 <= x0 < x1 <= image.width and 0 <= y0 < y1 <= image.height,
                            "invalid_reference",
                            "Crop must be inside the source page",
                        )
                        previous = next(
                            (
                                r
                                for r in state.references
                                if r.source_sha256 == original_hash and r.source_page_uri
                            ),
                            None,
                        )
                        if previous:
                            source_page_uri = previous.source_page_uri
                            self.store.read_resource(source_page_uri)
                        else:
                            page, _ = save_render(
                                self.store,
                                project_id,
                                revision,
                                image,
                                {"kind": "reference_page"},
                                {"source_sha256": original_hash, "engine": "Preserved reference page"},
                            )
                            source_page_uri = self.store.resource_uri(
                                project_id, revision, page["artifact_id"], "image.png"
                            )
                        image = image.crop(request.crop)
                        a, b, c, d, tx, ty = calibration
                        calibration = (a, b, c, d, tx + a * x0 + c * y0, ty + b * x0 + d * y0)
                    reference = m.DrawingReference(
                        id=request.reference_id,
                        glyph_id=request.glyph_id,
                        label=request.label,
                        image_to_font=calibration,
                        source_crop=request.crop,
                        source_page_uri=source_page_uri,
                        width=image.width,
                        height=image.height,
                        source_sha256=original_hash,
                        encoded_bytes=1,  # Exact normalized size is filled before committing.
                        uri=f"font-design://{project_id}/{revision}/{'0' * 32}/image.png?sha256={'0' * 64}",
                    )
                    artifact, png = save_render(
                        self.store,
                        project_id,
                        revision,
                        image,
                        {"kind": "drawing_reference"},
                        {"source_sha256": original_hash, "engine": "Imported PNG reference; no tracing"},
                    )
                    artifact["uri"] = self.store.resource_uri(
                        project_id, revision, artifact["artifact_id"], "image.png"
                    )
                    reference.uri = artifact["uri"]
                    reference.encoded_bytes = artifact["bytes"]
                    state.references = [r for r in state.references if r.id != reference.id] + [reference]
                    result.data = {"reference": reference.model_dump(mode="json"), "images": [artifact]}
                    result.changed = [f"reference:{reference.id}"]
                    if request.image_mode == "inline":
                        images.append(png)
                elif name == "variable_configure":
                    extra["variation"] = request.variation.model_dump()
                    previous_masters = set(fonts)
                    fonts = {
                        master.id: fonts[master.id] if master.id in fonts else deepcopy(fonts["default"])
                        for master in request.variation.masters
                    }
                    state.composition_links = {
                        key: deepcopy(
                            state.composition_links.get(key if key in previous_masters else "default", {})
                        )
                        for key in fonts
                    }
                    result.changed = ["variation"]
                    result.data = extra["variation"]
                elif name == "glyph_edit":
                    result.data = edit_glyph(font, request, links)
                    result.changed = [request.glyph_id]
                elif name == "font_edit":
                    changes = [edit_glyph(font, change, links) for change in request.glyphs]
                    dependent_changes = refresh_compositions(font, links)
                    if any(isinstance(op, m.Bearings) for op in request.spacing):
                        validate_font(font)  # Bearings traverse the new component graph.
                    spacing = (
                        edit_spacing(
                            font,
                            m.SpacingEdit(
                                project_id=project_id,
                                expected_revision=revision,
                                operations=request.spacing,
                            ),
                            links,
                        )
                        if request.spacing
                        else {"touched_ids": []}
                    )
                    result.data = {"glyphs": changes, "spacing": spacing}
                    result.changed = list(
                        dict.fromkeys(
                            [g.glyph_id for g in request.glyphs] + spacing["touched_ids"] + dependent_changes
                        )
                    )
                elif name == "spacing_edit":
                    result.data = edit_spacing(font, request, links)
                    result.changed = result.data["touched_ids"]
                elif name == "history_restore":
                    font, restored, _ = self.store.load(project_id, request.target_revision)
                    fonts = self.store.load_masters(project_id, restored, font)
                    extra = {
                        "brief": restored["brief"],
                        "decisions": restored["decisions"],
                        "restored_from": request.target_revision,
                    }
                    if "variation" in restored:
                        extra["variation"] = restored["variation"]
                    state = design_state(restored)
                    persist_design = "design" in restored
                    result.changed = ["project"]
                for key, master_font in fonts.items():
                    affected = refresh_compositions(master_font, state.composition_links.get(key, {}))
                    result.changed = list(dict.fromkeys([*result.changed, *affected]))
                state.composition_links = {k: v for k, v in state.composition_links.items() if v}
                if any(NETWORK_KEY in g.lib for f in fonts.values() for g in f):
                    state.version = 3
                if persist_design or state != m.DesignState():
                    extra["design"] = state.model_dump()
                new = self.store.commit(
                    project_id, fonts["default"], extra, request.summary or name, revision, masters=fonts
                )
                result.revision = new["revision"]
                result.summary = f"Committed {name}: {len(result.changed)} changed item(s)"
                if getattr(request, "detail", "full") == "summary":
                    result.data = {
                        "operation_count": (
                            sum(len(g.operations) for g in request.glyphs) + len(request.spacing)
                            if name == "font_edit"
                            else len(request.operations)
                        )
                    }
            elif name in ("project_open", "project_inspect"):
                offset, limit = getattr(request, "offset", 0), getattr(request, "limit", 50)
                names = sorted(font.keys())
                result.data = {
                    "capabilities": CAPABILITIES,
                    "variation": manifest.get("variation"),
                    "brief": manifest["brief"],
                    "decisions": manifest["decisions"],
                    "design_spec": state.spec.model_dump(),
                    "references": [r.model_dump() for r in state.references],
                    "composition_links": state.model_dump()["composition_links"],
                    "family": font.info.familyName,
                    "style": font.info.styleName,
                    "units_per_em": font.info.unitsPerEm,
                    "metrics": {
                        k: getattr(font.info, k) for k in ("ascender", "descender", "xHeight", "capHeight")
                    },
                    "glyphs": names[offset : offset + limit],
                    "total": len(names),
                    "next_offset": offset + limit if offset + limit < len(names) else None,
                    "source_path": source.relative_to(self.store.root).as_posix(),
                    "groups": dict(font.groups),
                    "kerning": [
                        {"left": left, "right": right, "value": value}
                        for (left, right), value in font.kerning.items()
                    ],
                }
                if name == "project_inspect" and request.detail == "summary":
                    result.data = {
                        k: result.data[k]
                        for k in ("family", "style", "units_per_em", "metrics", "total", "variation")
                    }
                    result.data["design_context"] = {
                        "brief": manifest["brief"][:1000],
                        "notes": state.spec.notes[:500],
                        "protected_features": state.spec.protected_features[:500],
                        "required_characters": state.spec.required_characters[:256],
                        "reference_glyphs": state.spec.reference_glyphs,
                        "digit_spacing": state.spec.digit_spacing,
                        "reference_ids": [r.id for r in state.references],
                        "rule_count": len(state.spec.metric_rules)
                        + len(state.spec.stroke_probes)
                        + len(state.spec.stroke_profiles)
                        + len(state.spec.variation_probes)
                        + len(state.spec.variation_profiles)
                        + len(state.spec.regions),
                        "latest_decision": manifest["decisions"][-1:] or [],
                        "full_context": "project_inspect(detail=full)",
                    }
                else:
                    result.data = select_inspection(result.data, request, font)
            elif name == "glyph_get":
                require(request.glyph_id in font, "missing_reference", f"Missing glyph {request.glyph_id}")
                result.data = {
                    "construction": font[request.glyph_id].lib.get(NETWORK_KEY),
                    "glyph_id": request.glyph_id,
                    **(
                        glyph_data(font[request.glyph_id]).model_dump()
                        if request.detail == "full"
                        else {"unicodes": font[request.glyph_id].unicodes}
                    ),
                    "metrics": metrics(font[request.glyph_id], font),
                }
            elif name == "font_analyze":
                validate_rule_scopes(state.spec, manifest)
                locks.close()
                report = analyze_font(font, state.spec, master_id)
                report["master_id"] = master_id
                if needs_variation(state.spec) or (request.interpolation and manifest.get("variation")):
                    compiled, binary_bytes = compile_font(
                        self.store,
                        project_id,
                        fonts["default"],
                        manifest,
                        source,
                        ["ttf"],
                    )
                    if needs_variation(state.spec):
                        attach_variation(report, analyze_variation(binary_bytes, state.spec))
                    if request.interpolation and manifest.get("variation"):
                        interpolation = inspect_interpolation(
                            self.store,
                            project_id,
                            manifest,
                            self.store.root / compiled["files"]["ttf"]["path"],
                            hashlib.sha256(binary_bytes).hexdigest(),
                        )
                        report["interpolation"] = interpolation
                        report["checks_passed"] &= interpolation["checks_passed"]
                self.store.verify(project_id, revision)
                uri = self.store.save_report(project_id, revision, report)
                if request.detail == "summary":
                    result.data = {
                        k: report[k]
                        for k in (
                            "checks_passed",
                            "coverage_complete",
                            "counts",
                            "review",
                            "artistic_approval",
                            "reference_fidelity",
                            "master_id",
                            "limitations",
                            "scope",
                            "outline_integrity_passed",
                            "design_coverage",
                            "next_steps",
                        )
                    }
                    result.data.update(
                        issues=report["issues"][:10],
                        review_candidates=report["review_candidates"][:10],
                        review_candidates_truncated=report["counts"]["review_candidates"] > 10,
                        truncated=report["issues_truncated"] or len(report["issues"]) > 10,
                    )
                else:
                    result.data = report
                if "interpolation" in report:
                    result.data["interpolation"] = {
                        k: report["interpolation"][k] for k in ("status", "checks_passed", "report_uri")
                    }
                if request.detail == "summary":
                    result.data["design_coverage"] = compact_coverage(report["design_coverage"])
                    result.data["review_groups"] = [
                        {"kind": r["kind"], "count": r["count"]} for r in report["review_groups"]
                    ]
                result.data["report_uri"] = uri
                result.summary = (
                    "Declared checks passed; visual quality not assessed"
                    if report["checks_passed"]
                    else "Design issues found"
                )
            elif name == "proof_review":
                result.data = record_review(self.store, project_id, revision, manifest, request)
                result.summary = "Agent review recorded for immutable proofs; source revision unchanged"
            elif name in ("font_build", "font_release_check"):
                controlled = (
                    name == "font_release_check"
                    or request.require_design_checks
                    or request.purpose == "release"
                )
                scope_error = None
                try:
                    validate_rule_scopes(state.spec, manifest)
                except FontError as exc:
                    if controlled:
                        raise
                    scope_error = str(exc)
                checked = self.store.load_masters(project_id, manifest, fonts["default"])
                locks.close()
                reports = {
                    mid: analyze_font(f, m.DesignSpec() if scope_error else state.spec, mid)
                    for mid, f in checked.items()
                }
                if scope_error:
                    for report in reports.values():
                        report["checks_passed"] = False
                        report["issues"].insert(0, {"kind": "invalid_design_scope", "message": scope_error})
                        report["counts"]["issues"] += 1
                        report["issues"] = report["issues"][:2000]
                        report["issues_truncated"] = report["counts"]["issues"] > len(report["issues"])
                        report["scope"]["design_contract"] = "unavailable"
                variation_report = None
                binary_hash = None
                needs_compilation = (
                    name == "font_release_check"
                    or request.purpose == "release"
                    or request.require_design_checks
                )
                if needs_compilation or (not scope_error and needs_variation(state.spec)):
                    compiled, binary_bytes = compile_font(
                        self.store, project_id, checked["default"], manifest, source, ["ttf"]
                    )
                    binary_hash = hashlib.sha256(binary_bytes).hexdigest()
                interpolation = None
                if needs_compilation and manifest.get("variation"):
                    interpolation = inspect_interpolation(
                        self.store,
                        project_id,
                        manifest,
                        self.store.root / compiled["files"]["ttf"]["path"],
                        binary_hash,
                    )
                if not scope_error and needs_variation(state.spec):
                    variation_report = analyze_variation(binary_bytes, state.spec)
                    for report in reports.values():
                        attach_variation(report, variation_report)
                evidence = {}
                for mid, report in reports.items():
                    report["master_id"] = mid
                    evidence[mid] = {
                        "checks_passed": report["checks_passed"],
                        "outline_integrity_passed": report["outline_integrity_passed"],
                        "counts": report["counts"],
                        "report_uri": self.store.save_report(project_id, revision, report),
                    }
                readiness = None
                if name == "font_release_check" or request.purpose == "release":
                    readiness = release_check(
                        self.store,
                        project_id,
                        revision,
                        manifest,
                        checked,
                        state.spec,
                        reports,
                        request.review_uris,
                        binary_hash,
                    )
                    readiness["analysis_reports"] = evidence
                    if interpolation is not None:
                        readiness["interpolation"] = interpolation
                        if not interpolation["checks_passed"]:
                            readiness["ready"] = False
                            readiness["reasons"].append(
                                {
                                    "kind": "interpolation_checks_failed",
                                    "report_uri": interpolation["report_uri"],
                                }
                            )
                    readiness["report_uri"] = self.store.save_report(project_id, revision, readiness)
                if name == "font_release_check":
                    result.data = readiness
                    result.summary = (
                        "Release contract satisfied" if readiness["ready"] else "Release requirements remain"
                    )
                else:
                    gated = request.require_design_checks or request.purpose == "release"
                    if gated:
                        if interpolation is not None:
                            require(
                                interpolation["checks_passed"],
                                "interpolation_checks_failed",
                                f"Interpolation checks failed; read {interpolation['report_uri']}",
                            )
                        require(
                            bool(state.spec.required_characters),
                            "design_contract_missing",
                            "Set design_spec.required_characters before using the export gate",
                        )
                        if variation_report is not None:
                            require(
                                variation_report["checks_passed"],
                                "design_checks_failed",
                                f"Variation: {variation_report['counts']['issues']} issues; read {evidence['default']['report_uri']}",
                            )
                        for mid, report in reports.items():
                            require(
                                report["checks_passed"],
                                "design_checks_failed",
                                f"Master {mid}: {report['counts']['issues']} issues; read {evidence[mid]['report_uri']}",
                            )
                    if readiness is not None:
                        require(
                            readiness["ready"],
                            "release_not_ready",
                            f"{len(readiness['reasons'])} release requirements remain; read {readiness['report_uri']}",
                        )
                    result.data, exported_bytes = compile_font(
                        self.store,
                        project_id,
                        checked["default"],
                        manifest,
                        source,
                        request.formats,
                        retain=True,
                    )
                    if readiness is not None:
                        require(
                            hashlib.sha256(exported_bytes).hexdigest() == binary_hash,
                            "proof_binary_mismatch",
                            "Export differs from the reviewed compiler output; regenerate proofs",
                        )
                    result.data.update(
                        purpose=request.purpose,
                        design_gate="passed" if gated else "not_requested",
                        analysis_reports=evidence,
                        release_status="contract_satisfied" if readiness is not None else "not_reviewed",
                        artistic_approval=False,
                    )
                    if readiness is not None:
                        result.data["release_report_uri"] = readiness["report_uri"]
                    artifact = result.data["artifact_id"]
                    for fmt, info in result.data["files"].items():
                        info["uri"] = self.store.resource_uri(project_id, revision, artifact, f"font.{fmt}")
                    self.store.verify(project_id, revision)
                    result.data["report_uri"] = self.store.save_report(
                        project_id, revision, {"kind": "font_delivery", **result.data}
                    )
                    result.summary = (
                        "Release exported with evidence"
                        if readiness is not None
                        else "Proof exported; release review not asserted"
                    )
            elif name == "font_validate":
                validate_rule_scopes(state.spec, manifest)
                locks.close()
                observations = validate_font(font)
                _, missing = coverage(font, state.spec, request.corpus)
                design_report = analyze_font(font, state.spec)
                result.data = {
                    "review": "automatic",
                    "valid": True,
                    "errors": [],
                    "observations": observations,
                    "missing_codepoints": missing,
                    "coverage_complete": not missing,
                    "outline_integrity_passed": design_report["outline_integrity_passed"],
                    "release_status": "not_reviewed",
                    "design": {**design_report, "master_id": "default"},
                }
                result.warnings = [f"Missing U+{u:04X}" for u in missing]
                if not font.info.openTypeNameLicense:
                    result.warnings.append("No font license declared by its creator")
                try:
                    build, binary_bytes = compile_font(
                        self.store, project_id, font, manifest, source, ["ttf"]
                    )
                    result.data["build"] = build
                    if needs_variation(state.spec):
                        attach_variation(result.data["design"], analyze_variation(binary_bytes, state.spec))
                except FontError as exc:
                    result.data.update(valid=False, errors=[{"code": exc.code, "message": str(exc)}])
                    if needs_variation(state.spec):
                        result.data["design"]["checks_passed"] = False
                        result.data["design"]["scope"]["variation"] = "unavailable_compile_failed"
                result.data["technical_valid"] = result.data["valid"]
                result.summary = (
                    "Technical validation passed" if result.data["valid"] else "Technical validation failed"
                )
                if request.detail == "summary":
                    report = self.store.save_report(
                        project_id, revision, {**result.data, "warnings": result.warnings}
                    )
                    issues = [o for o in observations if "kind" in o or o.get("direction") == "zero"]
                    result.data.pop("observations")
                    result.data.pop("build", None)
                    result.data["design"] = {
                        k: result.data["design"][k]
                        for k in (
                            "checks_passed",
                            "counts",
                            "review",
                            "artistic_approval",
                            "reference_fidelity",
                            "master_id",
                            "scope",
                            "outline_integrity_passed",
                            "design_coverage",
                        )
                    }
                    result.data.update(
                        counts={
                            "errors": len(result.data["errors"]),
                            "warnings": len(issues) + len(result.warnings),
                            "information": len(observations) - len(issues),
                        },
                        issues=issues[:10],
                        truncated=len(issues) > 10 or len(result.warnings) > 10,
                        report_uri=report,
                    )
                    if len(missing) > 10:
                        result.data.update(
                            missing_codepoints=missing[:10],
                            missing_codepoint_count=len(missing),
                            truncated=True,
                        )
                    result.warnings = result.warnings[:10]
            elif name in ("render_glyph", "render_text", "render_proof"):
                sources = [(font, manifest, source)]
                if request.compare_revision:
                    other, version, ufo = self.store.load(project_id, request.compare_revision)
                    if master_id != "default":
                        other_fonts = self.store.load_masters(project_id, version, other)
                        require(master_id in other_fonts, "missing_reference", f"Unknown master {master_id}")
                        other = other_fonts[master_id]
                    sources.append((other, version, ufo))
                locks.close()
                parameters = request.model_dump(exclude={"project_id", "revision", "compare_revision"})
                reference, reference_image = None, None
                if name == "render_glyph":
                    frame = glyph_frame([f for f, _, _ in sources], request.glyph_id)
                    if request.reference_id:
                        reference = next((r for r in state.references if r.id == request.reference_id), None)
                        require(
                            reference is not None and reference.glyph_id == request.glyph_id,
                            "missing_reference",
                            "Reference must exist and belong to the requested glyph",
                        )
                        data, _ = self.store.read_resource(reference.uri)
                        with Image.open(io.BytesIO(data)) as imported:
                            reference_image = imported.convert("RGB")
                        box = reference_frame(reference)
                        frame = [
                            min(frame[0], box[0]),
                            min(frame[1], box[1]),
                            max(frame[2], box[2]),
                            max(frame[3], box[3]),
                        ]
                elif name == "render_proof":
                    frame = proof_frame([f for f, _, _ in sources], request.glyph_ids)
                else:
                    # Shared em-normalized frame makes revisions with different vertical metrics comparable.
                    frame = (
                        max(f.info.ascender / f.info.unitsPerEm for f, _, _ in sources),
                        min(f.info.descender / f.info.unitsPerEm for f, _, _ in sources),
                    )
                result.data["images"] = []
                for f, version, ufo in sources:
                    if name == "render_glyph":
                        profiles = [
                            p
                            for p in design_state(version).spec.stroke_profiles
                            if p.glyph_id == request.glyph_id and applies_to_master(p, master_id)
                        ]
                        if reference is None:
                            image, details = glyph_view(
                                f, request.glyph_id, request, frame, profiles=profiles
                            )
                        else:
                            image, details = glyph_view(
                                f,
                                request.glyph_id,
                                request,
                                frame,
                                (reference_image, reference),
                                profiles=profiles,
                            )
                            details["reference"] = reference.model_dump(mode="json")
                            self.store.read_resource(
                                reference.uri
                            )  # Recheck immutable evidence after rendering.
                    elif name == "render_proof":
                        image, details = proof_view(f, request, frame)
                        result.warnings.extend(details["warnings"])
                    else:
                        build, path = compile_font(self.store, project_id, f, version, ufo, ["ttf"])
                        image, details = text_view(
                            path, request, (frame[0] * f.info.unitsPerEm, frame[1] * f.info.unitsPerEm)
                        )
                        details["build"] = build
                        result.warnings.extend(details["warnings"])
                    self.store.verify(project_id, version["revision"])
                    data, png = save_render(
                        self.store, project_id, version["revision"], image, parameters, details
                    )
                    data = {
                        **data,
                        "uri": self.store.resource_uri(
                            project_id, version["revision"], data["artifact_id"], "image.png"
                        ),
                        "report_uri": self.store.resource_uri(
                            project_id, version["revision"], data["artifact_id"], "artifact.json"
                        ),
                    }
                    if request.detail != "full":
                        data = {
                            k: v
                            for k, v in data.items()
                            if k
                            in {
                                "artifact_id",
                                "revision",
                                "path",
                                "uri",
                                "report_uri",
                                "mime_type",
                                "width",
                                "height",
                                "warnings",
                                "missing_codepoints",
                                "advance_units",
                                "metrics",
                                "location",
                                "reference",
                                "frame",
                                "scale",
                                "missing_glyphs",
                            }
                            or (k == "positions" and request.detail == "positions")
                        }
                        for key in ("warnings", "missing_codepoints", "missing_glyphs"):
                            if len(data.get(key, [])) > 10:
                                data[key + "_count"] = len(data[key])
                                data[key] = data[key][:10]
                                data["truncated"] = True
                    result.data["images"].append(data)
                    if request.image_mode == "inline":
                        images.append(png)
                if request.detail != "full":
                    if len(result.warnings) > 10:
                        result.data.update(warning_count=len(result.warnings), truncated=True)
                    result.warnings = result.warnings[:10]
            return result, images

    def history_page(self, request):
        entries = iter(self.store.history(request.project_id))
        if request.revision:
            entries = dropwhile(lambda e: e["revision"] != request.revision, entries)
        first = next(entries, None)
        require(first is not None, "missing_reference", "Revision is not committed")
        from itertools import chain

        entries = chain([first], entries)
        total = None
        if request.include_total:
            entries = list(entries)
            total = len(entries)
        page = list(islice(entries, request.offset, request.offset + request.limit + 1))
        data = {
            "entries": [
                {
                    k: e.get(k)
                    for k in ("revision", "parent", "created_at", "summary", "restored_from", "source_sha256")
                }
                for e in page[: request.limit]
            ],
            "next_offset": request.offset + request.limit if len(page) > request.limit else None,
            "integrity": "manifest chain only; source files are not inspected",
        }
        if total is not None:
            data["total"] = total
        return m.Result(
            ok=True,
            summary="History page",
            project_id=request.project_id,
            revision=first["revision"],
            data=data,
        )
