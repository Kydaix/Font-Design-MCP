"""Revision-scoped design contracts and explainable diagnostics, not artistic approval."""

from . import models as m
from .domain import metrics, require
from .geometry import FlattenPen, filled_spans, join_issues
from .quality import finding_id, measure_profile, outline_findings


def design_state(manifest):
    return m.DesignState.model_validate(manifest.get("design", {}))


def applies_to_master(rule, master_id):
    return rule.location is None and rule.master_id in (None, master_id)


def needs_variation(spec):
    return bool(spec.variation_probes) or any(
        r.location is not None for r in [*spec.metric_rules, *spec.stroke_probes, *spec.stroke_profiles]
    )


def validate_rule_scopes(spec, manifest):
    variation = m.Variation.model_validate(manifest["variation"]) if manifest.get("variation") else None
    masters = {s.id for s in variation.masters} if variation else {"default"}
    axes = {a.tag: a for a in variation.axes} if variation else {}

    def location_valid(location):
        require(
            variation is not None, "invalid_input", "Location and variation rules require a variable font"
        )
        require(
            all(
                tag in axes and axes[tag].minimum <= value <= axes[tag].maximum
                for tag, value in location.items()
            ),
            "invalid_input",
            "Design rule location has an unknown axis or is outside its range",
        )

    for rule in [*spec.metric_rules, *spec.stroke_probes, *spec.stroke_profiles]:
        require(
            rule.master_id is None or rule.master_id in masters,
            "invalid_input",
            f"Unknown design rule master: {rule.master_id}",
        )
        if rule.location is not None:
            location_valid(rule.location)
    for probe in spec.variation_probes:
        for value in probe.values:
            location_valid({**probe.location, probe.axis_tag: value})


def coverage(font, spec, corpus=""):
    cmap = {u: g.name for g in font for u in g.unicodes}
    required = set(map(ord, spec.required_characters + corpus))
    if spec.digit_spacing != "unspecified":
        required.update(range(48, 58))
    return cmap, sorted(required - set(cmap))


class IssueBuffer:
    """Keep exact counts while bounding report bytes independently of the source point budget."""

    def __init__(self, initial=()):
        self.items = []
        self.total = 0
        self.extend(initial)

    def append(self, issue):
        self.total += 1
        if len(self.items) < 2000:
            self.items.append(issue)

    def extend(self, issues):
        for issue in issues:
            self.append(issue)

    def __len__(self):
        return self.total


