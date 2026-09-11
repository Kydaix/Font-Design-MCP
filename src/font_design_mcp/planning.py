"""Evidence plans are suggestions; measurements and reviews must still be performed."""


def evidence_plan(font, spec, regions, structural):
    probes = []
    for region in regions:
        if region["covered"]:
            continue
        glyph = font.get(region["glyph"])
        bounds = glyph.getBounds(font) if glyph else None
        if not bounds:
            continue
        x0, y0, x1, y1 = bounds
        u0, v0, u1, v1 = region["bounds"]
        box = [x0 + u0 * (x1 - x0), y0 + v0 * (y1 - y0), x0 + u1 * (x1 - x0), y0 + v1 * (y1 - y0)]
        probes.append(
            {
                "region_id": region["id"],
                "glyph_id": region["glyph"],
                "font_bounds": box,
                "seed_positions": [
                    [(box[0] + box[2]) / 2, box[1] + fraction * (box[3] - box[1])]
                    for fraction in (0.25, 0.75)
                ],
                "minimum_samples": region["minimum_samples"],
                "target": None,
                "action": "Inspect the region, place a centerline on the actual stroke and declare normal-width bounds from the design intent. At junctions inspect the combined ink and adjoining branches separately.",
            }
        )
    cmap = {cp for glyph in font for cp in glyph.unicodes}
    words = [
        word
        for word in [
            "HAMBURGEFONTS",
            "MINIMUM",
            "KAYAK",
            "AVATAR",
            "WAVY",
            "Hamburgefonts",
            "minimum",
            "kayak",
            "0123456789",
        ]
        if all(ord(c) in cmap for c in word)
    ]
    return {
        "status": "proposed_not_measured_or_reviewed",
        "regions": probes,
        "proof_groups": [structural[i : i + 16] for i in range(0, len(structural), 16)],
        "usage_texts": list(dict.fromkeys([*spec.usage_texts, *words])),
        "usage_settings": {"sizes": [24, 72], "kern": [False, True]},
        "instruction": "Add language-specific words and missing structural glyphs to usage_texts. Proposed words do not become requirements until declared in the design contract.",
    }


def compact_coverage(coverage):
    return {
        **{k: v for k, v in coverage.items() if not isinstance(v, list)},
        "counts": {k: len(v) for k, v in coverage.items() if isinstance(v, list)},
        **{k: v[:12] for k, v in coverage.items() if isinstance(v, list)},
        "truncated": any(len(v) > 12 for v in coverage.values() if isinstance(v, list)),
    }
