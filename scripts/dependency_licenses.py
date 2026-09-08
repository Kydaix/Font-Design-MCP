"""Record licenses from installed wheel metadata, without scanning fonts or user files."""

from importlib.metadata import distributions
from pathlib import Path

root = Path(__file__).parents[1]
lines = [
    "# Dependency license inventory",
    "",
    "Generated from the locked installed distributions. "
    "This inventory does not impose any license on user-created fonts.",
    "",
    "Bundled native FreeType is used under the FreeType License (FTL); "
    "portions of this software are copyright © The FreeType Project (https://freetype.org). "
    "HarfBuzz uses its upstream permissive Old MIT license. Pillow wheels include native libraries; "
    "their notices ship in the wheel's license files.",
    "",
    "| Distribution | Version | Declared license |",
    "|---|---|---|",
]
for dist in sorted(distributions(), key=lambda d: d.metadata["Name"].lower()):
    name = dist.metadata["Name"]
    if name == "font-design-mcp":
        continue
    license_name = dist.metadata.get("License-Expression") or dist.metadata.get("License")
    if not license_name or len(license_name) > 160:
        classifiers = [
            c.split(" :: ")[-1] for c in dist.metadata.get_all("Classifier", []) if c.startswith("License ::")
        ]
        license_name = "; ".join(classifiers) or "See upstream/wheel LICENSE"
    license_name = license_name.replace("\n", " ").replace("|", "/")
    lines.append(f"| {name} | {dist.version} | {license_name} |")
lines += [
    "",
    "The source repository declares dependencies, but does not redistribute their binaries. "
    "For redistribution, retain the full LICENSE/NOTICE files from each wheel, including native notices. "
    "The locked versions and hashes are in uv.lock and requirements.lock.",
    "",
]
(root / "dist").mkdir(exist_ok=True)
(root / "dist" / "DEPENDENCIES.md").write_text("\n".join(lines), "utf-8")
