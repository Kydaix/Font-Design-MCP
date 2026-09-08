<div align="center">

# Font Design MCP

<!-- mcp-name: io.github.Kydaix/font-design-mcp -->

**Draw, inspect, refine, and build fonts through MCP.**

A local MCP server for AI-assisted type design, from vector outlines to TTF and WOFF2.

[![CI](https://github.com/Kydaix/font-design-mcp/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Kydaix/font-design-mcp/actions/workflows/ci.yml)
[![Python: 3.11–3.13](https://img.shields.io/badge/Python-3.11–3.13-3776AB)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**English** · [Français](README.fr.md)

[Get started](#get-started) · [Connect a client](#connect-a-client) · [Documentation](#documentation) · [Report an issue](https://github.com/Kydaix/font-design-mcp/issues)

</div>

---

## Get started

Version **0.2.0** adds atomic multi-glyph edits, reusable TTF/WOFF2 compilations, compact responses,
numeric drawing primitives and immutable MCP resources. See [upgrade notes and audit results](docs/AUDIT-IMPLEMENTATION.md).

To use a built wheel without cloning, replace the wheel path below with your downloaded artifact:

```sh
uvx --python 3.13 --from /absolute/path/font_design_mcp-0.2.0-py3-none-any.whl font-design-mcp doctor --build
uvx --python 3.13 --from /absolute/path/font_design_mcp-0.2.0-py3-none-any.whl font-design-mcp config --from /absolute/path/font_design_mcp-0.2.0-py3-none-any.whl
```

After 0.2.0 is published to PyPI, the equivalent command is
`uvx --python 3.13 font-design-mcp@0.2.0 doctor --build`. Publication is prepared, not claimed here.
`config --from /absolute/path/package.whl` prints a client configuration using that wheel;
plain `config` targets the versioned PyPI package. It never changes client settings.
The first UV invocation downloads dependencies; run `doctor --build` before connecting a host.

`--workspace` overrides `FONT_DESIGN_MCP_WORKSPACE`, which overrides the dedicated user-data default:
`%LOCALAPPDATA%/font-design-mcp/workspace` on Windows, `~/Library/Application Support/font-design-mcp/workspace`
on macOS, `$XDG_DATA_HOME/font-design-mcp/workspace` (or `~/.local/share/...`) on Linux.
The workspace stays outside UV's cache and survives upgrades or extension removal.

The [MCPB extension](mcpb/manifest.json) targets hosts supporting the UV runtime in manifest 0.4.
See [distribution and publication](docs/DISTRIBUTION.md) for building, tests and host-validation limits.

### Development from source

1. Clone the repository and install the dependencies with the commands below.
2. Run the diagnostic and demo to generate your first font specimen.
3. [Connect your MCP client](#connect-a-client) to start designing with an agent.

**Requirements:** Python 3.11–3.13, uv, and a GitHub account with access to this repository.
Commands work in PowerShell and POSIX shells. Install from source; this version is not published to PyPI.

```sh
git clone https://github.com/Kydaix/font-design-mcp.git
cd font-design-mcp
uv sync --frozen --python 3.11
uv run --frozen font-design-mcp doctor
uv run --frozen python examples/demo.py --workspace ./workspace
```

`doctor` checks dependencies and rasterizes a PNG; `doctor --build` also compiles TTF and WOFF2. Font operations run locally after installation;
the server needs no model API key or proprietary editor. The client agent may use a remote model.

The demo launches a real STDIO server through the official MCP Python SDK. It draws **A, V, O, Q, acute, and Á**,
sets AV kerning to −80 units, moves A's apex, compares revisions, validates, and builds both export formats.
Each run creates a new project and prints the path to **`specimen.html`**. Open it directly in a browser.

| Demo output | Contents |
|---|---|
| `specimen.html` | Read-only previews and links to the generated fonts; no web server needed |
| `demo-calls.json` | The MCP calls and their structured results |
| `demo-report.json` | Project, revision, source, build, and validation references |
| `revisions/` and `artifacts/` | UFO snapshots, PNGs, TTF/WOFF2, parameters, and hashes |

Generated workspaces stay local and are ignored by Git.

## Miette: a rounded typeface example

**Miette Regular** is an original, soft rounded font with **84 letters**: uppercase and lowercase Latin,
French accents, and æ/œ/Æ/Œ. Basic punctuation and spaces bring the total to 107 encoded characters.
Its drawings, accent components, optical kerning, and complete MCP build recipe are included.

[![Miette, an original rounded typeface created with Font Design MCP](examples/miette/preview.png)](examples/miette/README.md)

[Download TTF](examples/miette/Miette-Regular.ttf) · [Download WOFF2](examples/miette/Miette-Regular.woff2) · [Specimen and reproduction](examples/miette/README.md)

Open `examples/miette/specimen.html` locally to type your own text, adjust its size, and compare kerning.
This first Regular style focuses on French letters; digits and additional styles are not included.

## Connect a client

The MCP client launches the server process. Set an **absolute interpreter path** and an **absolute workspace
path** in the client's configuration:

```json
{
  "mcpServers": {
    "font-design": {
      "command": "/absolute/path/font-design-mcp/.venv/bin/python",
      "args": ["-m", "font_design_mcp", "serve", "--workspace", "/absolute/path/font-workspace"]
    }
  }
}
```

On Windows, use `C:/path/font-design-mcp/.venv/Scripts/python.exe` for `command` and a Windows absolute path
for the workspace. The user sets this directory at launch; a tool call cannot expand it.

<details>
<summary>Codex CLI configuration</summary>

Add a block like this to your Codex configuration, adapting both paths:

```toml
[mcp_servers.font_design]
command = "/absolute/path/font-design-mcp/.venv/bin/python"
args = ["-m", "font_design_mcp", "serve", "--workspace", "/absolute/path/font-workspace"]
startup_timeout_sec = 20
tool_timeout_sec = 180
```

The format follows the [official Codex MCP documentation](https://developers.openai.com/codex/mcp/).
The [Windows example](examples/codex.toml) needs its installation-specific paths adjusted.
The SDK client is tested end to end. Miette also exercised a live Codex MCP connection on Windows,
including project creation, inspection, image previews, and font exports.

</details>

<details>
<summary>Run the server directly</summary>

Windows / PowerShell:

```powershell
.\.venv\Scripts\font-design-mcp.exe serve --workspace "$PWD\workspace"
```

macOS / Linux:

```sh
.venv/bin/font-design-mcp serve --workspace "$PWD/workspace"
```

The process waits for MCP messages on stdin. Stdout is reserved for JSON-RPC, so there is no startup banner.
Logs go to stderr or captured compiler logs. Using the installed executable avoids dependency resolution
at server startup. Normally, let the client start the process itself.

</details>

**Image visibility depends on the client.** Render tools return actual MCP image blocks, plus persistent
paths, dimensions, hashes, and revisions. The client must forward those images to a model that can use them.

## Design a font

The client agent makes the creative decisions; the server applies validated operations and keeps a revision history.

| Step | What you can do |
| --- | --- |
| **Draw** | Start with a brief and a few structural glyphs. Create lines, cubic and quadratic curves, counters, components, and anchors. |
| **Preview and refine** | Inspect PNG previews with guides and handles. Move points by stable ID and compare revisions at the same sizes. |
| **Space and kern** | Stabilize proportions, set side bearings, then adjust kerning. Test words with kerning on and off before extending the alphabet. |
| **Validate and export** | Check geometry, coverage, and compilation. Build TTF and WOFF2 from a frozen revision. |

Record hypotheses and observed corrections in the project's decision journal.

<details>
<summary>Example: move a point and compare revisions</summary>

Every call names its project. Source edits require `expected_revision`; stale requests fail instead of
overwriting another edit. Points and handles have stable IDs, so a correction can be as small as:

```json
{
  "op": "move_point",
  "point_id": "Aouter_1",
  "x": 340,
  "y": 720
}
```

Pass this operation in `glyph_edit.operations` with the project ID, glyph ID, and current expected revision.
A successful edit returns the new revision and changed IDs. `compare_revision` on either render tool shows
two revisions under the same viewing conditions.

</details>

Technical validation and the agent's judgement are distinct from human approval. The server does not assign
an artistic score or accept an agent-supplied claim of authenticated human approval.

## Available tools

The official MCP SDK publishes input and output schemas through `tools/list`. Responses include structured
data, readable summaries, revisions, warnings, and identifiable errors.

| Tool | Purpose |
|---|---|
| `project_create` | Create a project with metadata, metrics, and an optional brief |
| `project_open` | Reopen a server-created project and verify its integrity |
| `project_inspect` | Read metadata, metrics, kerning, and a paginated glyph inventory |
| `project_update` | Update the brief, supported metadata, vertical metrics, or decision journal |
| `glyph_get` | Inspect contours, IDs, components, anchors, advance, bounds, and bearings |
| `glyph_edit` | Apply a typed, atomic vector-editing batch to a glyph |
| `font_edit` | Edit up to 128 glyphs and their spacing atomically in one revision |
| `spacing_edit` | Set advances, side bearings, kerning pairs, and kerning groups |
| `render_glyph` | Render a glyph with optional guides, handles, and revision comparison |
| `render_text` | Compile, shape, and render text at multiple sizes |
| `font_validate` | Check geometry, Unicode coverage, compilation, and OpenType tables |
| `font_build` | Export TTF and/or WOFF2 from a frozen revision |
| `history_list` | Browse committed revisions and change summaries |
| `history_restore` | Restore an earlier state by creating a new revision |

[Exact JSON schemas](docs/tool-schemas.json) · [Detailed tool reference, in French](docs/TOOLS.md)

In 0.2.0, inspection, glyph reads/edits, batch edits, validation, and renders default to
`detail="summary"`. Use `detail="full"` for complete data, including point IDs before editing them;
`render_text` also accepts `detail="positions"`. Rendered images remain inline by default;
`image_mode="resource"` returns references for retrieval through MCP resources.

## Save and restore your work

UFO 3 is the authoritative typography source. Fonts and images are derived artifacts tied to a revision:

```text
workspace/<project_id>/
├── HEAD.json
├── revisions/<revision>/
│   ├── source.ufo/
│   └── manifest.json
└── artifacts/<artifact_id>/
    ├── font.ttf / font.woff2 / image.png
    └── artifact.json
```

Edits validate the whole project, write a complete new UFO snapshot, then atomically update the revision
pointer under an OS lock. Invalid batches leave the committed state intact. Hashes detect external changes;
restoration preserves existing history. Back up the entire project directory, preferably with the server stopped.

Use a private local workspace and edit snapshots through the tools. The server checks paths and UFO
references, rejects symlinks/junctions and unsafe XML, and exposes no arbitrary code, shell, download, or
package-installation tool. Inputs, images, geometry, compiler time, and logs are bounded. These checks are
not an OS sandbox against a hostile process with the same user privileges, and snapshots are not a substitute
for an external backup. Disk usage has no automatic global quota or history purge.

Coordinates use font units, baseline `y=0`, with Y pointing up. Advance, visible width, and side bearings are
different measurements. UPM is fixed at creation. Closed contours use non-zero filling; counters need the
opposite winding. See the [architecture and recovery notes, in French](docs/ARCHITECTURE.md) for details.

## Supported formats and limits

**Current scope:** static fonts with one master, freeform closed contours, components, anchors, and kerning.
Text is shaped with HarfBuzz from a compiled TTF and rasterized with FreeType/Pillow, without system-font fallback.

**Not supported in this version:** OTF, variable fonts, multiple masters, arbitrary UFO/SVG import, image
tracing, editor adapters, collaborative networking, and a full graphical editor. No hinting or arbitrary
OpenType feature code is exposed. Text previews are single-line specimens, not paragraph layout.

Precomposed **Á built from components is tested**. General combining-mark positioning (`mark`/`mkmk`) and
complex-script coverage are not advertised. Source previews can differ slightly from compiled contours
after curve conversion, and unhinted FreeType output need not match native OS rendering.

## Build from source

After completing [Get started](#get-started), build the source archive and wheel:

```sh
uv build
```

Output: `dist/`. Dependency versions are pinned in `pyproject.toml` and `uv.lock`;
`requirements.lock` provides hashed dependencies for pip installations. Install them with
`pip install --require-hashes -r requirements.lock`, then install the built wheel with `pip install --no-deps /path/to/package.whl`.

### Checks

```sh
uv run --frozen pytest -q
uv run --frozen ruff check src tests scripts examples
uv run --frozen python tests/test_acceptance.py
```

The standalone acceptance client retains its captures and JSON-RPC transcript under `test-output/acceptance-*`.
It checks actual compiled kerning, edit isolation, revision conflicts, failed atomic batches, unsafe paths,
compiler failure, restart, and interrupted writes.

| Verification | Evidence |
| --- | --- |
| **Windows 11 x64, Python 3.11** | 36 local tests passed, including real STDIO calls, atomic multi-glyph edits, compilation caching, rendering, and recovery |
| **Windows, macOS, Linux runners** | [CI results](https://github.com/Kydaix/font-design-mcp/actions/workflows/ci.yml), covering Python 3.11 and 3.13 |
| **Installed wheel** | Entry point and full MCP demo tested in a separate environment |
| **MCPB extension** | Installed outside the repository; diagnostic, STDIO calls, and TTF/WOFF2 exports tested |

The CI result covers its runner environments, not every OS version or CPU architecture. The
[original delivery report, in French](docs/TESTING.md) records the local tests before CI was first run.

## Documentation

English is the default README language; a [French README](README.fr.md) is also maintained. The detailed
guides currently remain in French, except the dependency inventory and machine-readable schemas.

| Reference | Contents |
|---|---|
| [Tool reference](docs/TOOLS.md) | Input conventions, vector operations, spacing, results, and error codes |
| [JSON schemas](docs/tool-schemas.json) | Schemas exported from a live `tools/list` call |
| [Architecture](docs/ARCHITECTURE.md) | Domain, persistence, rendering, compilation, limits, and recovery |
| [Test report](docs/TESTING.md) | Original acceptance evidence, captures, and remaining visual review |
| [Dependency licenses](docs/DEPENDENCIES.md) | Locked dependencies and native-library notices |
| [Technical audit](docs/audit.md) | Performance, output size and installation findings |
| [Audit implementation](docs/AUDIT-IMPLEMENTATION.md) | Changes, measurements and remaining publication/host checks |

## Credits and license

Built with the official MCP Python SDK, UFO sources, HarfBuzz, and FreeType/Pillow.
See [dependency licenses](docs/DEPENDENCIES.md) for third-party notices.

The server code and original examples are [MIT licensed](LICENSE). **This does not automatically license
fonts you create with the server.** Font license metadata is empty by default and remains under the creator's
control. No third-party font outlines or font files are included.
