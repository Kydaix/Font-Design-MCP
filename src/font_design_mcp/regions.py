"""Spatial measurement coverage and explainable Latin structure candidates.

Templates identify places to inspect, not universal stylistic proportions. Explicit regions add
requirements for a project's anatomy. A measurement's location, not its caller-supplied name,
determines coverage. They never certify character recognition.
"""

from .geometry import FlattenPen, filled_spans

STEM = (0.02, 0.15, 0.28, 0.7)
LEFT = (0.15, 0.6, 0.42, 0.88)
RIGHT = (0.58, 0.6, 0.85, 0.88)
TEMPLATES = {
    "K": [
        ("stem", STEM),
        ("upper_branch", (0.45, 0.65, 0.8, 0.85)),
        ("lower_branch", (0.5, 0.12, 0.85, 0.3)),
        ("junction", (0.18, 0.35, 0.55, 0.62)),
    ],
    "M": [
        ("left_stem", STEM),
        ("right_stem", (0.72, 0.15, 0.98, 0.7)),
        ("left_branch", (0.22, 0.45, 0.44, 0.68)),
        ("right_branch", (0.56, 0.45, 0.78, 0.68)),
        ("junction", (0.4, 0.1, 0.6, 0.45)),
    ],
    "N": [
        ("left_stem", STEM),
        ("right_stem", (0.72, 0.15, 0.98, 0.7)),
        ("diagonal", (0.32, 0.35, 0.68, 0.65)),
    ],
    "Y": [
        ("stem", (0.4, 0.05, 0.6, 0.3)),
        ("left_branch", LEFT),
        ("right_branch", RIGHT),
        ("junction", (0.35, 0.32, 0.65, 0.58)),
    ],
    "V": [("left_branch", LEFT), ("right_branch", RIGHT), ("junction", (0.35, 0.03, 0.65, 0.3))],
    "W": [
        ("left_branch", (0.08, 0.5, 0.25, 0.8)),
        ("middle_left", (0.3, 0.3, 0.5, 0.6)),
        ("middle_right", (0.5, 0.3, 0.7, 0.6)),
        ("right_branch", (0.75, 0.5, 0.92, 0.8)),
    ],
    "X": [
        ("upper_left", LEFT),
        ("upper_right", RIGHT),
        ("lower_left", (0.15, 0.12, 0.42, 0.4)),
        ("lower_right", (0.58, 0.12, 0.85, 0.4)),
        ("junction", (0.35, 0.35, 0.65, 0.65)),
    ],
    "R": [("stem", STEM), ("bowl", (0.65, 0.6, 0.95, 0.9)), ("leg", (0.55, 0.12, 0.85, 0.32))],
}
TEMPLATES.update({lower: TEMPLATES[upper] for lower, upper in [("v", "V"), ("w", "W"), ("x", "X")]})
# k/y/m have different ascender/descender anatomy; their regions remain explicitly declared.


def region_coverage(font, spec, measurements, master_id):
    regions = []
    for glyph in sorted(font, key=lambda g: g.name):
        for cp in glyph.unicodes:
            for label, box in TEMPLATES.get(chr(cp), []):
                regions.append(
                    {
                        "id": f"{glyph.name}.{label}",
                        "glyph": glyph.name,
                        "bounds": box,
                        "minimum_samples": 2,
                        "source": "latin_template",
                    }
                )
    for region in spec.regions:
        if region.master_id in (None, master_id):
            regions.append(
                {
                    "id": region.id,
                    "glyph": region.glyph_id,
                    "bounds": region.bounds,
                    "minimum_samples": region.minimum_samples,
                    "source": "declared",
                    "role": region.role,
                }
            )
    observed = {}
    for row in measurements:
        points = []
        if row["kind"] == "stroke_profile" and row["checks_passed"]:
            points = [s["center"] for s in row["samples"] if s["actual"] is not None]
        elif (
            row["kind"] == "stroke_probe"
            and row["actual"] is not None
            and abs(row["actual"] - row["target"]) <= row["tolerance"]
        ):
            index = row.get("span_index", 0)
            if index < len(row["spans"]):
                middle = sum(row["spans"][index]) / 2
                points = [
                    (middle, row["position"]) if row["axis"] == "horizontal" else (row["position"], middle)
                ]
        observed.setdefault(row.get("glyph"), set()).update(
            tuple(round(v, 4) for v in point) for point in points
        )
    result = []
    for region in regions:
        glyph = font.get(region["glyph"])
        bounds = glyph.getBounds(font) if glyph else None
        points = []
        if bounds and bounds[2] > bounds[0] and bounds[3] > bounds[1]:
            x0, y0, x1, y1 = region["bounds"]
            for x, y in observed.get(region["glyph"], ()):
                u, v = (x - bounds[0]) / (bounds[2] - bounds[0]), (y - bounds[1]) / (bounds[3] - bounds[1])
                if x0 <= u <= x1 and y0 <= v <= y1:
                    points.append([x, y])
        spread = (
            max((max(p[i] for p in points) - min(p[i] for p in points) for i in (0, 1)), default=0)
            if points
            else 0
        )
        result.append(
            {
                **region,
                "sample_count": len(points),
                "sample_centers": sorted(points),
                "covered": len(points) >= region["minimum_samples"]
                and (region["minimum_samples"] == 1 or spread >= 1),
            }
        )
    return result


def anatomy_candidates(font):
    # Expected multiple separated strokes at selected heights for conventional Latin constructions.
    patterns = {"Y": (0.8, 2), "M": (0.1, 2), "N": (0.5, 3), "K": (0.85, 2), "X": (0.85, 2)}
    for glyph in font:
        for cp in glyph.unicodes:
            if chr(cp) not in patterns:
                continue
            fraction, expected = patterns[chr(cp)]
            bounds = glyph.getBounds(font)
            if not bounds:
                continue
            pen = FlattenPen(font, tolerance=min(0.25, font.info.unitsPerEm / 4000), budget=20000)
            try:
                glyph.draw(pen)
                y = bounds[1] + fraction * (bounds[3] - bounds[1])
                actual = len(filled_spans(pen.contours, "horizontal", y))
                if actual != expected:
                    yield {
                        "kind": "latin_structure_unexpected",
                        "glyph": glyph.name,
                        "codepoint": cp,
                        "position": y,
                        "expected_spans": expected,
                        "actual_spans": actual,
                        "message": "Conventional Latin structure differs; inspect identity and explain any intentional alternate construction",
                    }
            except ValueError as exc:
                yield {"kind": "anatomy_unavailable", "glyph": glyph.name, "message": str(exc)}
