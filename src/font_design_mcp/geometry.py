"""Bounded geometry helpers. Smooth intent is separate from geometric continuity."""

import math

from fontTools.pens.basePen import BasePen


def point_context(glyph, identifier):
    matches = [(c, i) for c in glyph.contours for i, p in enumerate(c.points) if p.identifier == identifier]
    if len(matches) != 1:
        raise ValueError(f"Expected one point with ID {identifier}")
    return matches[0]


def move_node(glyph, identifier, x, y):
    contour, index = point_context(glyph, identifier)
    points = contour.points
    node = points[index]
    if node.type is None:
        raise ValueError("preserve_handles requires an on-curve node")
    dx, dy = x - node.x, y - node.y
    moved = [node]
    for neighbor in (points[index - 1], points[(index + 1) % len(points)]):
        if neighbor.type is None and all(neighbor is not p for p in moved):
            moved.append(neighbor)
    for point in moved:
        point.x += dx
        point.y += dy
    return [p.identifier for p in moved]


def move_handle(glyph, identifier, x, y, mode):
    """Cubic handles only: a quadratic control can belong to two different joins."""
    contour, index = point_context(glyph, identifier)
    points, n = contour.points, len(contour.points)
    handle = points[index]
    if handle.type is not None:
        raise ValueError("move_handle requires an off-curve control")
    if points[(index - 1) % n].type is not None and points[(index + 2) % n].type == "curve":
        node_index, opposite_index = (index - 1) % n, (index - 2) % n
        opposite_is_cubic = points[node_index].type == "curve"
    elif points[(index + 1) % n].type == "curve" and points[(index - 2) % n].type is not None:
        node_index, opposite_index = (index + 1) % n, (index + 2) % n
        opposite_is_cubic = points[(index + 4) % n].type == "curve"
    else:
        raise ValueError("Aligned editing needs a cubic handle; edit quadratic controls explicitly")
    node, opposite = points[node_index], points[opposite_index]
    if opposite.type is not None or not opposite_is_cubic:
        raise ValueError("Aligned editing requires a cubic handle on both sides of the node")
    dx, dy = x - node.x, y - node.y
    length = math.hypot(dx, dy)
    other_length = math.hypot(opposite.x - node.x, opposite.y - node.y)
    if length <= 1e-8 or other_length <= 1e-8:
        raise ValueError("Cannot align a zero-length handle")
    if mode not in {"aligned", "symmetric"}:
        raise ValueError("Unknown handle mode")
    radius = length if mode == "symmetric" else other_length
    handle.x, handle.y = x, y
    opposite.x, opposite.y = node.x - dx * radius / length, node.y - dy * radius / length
    node.smooth = True
    return [handle.identifier, opposite.identifier, node.identifier]


def join_issues(glyph, tolerance_degrees, *, undeclared=False):
    """Check smooth intent, or report unmarked curve joins as non-blocking review candidates."""
    for contour in glyph.contours:
        points = contour.points
        for index, node in enumerate(points):
            if node.type is None or bool(node.smooth) == undeclared:
                continue
            previous, following = points[index - 1], points[(index + 1) % len(points)]
            if undeclared and previous.type is not None and following.type is not None:
                continue
            vin = (node.x - previous.x, node.y - previous.y)
            vout = (following.x - node.x, following.y - node.y)
            left, right = math.hypot(*vin), math.hypot(*vout)
            evidence = {
                "glyph": glyph.name,
                "contour": contour.identifier,
                "point_id": node.identifier,
                "position": [node.x, node.y],
            }
            if undeclared:
                evidence.update(
                    kind="unmarked_curve_join",
                    message="Review tangent discontinuity: an intentional corner is allowed",
                )
            if min(left, right) <= 1e-8:
                yield {
                    **evidence,
                    "kind": "unmarked_curve_join" if undeclared else "degenerate_tangent",
                    "message": "Curve join has a zero tangent",
                }
                continue
            dot = (vin[0] * vout[0] + vin[1] * vout[1]) / (left * right)
            angle = math.degrees(math.acos(max(-1, min(1, dot))))
            if angle > tolerance_degrees:
                yield {
                    **evidence,
                    "kind": "unmarked_curve_join" if undeclared else "smooth_mismatch",
                    "angle_degrees": round(angle, 3),
                    "tolerance_degrees": tolerance_degrees,
                    "message": (
                        "Review tangent discontinuity: an intentional corner is allowed"
                        if undeclared
                        else "Declared smooth join has misaligned tangents; intentional corners should not be smooth"
                    ),
                }


