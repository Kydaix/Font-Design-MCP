"""Original Miette drawings, in font units with Y up; no third-party font input.

The SVG strings describe pen centre lines, not a font import. FreeType expands
them into editable Bezier outlines; booleanOperations removes overlaps. Both
libraries already belong to the project's locked environment.
"""

import unicodedata

from fontTools.agl import UV2AGL

from font_design_mcp.drawing import path_contours

FAMILY = "Miette"
METRICS = {"units_per_em": 1000, "ascender": 960, "descender": -260,
           "cap_height": 710, "x_height": 520}
STROKE = 88
FRENCH = "àâéèêëîïôùûüÿç"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz" + FRENCH + FRENCH.upper() + "æœÆŒ"


def drawing(name, advance, paths, width=STROKE):
    return {"advance": advance,
            "contours": [c.model_dump() for c in path_contours(paths, name, width)]}


def oval(left, bottom, right, top):
    """Slightly upright, soft oval; its extrema include optical overshoot."""
    cx, cy = (left + right) / 2, (bottom + top) / 2
    rx, ry = (right - left) / 2, (top - bottom) / 2
    k = 0.56
    return (f"M {cx} {bottom} C {cx + k*rx} {bottom} {right} {cy-k*ry} {right} {cy} "
            f"C {right} {cy+k*ry} {cx+k*rx} {top} {cx} {top} "
            f"C {cx-k*rx} {top} {left} {cy+k*ry} {left} {cy} "
            f"C {left} {cy-k*ry} {cx-k*rx} {bottom} {cx} {bottom} Z")


