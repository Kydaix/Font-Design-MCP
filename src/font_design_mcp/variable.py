"""Compatibility checks and private Designspace generation for continuous axes."""

from fontTools.designspaceLib import AxisDescriptor, DesignSpaceDocument, InstanceDescriptor, SourceDescriptor

from .domain import require
from .layout import compiler_font
from .models import Variation


def validate_masters(variation, fonts):
    default = fonts["default"]
    for master in variation.masters:
        font = fonts[master.id]
        prefix = f"Master {master.id}"
        require(
            set(font.keys()) == set(default.keys()), "incompatible_masters", f"{prefix}: glyph sets differ"
        )
        require(
            font.info.unitsPerEm == default.info.unitsPerEm,
            "incompatible_masters",
            f"{prefix}: units per em differ",
        )
        require(font.groups == default.groups, "incompatible_masters", f"{prefix}: kerning groups differ")
        for name in default.keys():
            left, right = default[name], font[name]
            require(
                set(left.unicodes) == set(right.unicodes),
                "incompatible_masters",
                f"{prefix}, glyph {name}: Unicode mappings differ",
            )
            require(
                [[p.type for p in c.points] for c in left.contours]
                == [[p.type for p in c.points] for c in right.contours]
                and [c.baseGlyph for c in left.components] == [c.baseGlyph for c in right.components]
                and [a.name for a in left.anchors] == [a.name for a in right.anchors],
                "incompatible_masters",
                f"{prefix}, glyph {name}: contour/point types, component bases or anchors differ",
            )


def write_designspace(stage, configuration, fonts):
    variation = Variation.model_validate(configuration)
    validate_masters(variation, fonts)
    doc = DesignSpaceDocument()
    for axis in variation.axes:
        doc.addAxis(AxisDescriptor(**axis.model_dump()))
    for master in variation.masters:
        font = fonts[master.id]
        path = stage / f"master-{master.id}.ufo"
        compiler_font(font).save(path, formatVersion=3, validate=True)
        location = {axis.name: master.location[axis.tag] for axis in variation.axes}
        doc.addSource(
            SourceDescriptor(
                path=str(path),
                name=master.id,
                familyName=font.info.familyName,
                styleName=master.name,
                location=location,
                copyInfo=master.id == "default",
                copyLib=master.id == "default",
                copyFeatures=master.id == "default",
            )
        )
        doc.addInstance(
            InstanceDescriptor(
                name=master.id,
                familyName=font.info.familyName,
                styleName=master.name,
                location=location,
            )
        )
    path = stage / "input.designspace"
    doc.write(path)
    return path


def validate_variable_binary(binary, configuration):
    if configuration is None:
        return
    require({"fvar", "gvar"}.issubset(binary.keys()), "build_failed", "Missing variable OpenType tables")
    actual = [(a.axisTag, a.minValue, a.defaultValue, a.maxValue) for a in binary["fvar"].axes]
    expected = [(a["tag"], a["minimum"], a["default"], a["maximum"]) for a in configuration["axes"]]
    require(
        len(actual) == len(expected)
        and all(
            a[0] == e[0] and all(abs(x - y) <= 1 / 65536 for x, y in zip(a[1:], e[1:]))
            for a, e in zip(actual, expected)
        ),
        "build_failed",
        "Compiled variation axes differ from source",
    )
