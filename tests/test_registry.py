"""Development metadata must remain valid; release bundles must match their declared hash."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_registry", ROOT / "scripts" / "check_registry.py")
registry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(registry)


@pytest.fixture
def registry_project(tmp_path, monkeypatch):
    manifest = json.loads((ROOT / "server.json").read_text("utf-8"))
    bundle = b"synthetic release bundle"
    manifest["packages"][0]["fileSha256"] = hashlib.sha256(bundle).hexdigest()
    (tmp_path / "server.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "pyproject.toml").write_bytes((ROOT / "pyproject.toml").read_bytes())
    (tmp_path / "README.md").write_bytes((ROOT / "README.md").read_bytes())
    (tmp_path / "dist").mkdir()
    path = tmp_path / "dist" / f"font-design-mcp-{manifest['version']}.mcpb"
    path.write_bytes(bundle)
    # Keep these tests offline; the real versioned schema is validated by the CI script.
    monkeypatch.setattr(registry, "urlopen", lambda *a, **kw: io.StringIO('{"required": ["name"]}'))
    return tmp_path, path


def test_release_checksum_is_required_by_default(registry_project):
    root, bundle = registry_project
    registry.main([], root)
    bundle.write_bytes(b"changed development build")
    with pytest.raises(AssertionError, match="Release bundle checksum mismatch"):
        registry.main([], root)
    registry.main(["--metadata-only"], root)
    bundle.unlink()
    registry.main(["--metadata-only"], root)
    with pytest.raises(FileNotFoundError):
        registry.main([], root)


@pytest.mark.parametrize("args", [[], ["--metadata-only"]])
@pytest.mark.parametrize("invalid", ["schema", "version", "package_version", "url", "ownership"])
def test_metadata_checks_apply_in_both_modes(registry_project, args, invalid):
    root, _ = registry_project
    path = root / "server.json"
    manifest = json.loads(path.read_text("utf-8"))
    if invalid == "schema":
        del manifest["name"]
    elif invalid == "version":
        manifest["version"] = "999.0.0"
    elif invalid == "package_version":
        manifest["packages"][0]["version"] = "999.0.0"
    elif invalid == "url":
        manifest["packages"][0]["identifier"] = "https://example.invalid/wrong-release.mcpb"
    else:
        (root / "README.md").write_text("No ownership marker", encoding="utf-8")
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(jsonschema.ValidationError if invalid == "schema" else AssertionError):
        registry.main(args, root)
