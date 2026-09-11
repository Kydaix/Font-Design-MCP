"""Record repeatable host-level binary compatibility evidence; not artistic approval."""

import argparse
import hashlib
import importlib.metadata
import io
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

from font_design_mcp.interpolation import analyze_grid
from font_design_mcp.render import shape


def check(args):
    args.output.mkdir(parents=True, exist_ok=True)
    data = args.font.read_bytes()
    with TTFont(io.BytesIO(data), checkChecksums=2) as font:
        # Materialize every table so checksum and parser failures are not deferred.
        for tag in font.reader.keys():
            font[tag]
        required = {"head", "hhea", "maxp", "OS/2", "hmtx", "cmap", "name", "post", "glyf", "loca"}
        missing = sorted(required - set(font.keys()))
        axes = (
            [{"tag": a.axisTag, "minimum": a.minValue, "maximum": a.maxValue} for a in font["fvar"].axes]
            if "fvar" in font
            else []
        )
        variation = {"axes": axes, "masters": []}
        cmap = font.getBestCmap()
        font.flavor = None
        sfnt = io.BytesIO()
        font.save(sfnt)
        font.flavor = "woff2"
        compressed = io.BytesIO()
        font.save(compressed)
    with TTFont(io.BytesIO(compressed.getvalue())) as unpacked:
        unpacked.flavor = None
        restored = io.BytesIO()
        unpacked.save(restored)
        cmap_equal = unpacked.getBestCmap() == cmap
    texts = [t for t in args.text if all(ord(c) in cmap for c in t)]
    comparisons = []
    locations = [{}] + [{a["tag"]: (a["minimum"] + a["maximum"]) / 2 for a in axes}] if axes else [{}]
    for text in texts:
        for location in locations:
            for kern in (False, True):
                a = shape(sfnt.getvalue(), text, kern, location)
                b = shape(restored.getvalue(), text, kern, location)
                comparisons.append(
                    {
                        "text": text,
                        "location": location,
                        "kern": kern,
                        "same_positions": a == b,
                        "missing_glyph": any(p["gid"] == 0 for p in a),
                    }
                )
    grid = analyze_grid(sfnt.getvalue(), variation)
    report = {
        "font": str(args.font.resolve()),
        "sha256": hashlib.sha256(data).hexdigest(),
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "versions": {
            p: importlib.metadata.version(p) for p in ["fonttools", "uharfbuzz", "freetype-py", "brotli"]
        },
        "missing_required_tables": missing,
        "woff2_cmap_equal": cmap_equal,
        "shaping_roundtrip": comparisons,
        "grid": grid,
        "fontbakery": {"status": "not_requested"},
        "checks_passed": not missing
        and cmap_equal
        and bool(comparisons)
        and all(r["same_positions"] and not r["missing_glyph"] for r in comparisons)
        and not grid["findings"],
        "limitations": [
            "Checks use fontTools/HarfBuzz on this host, not native DirectWrite/CoreText/browser engines.",
            "A finite grid and binary roundtrip do not establish optical or artistic quality.",
        ],
    }
    if args.fontbakery:
        executable = shutil.which("fontbakery") or str(
            Path(sys.executable).parent / ("fontbakery.exe" if sys.platform == "win32" else "fontbakery")
        )
        if not Path(executable).is_file():
            report["fontbakery"] = {
                "status": "unavailable",
                "reason": "Install FontBakery in a separate checking environment or this interpreter environment.",
            }
            report["checks_passed"] = False
        else:
            target = args.output.resolve() / "fontbakery.json"
            with (args.output / "fontbakery.log").open("w", encoding="utf-8") as log:
                try:
                    process = subprocess.run(
                        [executable, "check-universal", "--json", str(target), str(args.font.resolve())],
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        timeout=180,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                    )
                    report["fontbakery"] = {
                        "status": "completed",
                        "exit_code": process.returncode,
                        "report": str(target),
                    }
                    report["checks_passed"] &= process.returncode == 0
                except subprocess.TimeoutExpired:
                    report["fontbakery"] = {"status": "timeout", "seconds": 180}
                    report["checks_passed"] = False
    (args.output / "binary-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "checks_passed": report["checks_passed"],
                "host": report["host"],
                "shaping_cases": len(comparisons),
                "grid_locations": len(grid["samples"]),
                "fontbakery": report["fontbakery"],
                "report": str(args.output / "binary-report.json"),
            }
        )
    )
    return 0 if report["checks_passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("font", type=Path)
    parser.add_argument("--output", type=Path, default=Path("test-output/binary-check"))
    parser.add_argument(
        "--text", action="append", default=["UniSlaw", "KAYAK", "MINIMUM", "minimum", "0123456789"]
    )
    parser.add_argument("--fontbakery", action="store_true")
    sys.exit(check(parser.parse_args()))
