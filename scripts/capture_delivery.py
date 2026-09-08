"""Export unchanged demo PNGs into dist with descriptive names and provenance."""

import argparse
import json
import shutil
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("project_id")
args = parser.parse_args()
root = Path(__file__).parents[1]
project = root / "workspace" / args.project_id
calls = json.loads((project / "demo-calls.json").read_text("utf-8"))
output = root / "dist" / "captures"
output.mkdir(parents=True, exist_ok=True)
manifest = []
for call in calls:
    if call["tool"] == "render_glyph":
        names = {
            "A": ["glyph-edited.png", "glyph-before.png"],
            "O": ["curves-guides.png"],
            "Aacute": ["accent-components.png"],
        }[call["arguments"]["glyph_id"]]
    elif call["tool"] == "render_text":
        names = ["text-edited.png", "text-before.png"]
    else:
        continue
    for filename, image in zip(names, call["result"]["data"]["images"]):
        shutil.copyfile(root / "workspace" / image["path"], output / filename)
        manifest.append({"capture": filename, **image})
(output / "provenance.json").write_text(json.dumps(manifest, indent=2), "utf-8")
print(
    json.dumps([{"capture": entry["capture"], "revision": entry["revision"]} for entry in manifest], indent=2)
)
