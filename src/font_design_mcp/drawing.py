"""Bounded numeric paths; no SVG documents, resources, or executable feature code."""

import ctypes
import math
import re

import freetype as ft
from booleanOperations import union
from fontTools.pens.recordingPen import RecordingPen
from fontTools.svgLib.path import parse_path
from ufoLib2.objects import Glyph

from .domain import require
from .models import Contour, Point

TOKEN = re.compile(r"[MLQCZ]|[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


def numeric_path(path):
    """Explicit absolute M/L/Q/C/Z only, with at most 256 segments per path."""
    tokens = TOKEN.findall(path)
    require(not TOKEN.sub("", path).strip(" ,\t\r\n"), "invalid_geometry", "Only numeric M/L/Q/C/Z paths")
    index, segments, started = 0, 0, False
    while index < len(tokens):
        command = tokens[index]
        require(command in {"M", "L", "Q", "C", "Z"}, "invalid_geometry", "Every segment needs a command")
        require(command == "M" or started, "invalid_geometry", "Path must start with M")
        size = {"M": 2, "L": 2, "Q": 4, "C": 6, "Z": 0}[command]
        points = tokens[index + 1 : index + 1 + size]
        require(
            len(points) == size and all(p not in {"M", "L", "Q", "C", "Z"} for p in points),
            "invalid_geometry",
            "Wrong segment coordinate count",
        )
        require(
            all(math.isfinite(float(p)) and abs(float(p)) <= 16000 for p in points),
            "invalid_geometry",
            "Path coordinates outside +/-16000",
        )
        started = command != "Z"
        index += size + 1
        segments += 1
    require(0 < segments <= 256, "limit_exceeded", "Maximum 256 segments per path")
    recording = RecordingPen()
    parse_path(" ".join(tokens), recording)
    return recording


def outline(path, width=88, cap="round", join="round"):
    recording = numeric_path(path)
    stroker = ft.Stroker()
    stroker.set(
        round(width * 32),
        {
            "round": ft.FT_STROKER_LINECAP_ROUND,
            "butt": ft.FT_STROKER_LINECAP_BUTT,
            "square": ft.FT_STROKER_LINECAP_SQUARE,
        }[cap],
        {
            "round": ft.FT_STROKER_LINEJOIN_ROUND,
            "bevel": ft.FT_STROKER_LINEJOIN_BEVEL,
            "miter": ft.FT_STROKER_LINEJOIN_MITER,
        }[join],
        4 * 65536,
    )

    def vector(point):
        return ctypes.byref(ft.FT_Vector(*(round(v * 64) for v in point)))

    operations = recording.value
    for index, (operation, points) in enumerate(operations):
        if operation == "moveTo":
            end = next(op for op, _ in operations[index + 1 :] if op in {"closePath", "endPath"})
            stroker.begin_subpath(vector(points[0]), end == "endPath")
        elif operation == "lineTo":
            stroker.line_to(vector(points[0]))
        elif operation == "curveTo":
            stroker.cubic_to(*(vector(point) for point in points))
        elif operation == "qCurveTo":
            stroker.conic_to(*(vector(point) for point in points))
        elif operation in {"closePath", "endPath"}:
            stroker.end_subpath()
    point_count, contour_count = stroker.get_counts()
    require(
        0 < point_count <= 8192 and 0 < contour_count <= 64,
        "limit_exceeded",
        "Expanded path exceeds 8192 points or 64 contours",
    )
    vectors = (ft.FT_Vector * point_count)()
    tags = (ctypes.c_ubyte * point_count)()
    ends = (ctypes.c_short * contour_count)()
    expanded = ft.Outline(ft.FT_Outline(0, 0, vectors, tags, ends, 0))
    stroker.export(expanded)
    glyph = Glyph()
    pen = glyph.getPen()
    started = False

    def xy(point):
        return point.x / 64, point.y / 64

    def move(point, _):
        nonlocal started
        if started:
            pen.closePath()
        pen.moveTo(xy(point))
        started = True

    expanded.decompose(
        move_to=move,
        line_to=lambda point, _: pen.lineTo(xy(point)),
        conic_to=lambda control, point, _: pen.qCurveTo(xy(control), xy(point)),
        cubic_to=lambda c1, c2, point, _: pen.curveTo(xy(c1), xy(c2), xy(point)),
    )
    pen.closePath()
    return glyph


def path_contours(paths, identifier, width=None, cap="round", join="round"):
    contours = []
    segments = 0
    for path in paths:
        recording = numeric_path(path)
        segments += len(recording.value)
        require(segments <= 512, "limit_exceeded", "Maximum 512 path segments per operation")
        if width is None:
            require(
                all(op != "endPath" for op, _ in recording.value),
                "invalid_geometry",
                "Filled paths must close with Z",
            )
            glyph = Glyph()
            recording.replay(glyph.getPen())
        else:
            glyph = outline(path, width, cap, join)
        contours.extend(glyph.contours)
        require(
            sum(len(c.points) for c in contours) <= 8192,
            "limit_exceeded",
            "Maximum 8192 generated points per operation",
        )
    clean = Glyph()
    union(contours, clean.getPointPen())
    require(
        len(clean.contours) <= 64 and sum(len(c.points) for c in clean) <= 8192,
        "limit_exceeded",
        "Union exceeds geometry budget",
    )
    return [
        Contour(
            id=f"{identifier}_c{ci}",
            points=[
                Point(
                    id=f"{identifier}_c{ci}_p{pi}",
                    x=round(p.x, 3),
                    y=round(p.y, 3),
                    type=p.type or "offcurve",
                    smooth=p.smooth,
                )
                for pi, p in enumerate(contour.points)
            ],
        )
        for ci, contour in enumerate(clean)
    ]


def primitive_path(op):
    x, y, w, h = op.x, op.y, op.width, op.height
    if op.shape == "rectangle":
        return f"M {x} {y} L {x + w} {y} L {x + w} {y + h} L {x} {y + h} Z"
    cx, cy, rx, ry, k = x + w / 2, y + h / 2, w / 2, h / 2, 0.5522847498
    return (
        f"M {cx} {y} C {cx + k * rx} {y} {x + w} {cy - k * ry} {x + w} {cy} "
        f"C {x + w} {cy + k * ry} {cx + k * rx} {y + h} {cx} {y + h} "
        f"C {cx - k * rx} {y + h} {x} {cy + k * ry} {x} {cy} "
        f"C {x} {cy - k * ry} {cx - k * rx} {y} {cx} {y} Z"
    )
