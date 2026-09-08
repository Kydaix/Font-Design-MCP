"""Build a deterministic source-only MCPB with a strict file allowlist."""

import hashlib
import json
import tomllib
import zipfile
from pathlib import Path

root = Path(__file__).parents[1]
manifest = json.loads((root / "mcpb" / "manifest.json").read_text("utf-8"))
version = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))["project"]["version"]
assert manifest["version"] == version
files = {name: root / name for name in ("pyproject.toml", "uv.lock", "README.md", "LICENSE")}
files.update({name: root / "mcpb" / name for name in ("manifest.json", "server.py", "icon.png")})
files.update({p.relative_to(root).as_posix(): p for p in (root / "src" / "font_design_mcp").glob("*.py")})
output = root / "dist" / f"font-design-mcp-{version}.mcpb"
output.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for name, path in sorted(files.items()):
        info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, path.read_bytes())
digest = hashlib.sha256(output.read_bytes()).hexdigest()
print(json.dumps({"file": str(output), "bytes": output.stat().st_size, "sha256": digest}))
