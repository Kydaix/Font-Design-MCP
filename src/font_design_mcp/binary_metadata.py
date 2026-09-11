"""Complete variable style metadata without changing outlines or design coordinates."""

from fontTools.otlLib.builder import buildStatTable


def complete_variable_metadata(binary, configuration):
    if not configuration:
        return
    weight_names = {
        100: "Thin",
        200: "ExtraLight",
        300: "Light",
        400: "Regular",
        500: "Medium",
        600: "Semibold",
        700: "Bold",
        800: "ExtraBold",
        900: "Black",
    }
    width_names = {
        50: "UltraCondensed",
        62.5: "ExtraCondensed",
        75: "Condensed",
        87.5: "SemiCondensed",
        100: "Normal",
        112.5: "SemiExpanded",
        125: "Expanded",
        150: "ExtraExpanded",
        200: "UltraExpanded",
    }
    axes = []
    for axis in configuration["axes"]:
        values = sorted(
            {master["location"][axis["tag"]] for master in configuration["masters"]} | {axis["default"]}
        )
        labels = weight_names if axis["tag"] == "wght" else width_names if axis["tag"] == "wdth" else {}
        axes.append(
            {
                "tag": axis["tag"],
                "name": axis["name"],
                "values": [
                    {
                        "value": value,
                        "name": labels.get(value, f"{axis['name']} {value:g}"),
                        "flags": 2 if value == axis["default"] else 0,
                    }
                    for value in values
                ],
            }
        )
    buildStatTable(binary, axes, elidedFallbackName=2, macNames=False)
    tags = sorted((a["tag"] for a in configuration["axes"]), key=lambda tag: (tag != "wght", tag))
    binary["fvar"].instances.sort(key=lambda instance: tuple(instance.coordinates[tag] for tag in tags))
