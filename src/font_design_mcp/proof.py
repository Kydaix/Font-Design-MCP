"""Multi-glyph proofs with a single shared scale, including across revisions."""

from types import SimpleNamespace

from PIL import Image, ImageDraw

from .render import glyph_frame, glyph_view


def proof_frame(fonts, names):
    frames = [glyph_frame([font], name) for font in fonts for name in names if name in font]
    if not frames:
        frames = [(0, f.info.descender, f.info.unitsPerEm, f.info.ascender) for f in fonts]
    return [
        min(f[0] for f in frames),
        min(f[1] for f in frames),
        max(f[2] for f in frames),
        max(f[3] for f in frames),
    ]


def proof_view(font, request, frame):
    columns = request.columns
    rows = (len(request.glyph_ids) + columns - 1) // columns
    width, height = request.cell_width, request.cell_height
    image = Image.new("RGB", (columns * width, rows * height), "white")
    draw = ImageDraw.Draw(image)
    options = SimpleNamespace(width=width, height=height - 24, guides=request.guides, points=request.points)
    missing, glyphs = [], []
    for i, name in enumerate(request.glyph_ids):
        x, y = (i % columns) * width, (i // columns) * height
        if name in font:
            tile, details = glyph_view(font, name, options, frame)
            image.paste(tile, (x, y))
            glyphs.append({"glyph_id": name, **details})
            label = name
        else:
            missing.append(name)
            label = f"{name} (MISSING)"
        draw.text((x + 8, y + height - 20), label, fill="black")
        draw.rectangle((x, y, x + width - 1, y + height - 1), outline=(200, 200, 200))
    return image, {
        "frame": frame,
        "glyphs": glyphs,
        "missing_glyphs": missing,
        "warnings": [f"Missing glyph {name}; no substitution" for name in missing],
        "scale": glyphs[0]["scale"] if glyphs else None,
    }
