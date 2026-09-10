"""Bounded outline checks and normal-width measurements. No inferred artistic approval."""

import hashlib
import json
import math
import unicodedata

from .geometry import FlattenPen, filled_spans


def expects_ink(codepoint):
    char = chr(codepoint)
    # Invisible formatting controls, separators, variation selectors and Unicode fillers.
    invisible = codepoint in {0x034F, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x3164, 0xFFA0}
    invisible |= 0x180B <= codepoint <= 0x180F or 0xFE00 <= codepoint <= 0xFE0F
    invisible |= 0xE0100 <= codepoint <= 0xE01EF
    return not (invisible or char.isspace() or unicodedata.category(char)[0] in "CZ")


def finding_id(row, master_id):
    data = json.dumps({"master_id": master_id, **row}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def canonical_polygon(contour, origin):
    pts = [(round(x - origin[0], 5), round(y - origin[1], 5)) for x, y in contour]
    if pts and pts[-1] == pts[0]:
        pts.pop()
    if not pts:
        return ()

    def rotate_minimum(seq):
        # Booth's algorithm: repeated vertices must not allocate O(n**2) rotations.
        n, i, j, k = len(seq), 0, 1, 0
        while i < n and j < n and k < n:
            a, b = seq[(i + k) % n], seq[(j + k) % n]
            if a == b:
                k += 1
                continue
            if a > b:
                i += k + 1
                if i == j:
                    i += 1
            else:
                j += k + 1
                if i == j:
                    j += 1
            k = 0
        start = min(i, j)
        return tuple(seq[start:] + seq[:start])

    return min(rotate_minimum(pts), rotate_minimum(list(reversed(pts))))


def outline_key(contours):
    all_points = [p for c in contours for p in c]
    if not all_points:
        return None
    origin = min(p[0] for p in all_points), min(p[1] for p in all_points)
    polygons = [canonical_polygon(c, origin) for c in contours]
    areas = [sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(c, c[1:])) for c in contours]
    largest = max(range(len(areas)), key=lambda i: (abs(areas[i]), polygons[i]))
    orientation = 1 if areas[largest] >= 0 else -1
    return tuple(
        sorted(((1 if a > 0 else -1 if a < 0 else 0) * orientation, p) for a, p in zip(areas, polygons))
    )


def cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def self_crossings(contours, work):
    """Strict crossings within a contour; overlaps/touches between contours are not certified."""
    for ci, contour in enumerate(contours):
        segments = [(i, a, b) for i, (a, b) in enumerate(zip(contour, contour[1:])) if a != b]
        active = []
        for i, a, b in sorted(segments, key=lambda s: min(s[1][0], s[2][0])):
            left = min(a[0], b[0])
            active = [(j, c, d) for j, c, d in active if max(c[0], d[0]) >= left]
            for j, c, d in active:
                work[0] -= 1
                if work[0] < 0:
                    raise ValueError("Outline intersection comparison budget exceeded")
                if abs(i - j) == 1 or {i, j} == {0, len(contour) - 2}:
                    continue
                if max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1]):
                    continue
                if cross(a, b, c) * cross(a, b, d) < -1e-8 and cross(c, d, a) * cross(c, d, b) < -1e-8:
                    yield {"contour_index": ci, "segments": [i, j], "near": list(a)}
            active.append((i, a, b))


def has_ink(contours, work):
    # A nonzero winding integral proves ink; zero integral also occurs for bow-ties
    # and separate oppositely oriented shapes, so it must not by itself reject them.
    area = sum(a[0] * b[1] - b[0] * a[1] for c in contours for a, b in zip(c, c[1:]))
    if abs(area) > 1e-8:
        return True
    ys = sorted({p[1] for c in contours for p in c})
    # Fast positive witnesses. A single midline can coincide with a bow-tie's crossing.
    for a, b in zip(ys, ys[1:]):
        work[0] -= sum(len(c) for c in contours)
        if work[0] < 0:
            raise ValueError("Outline ink scan budget exceeded")
        if filled_spans(contours, "horizontal", a + (b - a) / 3):
            return True
    # To conclude absence, split slabs at every proper segment intersection too.
    # Between those events the crossing order and winding are constant.
    events, active = set(ys), []
    segments = [(a, b) for c in contours for a, b in zip(c, c[1:]) if a != b]
    for a, b in sorted(segments, key=lambda s: min(s[0][0], s[1][0])):
        active = [(c, d) for c, d in active if max(c[0], d[0]) >= min(a[0], b[0])]
        for c, d in active:
            work[0] -= 1
            if work[0] < 0:
                raise ValueError("Outline ink intersection budget exceeded")
            if cross(a, b, c) * cross(a, b, d) < -1e-8 and cross(c, d, a) * cross(c, d, b) < -1e-8:
                dx, dy = b[0] - a[0], b[1] - a[1]
                ex, ey = d[0] - c[0], d[1] - c[1]
                t = ((c[0] - a[0]) * ey - (c[1] - a[1]) * ex) / (dx * ey - dy * ex)
                events.add(a[1] + t * dy)
        active.append((a, b))
    events = sorted(events)
    for a, b in zip(events, events[1:]):
        work[0] -= len(segments)
        if work[0] < 0:
            raise ValueError("Outline ink scan budget exceeded")
        if filled_spans(contours, "horizontal", (a + b) / 2):
            return True
    return False


