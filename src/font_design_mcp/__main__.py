import argparse
import importlib.metadata
import json
import logging
import platform
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(prog="font-design-mcp")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Run the MCP STDIO server")
    serve.add_argument("--workspace", type=Path, required=True, help="Fixed authorized directory")
    sub.add_parser("doctor", help="Report installed capabilities and rasterization diagnostic")
    args = parser.parse_args()
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    if args.command == "serve":
        import anyio

        from .server import serve

        anyio.run(serve, args.workspace)
    else:
        import freetype
        from fontTools.pens.freetypePen import FreeTypePen

        pen = FreeTypePen(None)
        pen.moveTo((2, 2))
        pen.lineTo((20, 2))
        pen.lineTo((20, 20))
        pen.closePath()
        assert pen.image(24, 24).getbbox()
        print(
            json.dumps(
                {
                    "platform": platform.platform(),
                    "architecture": platform.machine(),
                    "python": platform.python_version(),
                    "freetype": freetype.version(),
                    "png": "ok",
                    "dependencies": {
                        n: importlib.metadata.version(n)
                        for n in (
                            "mcp",
                            "pydantic",
                            "ufoLib2",
                            "fonttools",
                            "fontmake",
                            "uharfbuzz",
                            "freetype-py",
                            "Pillow",
                            "filelock",
                            "defusedxml",
                        )
                    },
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
