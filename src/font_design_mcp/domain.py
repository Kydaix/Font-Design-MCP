"""Font operations without persistence or MCP. UFO objects are the editable model."""

import math

from fontTools.misc.transform import Transform
from fontTools.pens.areaPen import AreaPen
from fontTools.pens.recordingPen import RecordingPen
from ufoLib2 import Font
from ufoLib2.objects import Anchor, Component, Contour, Point

from . import models as m


class FontError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def require(condition, code, message):
    if not condition:
        raise FontError(code, message)


def set_info(font, metadata=None, metrics=None):
    if font.info.openTypeOS2Type is None:
        # Original projects must not inherit ufo2ft's Preview & Print-only default.
        font.info.openTypeOS2Type = []
    if metadata:
        for field, key in [
            ("familyName", "family"),
            ("styleName", "style"),
            ("copyright", "copyright"),
            ("openTypeNameLicense", "license_text"),
        ]:
            setattr(font.info, field, getattr(metadata, key))
    if metrics:
        for field, key in [
            ("unitsPerEm", "units_per_em"),
            ("ascender", "ascender"),
            ("descender", "descender"),
            ("capHeight", "cap_height"),
            ("xHeight", "x_height"),
        ]:
            setattr(font.info, field, getattr(metrics, key))
        font.info.openTypeOS2TypoAscender = round(metrics.ascender)
        font.info.openTypeOS2TypoDescender = round(metrics.descender)
        font.info.openTypeOS2TypoLineGap = 0
        font.info.openTypeHheaAscender = round(metrics.ascender)
        font.info.openTypeHheaDescender = round(metrics.descender)
        font.info.openTypeHheaLineGap = 0
        font.info.openTypeOS2WinAscent = round(metrics.ascender)
        font.info.openTypeOS2WinDescent = round(-metrics.descender)


def new_font(metadata, metrics):
    font = Font()
    set_info(font, metadata, metrics)
    font.info.versionMajor, font.info.versionMinor = 1, 0
    g = font.newGlyph(".notdef")
    g.width = 600
    # Original technical fallback: outer rectangle and reverse inner contour.
    for cid, coords in [
        ("outer", [(60, 0), (540, 0), (540, 700), (60, 700)]),
        ("inner", [(140, 80), (140, 620), (460, 620), (460, 80)]),
    ]:
        g.contours.append(
            Contour(
                [Point(x, y, "line", identifier=f"{cid}{i}") for i, (x, y) in enumerate(coords)],
                identifier=cid,
            )
        )
    font.newGlyph("space").width = 250
    font["space"].unicodes = [32]
    return font


def glyph_data(g):
    return m.Glyph(
        advance=g.width,
        unicodes=g.unicodes,
        contours=[
            m.Contour(
                id=c.identifier,
                points=[
                    m.Point(id=p.identifier, x=p.x, y=p.y, type=p.type or "offcurve", smooth=p.smooth)
                    for p in c.points
                ],
            )
            for c in g.contours
        ],
        components=[
            m.Component(id=c.identifier, base=c.baseGlyph, transform=tuple(c.transformation))
            for c in g.components
        ],
        anchors=[m.Anchor(id=a.identifier, name=a.name, x=a.x, y=a.y) for a in g.anchors],
    )


def metrics(g, font):
    b = g.getBounds(font)
    return {
        "advance": g.width,
        "bounds": list(b) if b else None,
        "visible_width": b[2] - b[0] if b else 0,
        "left_bearing": b[0] if b else None,
        "right_bearing": g.width - b[2] if b else None,
    }


def contour_obj(c):
    return Contour(
        [
            Point(p.x, p.y, None if p.type == "offcurve" else p.type, smooth=p.smooth, identifier=p.id)
            for p in c.points
        ],
        identifier=c.id,
    )


def replace_glyph(g, data):
    g.clear()
    g.width, g.unicodes = data.advance, list(data.unicodes)
    g.contours.extend(contour_obj(c) for c in data.contours)
    g.components.extend(Component(c.base, c.transform, identifier=c.id) for c in data.components)
    g.anchors.extend(Anchor(a.x, a.y, a.name, identifier=a.id) for a in data.anchors)


def find(items, identifier):
    matches = [v for v in items if v.identifier == identifier]
    require(bool(matches), "missing_reference", f"No element {identifier}")
    require(len(matches) == 1, "duplicate_id", f"Ambiguous element {identifier}")
    return matches[0]


def put(items, obj, replace):
    old = next((v for v in items if v.identifier == obj.identifier), None)
    require(
        bool(old is not None) == replace,
        "missing_reference" if replace else "duplicate_id",
        "Replacement requires an existing ID; addition requires a new ID",
    )
    if old is not None:
        items[items.index(old)] = obj
    else:
        items.append(obj)


