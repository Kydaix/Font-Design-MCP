"""Run with the wheel's isolated interpreter to verify installation and public STDIO example."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import font_design_mcp

root = Path(__file__).parents[1]
installed = Path(font_design_mcp.__file__).parent
assert not installed.resolve().is_relative_to(root / "src"), installed
assert not Path.cwd().resolve().is_relative_to(root), "Run this smoke test outside the repository"
for source in (root / "src" / "font_design_mcp").glob("*.py"):
    assert (
        hashlib.sha256(source.read_bytes()).digest()
        == hashlib.sha256((installed / source.name).read_bytes()).digest()
    ), source.name
entry = Path(sys.executable).parent / ("font-design-mcp.exe" if os.name == "nt" else "font-design-mcp")
doctor = subprocess.run([str(entry), "doctor", "--build"], capture_output=True, text=True, check=True, timeout=120)
assert json.loads(doctor.stdout)["png"] == "ok"
demo = subprocess.run(
    [
        sys.executable,
        str(root / "examples" / "demo.py"),
        "--workspace",
        str(Path.cwd() / "workspace é"),
    ],
    capture_output=True,
    text=True,
    check=True,
    timeout=120,
)
report = json.loads(demo.stdout)
assert report["validation"]["valid"]
assert not demo.stderr.strip(), demo.stderr
result = {
    "status": "passed",
    "python": sys.executable,
    "package": font_design_mcp.__file__,
    "entry_point": str(entry),
    "project_id": report["project_id"],
    "build": report["build"],
}
(root / "test-output" / "wheel-smoke-report.json").write_text(json.dumps(result, indent=2), "utf-8")
print(json.dumps(result, indent=2))