# Each entry is advance width plus deliberately drawn Bezier centre lines.
# 44-unit stroke radius: straight stems end at y=44 / 666, rounds at y=34 / 676.
DESIGNS = {
    "A": (660, ["M 90 44 L 330 666 L 570 44", "M 172 255 L 488 255"]),
    "B": (638, ["M 110 44 L 110 666 L 292 666 C 435 666 494 612 494 522 C 494 430 425 367 302 367 L 110 367", "M 302 367 C 474 367 535 300 535 205 C 535 97 455 44 301 44 L 110 44"]),
    "C": (670, ["M 573 589 C 524 647 452 676 347 676 C 196 676 102 552 102 356 C 102 159 186 34 340 34 C 447 34 523 59 578 125"]),
    "D": (698, ["M 110 44 L 110 666 L 292 666 C 492 666 588 557 588 355 C 588 148 492 44 292 44 Z"]),
    "E": (575, ["M 112 666 L 112 44 L 479 44", "M 112 666 L 479 666", "M 112 368 L 438 368"]),
    "F": (548, ["M 112 44 L 112 666 L 465 666", "M 112 368 L 427 368"]),
    "G": (715, ["M 598 581 C 543 646 463 676 354 676 C 200 676 102 550 102 355 C 102 158 188 34 344 34 C 452 34 541 53 614 106 L 614 328 L 410 328"]),
    "H": (680, ["M 112 44 L 112 666", "M 568 44 L 568 666", "M 112 360 L 568 360"]),
    "I": (366, ["M 183 44 L 183 666", "M 78 666 L 288 666", "M 78 44 L 288 44"]),
    "J": (524, ["M 288 666 L 420 666 L 420 204 C 420 97 350 34 285 34 C 187 34 136 59 93 134"]),
    "K": (638, ["M 110 44 L 110 666", "M 538 666 L 110 281", "M 282 435 L 561 44"]),
    "L": (550, ["M 112 666 L 112 44 L 457 44"]),
    "N": (710, ["M 110 44 L 110 666 L 600 44 L 600 666"]),
    "O": (710, [oval(102, 34, 608, 676)]),
    "P": (620, ["M 110 44 L 110 666 L 285 666 C 445 666 516 589 516 483 C 516 374 436 315 282 315 L 110 315"]),
    "Q": (710, [oval(102, 34, 608, 676), "M 426 159 L 635 -50"]),
    "R": (654, ["M 110 44 L 110 666 L 287 666 C 445 666 516 590 516 491 C 516 390 437 329 284 329 L 110 329", "M 314 329 L 557 44"]),
    "S": (622, ["M 526 589 C 481 648 406 676 307 676 C 186 676 110 604 110 508 C 110 408 204 379 303 351 C 418 319 523 286 523 173 C 523 86 427 34 316 34 C 215 34 127 66 81 119"]),
    "T": (618, ["M 70 666 L 548 666", "M 309 666 L 309 44"]),
    "U": (690, ["M 110 666 L 110 260 C 110 109 194 34 345 34 C 496 34 580 109 580 260 L 580 666"]),
    "V": (660, ["M 88 666 L 330 44 L 572 666"]),
    "W": (934, ["M 82 666 L 260 44 L 467 492 L 674 44 L 852 666"]),
    "X": (650, ["M 92 666 L 558 44", "M 558 666 L 92 44"]),
    "Y": (638, ["M 86 666 L 319 344 L 552 666", "M 319 344 L 319 44"]),
    "Z": (614, ["M 84 666 L 530 666 L 84 44 L 530 44"]),
    "M": (810, ["M 110 44 L 110 666 L 405 235 L 700 666 L 700 44"]),
    "b": (580, ["M 104 44 L 104 706", oval(104, 34, 480, 486)]),
    "c": (512, ["M 428 430 C 387 467 335 486 271 486 C 166 486 98 400 98 260 C 98 125 169 34 271 34 C 331 34 392 56 428 90"]),
    "d": (580, [oval(98, 34, 474, 486), "M 474 44 L 474 706"]),
    "f": (372, ["M 140 44 L 140 549 C 140 676 204 728 307 696", "M 65 462 L 298 462"]),
    "g": (578, [oval(98, 34, 474, 486), "M 474 476 L 474 -30 C 474 -134 405 -182 286 -182 C 217 -182 158 -163 111 -131"]),
    "h": (566, ["M 104 44 L 104 706", "M 104 333 C 104 424 177 486 273 486 C 376 486 461 426 461 317 L 461 44"]),
    "j": (274, ["M 174 476 L 174 -56 C 174 -145 140 -183 61 -181", "M 174 656 L 174 658"]),
    "k": (514, ["M 104 44 L 104 706", "M 431 476 L 104 198", "M 252 323 L 454 44"]),
    "m": (852, ["M 104 44 L 104 476", "M 104 330 C 104 425 169 486 254 486 C 339 486 418 425 418 322 L 418 44", "M 418 328 C 418 426 485 486 574 486 C 673 486 748 424 748 317 L 748 44"]),
    "n": (566, ["M 104 44 L 104 476", "M 104 333 C 104 424 177 486 273 486 C 376 486 461 426 461 317 L 461 44"]),
    "o": (572, [oval(98, 34, 474, 486)]),
    "p": (580, [oval(104, 34, 480, 486), "M 104 476 L 104 -176"]),
    "q": (580, [oval(98, 34, 474, 486), "M 474 476 L 474 -176"]),
    "r": (388, ["M 104 44 L 104 476", "M 104 325 C 104 424 176 486 260 486 C 287 486 308 481 328 471"]),
    "a": (548, [
        "M 125 438 C 187 486 274 498 346 471 C 407 448 439 400 439 329 L 439 44",
        "M 439 289 C 355 318 216 317 152 278 C 72 230 78 99 158 54 C 252 0 393 47 439 146",
    ]),
    "e": (554, [
        "M 109 271 L 454 271 C 454 394 385 486 280 486 C 165 486 99 399 99 264 C 99 126 164 34 287 34 C 354 34 402 57 442 92",
    ]),
    "s": (480, ["M 399 428 C 355 475 287 497 215 481 C 136 466 96 422 106 369 C 117 310 183 292 251 272 C 322 251 389 228 387 156 C 385 82 316 33 231 34 C 161 35 103 60 70 99"]),
    "l": (294, ["M 120 706 L 120 135 C 120 62 150 34 218 44"]),
    "i": (256, ["M 128 44 L 128 476", "M 128 656 L 128 658"]),
    "t": (378, ["M 157 615 L 157 155 C 157 63 205 20 303 54", "M 67 455 L 303 455"]),
    "u": (566, ["M 104 476 L 104 213 C 104 98 182 34 281 34 C 382 34 461 116 461 227", "M 461 476 L 461 44"]),
    "v": (526, ["M 80 476 L 263 44 L 446 476"]),
    "w": (788, ["M 77 476 L 224 44 L 394 368 L 560 44 L 711 476"]),
    "x": (524, ["M 84 476 L 440 44", "M 440 476 L 84 44"]),
    "y": (536, ["M 80 476 L 301 72", "M 456 476 L 279 -28 C 236 -139 174 -188 95 -177"]),
    "z": (496, ["M 80 476 L 416 476 L 80 44 L 416 44"]),
    "æ": (888, [
        "M 125 438 C 187 486 274 498 346 471 C 407 448 439 400 439 329 L 439 44",
        "M 439 289 C 355 318 216 317 152 278 C 72 230 78 99 158 54 C 252 0 393 47 439 146",
        "M 449 271 L 794 271 C 794 394 725 486 620 486 C 505 486 439 399 439 264 C 439 126 504 34 627 34 C 694 34 742 57 782 92",
    ]),
    "œ": (910, [oval(98, 34, 450, 486), "M 460 271 L 814 271 C 814 394 745 486 640 486 C 525 486 450 399 450 264 C 450 126 515 34 638 34 C 705 34 753 57 793 92"]),
    "Æ": (944, ["M 90 44 L 326 666 L 844 666", "M 454 666 L 454 44 L 844 44", "M 454 368 L 798 368", "M 171 255 L 454 255"]),
    "Œ": (1040, ["M 580 666 L 347 666 C 196 666 102 552 102 356 C 102 159 186 44 340 44 L 580 44 Z", "M 580 666 L 950 666", "M 580 368 L 908 368", "M 580 44 L 950 44"]),
}


