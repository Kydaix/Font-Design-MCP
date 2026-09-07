"""Unhinted non-zero outline rasterization using FreeType, Pillow and HarfBuzz."""

import hashlib
import io
import os
import uuid

import freetype
import uharfbuzz as hb
from fontTools.misc.transform import Transform
from fontTools.pens.freetypePen import FreeTypePen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .domain import metrics, require
from .storage import safe_path, write_json

ENGINE = (
    f"FreeType {'.'.join(map(str, freetype.version()))}, fontTools FreeTypePen, Pillow; non-zero, unhinted"
)


def glyph_view(font, name, request, frame):
    g = font[name]
    xmin, ymin, xmax, ymax = frame
    w, h = request.width, request.height
    scale = min((w - 80) / max(1, xmax - xmin), (h - 80) / max(1, ymax - ymin))
    tx, ty = 40 - xmin * scale, 40 - ymin * scale
    pen = FreeTypePen(font)
    g.draw(pen)
    layer = pen.image(w, h, transform=Transform(scale, 0, 0, scale, tx, ty))
    image = Image.new("RGB", (w, h), "white")
    image.paste(layer, (0, 0), layer)
    draw = ImageDraw.Draw(image)

    def xy(x, y):
        return tx + x * scale, h - (ty + y * scale)

    if request.guides:
        mask = layer.getchannel("A")
        edge = ImageChops.subtract(
            mask.filter(ImageFilter.MaxFilter(3)), mask.filter(ImageFilter.MinFilter(3))
        )
        image.paste((110, 110, 110), (0, 0), edge)
        draw = ImageDraw.Draw(image)
        for y, label in [
            (0, "baseline"),
            (font.info.ascender, "ascender"),
            (font.info.descender, "descender"),
            (font.info.capHeight, "cap"),
            (font.info.xHeight, "x-height"),
        ]:
            yy = xy(0, y)[1]
            draw.line((0, yy, w, yy), fill=(180, 180, 180))
            draw.text((3, yy + 2), label, fill=(80, 80, 80))
        for x, label in [(0, "origin"), (g.width, "advance")]:
            xx = xy(x, 0)[0]
            draw.line((xx, 0, xx, h), fill=(180, 180, 180))
            draw.text((xx + 2, h - 16), label, fill=(80, 80, 80))
    if request.points:
        for c in g.contours:
            for i, p in enumerate(c.points):
                prev = c.points[i - 1]
                if p.type is None or prev.type is None:
                    draw.line([xy(prev.x, prev.y), xy(p.x, p.y)], fill=(140, 140, 140))
            for p in c.points:
                x, y = xy(p.x, p.y)
                box = (x - 3, y - 3, x + 3, y + 3)
                if p.type is None:
                    draw.ellipse(box, fill="white", outline="black")
                else:
                    draw.rectangle(box, fill="white", outline="black")
        for a in g.anchors:
            x, y = xy(a.x, a.y)
            draw.line((x - 5, y, x + 5, y), fill="black")
            draw.line((x, y - 5, x, y + 5), fill="black")
            draw.text((x + 7, y), a.name, fill="black")
    return image, {
        "metrics": metrics(g, font),
        "frame": frame,
        "scale": scale,
        "origin_pixel": xy(0, 0),
        "component_points": "Inspect base glyph for component controls",
    }


def glyph_frame(fonts, name):
    bounds = []
    for font in fonts:
        require(name in font, "missing_reference", f"Missing glyph {name}")
        b = font[name].getBounds(font)
        bounds.append(
            (
                min(0, b[0] if b else 0),
                min(font.info.descender, b[1] if b else 0),
                max(font[name].width, b[2] if b else 0),
                max(font.info.ascender, b[3] if b else 0),
            )
        )
    return [
        min(b[0] for b in bounds),
        min(b[1] for b in bounds),
        max(b[2] for b in bounds),
        max(b[3] for b in bounds),
    ]


