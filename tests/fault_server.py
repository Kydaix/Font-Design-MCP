"""Test-only process fault injection. Never installed and never exposed as an MCP tool."""

import os
import sys
from pathlib import Path

import anyio
from ufoLib2 import Font

from font_design_mcp import build
from font_design_mcp.server import serve

root, fault = sys.argv[1:]
if fault == "interrupt":
    original = Font.save

    def interrupted(self, path=None, *args, **kwargs):
        if ".stage-" in str(path):
            Path(path).mkdir()
            (Path(path) / "partial").write_bytes(b"interrupted UFO write")
            os._exit(91)
        return original(self, path, *args, **kwargs)

    Font.save = interrupted
elif fault == "compiler":
    original_compiler = build.run_compiler

    def failed(command, cwd, timeout=60, epoch=None):
        command[command.index("-u") + 1] = str(cwd / "deliberately-missing.ufo")
        return original_compiler(command, cwd, timeout, epoch)

    build.run_compiler = failed
elif fault == "slowcompiler":
    original_compiler = build.run_compiler

    def slow(command, cwd, timeout=60, epoch=None):
        script = "import os,time; from pathlib import Path; Path('child.pid').write_text(str(os.getpid())); time.sleep(60)"
        return original_compiler([sys.executable, "-c", script], cwd, timeout, epoch)

    build.run_compiler = slow
else:
    raise ValueError(fault)
anyio.run(serve, Path(root))
