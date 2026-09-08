"""Measure UTF-8 JSON bytes, not model tokens; use the live exported catalogue."""

import copy
import json
import sys
import tempfile
from pathlib import Path

from font_design_mcp import models as m
from font_design_mcp.drawing import path_contours
from font_design_mcp.service import TOOLS, Service

root = Path(__file__).parents[1]
sys.path.insert(0, str(root / "examples" / "miette"))


def size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


catalogue = json.loads((root / "dist" / "tool-schemas.json").read_text("utf-8"))
annotated = copy.deepcopy(catalogue)
for tool in annotated["tools"]:
    tool["inputSchema"] = TOOLS[tool["name"]][0].model_json_schema()
    tool["outputSchema"] = m.Result.model_json_schema()
path = ["M 90 44 L 330 666 L 570 44", "M 172 255 L 488 255"]
primitive = {"op": "stroke_path", "paths": path, "width": 88, "advance": 660}
expanded = {
    "op": "replace_glyph",
    "glyph": {"advance": 660, "contours": [c.model_dump() for c in path_contours(path, "outline", 88)]},
}
report = {
    "unit": "UTF-8 JSON bytes; excludes images and MCP envelope; not model tokens",
    "catalogue_tools": len(catalogue["tools"]),
    "catalogue_bytes": size(catalogue),
    "same_catalogue_with_titles_bytes": size(annotated),
    "stroke_request_bytes": size(primitive),
    "expanded_request_bytes": size(expanded),
}
with tempfile.TemporaryDirectory(prefix="font-output-size-") as folder:
    from drawings import METRICS, glyphs

    service = Service(Path(folder).resolve())
    created, _ = service.execute(
        "project_create", m.ProjectCreate(metadata=m.Metadata(family="Miette"), metrics=m.Metrics(**METRICS))
    )
    pid = created.project_id
    state, _ = service.execute(
        "font_edit",
        m.FontEdit(
            project_id=pid,
            expected_revision=created.revision,
            glyphs=[
                {
                    "glyph_id": name,
                    "create": name != "space",
                    "operations": [{"op": "replace_glyph", "glyph": data}],
                }
                for name, data in glyphs().items()
            ],
        ),
    )
    for tool, model, extra in [
        ("render_text", m.RenderText, {"text": "Miette aime les belles lettres"}),
        ("font_validate", m.Validate, {}),
    ]:
        report[tool] = {}
        for detail in ("full", "summary"):
            result, _ = service.execute(tool, model(project_id=pid, detail=detail, **extra))
            report[tool][detail] = size(result.data)
(root / "dist" / "audit-output-sizes.json").write_text(json.dumps(report, indent=2), "utf-8")
print(json.dumps(report, indent=2))