def shape(binary_bytes, text, kern=True):
    face = hb.Face(binary_bytes)
    font = hb.Font(face)
    hb.ot_font_set_funcs(font)
    font.scale = (face.upem, face.upem)
    buf = hb.Buffer()
    buf.flags = hb.BufferFlags.PRESERVE_DEFAULT_IGNORABLES
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, {"kern": kern})
    return [
        {
            "gid": i.codepoint,
            "cluster": i.cluster,
            "x_advance": p.x_advance,
            "y_advance": p.y_advance,
            "x_offset": p.x_offset,
            "y_offset": p.y_offset,
        }
        for i, p in zip(buf.glyph_infos, buf.glyph_positions)
    ]


def text_view(binary_path, request, vertical_frame):
    data = binary_path.read_bytes()
    positions = shape(data, request.text, request.kern)
    top, bottom = vertical_frame
    with TTFont(io.BytesIO(data)) as font:
        upm = font["head"].unitsPerEm
        glyphset = font.getGlyphSet()
        order, cmap = font.getGlyphOrder(), font.getBestCmap()
        missing = sorted({ord(ch) for ch in request.text if ord(ch) not in cmap})
        warnings = [f"Missing U+{u:04X}; no system font substitution" for u in missing]
        rows = []
        for size in request.sizes:
            scale = size / upm
            height = max(48, int((top - bottom) * scale) + 44)
            require(height <= 2048, "limit_exceeded", "Text row exceeds 2048 pixels")
            image = Image.new("RGB", (request.width, height), "black" if request.dark else "white")
            pen = FreeTypePen(glyphset)
            x, y = 0, 0
            for item in positions:
                g = glyphset[order[item["gid"]]]
                g.draw(TransformPen(pen, (1, 0, 0, 1, x + item["x_offset"], y + item["y_offset"])))
                x += item["x_advance"]
                y += item["y_advance"]
            box = pen.bbox if pen.contours else (0, 0, 0, 0)
            if 20 + box[2] * scale > request.width or 20 + box[0] * scale < 0:
                warnings.append(f"Specimen clipped horizontally at {size}px; use shorter text or wider image")
            if 20 + (box[1] - bottom) * scale < 0 or 20 + (box[3] - bottom) * scale > height:
                warnings.append(
                    f"Specimen clipped vertically at {size}px; inspect glyph and vertical metrics"
                )
            layer = pen.image(request.width, height, transform=(scale, 0, 0, scale, 20, 20 - bottom * scale))
            image.paste("white" if request.dark else "black", (0, 0), layer.getchannel("A"))
            ImageDraw.Draw(image).text(
                (4, 4),
                f"{size}px | kern {'on' if request.kern else 'off'}",
                fill="white" if request.dark else "black",
            )
            rows.append(image)
        require(sum(im.height for im in rows) <= 2048, "limit_exceeded", "Text image exceeds 2048 pixels")
        image = Image.new("RGB", (request.width, sum(im.height for im in rows)))
        offset = 0
        for row in rows:
            image.paste(row, (0, offset))
            offset += row.height
    return image, {
        "positions": positions,
        "missing_codepoints": missing,
        "advance_units": [sum(i["x_advance"] for i in positions), sum(i["y_advance"] for i in positions)],
        "warnings": warnings,
        "harfbuzz": hb.version_string(),
    }


def save_render(store, project_id, revision, image, parameters, details):
    root = safe_path(store.root, store.project(project_id) / "artifacts")
    root.mkdir(exist_ok=True)
    identifier = uuid.uuid4().hex
    stage = safe_path(store.root, root / (".stage-" + identifier))
    stage.mkdir()
    output = io.BytesIO()
    image.save(output, format="PNG")
    png = output.getvalue()
    require(len(png) <= 2_000_000, "limit_exceeded", "PNG exceeds 2 MB")
    (stage / "image.png").write_bytes(png)
    data = {
        "artifact_id": identifier,
        "revision": revision,
        "path": f"{project_id}/artifacts/{identifier}/image.png",
        "mime_type": "image/png",
        "width": image.width,
        "height": image.height,
        "bytes": len(png),
        "sha256": hashlib.sha256(png).hexdigest(),
        "engine": ENGINE,
        "parameters": parameters,
        **details,
    }
    write_json(stage / "artifact.json", data)
    os.replace(stage, safe_path(store.root, root / identifier))
    return data, png
