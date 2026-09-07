import importlib.metadata as md
import inspect

import freetype
from fontTools.pens.freetypePen import FreeTypePen
from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel import Server
from PIL import Image
from ufoLib2.objects import Anchor, Component, Contour, Point

for name in (
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
):
    print(name, md.version(name))
for obj in (
    FreeTypePen.image,
    Contour,
    Point,
    Component,
    Anchor,
    Server.call_tool,
    Server.list_tools,
    FastMCP.tool,
):
    print(obj.__qualname__, inspect.signature(obj))
p = FreeTypePen(None)
p.moveTo((2, 2))
p.lineTo((20, 2))
p.lineTo((20, 20))
p.closePath()
im = p.image(width=24, height=24)
assert im.getbbox() is not None
im.save("probe.png")
print("FreeType", freetype.version(), "PNG", Image.open("probe.png").size)
