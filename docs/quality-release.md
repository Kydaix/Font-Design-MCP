# Outline quality and release evidence

Version 0.6.0 separates technical validity, design diagnostics and visual review. A proof
export supports iteration. A release export requires measurements and agent attestations attached to the
exact source revision. Passing this contract never asserts human approval or aesthetic perfection.

## Default diagnostics

`font_analyze` checks filled ink after component decomposition. Visible letters, numbers, symbols and
combining marks without ink produce `empty_visible_glyph`. Expected invisible characters, spaces,
formatting controls and variation selectors are exempt. Cancelled winding and collapsed components count.

Degenerate contours, strict within-contour crossings and matching sampled outlines for different
characters are review candidates with stable per-master `finding_id` values. Canonically equivalent
Unicode aliases are excluded. Matching ignores translation, start point and global winding reversal,
but preserves relative counter winding. It is a diagnostic signal, not general character recognition.

Flattening tolerance is `min(0.25, UPM/4000)`. Budgets: 20,000 points per glyph, one million per font,
two million scan/comparison operations. Exhaustion fails explicitly. Tangencies, collinear contacts and
interactions between contours are not certified. Only the first 16 crossings per glyph are detailed;
an additional candidate reports that limit. Global lists retain at most 2,000 entries with exact counts.

`outline_integrity_passed` covers blocking ink/budget checks, not candidate resolution. `checks_passed`
also includes the declared contract. `design_coverage` exposes measured and unmeasured structural glyphs.
Present characters in `HOnosaASUKMNVRWXYkmy0123456789` augment declared reference glyphs automatically;
omitting K/M/Y from a manual list does not remove them from release measurement requirements.

## Perpendicular stroke and counter profiles

Add `stroke_profiles` to the complete `design_spec`, preserving its other fields:

```json
{
  "id": "K-leg", "glyph_id": "K", "master_id": "semibold",
  "start": [606, 80], "end": [500, 200], "samples": 5,
  "region": "ink", "minimum": 120, "maximum": 142, "max_ratio": 1.10
}
```

These illustrative coordinates and tolerances must match the intended design. Each of 2–17 samples
cuts perpendicular to the start/end centerline and measures the interval containing its center.
Samples include both endpoints; keep them away from joins and terminals. `minimum` and `maximum` are
inclusive widths in font units. Optional `max_ratio` bounds largest/smallest width over the profile.
A center outside the requested region fails. `region="counter"` measures white bounded by ink on both
sides, never the unbounded exterior. Profiles follow straight local centerlines, not arbitrary curves.
Flattening tolerance does not guarantee width accuracy near tangencies.

Up to 512 profiles can be declared. Choose `master_id` or `location`, never both. Unscoped profiles apply
to every master; locations measure the compiled variable instance. Existing `variation_probes` express
weight progression over an axis. `render_glyph(measurements=true)` overlays applicable source-master
profiles in blue/red and stores sample endpoints and widths in its immutable report. Compiled-location
measurements stay in the variation analysis rather than being overlaid on a different UFO master.
Measurements explain geometry; they do not automatically move points to satisfy the contract.

## Evidence workflow

1. Define languages, repertoire, usage sizes, contrast and references. Establish structural glyphs,
   including diagonals, joins and digits, before expanding accented derivatives.
2. Run `font_analyze(detail="full")`; repair blockers and inspect candidates. Measure every structural
   glyph with an appropriate stroke probe or profile.
3. Inspect `render_proof` batches of at most 32 glyphs for each master, including visible helper glyphs.
   Inspect `render_glyph(reference_id=...)` overlays for imported default-master references.
4. Inspect `render_text(sizes=[24,72], kern=true)` and `kern=false` at each master's location. Add
   intermediate-axis text proofs for variable fonts.