def analyze_font(font, spec, master_id="default"):
    cmap, missing = coverage(font, spec)
    issues = IssueBuffer(
        {"kind": "missing_codepoint", "codepoint": code, "message": f"Required U+{code:04X} is missing"}
        for code in missing
    )
    measurements = []
    candidates = IssueBuffer()
    outline_scope = {}
    outline_errors = 0
    for blocking, finding in outline_findings(font, outline_scope):
        if blocking:
            issues.append(finding)
            outline_errors += 1
        else:
            candidates.append(finding)
    smooth_count = 0
    for name in spec.reference_glyphs:
        if name not in font:
            issues.append(
                {
                    "kind": "missing_reference_glyph",
                    "glyph": name,
                    "message": "A declared structural reference glyph is missing",
                }
            )
    for glyph in sorted(font, key=lambda g: g.name):
        issues.extend(join_issues(glyph, spec.tangent_tolerance_degrees))
        candidates.extend(join_issues(glyph, spec.tangent_tolerance_degrees, undeclared=True))
        smooth_count += sum(p.type is not None and p.smooth for c in glyph.contours for p in c.points)
    metric_rules = [r for r in spec.metric_rules if applies_to_master(r, master_id)]
    stroke_probes = [r for r in spec.stroke_probes if applies_to_master(r, master_id)]
    stroke_profiles = [r for r in spec.stroke_profiles if applies_to_master(r, master_id)]
    if spec.digit_spacing == "tabular":
        digits = [(cmap[u], font[cmap[u]].width) for u in range(48, 58) if u in cmap]
        if digits:
            low, high = min(w for _, w in digits), max(w for _, w in digits)
            measurements.append({"kind": "digit_advances", "values": dict(digits), "spread": high - low})
            if high - low > spec.digit_tolerance:
                issues.append(
                    {
                        "kind": "tabular_advance_mismatch",
                        "glyphs": [g for g, _ in digits],
                        "spread": high - low,
                        "tolerance": spec.digit_tolerance,
                        "message": "Tabular digits must share advance widths, not visible widths",
                    }
                )

    def missing_glyph(name, rule):
        if name in font:
            return False
        issues.append(
            {
                "kind": "missing_rule_glyph",
                "glyph": name,
                "rule_id": rule,
                "message": "Cannot evaluate a design rule on a missing glyph",
            }
        )
        return True

    def measure(kind, name, rule, actual, target, tolerance, **extra):
        row = {
            "kind": kind,
            "glyph": name,
            "rule_id": rule,
            "actual": actual,
            "target": target,
            "tolerance": tolerance,
            **extra,
        }
        measurements.append(row)
        if actual is None or abs(actual - target) > tolerance:
            issues.append(
                {
                    **row,
                    "kind": "unmeasurable" if actual is None else "design_target_mismatch",
                    "message": "Measurement unavailable" if actual is None else "Outside declared tolerance",
                }
            )

    for rule in metric_rules:
        for name in rule.glyphs:
            if missing_glyph(name, rule.id):
                continue
            data = metrics(font[name], font)
            bounds = data["bounds"]
            actual = (
                (bounds[3] - bounds[1] if bounds else None) if rule.metric == "height" else data[rule.metric]
            )
            if bounds is None and rule.metric != "advance":
                actual = None
            measure(rule.metric, name, rule.id, actual, rule.target, rule.tolerance)
    flattened = {}
    flattened_points = 0
    # Raster-like diagnostics need not change source curves. Error is declared, never hidden.
    tolerance = min(0.25, font.info.unitsPerEm / 4000)

    def contours_for(name):
        nonlocal flattened_points
        if name not in flattened:
            pen = FlattenPen(font, tolerance=tolerance, budget=min(20000, max(1, 200000 - flattened_points)))
            try:
                if flattened_points >= 200000:
                    raise ValueError("Whole-font diagnostic flattening budget exceeded")
                font[name].draw(pen)
                flattened[name] = pen.contours
            except ValueError as exc:
                flattened[name] = str(exc)
            flattened_points += pen.count
        return flattened[name]

    for probe in stroke_probes:
        name = probe.glyph_id
        if missing_glyph(name, probe.id):
            continue
        contours = contours_for(name)
        if isinstance(contours, str):
            issues.append(
                {"kind": "diagnostic_limit", "glyph": name, "rule_id": probe.id, "message": contours}
            )
            continue
        try:
            spans = filled_spans(contours, probe.axis, probe.position)
        except ValueError as exc:
            issues.append({"kind": "unmeasurable", "glyph": name, "rule_id": probe.id, "message": str(exc)})
            continue
        span = spans[probe.span_index] if probe.span_index < len(spans) else None
        measure(
            "stroke_probe",
            name,
            probe.id,
            span[1] - span[0] if span else None,
            probe.target,
            probe.tolerance,
            axis=probe.axis,
            position=probe.position,
            spans=[list(pair) for pair in spans[:64]],
            span_count=len(spans),
            spans_truncated=len(spans) > 64,
            flatten_tolerance=tolerance,
        )
    for profile in stroke_profiles:
        if missing_glyph(profile.glyph_id, profile.id):
            continue
        contours = contours_for(profile.glyph_id)
        try:
            if isinstance(contours, str):
                raise ValueError(contours)
            row = measure_profile(contours, profile, tolerance)
            measurements.append(row)
            if not row["checks_passed"]:
                issues.append(
                    {
                        **row,
                        "kind": "stroke_profile_mismatch",
                        "message": "Normal widths or variation exceed the declared profile; inspect sample endpoints",
                    }
                )
        except ValueError as exc:
            issues.append(
                {
                    "kind": "diagnostic_limit",
                    "glyph": profile.glyph_id,
                    "rule_id": profile.id,
                    "message": str(exc),
                }
            )
    for row in candidates.items:
        row["finding_id"] = finding_id(row, master_id)
    measured = sorted({row["glyph"] for row in measurements if "glyph" in row})
    shape_measured = sorted(
        {row["glyph"] for row in measurements if row["kind"] in {"stroke_probe", "stroke_profile"}}
    )
    unprobed_references = sorted(set(spec.reference_glyphs) - set(shape_measured))
    structural = sorted(
        set(spec.reference_glyphs)
        | {cmap[ord(c)] for c in "HOnosaASUKMNVRWXYkmy0123456789" if ord(c) in cmap}
    )
    return {
        "review": "automatic",
        "artistic_approval": False,
        "reference_fidelity": "not_assessed",
        "checks_passed": not issues,
        "coverage_complete": not missing,
        "outline_integrity_passed": outline_errors == 0 and outline_scope["complete"],
        "design_coverage": {
            "measured_glyphs": measured,
            "shape_measured_glyphs": shape_measured,
            "unprobed_reference_glyphs": unprobed_references,
            "structural_glyphs": structural,
            "unprobed_structural_glyphs": sorted(set(structural) - set(shape_measured)),
            "visual_review": "not_recorded_by_analysis",
        },
        "next_steps": [
            *(["Repair blocking findings, then rerun font_analyze."] if issues else []),
            *(
                ["Inspect localized review candidates; record intentional choices with proof_review."]
                if candidates
                else []
            ),
            *(
                ["Add stroke probes/profiles for structural glyphs: " + ", ".join(unprobed_references)]
                if unprobed_references
                else []
            ),
            "Render structural glyphs and shaped text at usage sizes before expanding coverage.",
            "Use font_release_check for revision-bound review coverage; analysis alone is not release approval.",
        ],
        "missing_codepoints": missing,
        "issues": issues.items,
        "issues_truncated": len(issues.items) < len(issues),
        "measurements": measurements,
        "counts": {
            "issues": len(issues),
            "measurements": len(measurements),
            "review_candidates": len(candidates),
        },
        "review_candidates": candidates.items,
        "review_candidates_truncated": len(candidates.items) < len(candidates),
        "scope": {
            "master_id": master_id,
            "smooth_joins_checked": smooth_count,
            "metric_rules_checked": len(metric_rules),
            "stroke_probes_checked": len(stroke_probes),
            "stroke_profiles_checked": len(stroke_profiles),
            "outline_integrity": outline_scope,
            "rules_for_other_masters": sum(
                r.master_id is not None and r.master_id != master_id
                for r in [*spec.metric_rules, *spec.stroke_probes, *spec.stroke_profiles]
            ),
            "variation": "pending" if needs_variation(spec) else "not_requested",
            "not_assessed": [
                "Visual fidelity to references",
                "Optical spacing and kerning",
                "Unprobed strokes and unsampled axis locations",
                "Artistic coherence",
            ],
        },
        "limitations": [
            "Passing checks is not professional or human approval.",
            "Default outline checks supplement declared smooth joins, coverage and explicit metric/profile rules.",
            "Stroke probes use bounded polyline approximation; choose scanlines away from joins and extrema.",
            "No automatic tracing, style inference, G2 continuity or self-intersection certification.",
        ],
    }


