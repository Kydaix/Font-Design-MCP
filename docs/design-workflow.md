# Reference-driven type design

This workflow improves controlled reconstruction and finishing. It does **not** trace a sketch, infer a
style automatically, or certify professional/artistically perfect typography. The client agent must
receive and inspect the returned images. Preserve distinctive features rather than regularizing every
intentional asymmetry.

Version 0.6.0 extends this workflow with [default diagnostics, normal-width profiles and
release evidence](quality-release.md). Profiles use manifest schema 4; regional coverage, cropped references
and persistent stroke networks use schema 5. Schemas 1–4 remain readable. Visual review records reference
an exact revision without changing its sources.

## 1. Define a small, testable design contract

`project_create` and `project_update` accept `design_spec`. Updating it replaces the **whole** spec;
inspect the current one with `project_inspect(detail="full")` first. Unspecified fields take their defaults.
Choose reference letters and digits early. Values below are an illustrative brief, not typographic norms:

```json
{
  "required_characters": "HOnobdpq0123456789",
  "reference_glyphs": ["H", "O", "n", "o", "zero", "eight"],
  "notes": "Low contrast, slightly squared bowls; evaluate at 16, 32 and 72 pixels.",
  "protected_features": "Keep the deliberately asymmetric O and the original shape of 2.",
  "digit_spacing": "tabular",
  "tangent_tolerance_degrees": 3,
  "metric_rules": [
    {"id": "H-height", "glyphs": ["H"], "metric": "height", "target": 700, "tolerance": 1}
  ],
  "stroke_probes": [
    {"id": "H-left-stem", "glyph_id": "H", "axis": "horizontal", "position": 200,
     "span_index": 0, "target": 80, "tolerance": 2}
  ]
}
```

`notes` and `protected_features` are guidance for the agent, not machine-verified image semantics.
`reference_glyphs` must exist to pass the declared contract. Include round overshoots in targets where
appropriate: do not apply one height equality to both round and flat letters automatically.

`digit_spacing="tabular"` checks the spread of the ten **advance** widths against `digit_tolerance`.
It does not force equal visible widths. `"proportional"` requires digit coverage but does not equate
advances; `"unspecified"` adds no digit requirement. Digit lookup uses Unicode, not assumed glyph names.

## 2. Import drawings with explicit calibration

Place a PNG in the launch workspace's `inbox/` directory. The MCP intentionally has no arbitrary download
or external filesystem tool. For a drawing at `inbox/O.png`, call `reference_import` with:

```json
{
  "project_id": "<current project ID>",
  "expected_revision": "<current revision>",
  "reference_id": "O-paper",
  "glyph_id": "O",
  "source_path": "inbox/O.png",
  "image_to_font": [1, 0, 0, -1, 0, 700],
  "label": "Original O, baseline at pixel y=700"
}
```

Always use the returned revision for the next write. Importing a reference does not create or draw its
glyph. The image is returned inline by default; `image_mode="resource"` uses the standard MCP resource
link instead. Clients must forward image content to a vision-capable model.

The affine matrix `[a,b,c,d,tx,ty]` maps image pixels to font units:
`font_x = a*pixel_x + c*pixel_y + tx`, `font_y = b*pixel_x + d*pixel_y + ty`.
Image coordinates start at the top left and point **down**; font coordinates start on the baseline and
point **up**. In the example, image pixel `(10,700)` maps to font point `(10,0)`. Calibrate from shared
page guides; do not fit every letter independently into a common bounding box. Rotation/shear may be
specified explicitly, but perspective correction, segmentation and automatic crop extraction are not
implemented. Import individual crops with consistently calibrated transforms.

Only single-frame PNGs up to 2 MB and 2048×2048 pixels are accepted. There are at most 64 active references,
with a combined normalized PNG budget of 32 MB. Coordinates stay inside ±16000 font units. Paths outside
`inbox/`, parent traversal, symlinks, junctions and hard links are rejected. Transparent input is composited
on white and metadata is discarded. The source-byte SHA-256 and the sanitized pixel reference are retained;
the original file and its metadata are not copied verbatim, so keep your original scans separately.

