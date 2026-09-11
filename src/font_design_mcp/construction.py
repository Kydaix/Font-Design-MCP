"""Editable centerline construction with shared normal-width parameters.

Width transforms move centerlines before stroking. They do not stretch finished outlines.
Contours retain per-stroke ownership; overlaps are intentional and compiled as non-zero fill.
"""

from . import models as m
from .domain import contour_obj, require
from .drawing import numeric_path, path_contours

NETWORK_KEY = "io.font-design-mcp.stroke-network"


def rebuild(glyph, network):
    contours = []
    for stroke in network.strokes:
        commands = []
        for op, points in numeric_path(stroke.path).value:
            command = {
                "moveTo": "M",
                "lineTo": "L",
                "curveTo": "C",
                "qCurveTo": "Q",
                "closePath": "Z",
                "endPath": "",
            }[op]
            coords = []
            for x, y in points:
                x = network.origin_x + (x - network.origin_x) * network.horizontal_scale
                require(abs(x) <= 16000, "invalid_geometry", "Scaled centerline exceeds coordinate limits")
                coords.extend([str(x), str(y)])
            commands.append(" ".join([command, *coords]))
        contours.extend(
            path_contours(
                [" ".join(commands)],
                f"net_{stroke.id}",
                network.parameters[stroke.width_parameter],
                stroke.cap,
                stroke.join,
            )
        )
    require(
        len(contours) <= 64 and sum(len(c.points) for c in contours) <= 8192,
        "limit_exceeded",
        "Stroke network exceeds glyph geometry budget",
    )
    glyph.contours.clear()
    glyph.components.clear()
    glyph.contours.extend(contour_obj(c) for c in contours)
    glyph.width = network.advance
    glyph.lib[NETWORK_KEY] = network.model_dump(mode="json")


def edit_network(glyph, operation):
    if isinstance(operation, m.DetachStrokeNetwork):
        require(NETWORK_KEY in glyph.lib, "missing_reference", "No stroke network to detach")
        del glyph.lib[NETWORK_KEY]
        return
    if isinstance(operation, m.SetStrokeNetwork):
        require(
            operation.replace or not (glyph.contours or glyph.components),
            "glyph_exists",
            "Replacing an outline with a network requires replace=true",
        )
        network = operation.network
    else:
        require(NETWORK_KEY in glyph.lib, "missing_reference", "No stroke network to update")
        network = m.StrokeNetwork.model_validate(glyph.lib[NETWORK_KEY])
        require(
            set(operation.parameters) <= set(network.parameters),
            "missing_reference",
            "Unknown width parameter",
        )
        network.parameters.update(operation.parameters)
        if operation.horizontal_scale is not None:
            network.horizontal_scale = operation.horizontal_scale
        if operation.advance is not None:
            network.advance = operation.advance
    rebuild(glyph, network)
