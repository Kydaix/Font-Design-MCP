"""Check that built archives contain source only, never environments or private workspaces."""

import tarfile
import zipfile
from pathlib import Path

root = Path(__file__).parents[1]
with tarfile.open(root / "dist" / "font_design_mcp-0.1.0.tar.gz") as archive:
    names = archive.getnames()
    assert any(name.endswith("README.md") for name in names)
    assert any(name.endswith("tests/test_acceptance.py") for name in names)
    assert not any(
        part in (".venv", ".uv-cache", "workspace", "test-output", ".pytest-tmp")
        for name in names
        for part in Path(name).parts
    )
with zipfile.ZipFile(root / "dist" / "font_design_mcp-0.1.0-py3-none-any.whl") as archive:
    names = archive.namelist()
    assert "font_design_mcp/server.py" in names
    assert not any(name.startswith(("tests/", "examples/", "scripts/")) for name in names)
print("Wheel and sdist contents verified; no virtualenv/cache/workspace/test outputs included")
