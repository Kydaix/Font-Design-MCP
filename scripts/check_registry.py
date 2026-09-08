"""Validate registry metadata against the official versioned schema before publication."""

import hashlib
import json
import tomllib
from pathlib import Path
from urllib.request import urlopen

import jsonschema

root = Path(__file__).parents[1]
manifest = json.loads((root / "server.json").read_text("utf-8"))
with urlopen(manifest["$schema"], timeout=20) as response:
    schema = json.load(response)
jsonschema.validate(manifest, schema)
version = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))["project"]["version"]
assert manifest["version"] == version == manifest["packages"][0]["version"]
package = manifest["packages"][0]
assert package["registryType"] == "mcpb"
bundle = root / "dist" / f"font-design-mcp-{version}.mcpb"
assert hashlib.sha256(bundle.read_bytes()).hexdigest() == package["fileSha256"]
assert f"mcp-name: {manifest['name']}" in (root / "README.md").read_text("utf-8")
print("Registry schema, package version and README ownership marker validated")