def element_ids(g):
    return {
        v.identifier
        for v in [*g.contours, *g.components, *g.anchors, *(p for c in g.contours for p in c.points)]
    }


def edit_glyph(font, request):
    name = request.glyph_id
    require(
        (name not in font) == request.create,
        "missing_reference" if not request.create else "glyph_exists",
        "Set create=true only for a new glyph",
    )
    g = font.newGlyph(name) if request.create else font[name]
    before = element_ids(g)
    touched = []
    for op in request.operations:
        if isinstance(op, m.PutContour):
            put(g.contours, contour_obj(op.contour), op.replace)
            touched.append(op.contour.id)
        elif isinstance(op, m.MovePoint):
            p = find([p for c in g.contours for p in c.points], op.point_id)
            p.x, p.y = op.x, op.y
            touched.append(op.point_id)
        elif isinstance(op, m.Transform):
            transform_glyph(g, op.matrix, op.contour_ids)
            touched.extend(op.contour_ids if op.contour_ids is not None else sorted(element_ids(g)))
        elif isinstance(op, m.PutComponent):
            c = op.component
            put(g.components, Component(c.base, c.transform, identifier=c.id), op.replace)
            touched.append(c.id)
        elif isinstance(op, m.PutAnchor):
            a = op.anchor
            put(g.anchors, Anchor(a.x, a.y, a.name, identifier=a.id), op.replace)
            touched.append(a.id)
        elif isinstance(op, m.Remove):
            items = getattr(
                g, {"contour": "contours", "component": "components", "anchor": "anchors"}[op.kind]
            )
            items.remove(find(items, op.id))
            touched.append(op.id)
        elif isinstance(op, m.SetUnicodes):
            g.unicodes = list(op.unicodes)
            touched.append("unicodes")
        elif isinstance(op, m.ReplaceGlyph):
            replace_glyph(g, op.glyph)
            touched.extend(sorted(element_ids(g)))
    return {
        "glyph_id": name,
        "touched_ids": sorted(set(touched)),
        "removed_ids": sorted(before - element_ids(g)),
        "added_ids": sorted(element_ids(g) - before),
    }


def transform_glyph(g, matrix, contour_ids=None):
    t = Transform(*matrix)
    require(abs(t.xx * t.yy - t.xy * t.yx) > 1e-8, "invalid_geometry", "Singular affine transform")
    contours = g.contours if contour_ids is None else [find(g.contours, i) for i in contour_ids]
    for c in contours:
        for p in c.points:
            p.x, p.y = t.transformPoint((p.x, p.y))
    if contour_ids is None:
        for c in g.components:
            c.transformation = t.transform(c.transformation)
        for a in g.anchors:
            a.x, a.y = t.transformPoint((a.x, a.y))


def edit_spacing(font, request):
    touched = []
    for op in request.operations:
        if isinstance(op, (m.SetAdvance, m.Bearings)):
            require(op.glyph_id in font, "missing_reference", f"Missing glyph {op.glyph_id}")
            g = font[op.glyph_id]
            if isinstance(op, m.SetAdvance):
                g.width = op.value
            else:
                b = g.getBounds(font)
                require(b is not None, "invalid_geometry", "Empty glyph has no side bearings; set advance")
                transform_glyph(g, (1, 0, 0, 1, op.left - b[0], 0))
                g.width = b[2] - b[0] + op.left + op.right
            touched.append(op.glyph_id)
        elif isinstance(op, m.KernGroup):
            if op.glyphs is None:
                require(op.name in font.groups, "missing_reference", f"Missing group {op.name}")
                del font.groups[op.name]
            else:
                font.groups[op.name] = list(op.glyphs)
            touched.append(op.name)
        elif isinstance(op, m.KernPair):
            pair = (op.left, op.right)
            if op.value is None:
                require(pair in font.kerning, "missing_reference", "Missing kerning pair")
                del font.kerning[pair]
            else:
                font.kerning[pair] = op.value
            touched.append(f"{op.left}/{op.right}")
    return {"touched_ids": touched}