def glyphs():
    result = {}
    for char, (advance, paths) in DESIGNS.items():
        name = UV2AGL.get(ord(char), f"uni{ord(char):04X}")
        data = drawing(name, advance, paths)
        data["unicodes"] = [ord(char)]
        data["anchors"] = [{"id": f"{name}_top", "name": "top", "x": advance / 2,
                            "y": 710 if char.isupper() else 520}]
        result[name] = data
    result["i.base"] = drawing("i_base", 256, ["M 128 44 L 128 476"])
    marks = {
        "acute": ["M -45 0 L 60 115"],
        "grave": ["M -60 115 L 45 0"],
        "circumflex": ["M -105 0 L 0 85 L 105 0"],
        "dieresis": ["M -75 52 L -75 54", "M 75 52 L 75 54"],
        "cedilla": ["M 8 -17 L -12 -64 C 60 -57 85 -89 62 -127 C 45 -151 8 -155 -23 -138"],
    }
    for name, paths in marks.items():
        result[name] = drawing(name, 300, paths, width=70 if name == "dieresis" else 64)
    accent_names = {"\u0300": "grave", "\u0301": "acute", "\u0302": "circumflex",
                    "\u0308": "dieresis", "\u0327": "cedilla"}
    for char in FRENCH + FRENCH.upper():
        base_char, mark = unicodedata.normalize("NFD", char)
        base = "i.base" if base_char == "i" else base_char
        name = UV2AGL[ord(char)]
        advance = result[base]["advance"]
        accent = accent_names[mark]
        x = advance / 2 + (12 if base_char == "a" else 0)
        y = 0 if accent == "cedilla" else (790 if base_char.isupper() else 590)
        scale_x = 0.78 if base_char == "i" and accent == "circumflex" else 1
        result[name] = {"advance": advance, "unicodes": [ord(char)], "components": [
            {"id": f"{name}_base", "base": base},
            {"id": f"{name}_accent", "base": accent, "transform": [scale_x, 0, 0, 1, x, y]},
        ]}
    punctuation = {
        ".": (230, ["M 115 46 L 115 48"]),
        ",": (230, ["M 125 59 C 132 8 119 -26 88 -57"]),
        ":": (250, ["M 125 96 L 125 98", "M 125 390 L 125 392"]),
        ";": (250, ["M 135 69 C 142 18 129 -16 98 -47", "M 135 390 L 135 392"]),
        "!": (254, ["M 127 666 L 127 233", "M 127 46 L 127 48"]),
        "?": (468, ["M 76 551 C 96 637 169 680 240 676 C 331 674 384 614 384 540 C 384 478 344 441 282 402 C 230 369 216 338 216 269", "M 216 46 L 216 48"]),
        "-": (355, ["M 73 260 L 282 260"]),
        "–": (590, ["M 73 260 L 517 260"]),
        "—": (890, ["M 73 260 L 817 260"]),
        "'": (206, ["M 116 682 L 91 559"]),
        "’": (220, ["M 110 689 C 147 616 134 566 79 536"]),
        "‘": (220, ["M 140 689 C 85 659 72 609 109 536"]),
        '"': (352, ["M 111 682 L 86 559", "M 266 682 L 241 559"]),
        "“": (386, ["M 140 689 C 85 659 72 609 109 536", "M 306 689 C 251 659 238 609 275 536"]),
        "”": (386, ["M 110 689 C 147 616 134 566 79 536", "M 276 689 C 313 616 300 566 245 536"]),
        "(": (324, ["M 238 724 C 126 625 86 455 86 309 C 86 162 126 -8 238 -106"]),
        ")": (324, ["M 86 724 C 198 625 238 455 238 309 C 238 162 198 -8 86 -106"]),
        "«": (478, ["M 207 390 L 80 280 L 207 170", "M 391 390 L 264 280 L 391 170"]),
        "»": (478, ["M 87 390 L 214 280 L 87 170", "M 271 390 L 398 280 L 271 170"]),
        "…": (690, ["M 115 46 L 115 48", "M 345 46 L 345 48", "M 575 46 L 575 48"]),
    }
    for char, (advance, paths) in punctuation.items():
        name = UV2AGL[ord(char)]
        result[name] = drawing(name, advance, paths, width=76 if char not in ".:;!…" else 88)
        result[name]["unicodes"] = [ord(char)]
    for name, cp, advance in [("space", 32, 250), ("nbspace", 160, 250), ("narrownbspace", 8239, 180)]:
        result[name] = {"advance": advance, "unicodes": [cp]}
    return result


