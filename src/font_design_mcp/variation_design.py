"""Bounded measurements of the exported variable outlines at explicitly requested locations."""

import io

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

from .build import check_cancelled
from .design import IssueBuffer
from .geometry import FlattenPen, filled_spans
from .quality import measure_profile


def analyze_variation(binary_bytes, spec):
    issues = IssueBuffer()
    measurements = []
    point_count = 0
    with TTFont(io.BytesIO(binary_bytes)) as binary:
        defaults = {a.axisTag: a.defaultValue for a in binary["fvar"].axes}
        tolerance = min(0.25, binary["head"].unitsPerEm / 4000)

        def evaluate(rule, location, metric=None, name=None):
            nonlocal point_count
            check_cancelled()
            name = name or rule.glyph_id
            location = {**defaults, **location}
            row = {"rule_id": rule.id, "glyph": name, "location": location, "actual": None}
            glyphset = binary.getGlyphSet(location=location)
            if name not in glyphset:
                issues.append({**row, "kind": "missing_rule_glyph", "message": "Missing exported glyph"})
                return row
            glyph = glyphset[name]
            try:
                if metric:
                    if metric == "advance":
                        actual = glyph.width
                    else:
                        pen = BoundsPen(glyphset)
                        glyph.draw(pen)
                        bounds = pen.bounds
                        actual = (
                            None
                            if bounds is None
                            else {
                                "visible_width": bounds[2] - bounds[0],
                                "height": bounds[3] - bounds[1],
                                "left_bearing": bounds[0],
                                "right_bearing": glyph.width - bounds[2],
                            }[metric]
                        )
                    row.update(kind=metric, actual=actual)
                else:
                    if point_count >= 200000:
                        raise ValueError("Whole-report variable diagnostic flattening budget exceeded")
                    pen = FlattenPen(glyphset, tolerance=tolerance, budget=min(20000, 200000 - point_count))
                    try:
                        glyph.draw(pen)
                    finally:
                        point_count += pen.count
                    if hasattr(rule, "region"):
                        row.update(measure_profile(pen.contours, rule, tolerance))
                        return row
                    spans = filled_spans(pen.contours, rule.axis, rule.position)
                    span = spans[rule.span_index] if rule.span_index < len(spans) else None
                    row.update(
                        kind="stroke_probe",
                        actual=span[1] - span[0] if span else None,
                        axis=rule.axis,
                        position=rule.position,
                        span_index=rule.span_index,
                        spans=[list(s) for s in spans[:64]],
                        span_count=len(spans),
                        spans_truncated=len(spans) > 64,
                        flatten_tolerance=tolerance,
                    )
                if row["actual"] is None:
                    issues.append({**row, "kind": "unmeasurable", "message": "No measurable outline/span"})
            except ValueError as exc:
                issues.append({**row, "kind": "diagnostic_limit", "message": str(exc)})
            return row

        for rule in [*spec.metric_rules, *spec.stroke_probes, *spec.stroke_profiles]:
            if rule.location is None:
                continue
            metric = getattr(rule, "metric", None)
            names = rule.glyphs if metric else [rule.glyph_id]
            for name in names:
                row = evaluate(rule, rule.location, metric, name)
                if hasattr(rule, "region"):
                    measurements.append(row)
                    if not row.get("checks_passed", False):
                        issues.append(
                            {
                                **row,
                                "kind": "stroke_profile_mismatch",
                                "message": "Exported normal widths exceed the declared profile",
                            }
                        )
                    continue
                row.update(target=rule.target, tolerance=rule.tolerance)
                measurements.append(row)
                if row["actual"] is not None and abs(row["actual"] - rule.target) > rule.tolerance:
                    issues.append(
                        {**row, "kind": "design_target_mismatch", "message": "Outside declared tolerance"}
                    )

        for probe in spec.variation_probes:
            samples = [evaluate(probe, {**probe.location, probe.axis_tag: value}) for value in probe.values]
            sign = 1 if probe.direction == "nondecreasing" else -1
            # Compare against the running extremum: adding more samples must not hide a
            # cumulative reversal by splitting it into individually sub-tolerance steps.
            previous = None
            for current in samples:
                if current["actual"] is None:
                    continue
                if previous is None or sign * current["actual"] > sign * previous["actual"]:
                    previous = current
                    continue
                if sign * (current["actual"] - previous["actual"]) < -probe.tolerance:
                    issues.append(
                        {
                            "kind": "variation_direction_mismatch",
                            "rule_id": probe.id,
                            "glyph": probe.glyph_id,
                            "direction": probe.direction,
                            "tolerance": probe.tolerance,
                            "from": previous,
                            "to": current,
                            "message": "Measured stroke moves against the declared direction",
                        }
                    )
            first, last = samples[0]["actual"], samples[-1]["actual"]
            if first is not None and last is not None:
                change = sign * (last - first)
                if change + probe.tolerance < probe.minimum_change:
                    issues.append(
                        {
                            "kind": "variation_change_insufficient",
                            "rule_id": probe.id,
                            "glyph": probe.glyph_id,
                            "actual": change,
                            "minimum_change": probe.minimum_change,
                            "tolerance": probe.tolerance,
                            "message": "Endpoint stroke change is smaller than requested",
                        }
                    )
            measurements.append(
                {
                    "kind": "variation_probe",
                    "rule_id": probe.id,
                    "glyph": probe.glyph_id,
                    "axis_tag": probe.axis_tag,
                    "direction": probe.direction,
                    "samples": samples,
                    "tolerance": probe.tolerance,
                    "minimum_change": probe.minimum_change,
                }
            )
    return {
        "status": "checked",
        "checks_passed": not issues,
        "issues": issues.items,
        "issues_truncated": len(issues.items) < len(issues),
        "measurements": measurements,
        "counts": {"issues": len(issues), "measurements": len(measurements)},
        "limitations": [
            "Only declared scanlines and sampled locations are checked; this is not continuous axis certification.",
            "Span indices identify sorted filled intervals; inspect probes near intersections or topology changes.",
        ],
    }


def attach_variation(report, variation):
    """Keep aggregate counts exact and issue lists bounded."""
    report["variation"] = variation
    report["scope"]["variation"] = variation["status"]
    report["checks_passed"] = report["checks_passed"] and variation["checks_passed"]
    total = report["counts"]["issues"] + variation["counts"]["issues"]
    report["issues"] = (report["issues"] + variation["issues"])[:2000]
    report["issues_truncated"] = len(report["issues"]) < total
    report["counts"]["issues"] = total
    report["counts"]["measurements"] += variation["counts"]["measurements"]
    return report