def outline_findings(font, scope):
    """Yield (blocking, finding). Bounds are enforced across the whole font, not per rule."""
    remaining, work = 1_000_000, [2_000_000]
    signatures = {}
    tolerance = min(0.25, font.info.unitsPerEm / 4000)
    scope.update(
        glyphs_checked=0,
        complete=True,
        flatten_tolerance=tolerance,
        intersection_scope="Strict within-contour crossings of bounded flattened outlines",
    )
    for glyph in sorted(font, key=lambda g: g.name):
        try:
            if remaining <= 0:
                raise ValueError("Whole-font outline flattening budget exceeded")
            pen = FlattenPen(font, tolerance=tolerance, budget=min(20000, remaining))
            try:
                glyph.draw(pen)
            finally:
                remaining -= pen.count
            ink = has_ink(pen.contours, work)
            scope["glyphs_checked"] += 1
            if not ink and any(expects_ink(cp) for cp in glyph.unicodes):
                yield (
                    True,
                    {
                        "kind": "empty_visible_glyph",
                        "glyph": glyph.name,
                        "codepoints": glyph.unicodes,
                        "message": "Encoded visible character has no filled outline; draw it before delivery",
                    },
                )
            seen = 0
            for ci, contour in enumerate(pen.contours):
                if not has_ink([contour], work):
                    yield (
                        False,
                        {
                            "kind": "degenerate_contour",
                            "glyph": glyph.name,
                            "contour_index": ci,
                            "message": "This contour has no filled area; remove it or explain its purpose",
                        },
                    )
            for crossing in self_crossings(pen.contours, work):
                yield (
                    False,
                    {
                        "kind": "self_intersection",
                        "glyph": glyph.name,
                        **crossing,
                        "message": "Inspect this crossing; overlaps may be intentional",
                    },
                )
                seen += 1
                if seen >= 16:
                    yield (
                        False,
                        {
                            "kind": "intersection_details_limited",
                            "glyph": glyph.name,
                            "message": "First 16 crossings shown; repair and rerun to expose remaining crossings",
                        },
                    )
                    break
            if ink and glyph.unicodes:
                key = outline_key(pen.contours)
                semantics = {unicodedata.normalize("NFD", chr(cp)) for cp in glyph.unicodes}
                if len(semantics) > 1:
                    yield (
                        False,
                        {
                            "kind": "shared_unicode_outline",
                            "glyph": glyph.name,
                            "codepoints": sorted(glyph.unicodes),
                            "message": "Non-equivalent characters share this glyph; verify this association is intentional",
                        },
                    )
                for other, other_semantics in signatures.get(key, []):
                    if semantics.isdisjoint(other_semantics):
                        yield (
                            False,
                            {
                                "kind": "matching_outlines",
                                "glyphs": [other, glyph.name],
                                "flatten_tolerance": tolerance,
                                "message": "Different characters have matching sampled outlines up to translation; verify identity",
                            },
                        )
                signatures.setdefault(key, []).append((glyph.name, semantics))
        except ValueError as exc:
            scope["complete"] = False
            yield True, {"kind": "diagnostic_limit", "glyph": glyph.name, "message": str(exc)}
            if remaining <= 0 or work[0] < 0:
                break


def measure_profile(contours, profile, tolerance):
    start, end = profile.start, profile.end
    length = math.dist(start, end)
    tangent = ((end[0] - start[0]) / length, (end[1] - start[1]) / length)
    normal = (-tangent[1], tangent[0])
    rotated = [
        [(x * normal[0] + y * normal[1], x * tangent[0] + y * tangent[1]) for x, y in contour]
        for contour in contours
    ]
    samples = []
    for i in range(profile.samples):
        t = i / (profile.samples - 1)
        center = (start[0] + t * (end[0] - start[0]), start[1] + t * (end[1] - start[1]))
        u = center[0] * normal[0] + center[1] * normal[1]
        v = center[0] * tangent[0] + center[1] * tangent[1]
        spans = filled_spans(rotated, "horizontal", v)
        if profile.region == "counter":
            spans = [(a[1], b[0]) for a, b in zip(spans, spans[1:])]
        span = next(((a, b) for a, b in spans if a + 1e-8 < u < b - 1e-8), None)
        endpoints = (
            [[a * normal[0] + v * tangent[0], a * normal[1] + v * tangent[1]] for a in span] if span else []
        )
        actual = span[1] - span[0] if span else None
        samples.append(
            {
                "index": i,
                "center": list(center),
                "actual": actual,
                "endpoints": endpoints,
                "within_range": actual is not None
                and profile.minimum - 1e-7 <= actual <= profile.maximum + 1e-7,
            }
        )
    widths = [s["actual"] for s in samples if s["actual"] is not None]
    ratio = max(widths) / min(widths) if len(widths) == len(samples) else None
    passed = all(s["within_range"] for s in samples)
    passed &= profile.max_ratio is None or (ratio is not None and ratio <= profile.max_ratio + 1e-9)
    return {
        "kind": "stroke_profile",
        "glyph": profile.glyph_id,
        "rule_id": profile.id,
        "region": profile.region,
        "minimum": profile.minimum,
        "maximum": profile.maximum,
        "max_ratio": profile.max_ratio,
        "actual_ratio": ratio,
        "samples": samples,
        "checks_passed": passed,
        "flatten_tolerance": tolerance,
    }
