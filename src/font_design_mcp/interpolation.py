"""Bounded fontTools correspondence checks and compiled instance-grid integrity.

The worker runs in a timed child process so pathological outlines cannot occupy an MCP worker
indefinitely. Results are immutable reports tied to source revisions and binary hashes.
"""

import hashlib
import io
import itertools
import json
import subprocess
import sys

from fontTools.ttLib import TTFont
from fontTools.varLib.interpolatable import test_gen

from .domain import FontError, require
from .geometry import FlattenPen
from .quality import expects_ink, has_ink
from .storage import Store


def sample_locations(variation):
    axes = variation["axes"]
    locations = [
        dict(zip([a["tag"] for a in axes], values))
        for values in itertools.product(
            *[sorted({a["minimum"], (a["minimum"] + a["maximum"]) / 2, a["maximum"]}) for a in axes]
        )
    ]
    for master in variation["masters"]:
        if master["location"] not in locations:
            locations.append(master["location"])
    return locations


def analyze_sources(fonts):
    rows = []
    names = list(fonts)
    for glyph, issue in test_gen(
        [fonts[n] for n in names], names=names, upem=fonts["default"].info.unitsPerEm
    ):
        if len(rows) >= 2000:
            return {"complete": False, "findings": rows, "error": "Interpolation finding budget exceeded"}
        rows.append({"glyph": glyph, **issue})
    return {"complete": True, "findings": rows}


def analyze_grid(binary_bytes, variation):
    rows, counts = [], []
    points, work = 0, [4_000_000]
    with TTFont(io.BytesIO(binary_bytes)) as binary:
        cmap = binary.getBestCmap()
        visible = {name for cp, name in cmap.items() if expects_ink(cp)}
        for location in sample_locations(variation):
            glyphset = binary.getGlyphSet(location=location)
            checked = 0
            for name in sorted(visible):
                if points >= 4_000_000:
                    raise ValueError("Compiled grid point budget exceeded")
                pen = FlattenPen(
                    glyphset,
                    tolerance=min(0.25, binary["head"].unitsPerEm / 4000),
                    budget=min(20000, 4_000_000 - points),
                )
                glyphset[name].draw(pen)
                points += pen.count
                if not has_ink(pen.contours, work):
                    rows.append({"kind": "empty_interpolated_glyph", "glyph": name, "location": location})
                checked += 1
                if len(rows) >= 2000:
                    raise ValueError("Compiled grid finding budget exceeded")
            counts.append({"location": location, "glyphs_checked": checked})
    return {"complete": True, "findings": rows, "samples": counts}


def inspect_interpolation(store, project_id, manifest, binary_path, expected_sha256):
    if not manifest.get("variation"):
        return {"status": "not_applicable", "checks_passed": True}
    command = [
        sys.executable,
        "-m",
        "font_design_mcp.interpolation",
        str(store.root),
        project_id,
        manifest["revision"],
        str(binary_path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=45,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except subprocess.TimeoutExpired as exc:
        raise FontError("diagnostic_limit", "Interpolation worker exceeded 45 seconds") from exc
    if result.returncode or len(result.stdout) > 2_000_000:
        raise FontError("diagnostic_limit", "Interpolation worker failed; no passing evidence produced")
    report = json.loads(result.stdout)
    if report.get("status") == "checked":
        require(
            report.get("binary_sha256") == expected_sha256,
            "external_modification",
            "Interpolation binary differs from the verified compiler output",
        )
    report["report_uri"] = store.save_report(project_id, manifest["revision"], report)
    return report


if __name__ == "__main__":
    from pathlib import Path

    root, pid, revision, path = sys.argv[1:]
    store = Store(root)
    font, manifest, _ = store.load(pid, revision)
    fonts = store.load_masters(pid, manifest, font)
    data = Path(path).read_bytes()
    try:
        sources = analyze_sources(fonts)
        grid = analyze_grid(data, manifest["variation"])
        blocking_types = {
            "missing",
            "open_path",
            "path_count",
            "node_count",
            "node_incompatibility",
            "contour_order",
            "wrong_start_point",
        }
        blockers = [r for r in sources["findings"] if r["type"] in blocking_types] + grid["findings"]
        report = {
            "status": "checked",
            "checks_passed": sources["complete"] and not blockers,
            "sources": sources,
            "grid": grid,
            "blockers": blockers,
            "binary_sha256": hashlib.sha256(data).hexdigest(),
            "limitations": [
                "Source correspondence candidates and finite instance-grid ink checks; continuous design quality is not certified."
            ],
        }
    except (ValueError, ImportError) as exc:
        report = {"status": "unavailable", "checks_passed": False, "error": str(exc)}
    store.verify(pid, revision)
    print(json.dumps(report))