References live in immutable `artifacts/` entries, linked from the new revision's manifest. The image
artifact itself is anchored to the import's parent revision; it is reference evidence, not a rendering
of that revision's font. Changing/deleting the inbox file afterwards does not change the imported image.
`replace=true` creates a new reference association; old revisions retain their previous evidence.
`project_update(remove_reference_ids=["O-paper"])` removes an active association, never its history.

## 3. Reconstruct, then compare to the drawing

Use the existing paths/contours/components to reconstruct the intended form. For reference comparison:

```json
{
  "project_id": "<project ID>",
  "glyph_id": "O",
  "reference_id": "O-paper",
  "guides": false,
  "points": false
}
```

Send this to `render_glyph`. The reference appears beneath the outline at the declared calibration;
its identity/hash and the actual frame/scale are reported. `compare_revision` uses the **same reference
from the primary requested revision**, common frame and scale on both sides. A drawing is not automatically
matched, rescaled or redrawn. Reference comparison does not compute a fidelity score.

## 4. Correct curves without breaking their joins

Use `glyph_get(detail="full")` to retrieve current IDs before editing.

* `move_point` remains a raw coordinate edit by default for compatibility. With `preserve_handles=true`,
  it translates an on-curve node and its adjacent off-curve handles by the same delta.
* `move_handle` moves a cubic control and aligns its opposite control. `mode="aligned"` preserves the
  opposite handle's old length; `"symmetric"` uses equal lengths. Both require nonzero cubic handles on
  both sides. Ambiguous quadratic controls and line/curve joins require explicit low-level edits instead.
* `set_smooth` changes the declared intention of an on-curve node. It does **not** repair geometry.
  Use `smooth=false` for an intentional corner, not to conceal an unwanted bump.

All moved handle IDs are returned with `detail="full"`. Source validation and `expected_revision`
continue to apply. A failed operation does not commit a partial glyph or batch.

## 5. Keep opted-in accents attached

`compose_accent(auto_align=true)` records a relationship between the base/mark anchors. Later anchor,
outline and side-bearing changes recompute the mark translation and inherit the base advance in the same
transaction. Linked dependencies are refreshed in order and indirect changes appear in `changed`.
Missing anchors/cycles fail atomically. A new variable master clones links independently from the default.

The default remains `auto_align=false` for existing clients. Linked composites own their component
placement and advance: use `detach_composition` before a local outline/metrics override. Detaching retains
the current component geometry; it does not flatten it. Custom anchors on composites are not automatically
inherited or propagated from base anchors. This feature is for precomposed glyphs, not combining-mark GPOS.

## 6. Analyze and proof, repeatedly

`font_analyze` checks a selected `master_id`; source-only rules do not require compilation:

* explicit smooth-node tangent alignment (including wraparound and quadratic joins), and degenerate tangents;
* required Unicode coverage and reference-glyph presence;
* declared advance/bounds/bearing/height targets;
* scanline stroke probes with non-zero winding fill, including component outlines;
* tabular advance consistency when requested.

A horizontal probe cuts at `y=position`, and spans are ordered left to right. A vertical probe cuts at
`x=position`, ordered bottom to top. `span_index` selects the filled interval. Pick regions away from joins,
terminals and extrema. The algorithm uses adaptive polyline approximation only for diagnostics; it never
changes source contours. `flatten_tolerance` is not a guaranteed error bound for a nearly tangent scanline.
Subdivision is bounded per glyph and per analysis; an exhausted budget is an issue, not a passing check.
Up to 64 spans per probe are shown; total counts and truncation are explicit.

Default responses include up to ten issues and a hash-addressed report URI. Full reports retain all
measurements and up to 2000 issues with exact issue counts and `issues_truncated`. No overflow is treated
as success. Reports over the resource limit fail explicitly instead of creating unreadable evidence.

Use `render_proof` with an explicit list of up to 32 glyph IDs. Every tile uses one shared frame and scale,
including revision comparisons. Missing glyphs are labeled, never substituted. Grid dimensions are bounded
to 2048 pixels. Proofs compare shapes, not shaping behavior; separately use `render_text` for words and
numbers at intended sizes with and without kerning. Stabilize bearings before adding many kern pairs.