5. Record observations with `proof_review`, supplying the exact `revision`, render **report_uris**,
   `verdict="accept"` or `"revise"`, and a meaningful `observation`. Intentional candidates require
   `resolutions=[{"finding_id":"...", "reason":"specific explanation"}]`. All involved glyphs must
   actually appear in this review's proofs. Blocking issues cannot be waived. Incomplete proofs may
   receive a `revise` review, but cannot support acceptance.
6. Call `font_release_check(project_id=..., review_uris=[...])` using the review report URIs. It reports
   missing glyph reviews, structural measurements, reference overlays, text proofs and unresolved findings.
7. Export with `font_build(purpose="release", review_uris=[...])`. Its immutable delivery report binds
   exact output hashes, analyses and review evidence.

| Export | Meaning |
|---|---|
| `font_build()` | Proof export; `release_status="not_reviewed"`, diagnostics attached. |
| `font_build(require_design_checks=true)` | Gates default blocking diagnostics and declared rules, without asserting visual review. |
| `font_build(purpose="release", review_uris=[...])` | Also gates revision-bound review requirements; `release_not_ready` identifies incomplete evidence. |

Each master needs visible-glyph review and shaped text at <=32 px and >=48 px, with and without kerning.
Each variable axis needs text reviewed at a strictly interior value. Imported references need a reviewed
default-master overlay. These requirements do not certify every axis location, language sequence or platform.

Reviews are immutable artifacts, not new source revisions. Every source/contract/metrics edit invalidates
old evidence for the new revision. It remains usable when explicitly exporting the old revision.
Wrong-project evidence, mismatched revisions and modified image hashes are rejected. Text proofs are also
bound to the compiled TTF hash: a changed compiler output requires fresh text proofs, even for the same
source revision. A caller attestation
cannot prove that the client displayed the image or judged it correctly; never automate positive reviews
without inspecting the actual images. Optical spacing, style and arbitrary character identity still need
design judgment.

## Compatibility and regression tests

Schemas 1–4 remain readable. Active profiles use design-state version 2 and manifest schema 4; regional,
variation-profile, provenance, usage, cropped-reference and network features use version 3/schema 5, which older
servers reject explicitly. Empty new fields are omitted from older contracts. Preserve sources,
manifests and referenced proof/review artifacts in backups.

Run `pytest tests/test_quality.py` for seeded blank-M, K=H, UniSlaw K taper, counter/rotation, stale/tampered
evidence and complete-delivery scenarios. Protocol regressions launch a separate STDIO MCP process.
Test review attestations are explicitly fixture data, not claims about a finished typeface.

## Spatial coverage, usage and progression

`design_coverage.regions` checks **where** successful samples fall, independently of rule IDs. Conventional
Latin K/M/N/Y/V/W/X/R/v/w/x templates expose branches and joins. Each region needs two distinct spatial
samples by default; copying a stem probe or renaming it cannot cover other branches. These templates are
not a universal anatomy model. Add `regions=[{id,glyph_id,bounds:[u0,v0,u1,v1],role,minimum_samples,master_id?}]`
for the project's other constructions. Bounds are normalized to each glyph's visible box. Region roles:
`stem`, `branch`, `junction`, `counter`, `curve`, `terminal`. Source-master regions do not accept locations.
The full report's `evidence_plan` gives absolute region boxes and seed positions, proof groups and supported
words. Seeds must be placed on actual strokes after inspection; proposed targets remain null. It records
no passing measurement or review. Summaries bound each coverage list to 12 items, with counts and a full report URI.
`review_groups` groups stable candidate IDs by diagnostic kind to support fixing shared causes.

Declare `usage_texts` (up to 64 strings, 2–80 characters). Accepted text evidence requires adjacent visible
shaped glyphs and actual raster ink at every requested size. Empty text, spaces, a single letter, or spaced
isolated letters cannot establish word usage. Reports retain visible glyphs, codepoints, adjacent pairs and
sizes containing ink. Each master/kern/small-or-large combination must cover all structural glyphs and each
declared sequence. A proof containing just `HH` cannot satisfy a contract requesting `KAYAK`.

