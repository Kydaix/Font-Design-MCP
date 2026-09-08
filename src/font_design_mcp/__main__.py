import argparse
import importlib
import importlib.metadata
import json
import logging
import os
import platform
import sys
import tempfile
from pathlib import Path

from . import __version__


def workspace_path(explicit=None):
    if explicit or os.environ.get("FONT_DESIGN_MCP_WORKSPACE"):
        return Path(explicit or os.environ["FONT_DESIGN_MCP_WORKSPACE"]).expanduser().absolute()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return (base / "font-design-mcp" / "workspace").absolute()


def doctor(build=False):
    report = {
        "ok": True,
        "version": __version__,
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "workspace": str(workspace_path()),
        "dependencies": {},
        "errors": [],
    }
    for distribution, module in [
        ("mcp", "mcp"),
        ("pydantic", "pydantic"),
        ("ufoLib2", "ufoLib2"),
        ("fonttools", "fontTools"),
        ("fontmake", "fontmake"),
        ("uharfbuzz", "uharfbuzz"),
        ("freetype-py", "freetype"),
        ("Pillow", "PIL.Image"),
        ("filelock", "filelock"),
        ("defusedxml", "defusedxml.ElementTree"),
        ("booleanOperations", "booleanOperations"),
    ]:
        try:
            importlib.import_module(module)
            report["dependencies"][distribution] = importlib.metadata.version(distribution)
        except Exception as exc:
            report["errors"].append({"dependency": distribution, "message": str(exc)})
    if not report["errors"]:
        try:
            import freetype
            from fontTools.pens.freetypePen import FreeTypePen

            pen = FreeTypePen(None)
            pen.moveTo((2, 2))
            pen.lineTo((20, 2))
            pen.lineTo((20, 20))
            pen.closePath()
            if not pen.image(24, 24).getbbox():
                raise RuntimeError("Empty rasterization")
            report.update(png="ok", freetype=freetype.version())
            if build:
                from .models import Build, Metadata, ProjectCreate
                from .service import Service

                with tempfile.TemporaryDirectory(prefix="font-design-doctor-") as folder:
                    service = Service(folder)
                    created, _ = service.execute(
                        "project_create", ProjectCreate(metadata=Metadata(family="Doctor"))
                    )
                    built, _ = service.execute("font_build", Build(project_id=created.project_id))
                    report["build"] = {fmt: info["sha256"] for fmt, info in built.data["files"].items()}
        except Exception as exc:
            report["errors"].append({"diagnostic": "build" if build else "png", "message": str(exc)})
    report["ok"] = not report["errors"]
    return report


def main():
    parser = argparse.ArgumentParser(prog="font-design-mcp")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    serve_parser = sub.add_parser("serve", help="Run the MCP STDIO server")
    serve_parser.add_argument(
        "--workspace", type=Path, help="Fixed authorized directory; overrides environment/default"
    )
    diagnostic = sub.add_parser("doctor", help="Diagnose dependencies and rasterization")
    diagnostic.add_argument(
        "--build", action="store_true", help="Also compile and roundtrip TTF/WOFF2 in a temporary workspace"
    )
    config = sub.add_parser("config", help="Print client JSON; does not edit client files")
    config.add_argument("--workspace", type=Path)
    config.add_argument(
        "--from", dest="source", help="Wheel path or pinned Git URL; defaults to the versioned PyPI package"
    )
    args = parser.parse_args()
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    if args.command == "serve":
        import anyio

        from .server import serve

        anyio.run(serve, workspace_path(args.workspace))
    elif args.command == "config":
        source = args.source or f"font-design-mcp=={__version__}"
        print(
            json.dumps(
                {
                    "mcpServers": {
                        "font-design": {
                            "command": "uvx",
                            "args": [
                                "--python",
                                "3.13",
                                "--from",
                                source,
                                "font-design-mcp",
                                "serve",
                                "--workspace",
                                str(workspace_path(args.workspace)),
                            ],
                        }
                    }
                },
                indent=2,
            )
        )
    else:
        report = doctor(args.build)
        print(json.dumps(report, indent=2))
        if not report["ok"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