### Variable targets and honest report scope

Each metric rule or stroke probe accepts an optional `master_id` **or** `location` (never both).
A location checks compiled variable outlines, with omitted axes at their defaults; `location={}` explicitly
checks the default compiled instance. Unknown masters/axes, out-of-range coordinates and location rules
on static fonts fail analysis instead of being silently skipped. Contracts can be saved before configuration,
but must resolve when analyzed, validated or used for gated export.

Add `variation_probes` to the design spec to check a chosen stroke across an axis:

```json
{
  "id": "N-weight",
  "glyph_id": "N",
  "axis": "horizontal",
  "position": 400,
  "span_index": 0,
  "axis_tag": "wght",
  "values": [600, 650, 700, 750, 800],
  "location": {"wdth": 100},
  "direction": "nondecreasing",
  "tolerance": 2,
  "minimum_change": 20
}
```

Values must be strictly increasing, 2–9 samples per probe, up to 32 probes. The sampled axis must not also
appear in `location`. `direction` accepts `nondecreasing` or `nonincreasing`; `minimum_change` optionally
requires a signed endpoint change (default 0). Tolerance, targets and changes are in font units.
This example only applies to a font with those axes/ranges. Sample both normal and extended widths when relevant.
Intervals are still sorted spatially: a span changing identity near a junction is a reason to inspect the probe.

Reports include `scope`: checked smooth joins, applied metric/probe counts, rules for other masters,
and variation status (`not_requested`, `pending`, `checked`, or `unavailable_compile_failed`).
Variation evidence appears in `variation.measurements`; aggregate counts include these measurements.
`checks_passed` means the requested checks passed, even when no stroke rule was declared.
It is never a visual quality score. Unmarked curve tangent discontinuities appear separately in
`review_candidates`, with point IDs and exact counts (up to 2000 entries). Intentional corners remain valid.

### Combining marks in exports

Private compiler copies receive controlled `languagesystem` declarations derived from encoded scripts.
This keeps Latin `mark` active alongside `kern`; authoritative UFO features and hashes remain unchanged.
Export validation checks that matching encoded Latin base/mark anchor pairs are reachable through the
Latin `mark` feature, including cached TTF and WOFF2. Missing anchors do not create an attachment requirement.
Mark stacking, ligature attachment and optical accent placement need their own review.

## 7. Interpret validation and export accurately

`font_validate.valid` retains its technical meaning; `technical_valid` makes that explicit.
`coverage_complete` and `design.checks_passed` are separate. Its design summary is for the **default master**;
use `font_analyze(master_id=...)` for other masters. Compilation still validates all configured masters.

`font_build(require_design_checks=true)` requires nonempty `required_characters` and successful diagnostics
on **every configured master**, plus all declared location/variation checks on compiled outlines, before retaining
an export. Rules without a scope apply to every master; use `master_id` for weight-specific targets.
The default export remains ungated for compatibility; its response reports `design_gate="not_requested"`. Passing this gate
is not proof of interpolation quality, visual fidelity, readability, absence of all geometry defects, or
professional/human approval.

Not implemented: automatic tracing/curve fitting, automatic style inference, persistent parametric glyph
recipes, curvature-continuity certification, automatic optical spacing, or exhaustive variable-axis proofing.
These remain distinct follow-up layers; do not describe the new diagnostics as an autonomous type designer.

## Persistence and compatibility

Projects that use design specs, linked compositions or references use manifest schema **3**. This server
still opens schemas 1 and 2; ordinary legacy edits do not migrate a project unless design state is introduced.
Older servers reject schema 3 instead of silently dropping its relationships. Restoring an old revision
restores its design state too, and may return to a legacy schema.

UFO remains authoritative for outlines. Design metadata and imported reference images are also authoritative
project inputs. **Back up the entire project directory, including referenced artifacts**, not only UFOs.
Keep your original scans separately. Source/artifact hashes detect changes; reference hashes are rechecked
on project reads and before publishing overlays. Compilation receives no image or arbitrary UFO lib hook.
A failed import can leave an unreferenced immutable artifact, but never a partially committed project.
