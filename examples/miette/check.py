"""Check the shipped font binaries, not just the drawing recipe. Run with uv run."""

import argparse
import json
from pathlib import Path

import uharfbuzz as hb
from drawings import LETTERS
from fontTools.pens.freetypePen import FreeTypePen
from fontTools.ttLib import TTFont


def check(folder=Path(__file__).parent):
    face = hb.Face((folder / "Miette-Regular.ttf").read_bytes())
    shaper = hb.Font(face)
    shaper.scale = (1000, 1000)
    hb.ot_font_set_funcs(shaper)

    def shape(text, kern=True):
        buffer = hb.Buffer()
        buffer.add_str(text)
        buffer.guess_segment_properties()
        hb.shape(shaper, buffer, {"kern": kern})
        assert all(info.codepoint != 0 for info in buffer.glyph_infos), text
        return sum(position.x_advance for position in buffer.glyph_positions)

    with TTFont(folder / "Miette-Regular.ttf") as font, TTFont(folder / "Miette-Regular.woff2") as web:
        cmap = font.getBestCmap()
        assert web.getBestCmap() == cmap
        required = LETTERS + ".,:;!?…-–—'‘’\"“”()«» \u00a0\u202f"
        assert set(map(ord, required)) == set(cmap)
        assert not set(range(ord("0"), ord("9") + 1)).intersection(cmap)
        assert font["head"].unitsPerEm == 1000 and font["OS/2"].usWeightClass == 400
        assert font["name"].getDebugName(1) == "Miette" and "fvar" not in font
        assert font["head"].yMax <= font["OS/2"].sTypoAscender
        assert font["head"].yMin >= font["OS/2"].sTypoDescender
        assert "GPOS" in font and font["OS/2"].fsType == 0
        for pair, expected in {"AV": 56, "ÀV": 56, "To": 60, "Tô": 60, "Yo": 64, "Yô": 64, "Tœ": 60}.items():
            assert shape(pair, False) - shape(pair) == expected, pair
        assert shape("rn") - shape("m") >= 50
        shape(LETTERS)
        shape("À l’heure où la lumière s’adoucit, le cœur se réjouit. Noël, île, forêt, français !")
        glyph_set = font.getGlyphSet()
        for name, x, y in [("o", 286, 260), ("b", 290, 260), ("B", 290, 510),
                           ("B", 300, 200), ("a", 270, 175), ("e", 280, 375)]:
            pen = FreeTypePen(glyph_set)
            glyph_set[name].draw(pen)
            mask = pen.image(width=1000, height=960).getchannel("A")
            assert mask.getpixel((x, 960 - y)) == 0, f"Closed counter: {name}"
            assert mask.getbbox() is not None
        for char in "àâéèêëîïôùûüÿçÀÂÉÈÊËÎÏÔÙÛÜŸÇ":
            assert font["glyf"][cmap[ord(char)]].isComposite(), char
        assert len(font["glyf"]["icircumflex"].components) == 2
        result = {"letters": len(LETTERS), "encoded_characters": len(cmap),
                  "glyphs": len(font.getGlyphOrder()), "units_per_em": face.upem,
                  "bounds_y": [font["head"].yMin, font["head"].yMax],
                  "coverage": "passed", "kerning_and_accent_inheritance": "passed",
                  "compiled_counters": "passed", "ttf_woff2_agreement": "passed"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", nargs="?", type=Path, default=Path(__file__).parent)
    check(parser.parse_args().folder)
