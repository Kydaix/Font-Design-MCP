"""Exercise the packed npx installer in an isolated profile, without a preinstalled uv/Python."""

import asyncio
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
from pathlib import Path

from mcp import Client, StdioServerParameters

root = Path(__file__).parents[1]
node, npm = shutil.which("node"), shutil.which("npm")
assert node and npm, "Node.js 20+ and npm are required to check the npx installer"


async def main():
    with tempfile.TemporaryDirectory(prefix="font installer é ") as directory:
        home = Path(directory).resolve()
        packed = subprocess.run(
            [npm, "pack", "--json", "--pack-destination", str(home)],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        metadata = json.loads(packed.stdout)[0]
        names = [entry["path"] for entry in metadata["files"]]
        assert {"install.mjs", "pyproject.toml", "src/font_design_mcp/install.py"} <= set(names)
        assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
        help_result = subprocess.run(
            [
                npm,
                "exec",
                "--yes",
                "--package",
                str(home / metadata["filename"]),
                "--",
                "font-design-mcp",
                "--help",
            ],
            env={**os.environ, "npm_config_cache": str(home / "npm-cache")},
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert "--clients" in help_result.stdout and "--dry-run" in help_result.stdout
        with tarfile.open(home / metadata["filename"]) as archive:
            archive.extractall(home, filter="data")
        if os.name == "nt":
            system = Path(os.environ["SystemRoot"])
            path = os.pathsep.join(
                str(system / part) for part in ("System32", "System32/WindowsPowerShell/v1.0")
            )
        else:
            path = "/usr/bin:/bin"
        env = {
            **os.environ,
            "HOME": str(home),
            "USERPROFILE": str(home),
            "PATH": path,
            "LOCALAPPDATA": str(home / "local"),
            "APPDATA": str(home / "roaming"),
            "XDG_DATA_HOME": str(home / "data"),
            "XDG_CONFIG_HOME": str(home / "config"),
            "CODEX_HOME": str(home / ".codex"),
            "CLAUDE_CONFIG_DIR": str(home / ".claude"),
            "UV_TOOL_DIR": str(home / "tools"),
            "UV_TOOL_BIN_DIR": str(home / "bin"),
            "UV_PYTHON_INSTALL_DIR": str(home / "python"),
            "UV_CACHE_DIR": str(home / "cache"),
        }
        if os.name == "nt":
            # Python uppercases Windows environment keys; exercise that inherited form.
            env["PSMODULEPATH"] = str(home / "unusable-powershell-modules")
        # All generated runtime/config paths stay inside this temporary profile.
        command = [
            node,
            str(home / "package" / "install.mjs"),
            "--clients",
            "codex",
            "cursor",
            "claude-code",
            "--workspace",
            str(home / "fonts"),
        ]
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=360)
        assert result.returncode == 0, result.stdout + result.stderr
        config = tomllib.loads((home / ".codex" / "config.toml").read_text("utf-8"))
        server = config["mcp_servers"]["font-design"]
        assert Path(server["command"]).is_relative_to(home / "tools")
        assert not Path(server["command"]).is_relative_to(home / "package")
        async with Client(StdioServerParameters(command=server["command"], args=server["args"])) as client:
            assert len((await client.list_tools()).tools) == 15
        assert not (root / "docs").exists()
        print(
            "npx package: clean-profile bootstrap, persistent Python, three client configs and live MCP passed"
        )


asyncio.run(main())