def validate_font(font):
    """Blocking geometry/security checks. Overlaps and optical overshoots are not errors."""
    require(len(font) <= 512, "limit_exceeded", "Maximum 512 glyphs")
    require(".notdef" in font and "space" in font, "missing_reference", "Technical glyphs required")
    require(font["space"].unicodes == [32], "invalid_unicode", "space must map to U+0020")
    require(not font[".notdef"].unicodes, "invalid_unicode", ".notdef must not map Unicode")
    require(bool(font[".notdef"].contours), "invalid_geometry", ".notdef needs a visible fallback outline")
    require(
        not font["space"].contours and not font["space"].components, "invalid_geometry", "space must be blank"
    )
    require(not font.features.text.strip(), "capability_unavailable", "Raw feature code is unsupported")
    require(not font.lib, "capability_unavailable", "Arbitrary UFO lib entries are unsupported")
    require(len(font.layers) == 1, "capability_unavailable", "Only a single master/layer is supported")
    m.Metrics(
        units_per_em=font.info.unitsPerEm,
        ascender=font.info.ascender,
        descender=font.info.descender,
        cap_height=font.info.capHeight,
        x_height=font.info.xHeight,
    )
    m.Metadata(family=font.info.familyName, style=font.info.styleName)
    unicode_map, total, observations = {}, 0, []
    for g in font:
        m.GlyphGet(project_id="0" * 32, glyph_id=g.name)
        data = glyph_data(g)  # Revalidate also after affine transforms and external load.
        require(not g.lib and not g.image.fileName, "capability_unavailable", "Glyph lib/images unsupported")
        ids = [
            v.id
            for v in [
                *data.contours,
                *data.components,
                *data.anchors,
                *(p for c in data.contours for p in c.points),
            ]
        ]
        require(len(ids) == len(set(ids)), "duplicate_id", f"IDs must be unique within {g.name}")
        for u in g.unicodes:
            require(u not in unicode_map, "invalid_unicode", f"Duplicate Unicode U+{u:04X}")
            unicode_map[u] = g.name
        for c in g.contours:
            total += len(c.points)
            on = [i for i, p in enumerate(c.points) if p.type is not None]
            require(bool(on), "invalid_geometry", "A contour needs explicit on-curve points")
            for j, i in enumerate(on):
                controls = (i - on[j - 1] - 1) % len(c.points)
                kind = c.points[i].type
                require(
                    (kind == "line" and controls == 0)
                    or (kind == "curve" and controls == 2)
                    or (kind == "qcurve" and controls >= 1),
                    "invalid_geometry",
                    f"Malformed {kind} segment in {g.name}/{c.identifier}",
                )
            pen = AreaPen()
            c.draw(pen)
            observations.append(
                {
                    "glyph": g.name,
                    "contour": c.identifier,
                    "signed_area": pen.value,
                    "direction": "ccw" if pen.value > 0 else "cw" if pen.value < 0 else "zero",
                }
            )
    require(total <= 50000, "limit_exceeded", "Maximum 50000 source points")

    # ponytail: bounded DFS per root; memoize if the 512-glyph ceiling is raised.
    def visit(name, stack):
        require(name in font, "missing_reference", f"Missing component base {name}")
        require(name not in stack, "component_cycle", f"Component cycle at {name}")
        require(len(stack) < 16, "limit_exceeded", "Component depth exceeds 16")
        g = font[name]
        count = 1 + sum(len(c.points) for c in g.contours)
        for c in g.components:
            count += visit(c.baseGlyph, (*stack, name))
            require(count <= 20000, "limit_exceeded", "Expanded glyph exceeds 20000 points")
        return count

    for g in font:
        visit(g.name, ())
        g.draw(RecordingPen())
        b = g.getBounds(font)
        require(
            b is None or all(math.isfinite(v) and abs(v) <= 16000 for v in b),
            "invalid_geometry",
            "Expanded bounds outside +/-16000 units",
        )
        if b and (b[1] < font.info.descender or b[3] > font.info.ascender):
            observations.append(
                {
                    "glyph": g.name,
                    "kind": "vertical_overshoot",
                    "bounds": list(b),
                    "message": "Outside vertical metrics; may be optical intent, review clipping",
                }
            )
    occupied = set()
    for name, members in font.groups.items():
        m.KernGroup(op="kern_group", name=name, glyphs=members)
        side = name.split(".")[1]
        for member in members:
            require(member in font, "missing_reference", f"Missing group member {member}")
            require((side, member) not in occupied, "invalid_kerning", "Overlapping same-side groups")
            occupied.add((side, member))
    require(len(font.kerning) <= 4096, "limit_exceeded", "Maximum 4096 kerning pairs")
    for (left, right), value in font.kerning.items():
        m.KernPair(op="kern_pair", left=left, right=right, value=value)
        for side, key in [(1, left), (2, right)]:
            require(
                key in font or (key in font.groups and key.startswith(f"public.kern{side}.")),
                "missing_reference",
                f"Invalid kerning side {key}",
            )
    return observations
