# Miette Regular

An original, soft rounded typeface created with Font Design MCP. Its double-storey **a**, single-storey **g**,
open **c/e**, hooked **l**, and barred capital **I** give it a friendly voice while keeping nearby shapes distinct.

[![Miette specimen, rendered with the included font](preview.png)](specimen.html)

[TTF](Miette-Regular.ttf) · [WOFF2](Miette-Regular.woff2) · [Interactive specimen](specimen.html) · [MCP rendering](proof.png)

Open **specimen.html locally**, with the two font files beside it. You can type text, change its size,
switch between paper and ink, and compare kerning on/off. The page is in French, runs offline, normalizes
input to NFC, and identifies characters that would use a browser fallback.

## Coverage

**84 letters**, **107 encoded characters**, **114 glyphs** including unencoded components and `.notdef`.

| Set | Characters |
| --- | --- |
| Basic Latin | A–Z, a–z |
| French accents | à â é è ê ë î ï ô ù û ü ÿ ç |
| Accented capitals | À Â É È Ê Ë Î Ï Ô Ù Û Ü Ÿ Ç |
| Encoded ligatures | æ œ Æ Œ |
| Punctuation | . , : ; ! ? … - – — ' ‘ ’ " “ ” ( ) « » |
| Spaces | Space, no-break space, narrow no-break space |

One upright Regular style, 1000 units per em, 520-unit x-height and 710-unit cap height.
The 57 optical kerning pairs use groups so accented letters inherit their base letter's spacing;
the appropriate ligatures share the same leading-side groups. For example, `To`, `Tô`, and `Tœ` each
receive −60 units of kerning.

This first version focuses on French. It has **no digits, additional weights, italics, hinting, or general
combining-mark positioning**. Names such as “Miette” are working names, not availability claims. The font
has been inspected in small and large specimens; technical checks do not guarantee readability in every
context or replace a reader's review.

## Reproduce

From the repository root, after `uv sync --frozen`:

```sh
uv run --frozen python examples/miette/build.py --workspace ./workspace
uv run --frozen python examples/miette/check.py
```

The build creates a **new MCP project** and refreshes the included TTF, WOFF2, `proof.png`, and `project.json`.
The HTML specimen loads these files directly. The preview screenshot is an illustration of the shipped
specimen, not a build output. Use `--output ./test-output/miette` to keep the shipped files intact.

Every project mutation, preview, validation, and font build is an SDK call to a real STDIO server.
The workspace keeps editable UFO snapshots, derived artifacts, and an append-only `miette-calls.jsonl`
request/result log. `project.json` identifies the frozen revision and exported file hashes.

For a focused redraw after changing the recipe, reuse a project in the same workspace:

```sh
uv run --frozen python examples/miette/build.py --workspace ./workspace --project-id YOUR_PROJECT_ID --only e cedilla
```

This makes new revisions and reapplies the example's spacing recipe. It does not edit old snapshots.

## Drawing and checks

- [drawings.py](drawings.py) contains original Bézier centre lines, metrics, accent placement, and kerning.
  [FreeType's stroker](https://freetype-py.readthedocs.io/en/stable/stroker.html) expands the lines with round
  caps and joins; [booleanOperations](https://github.com/typemytype/booleanOperations) merges overlaps while
  preserving Bézier segments. The MCP receives explicit closed contours with stable point IDs.
- [build.py](build.py) is the reproducible MCP client. It checks coverage and compilation before exporting.
- [check.py](check.py) checks the **actual shipped binaries**: Unicode coverage, TTF/WOFF2 agreement, vertical
  extents, compiled counters, accented components, and HarfBuzz kerning including accent inheritance.
- [project.json](project.json) holds the build and automatic-validation report. Local visual review covered
  16–96 px specimens, French sentences and ambiguous pairs. The HTML was also checked in Firefox at desktop
  and mobile viewport widths, including its controls, font loading, and unsupported-character notice.

The narrow **î** uses an optically narrower circumflex, with no dot underneath. The cédille was shortened
after the first specimen. Rounded letters have a 10-unit overshoot; ascenders and accents fit within the
explicit line metrics. These are authored choices in this example, not a generic font-generation algorithm.

No third-party font outlines, tracing input, or model API are used. All required packages are already in
the repository's lockfile. Copyright and license text in the font metadata remain unset; the server's MIT
license is not automatically copied into generated fonts. The binary uses `fsType=0` for installable embedding,
as defined by the [OpenType specification](https://learn.microsoft.com/en-us/typography/opentype/spec/os2#fstype).
