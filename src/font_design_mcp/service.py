"""Application boundary shared by MCP and domain tests."""

import uuid

from . import models as m
from .build import compile_font
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
from .render import glyph_frame, glyph_view, save_render, text_view
from .storage import Store

CAPABILITIES = {
    "source": "UFO 3",
    "formats": ["ttf", "woff2"],
    "transport": "stdio",
    "static_single_master": True,
    "curves": ["line", "cubic", "quadratic"],
    "fill_rule": "nonzero",
    "precomposed_components": True,
    "combining_mark_positioning": "not advertised; untested",
    "svg_import": False,
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
        m.Page,
        True,
        "Inspect a specified revision, metadata, metrics, kerning and a paginated glyph inventory.",
    ),
    "project_update": (
        m.ProjectUpdate,
        False,
        "Atomically update metadata, brief or decision journal. Requires expected_revision. UPM changes on nonempty fonts fail.",
    ),
    "glyph_get": (
        m.GlyphGet,
        True,
        "Read stable contour/point/component/anchor IDs and advance, bounds and bearings in font units, Y upwards.",
    ),
    "glyph_edit": (
        m.GlyphEdit,
        False,
        "Apply an atomic typed vector batch to a named glyph. Offcurve points are handles. Replacements must be explicit; removed IDs are returned.",
    ),
    "spacing_edit": (
        m.SpacingEdit,
        False,
        "Atomically set advances, both side bearings, kerning groups or pairs. Bearings move outlines; advances do not.",
    ),
    "render_glyph": (
        m.RenderGlyph,
        False,
        "Persist and return PNG image content from the selected UFO revision, with optional guides/handles. Comparison uses the same frame.",
    ),
    "render_text": (
        m.RenderText,
        False,
        "Compile the revision, shape with HarfBuzz and return monochrome FreeType PNGs. Missing Unicode is reported; no fallback font. Optional same-conditions revision comparison.",
    ),
    "font_validate": (
        m.Validate,
        False,
        "Run technical checks, compile a TTF, inspect tables and corpus coverage. Reports errors, warnings and observations; does not assess artistic merit.",
    ),
    "font_build": (
        m.Build,
        False,
        "Build real TTF and/or WOFF2 from a frozen revision. Returns persistent relative paths and hashes. Does not alter UFO sources.",
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

    def execute(self, name, request):
        images = []
        if name == "project_create":
            project_id = uuid.uuid4().hex
            self.store.project(project_id).mkdir()
            with self.store.lock(project_id):
                font = new_font(request.metadata, request.metrics)
                manifest = self.store.commit(
                    project_id, font, {"brief": request.brief, "decisions": []}, "Project created"
                )
            return m.Result(
                ok=True,
                summary="Project created with .notdef and space",
                project_id=project_id,
                revision=manifest["revision"],
                changed=[".notdef", "space"],
                data=CAPABILITIES,
            ), images
        with self.store.lock(request.project_id):
            revision = getattr(request, "revision", None)
            font, manifest, source = self.store.load(request.project_id, revision)
            project_id, revision = request.project_id, manifest["revision"]
            result = m.Result(ok=True, summary=f"{name} completed", project_id=project_id, revision=revision)
            if isinstance(request, m.WriteRef):
                require(
                    request.expected_revision == revision,
                    "stale_revision",
                    f"Expected {request.expected_revision}; current revision is {revision}",
                )
                extra = {"brief": manifest["brief"], "decisions": list(manifest["decisions"])}
                if name == "project_update":
                    require(
                        request.metrics is None or request.metrics.units_per_em == font.info.unitsPerEm,
                        "capability_unavailable",
                        "UPM is fixed after creation; no implicit rescaling",
                    )
                    set_info(font, request.metadata, request.metrics)
                    if request.brief is not None:
                        extra["brief"] = request.brief
                    if request.decision:
                        require(
                            len(extra["decisions"]) < 128, "limit_exceeded", "Maximum 128 decision entries"
                        )
                        extra["decisions"].append(request.decision.model_dump())
                    result.changed = ["project"]
                elif name == "glyph_edit":
                    result.data = edit_glyph(font, request)
                    result.changed = [request.glyph_id]
                elif name == "spacing_edit":
                    result.data = edit_spacing(font, request)
                    result.changed = result.data["touched_ids"]
                elif name == "history_restore":
                    font, restored, _ = self.store.load(project_id, request.target_revision)
                    extra = {
                        "brief": restored["brief"],
                        "decisions": restored["decisions"],
                        "restored_from": request.target_revision,
                    }
                    result.changed = ["project"]
                new = self.store.commit(project_id, font, extra, request.summary or name, revision)
                result.revision = new["revision"]
                result.summary = f"Committed {name}: {len(result.changed)} changed item(s)"
            elif name in ("project_open", "project_inspect"):
                offset, limit = getattr(request, "offset", 0), getattr(request, "limit", 50)
                names = sorted(font.keys())
                result.data = {
                    "capabilities": CAPABILITIES,
                    "brief": manifest["brief"],
                    "decisions": manifest["decisions"],
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
            elif name == "glyph_get":
                require(request.glyph_id in font, "missing_reference", f"Missing glyph {request.glyph_id}")
                result.data = {
                    "glyph_id": request.glyph_id,
                    **glyph_data(font[request.glyph_id]).model_dump(),
                    "metrics": metrics(font[request.glyph_id], font),
                }
            elif name == "history_list":
                entries = [
                    {
                        key: entry.get(key)
                        for key in (
                            "revision",
                            "parent",
                            "created_at",
                            "summary",
                            "restored_from",
                            "source_sha256",
                        )
                    }
                    for entry in self.store.history(project_id)
                ]
                if request.revision:
                    entries = entries[next(i for i, v in enumerate(entries) if v["revision"] == revision) :]
                offset, limit = request.offset, request.limit
                result.data = {
                    "entries": entries[offset : offset + limit],
                    "total": len(entries),
                    "next_offset": offset + limit if offset + limit < len(entries) else None,
                }
            elif name in ("font_build", "font_validate"):
                if name == "font_validate":
                    observations = validate_font(font)
                    coverage = {u for g in font for u in g.unicodes}
                    missing = sorted({ord(ch) for ch in request.corpus} - coverage)
                    result.data = {
                        "review": "automatic",
                        "valid": True,
                        "errors": [],
                        "observations": observations,
                        "missing_codepoints": missing,
                    }
                    result.warnings = [f"Missing U+{u:04X}" for u in missing]
                    if not font.info.openTypeNameLicense:
                        result.warnings.append("No font license declared by its creator")
                    try:
                        build, _ = compile_font(self.store, project_id, font, manifest, source, ["ttf"])
                        result.data["build"] = build
                    except FontError as exc:
                        result.data.update(valid=False, errors=[{"code": exc.code, "message": str(exc)}])
                    result.summary = (
                        "Technical validation passed"
                        if result.data["valid"]
                        else "Technical validation failed"
                    )
                else:
                    result.data, _ = compile_font(
                        self.store, project_id, font, manifest, source, request.formats
                    )
            elif name in ("render_glyph", "render_text"):
                sources = [(font, manifest, source)]
                if request.compare_revision:
                    sources.append(self.store.load(project_id, request.compare_revision))
                parameters = request.model_dump(exclude={"project_id", "revision", "compare_revision"})
                if name == "render_glyph":
                    frame = glyph_frame([f for f, _, _ in sources], request.glyph_id)
                else:
                    # Shared em-normalized frame makes revisions with different vertical metrics comparable.
                    frame = (
                        max(f.info.ascender / f.info.unitsPerEm for f, _, _ in sources),
                        min(f.info.descender / f.info.unitsPerEm for f, _, _ in sources),
                    )
                result.data["images"] = []
                for f, version, ufo in sources:
                    if name == "render_glyph":
                        image, details = glyph_view(f, request.glyph_id, request, frame)
                    else:
                        build, path = compile_font(self.store, project_id, f, version, ufo, ["ttf"])
                        image, details = text_view(
                            path, request, (frame[0] * f.info.unitsPerEm, frame[1] * f.info.unitsPerEm)
                        )
                        details["build"] = build
                        result.warnings.extend(details["warnings"])
                    data, png = save_render(
                        self.store, project_id, version["revision"], image, parameters, details
                    )
                    result.data["images"].append(data)
                    images.append(png)
            return result, images