`variation_profiles` (up to 128) extend stroke profiles with `axis_tag`, 2–9 increasing `values`, `location`
for other fixed axes, `direction`, `tolerance` and `minimum_change`. They compare each normal-width sample
through the compiled axis sequence; they detect local reversals even when endpoints are in order. They
use fixed local centerlines, so inspect whether each cut still hits the intended branch as shape changes.

## Persistent constructions and references

`stroke_network` is an optional glyph-edit operation with a `network`:

```json
{
  "parameters": {"diagonal": 140},
  "strokes": [{"id":"arm","path":"M 100 100 L 500 600","width_parameter":"diagonal"}],
  "horizontal_scale": 1, "origin_x": 0, "advance": 800
}
```

Up to 16 named parameters and 16 strokes share width controls. `update_stroke_network` changes known
parameters, horizontal scale and/or advance. Scaling changes centerlines **before** stroking, preserving
normal widths unless their parameter also changes. Per-stroke contours keep intentional overlaps. Arbitrary
point, component and bearing edits require `detach_stroke_network`; anchors and Unicode mappings remain
editable. This is an optional centerline representation, not an automatic optical-design solver.
Only the typed network key is allowed in glyph lib; executable/arbitrary UFO lib entries remain rejected.

`reference_import(crop=[left,top,right,bottom])` takes calibration for the **original page**, preserves its
normalized PNG and derives the crop calibration. Reuse of the same page is deduplicated. Immutable source
and crop hashes are verified on load; the 32 MB project reference budget includes preserved pages.
`render_glyph(comparison_mode="difference", reference_id=...)` distinguishes source ink, reference ink and
overlap. Its thresholded intersection-over-union is a raster comparison, not an aesthetic score.
`glyph_origins=[{glyph_id,status,reference_ids,observation}]` distinguishes `observed`, `extrapolated` and
`original`; observed origins must reference existing imports. Reference-based release contracts require
these statements for structural glyphs. An unreadable tiny raster letter must not be presented as an exact trace.

`project_inspect(detail="full", sections=["design"], glyph_ids=["K"])` selects context. Available sections:
metadata, design, glyphs, spacing, compositions, history. Kerning, groups, decisions, references and flattened
composition links each have pagination metadata; glyph focus includes related spacing/compositions and
lists direct component neighbors. Read the full contract explicitly before replacing it.

## Interpolation and external binary checks

`font_analyze(interpolation=true)` runs fontTools source-correspondence diagnostics and compiled ink checks
at the min/mid/max Cartesian grid plus master locations. Controlled proof and release builds run these
checks automatically for variable fonts. Wrong starts/order, structural correspondence failures and empty
instances block these exports. Other fontTools findings remain diagnostic candidates. A child process is
limited to 45 seconds; finding, flattening and work budgets fail closed. Finite samples cannot certify the
continuous axis space. See the [fontTools documentation](https://fonttools.readthedocs.io/en/latest/varLib/interpolatable.html).

Run `pytest tests/test_quality.py tests/test_quality_workflow.py` for real and injected defect regressions.
The CI matrix runs the suite on Windows, Linux and macOS; a local Windows pass is not a result for other OSes.
`scripts/check_font_binary.py` records host, dependency versions, tables, shaping and TTF/WOFF2 round trips.
Its optional `--fontbakery` runs an installed universal profile and preserves the raw report; absence is
reported as unavailable. This supplements the MCP checks without changing its normal dependency surface.
See [FontBakery CLI usage](https://fontbakery.readthedocs.io/en/latest/user/USAGE.html).

Variable exports also populate STAT axis values for declared master coordinates and order named instances
by weight, then remaining axes. Registered weight/width coordinates use conventional labels; other values
use the axis name and coordinate. Source outlines and coordinates remain unchanged. Changing this compiler
policy invalidates cached binaries and requires fresh text evidence. `scripts/render_browser_proof.py`
can additionally render the UniSlaw specimen through an installed Chromium browser, recording successful
font loading and the browser version; this remains a finite browser check, not approval of the entire font.
