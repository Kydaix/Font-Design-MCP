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


class FilledPath(Model):
    op: Literal["filled_path"]
    paths: list[Annotated[str, Field(min_length=1, max_length=16000)]] = Field(min_length=1, max_length=32)
    id: Annotated[str, Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]{0,23}$")] = "outline"
    replace: bool = False
    advance: Advance | None = None


class StrokePath(FilledPath):
    op: Literal["stroke_path"]
    width: Annotated[float, Field(gt=0, le=2000, allow_inf_nan=False)]
    cap: Literal["round", "butt", "square"] = "round"
    join: Literal["round", "bevel", "miter"] = "round"


class Primitive(Model):
    op: Literal["primitive"]
    shape: Literal["rectangle", "ellipse"]
    x: Coord
    y: Coord
    width: Annotated[float, Field(gt=0, le=16000)]
    height: Annotated[float, Field(gt=0, le=16000)]
    id: Annotated[str, Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]{0,23}$")] = "outline"
    replace: bool = False
    advance: Advance | None = None


class Duplicate(Model):
    op: Literal["duplicate"]
    source: GlyphID
    matrix: Matrix = IDENTITY


class ComposeAccent(Model):
    op: Literal["compose_accent"]
    base: GlyphID
    mark: GlyphID
    base_anchor: ID = "top"
    mark_anchor: ID = "_top"


Edit = Annotated[
    PutContour
    | MovePoint
    | Transform
    | PutComponent
    | PutAnchor
    | Remove
    | SetUnicodes
    | ReplaceGlyph
    | FilledPath
    | StrokePath
    | Primitive
    | Duplicate
    | ComposeAccent,
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

AxisTag = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9]{3}$")]
AxisValue = Annotated[float, Field(ge=-32768, le=32767, allow_inf_nan=False)]
Location = Annotated[dict[AxisTag, AxisValue], Field(max_length=4)]


class Axis(Model):
    tag: AxisTag
    name: str = Field(min_length=1, max_length=100, pattern=r"^[^\x00-\x1f]+$")
    minimum: AxisValue
    default: AxisValue
    maximum: AxisValue

    @model_validator(mode="after")
    def bounds(self):
        if not self.minimum <= self.default <= self.maximum or self.minimum == self.maximum:
            raise ValueError("Require minimum <= default <= maximum and minimum < maximum")
        return self


class Master(Model):
    id: ID
    name: str = Field(min_length=1, max_length=100, pattern=r"^[^\x00-\x1f]+$")
    location: Location


class Variation(Model):
    axes: list[Axis] = Field(min_length=1, max_length=4)
    masters: list[Master] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def designspace(self):
        tags = {axis.tag for axis in self.axes}
        if len(tags) != len(self.axes) or len({a.name for a in self.axes}) != len(self.axes):
            raise ValueError("Axis tags and names must be unique")
        if len({s.id.casefold() for s in self.masters}) != len(self.masters):
            raise ValueError("Master IDs must be unique, including on case-insensitive filesystems")
        if len({s.name for s in self.masters}) != len(self.masters):
            raise ValueError("Master names must be unique")
        locations = []
        for master in self.masters:
            if set(master.location) != tags:
                raise ValueError("Every master must specify every axis, with no unknown axes")
            if any(not a.minimum <= master.location[a.tag] <= a.maximum for a in self.axes):
                raise ValueError("Master location outside axis range")
            locations.append(tuple(master.location[a.tag] for a in self.axes))
        if len(set(locations)) != len(locations):
            raise ValueError("Master locations must be unique")
        default = next((s for s in self.masters if s.id == "default"), None)
        if default is None or any(default.location[a.tag] != a.default for a in self.axes):
            raise ValueError("Master 'default' must be at the axes' default location")
        for axis in self.axes:
            values = [s.location[axis.tag] for s in self.masters]
            if min(values) != axis.minimum or max(values) != axis.maximum:
                raise ValueError("Masters must cover each axis minimum and maximum")
        return self


class ProjectCreate(Model):
    metadata: Metadata
    metrics: Metrics = Field(default_factory=Metrics)
    brief: ShortText = ""


class ProjectRef(Model):
    project_id: Revision


class ReadRef(ProjectRef):
    revision: Revision | None = None


class Page(ReadRef):
    detail: Literal["summary", "full"] = "summary"
    include_total: bool = False
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


class VariableConfigure(WriteRef):
    variation: Variation


class GlyphGet(ReadRef):
    master_id: ID = "default"
    glyph_id: GlyphID
    detail: Literal["summary", "full"] = "summary"


class GlyphChange(Model):
    glyph_id: GlyphID
    create: bool = False
    operations: list[Edit] = Field(min_length=1, max_length=128)


class GlyphEdit(WriteRef, GlyphChange):
    master_id: ID = "default"
    detail: Literal["summary", "full"] = "summary"


class FontEdit(WriteRef):
    master_id: ID = "default"
    glyphs: list[GlyphChange] = Field(min_length=1, max_length=128)
    spacing: list[Spacing] = Field(default_factory=list, max_length=128)
    detail: Literal["summary", "full"] = "summary"

    @model_validator(mode="after")
    def budget(self):
        if sum(len(g.operations) for g in self.glyphs) + len(self.spacing) > 512:
            raise ValueError("Maximum 512 operations per transaction")
        if len({g.glyph_id for g in self.glyphs}) != len(self.glyphs):
            raise ValueError("Each glyph may appear only once in a transaction")
        return self


class SpacingEdit(WriteRef):
    master_id: ID = "default"
    operations: list[Spacing] = Field(min_length=1, max_length=128)


class RenderGlyph(GlyphGet):
    image_mode: Literal["inline", "resource"] = "inline"
    compare_revision: Revision | None = None
    width: int = Field(default=640, ge=128, le=1024)
    height: int = Field(default=640, ge=128, le=1024)
    guides: bool = True
    points: bool = True


class RenderText(ReadRef):
    location: Location = Field(default_factory=dict)
    detail: Literal["summary", "positions", "full"] = "summary"
    image_mode: Literal["inline", "resource"] = "inline"
    compare_revision: Revision | None = None
    text: str = Field(min_length=1, max_length=256)
    sizes: list[Annotated[int, Field(ge=8, le=160)]] = Field(default=[32, 72], min_length=1, max_length=4)
    kern: bool = True
    width: int = Field(default=1000, ge=128, le=2048)
    dark: bool = False


class Validate(ReadRef):
    detail: Literal["summary", "full"] = "summary"
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