def spacing_operations():
    """Optical pairs; precomposed accents inherit their base letter's groups."""
    pairs = [
        ("A", "V", -56), ("A", "W", -36), ("A", "Y", -54), ("A", "T", -28),
        ("A", "O", -14), ("A", "C", -14), ("A", "G", -14), ("A", "U", -10),
        ("V", "A", -58), ("V", "a", -40), ("V", "e", -44), ("V", "o", -44),
        ("V", "u", -20), ("V", ".", -70),
        ("W", "A", -36), ("W", "a", -24), ("W", "e", -28), ("W", "o", -28),
        ("Y", "A", -64), ("Y", "a", -56), ("Y", "e", -64), ("Y", "o", -64),
        ("Y", "u", -38), ("Y", "i", -12), ("Y", ".", -66),
        ("T", "A", -28), ("T", "a", -50), ("T", "c", -58), ("T", "e", -60),
        ("T", "o", -60), ("T", "r", -32), ("T", "s", -44), ("T", "u", -36),
        ("T", "w", -30), ("T", "y", -28), ("T", ".", -50),
        ("F", "A", -26), ("F", "a", -24), ("F", "e", -22), ("F", "o", -22), ("F", ".", -56),
        ("P", "A", -42), ("P", ".", -66),
        ("L", "T", -36), ("L", "V", -46), ("L", "W", -32), ("L", "Y", -50),
        ("r", "a", -8), ("r", "e", -8), ("r", "o", -8), ("r", ".", -26),
        ("v", "a", -8), ("v", "o", -12), ("v", ".", -34),
        ("w", "o", -6), ("w", ".", -20), ("y", ".", -34),
    ]

    def group(side, char):
        return f"public.kern{side}.{UV2AGL[ord(char)]}"

    operations = []
    for side in (1, 2):
        for char in sorted({p[side - 1] for p in pairs}):
            names = [UV2AGL[ord(c)] for c in LETTERS if unicodedata.normalize("NFD", c)[0] == char]
            if char == ".":
                names = ["period", "comma", "ellipsis"]
            if side == 2 and char in "aAoO":
                names.append({"a": "ae", "A": "AE", "o": "oe", "O": "OE"}[char])
            operations.append({"op": "kern_group", "name": group(side, char), "glyphs": names})
    operations.extend({"op": "kern_pair", "left": group(1, left), "right": group(2, right), "value": value}
                      for left, right, value in pairs)
    return operations


if __name__ == "__main__":
    data = glyphs()
    assert len(data["o"]["contours"]) == 2
    assert len(data["H"]["contours"]) == 1
    assert all(len(c["points"]) <= 2048 for g in data.values() for c in g.get("contours", []))
    assert set(map(ord, LETTERS)).issubset(cp for g in data.values() for cp in g.get("unicodes", []))
    assert all(g in data for op in spacing_operations() if op["op"] == "kern_group" for g in op["glyphs"])
    print(f"{len(data)} drawings; closed outlines, counter and union checks passed")
