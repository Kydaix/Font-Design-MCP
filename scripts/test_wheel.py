"""Build artifacts first, then install and test the wheel outside the checkout."""

import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

root = Path(__file__).parents[1]
version = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))["project"]["version"]
wheel = root / "dist" / f"font_design_mcp-{version}-py3-none-any.whl"
(root / "test-output").mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix="font wheel é ") as folder:
    env = Path(folder) / "environment"
    subprocess.run(["uv", "venv", "--python", sys.executable, str(env)], check=True)
    python = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(["uv", "pip", "install", "--python", str(python), str(wheel)], check=True, cwd=folder)
    subprocess.run(
        [str(python), str(root / "scripts" / "wheel_smoke.py")],
        check=True,
        cwd=folder,
        env={k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}},
    )
