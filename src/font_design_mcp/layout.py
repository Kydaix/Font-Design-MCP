"""Controlled language declarations and Latin mark-to-base export checks."""

from copy import deepcopy
from unicodedata import category

from fontTools.unicodedata import ot_tags_from_script, script, script_extension

from .domain import require


def compiler_font(font):
    """Only the private compiler copy receives generated feature declarations."""
    result = deepcopy(font)
    tags = {"DFLT"}
    for glyph in font:
        for code in glyph.unicodes:
            if script(chr(code)) not in {"Zyyy", "Zinh", "Zzzz"}:
                tags.update(ot_tags_from_script(script(chr(code))))
    result.features.text = "\n".join(f"languagesystem {tag} dflt;" for tag in sorted(tags)) + "\n"
    return result


def _latin_mark_pairs(font):
    marks = {}
    for glyph in font:
        if not any(
            category(chr(code)).startswith("M")
            and (script(chr(code)) in {"Zyyy", "Zinh", "Latn"} or "Latn" in script_extension(chr(code)))
            for code in glyph.unicodes
        ):
            continue
        for anchor in glyph.anchors:
            if anchor.name.startswith("_"):
                marks.setdefault(anchor.name[1:], set()).add(glyph.name)
    pairs = set()
    for glyph in font:
        if not any(script(chr(code)) == "Latn" for code in glyph.unicodes):
            continue
        for anchor in glyph.anchors:
            for mark in marks.get(anchor.name, ()):
                pairs.add((glyph.name, mark))
    return pairs


def validate_latin_marks(binary, source):
    """Check reachable mark-to-base lookups, not merely the presence of GPOS."""
    expected = _latin_mark_pairs(source)
    report = {
        "scope": "Encoded Latin bases and matching encoded combining-mark anchors; not stacked marks.",
        "expected_pairs": len(expected),
        "status": "not_applicable" if not expected else "passed",
    }
    if not expected:
        return report
    require("GPOS" in binary, "build_failed", "Latin mark anchors did not produce GPOS")
    gpos = binary["GPOS"].table
    scripts = {record.ScriptTag: record.Script for record in gpos.ScriptList.ScriptRecord}
    require("latn" in scripts, "build_failed", "Latin mark positioning has no latn script")
    latin = scripts["latn"]
    languages = ([latin.DefaultLangSys] if latin.DefaultLangSys else []) + [
        record.LangSys for record in latin.LangSysRecord
    ]
    require(bool(languages), "build_failed", "Latin mark positioning has no language system")
    for language in languages:
        feature_ids = set(language.FeatureIndex)
        if language.ReqFeatureIndex != 0xFFFF:
            feature_ids.add(language.ReqFeatureIndex)
        lookup_ids = set()
        for feature_id in feature_ids:
            feature = gpos.FeatureList.FeatureRecord[feature_id]
            if feature.FeatureTag == "mark":
                lookup_ids.update(feature.Feature.LookupListIndex)
        covered = set()
        for lookup_id in lookup_ids:
            lookup = gpos.LookupList.Lookup[lookup_id]
            for table in lookup.SubTable:
                kind = lookup.LookupType
                if kind == 9:
                    kind, table = table.ExtensionLookupType, table.ExtSubTable
                if kind != 4:
                    continue
                marks = dict(zip(table.MarkCoverage.glyphs, table.MarkArray.MarkRecord))
                bases = dict(zip(table.BaseCoverage.glyphs, table.BaseArray.BaseRecord))
                for base, mark in expected - covered:
                    if base not in bases or mark not in marks:
                        continue
                    record = marks[mark]
                    anchors = bases[base].BaseAnchor
                    if (
                        record.MarkAnchor is not None
                        and record.Class < len(anchors)
                        and anchors[record.Class] is not None
                    ):
                        covered.add((base, mark))
        missing = expected - covered
        examples = ", ".join(f"{base}/{mark}" for base, mark in sorted(missing)[:8])
        require(
            not missing,
            "build_failed",
            f"Latin mark positioning is unreachable for {len(missing)} anchor pair(s): {examples}",
        )
    return report
