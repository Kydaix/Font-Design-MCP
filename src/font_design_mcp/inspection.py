"""Selective, bounded inspection; each collection exposes its own continuation."""

SECTIONS = {
    "metadata": {"capabilities", "variation", "family", "style", "units_per_em", "metrics", "source_path"},
    "design": {"brief", "design_spec", "references"},
    "glyphs": {"glyphs", "total", "next_offset", "neighbors"},
    "spacing": {"kerning", "groups"},
    "compositions": {"composition_links"},
    "history": {"decisions"},
}


def select_inspection(data, request, font):
    selected = getattr(request, "sections", None)
    keep = set().union(*(SECTIONS[s] for s in selected)) if selected is not None else set(data)
    data = {k: v for k, v in data.items() if k in keep}
    offset, limit = getattr(request, "offset", 0), getattr(request, "limit", 50)
    focus = set(getattr(request, "glyph_ids", []))
    if focus:
        neighbors = set(focus)
        for glyph in font:
            bases = {c.baseGlyph for c in glyph.components}
            if glyph.name in focus:
                neighbors.update(bases)
            if bases & focus:
                neighbors.add(glyph.name)
        if "glyphs" in data:
            names = sorted(n for n in focus if n in font)
            data.update(
                glyphs=names[offset : offset + limit],
                total=len(names),
                next_offset=offset + limit if offset + limit < len(names) else None,
            )
            data["neighbors"] = sorted(neighbors - focus)[:100]
        if "kerning" in data:
            groups = {name for name, members in font.groups.items() if set(members) & focus}
            data["kerning"] = [
                r for r in data["kerning"] if r["left"] in focus | groups or r["right"] in focus | groups
            ]
        if "groups" in data:
            data["groups"] = {k: v for k, v in data["groups"].items() if set(v) & focus}
        if "composition_links" in data:
            data["composition_links"] = {
                mid: {
                    g: link for g, link in links.items() if g in focus or {link["base"], link["mark"]} & focus
                }
                for mid, links in data["composition_links"].items()
            }
    pages = {}

    def page(key, rows):
        pages[key] = {
            "total": len(rows),
            "offset": offset,
            "next_offset": offset + limit if offset + limit < len(rows) else None,
        }
        return rows[offset : offset + limit]

    for key in ("kerning", "decisions", "references"):
        if key in data:
            data[key] = page(key, data[key])
    if "groups" in data:
        data["groups"] = dict(page("groups", sorted(data["groups"].items())))
    if "composition_links" in data:
        rows = [
            (mid, glyph, link)
            for mid, links in sorted(data["composition_links"].items())
            for glyph, link in sorted(links.items())
        ]
        data["composition_links"] = {}
        for mid, glyph, link in page("composition_links", rows):
            data["composition_links"].setdefault(mid, {})[glyph] = link
    data["pagination"] = pages
    return data