def refresh_compositions(font, links):
    """Recompute opted-in accent placement and advances in dependency order, atomically at service level."""
    done, visiting, changed = set(), set(), []

    def visit(name):
        if name in done or name not in links:
            return
        require(
            name not in visiting and len(visiting) < 16, "component_cycle", "Linked composition cycle/depth"
        )
        visiting.add(name)
        link = m.AccentLink.model_validate(links[name])
        require(
            name in font and link.base in font and link.mark in font,
            "missing_reference",
            f"Missing linked composition glyph for {name}",
        )
        for dependency in (link.base, link.mark):
            visit(dependency)
        glyph, base, mark = font[name], font[link.base], font[link.mark]
        components = {c.identifier: c for c in glyph.components}
        require(
            not glyph.contours and len(glyph.components) == 2 and set(components) == {"base", "mark"},
            "linked_composition",
            f"Detach {name} before changing its component structure",
        )
        require(
            components["base"].baseGlyph == link.base and components["mark"].baseGlyph == link.mark,
            "linked_composition",
            f"Component bases changed in linked glyph {name}",
        )
        anchors = []
        for source, anchor_name in ((base, link.base_anchor), (mark, link.mark_anchor)):
            matches = [a for a in source.anchors if a.name == anchor_name]
            require(len(matches) == 1, "missing_reference", f"Expected one anchor {anchor_name} for {name}")
            anchors.append(matches[0])
        translation = (1, 0, 0, 1, anchors[0].x - anchors[1].x, anchors[0].y - anchors[1].y)
        if (
            glyph.width != base.width
            or tuple(components["base"].transformation) != m.IDENTITY
            or tuple(components["mark"].transformation) != translation
        ):
            glyph.width = base.width
            components["base"].transformation = m.IDENTITY
            components["mark"].transformation = translation
            changed.append(name)
        visiting.remove(name)
        done.add(name)

    for name in sorted(links):
        visit(name)
    return changed
