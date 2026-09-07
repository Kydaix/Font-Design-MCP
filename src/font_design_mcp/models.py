"""The public input contract. Coordinates use font units, baseline y=0, y upwards."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ID = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,63}$")]
GlyphID = Annotated[str, Field(pattern=r"^(?:\.notdef|[a-zA-Z_][a-zA-Z0-9_.]{0,62})$")]
Revision = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
Coord = Annotated[float, Field(ge=-16000, le=16000, allow_inf_nan=False)]
Advance = Annotated[float, Field(ge=0, le=16000, allow_inf_nan=False)]
Scalar = Annotated[float, Field(ge=-16, le=16, allow_inf_nan=False)]
Matrix = tuple[Scalar, Scalar, Scalar, Scalar, Coord, Coord]
IDENTITY = (1, 0, 0, 1, 0, 0)
ShortText = Annotated[str, Field(max_length=4000)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Metrics(Model):
    units_per_em: int = Field(default=1000, ge=16, le=4096)
    ascender: Coord = 800
    descender: Coord = -200
    cap_height: Coord = 700
    x_height: Coord = 500

    @model_validator(mode="after")
    def order(self):
        if not self.descender <= 0 < self.x_height <= self.cap_height <= self.ascender:
            raise ValueError("Require descender <= 0 < x_height <= cap_height <= ascender")
        return self


class Metadata(Model):
    family: str = Field(min_length=1, max_length=100, pattern=r"^[^\x00-\x1f]+$")
    style: str = Field(default="Regular", min_length=1, max_length=100, pattern=r"^[^\x00-\x1f]+$")
    copyright: str = Field(default="", max_length=1000)
    license_text: str = Field(default="", max_length=4000)


class Decision(Model):
    hypothesis: ShortText
    variant: ShortText = ""
    observation: ShortText = ""
    review: Literal["unreviewed", "automatic", "agent"] = "unreviewed"
    # Human approval cannot be asserted by an MCP tool caller.


class Point(Model):
    id: ID
    x: Coord
    y: Coord
    type: Literal["line", "curve", "qcurve", "offcurve"] = "line"
    smooth: bool = False


class Contour(Model):
    id: ID
    points: list[Point] = Field(min_length=2, max_length=2048)


class Component(Model):
    id: ID
    base: GlyphID
    transform: Matrix = IDENTITY


class Anchor(Model):
    id: ID
    name: ID
    x: Coord
    y: Coord


class Glyph(Model):
    advance: Advance = 600
    unicodes: list[Annotated[int, Field(ge=0, le=0x10FFFF)]] = Field(default_factory=list, max_length=32)
    contours: list[Contour] = Field(default_factory=list, max_length=64)
    components: list[Component] = Field(default_factory=list, max_length=32)
    anchors: list[Anchor] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def unicode_scalars(self):
        if any(0xD800 <= u <= 0xDFFF for u in self.unicodes):
            raise ValueError("Unicode surrogate is not a scalar value")
        if len(set(self.unicodes)) != len(self.unicodes):
            raise ValueError("Duplicate Unicode association")
        return self


class PutContour(Model):
    op: Literal["put_contour"]
    contour: Contour
    replace: bool = False


class MovePoint(Model):
    op: Literal["move_point"]
    point_id: ID
    x: Coord
    y: Coord


class Transform(Model):
    op: Literal["transform"]
    matrix: Matrix
    contour_ids: list[ID] | None = Field(default=None, max_length=64)


class PutComponent(Model):
    op: Literal["put_component"]
    component: Component
    replace: bool = False


class PutAnchor(Model):
    op: Literal["put_anchor"]
    anchor: Anchor
    replace: bool = False


class Remove(Model):
    op: Literal["remove"]
    kind: Literal["contour", "component", "anchor"]
    id: ID


class SetUnicodes(Model):
    op: Literal["set_unicodes"]
    unicodes: list[Annotated[int, Field(ge=0, le=0x10FFFF)]] = Field(max_length=32)


class ReplaceGlyph(Model):
    op: Literal["replace_glyph"]
    glyph: Glyph


Edit = Annotated[
    PutContour | MovePoint | Transform | PutComponent | PutAnchor | Remove | SetUnicodes | ReplaceGlyph,
    Field(discriminator="op"),
]


class SetAdvance(Model):
    op: Literal["advance"]
    glyph_id: GlyphID
    value: Advance


class Bearings(Model):
    op: Literal["bearings"]
    glyph_id: GlyphID
    left: Coord
    right: Coord


class KernPair(Model):
    op: Literal["kern_pair"]
    left: GlyphID
    right: GlyphID
    value: Coord | None


class KernGroup(Model):
    op: Literal["kern_group"]
    name: Annotated[str, Field(pattern=r"^public\.kern[12]\.[a-zA-Z0-9_]{1,40}$")]
    glyphs: list[GlyphID] | None = Field(max_length=512)


Spacing = Annotated[SetAdvance | Bearings | KernPair | KernGroup, Field(discriminator="op")]


class ProjectCreate(Model):
    metadata: Metadata
    metrics: Metrics = Field(default_factory=Metrics)
    brief: ShortText = ""


class ProjectRef(Model):
    project_id: Revision


class ReadRef(ProjectRef):
    revision: Revision | None = None


class Page(ReadRef):
    offset: int = Field(default=0, ge=0, le=100000)
    limit: int = Field(default=50, ge=1, le=100)


class WriteRef(ProjectRef):
    expected_revision: Revision
    summary: str = Field(default="", max_length=500)


class ProjectUpdate(WriteRef):
    metadata: Metadata | None = None
    metrics: Metrics | None = None
    brief: ShortText | None = None
    decision: Decision | None = None


class GlyphGet(ReadRef):
    glyph_id: GlyphID


class GlyphEdit(WriteRef):
    glyph_id: GlyphID
    create: bool = False
    operations: list[Edit] = Field(min_length=1, max_length=128)


class SpacingEdit(WriteRef):
    operations: list[Spacing] = Field(min_length=1, max_length=128)


class RenderGlyph(GlyphGet):
    compare_revision: Revision | None = None
    width: int = Field(default=640, ge=128, le=1024)
    height: int = Field(default=640, ge=128, le=1024)
    guides: bool = True
    points: bool = True


class RenderText(ReadRef):
    compare_revision: Revision | None = None
    text: str = Field(min_length=1, max_length=256)
    sizes: list[Annotated[int, Field(ge=8, le=160)]] = Field(default=[32, 72], min_length=1, max_length=4)
    kern: bool = True
    width: int = Field(default=1000, ge=128, le=2048)
    dark: bool = False


class Validate(ReadRef):
    corpus: str = Field(default="", max_length=4000)


class Build(ReadRef):
    formats: list[Literal["ttf", "woff2"]] = Field(default=["ttf", "woff2"], min_length=1, max_length=2)


class Restore(WriteRef):
    target_revision: Revision


class Result(Model):
    ok: bool
    summary: str
    project_id: str | None = None
    revision: str | None = None
    changed: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    data: dict = Field(default_factory=dict)
    error: dict | None = None