class FlattenPen(BasePen):
    """Adaptive polyline approximation for diagnostic scanlines, never for exported outlines."""

    def __init__(self, glyphset, tolerance=0.25, budget=20000):
        super().__init__(glyphset)
        self.tolerance = tolerance
        self.budget = budget
        self.contours = []
        self.current = []
        self.count = 0

    def append(self, point):
        self.count += 1
        if self.count > self.budget:
            raise ValueError("Diagnostic flattening exceeds 20000 points")
        self.current.append(tuple(point))

    def _moveTo(self, point):
        self.current = []
        self.append(point)

    def _lineTo(self, point):
        self.append(point)

    def _closePath(self):
        if self.current:
            if self.current[-1] != self.current[0]:
                self.append(self.current[0])
            self.contours.append(self.current)
        self.current = []

    def _endPath(self):
        raise ValueError("Diagnostic scanlines require closed contours")

    def flatten(self, points, depth=0):
        start, end = points[0], points[-1]
        dx, dy = end[0] - start[0], end[1] - start[1]
        chord = math.hypot(dx, dy)
        polygon = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
        # The excess-length test catches collinear reversals and loops with coincident endpoints.
        distances = [
            abs(dx * (p[1] - start[1]) - dy * (p[0] - start[0])) / chord
            if chord > 1e-8
            else math.dist(start, p)
            for p in points[1:-1]
        ]
        if max(distances, default=0) <= self.tolerance and polygon - chord <= self.tolerance:
            self.append(end)
            return
        if depth >= 20:
            raise ValueError("Diagnostic curve subdivision did not converge")
        left, right, level = [start], [end], points
        while len(level) > 1:
            level = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(level, level[1:])]
            left.append(level[0])
            right.append(level[-1])
        self.flatten(left, depth + 1)
        self.flatten(list(reversed(right)), depth + 1)

    def _curveToOne(self, p1, p2, p3):
        self.flatten([self._getCurrentPoint(), p1, p2, p3])

    def _qCurveToOne(self, p1, p2):
        self.flatten([self._getCurrentPoint(), p1, p2])


def filled_spans(contours, axis, position):
    """Non-zero winding fill, half-open intersections; returns left-to-right/bottom-to-top spans."""
    events = []
    for contour in contours:
        for a, b in zip(contour, contour[1:]):
            if axis == "vertical":
                a, b = (a[1], a[0]), (b[1], b[0])
            if (a[1] <= position < b[1]) or (b[1] <= position < a[1]):
                x = a[0] + (position - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                events.append((x, 1 if b[1] > a[1] else -1))
    grouped = []
    for x, winding in sorted(events):
        if grouped and abs(x - grouped[-1][0]) < 1e-8:
            grouped[-1] = (grouped[-1][0], grouped[-1][1] + winding)
        else:
            grouped.append((x, winding))
    spans, winding, start = [], 0, None
    for x, delta in grouped:
        before, winding = winding, winding + delta
        if before == 0 and winding != 0:
            start = x
        elif before != 0 and winding == 0 and start is not None:
            if x - start > 1e-8:
                spans.append((start, x))
            start = None
    if winding:
        raise ValueError("Unbalanced outline winding on diagnostic scanline")
    return spans
