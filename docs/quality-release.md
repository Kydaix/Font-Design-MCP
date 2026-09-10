# Outline quality and release evidence

The development version separates technical validity, design diagnostics and visual review. A proof
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

Up to 64 profiles can be declared. Choose `master_id` or `location`, never both. Unscoped profiles apply
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

Schemas 1–3 remain readable. Active profiles use design-state version 2 and manifest schema 4, which older
servers reject explicitly. Empty profile lists are omitted from older contracts. Preserve sources,
manifests and referenced proof/review artifacts in backups.

Run `pytest tests/test_quality.py` for seeded blank-M, K=H, UniSlaw K taper, counter/rotation, stale/tampered
evidence and complete-delivery scenarios. Protocol regressions launch a separate STDIO MCP process.
Test review attestations are explicitly fixture data, not claims about a finished typeface.
