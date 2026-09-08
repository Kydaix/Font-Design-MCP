"""Install the actual bundle with UV outside the checkout and exercise its STDIO entry point."""

import asyncio
import json
import os
import subprocess
import tempfile
import tomllib
import zipfile
from pathlib import Path

from mcp import Client, StdioServerParameters

root = Path(__file__).parents[1]
version = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))["project"]["version"]


async def main():
    with tempfile.TemporaryDirectory(prefix="font mcpb é ") as directory:
        bundle, workspace = Path(directory) / "extension", Path(directory) / "workspace"
        bundle.mkdir()
        with zipfile.ZipFile(root / "dist" / f"font-design-mcp-{version}.mcpb") as archive:
            for name in archive.namelist():
                assert (bundle / name).resolve().is_relative_to(bundle.resolve())
                assert not any(p in {".venv", "workspace", "test-output", "tests"} for p in Path(name).parts)
            archive.extractall(bundle)
        manifest = json.loads((bundle / "manifest.json").read_text("utf-8"))
        config = manifest["server"]["mcp_config"]
        args = [
            arg.replace("${__dirname}", str(bundle)).replace("${user_config.workspace}", str(workspace))
            for arg in config["args"]
        ]
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in {"VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "UV_PROJECT_ENVIRONMENT"}
        }
        diagnostic_args = args[: args.index("serve")] + ["doctor", "--build"]
        diagnostic = subprocess.run(
            [config["command"], *diagnostic_args],
            cwd=directory,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert diagnostic.returncode == 0, diagnostic.stdout + diagnostic.stderr
        assert json.loads(diagnostic.stdout)["ok"]
        async with Client(
            StdioServerParameters(command=config["command"], args=args, env=env), mode="2026-07-28"
        ) as client:
            created = await client.call_tool("project_create", {"metadata": {"family": "Bundle smoke"}})
            assert created.structured_content["ok"]
            pid = created.structured_content["project_id"]
            built = await client.call_tool("font_build", {"project_id": pid})
            assert built.structured_content["ok"]
            assert (workspace / built.structured_content["data"]["files"]["ttf"]["path"]).is_file()
            assert not workspace.is_relative_to(bundle)
        print("MCPB: isolated UV install, doctor TTF/WOFF2, modern STDIO and external workspace passed")


asyncio.run(main())
