"""Validate registry metadata and, by default, the release bundle checksum."""

import argparse
import hashlib
import json
import tomllib
from pathlib import Path
from urllib.request import urlopen

import jsonschema


def main(argv=None, root=Path(__file__).resolve().parents[1]):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Validate development metadata without matching a local bundle to the published release hash",
    )
    args = parser.parse_args(argv)
    manifest = json.loads((root / "server.json").read_text("utf-8"))
    with urlopen(manifest["$schema"], timeout=20) as response:
        schema = json.load(response)
    jsonschema.validate(manifest, schema)
    version = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))["project"]["version"]
    package = manifest["packages"][0]
    assert manifest["version"] == version == package["version"], "Registry/package version mismatch"
    assert package["registryType"] == "mcpb", "Expected an MCPB registry package"
    assert package["identifier"] == (
        f"{manifest['repository']['url']}/releases/download/v{version}/font-design-mcp-{version}.mcpb"
    ), "Registry download URL must match the package version"
    assert f"mcp-name: {manifest['name']}" in (root / "README.md").read_text("utf-8"), (
        "README registry ownership marker is missing"
    )
    if not args.metadata_only:
        bundle = root / "dist" / f"font-design-mcp-{version}.mcpb"
        digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
        assert digest == package["fileSha256"], (
            f"Release bundle checksum mismatch: built {digest}, registry declares {package['fileSha256']}"
        )
    print("Registry schema, package version, download URL and README ownership marker validated")
    print("Release checksum not checked (metadata-only mode)" if args.metadata_only else "Release checksum validated")


if __name__ == "__main__":
    main()
