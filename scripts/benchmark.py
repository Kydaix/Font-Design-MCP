"""Reproducible work/latency/JSON-byte measurements; no model-token or billing estimates."""

import argparse
import asyncio
import hashlib
import json
import math
import statistics
import sys
import tempfile
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

from font_design_mcp import __version__
from font_design_mcp import models as m
from font_design_mcp.service import Service
from font_design_mcp.telemetry import measurement

root = Path(__file__).parents[1]
sys.path[:0] = [str(root / "examples"), str(root / "examples" / "miette")]


async def startup_samples(repeats):
    from mcp import Client, StdioServerParameters

    samples = []
    with tempfile.TemporaryDirectory(prefix="font-startup-") as folder:
        for index in range(repeats):
            started = time.perf_counter()
            parameters = StdioServerParameters(
                command=sys.executable, args=["-m", "font_design_mcp", "serve", "--workspace", folder]
            )
            async with Client(parameters, mode="2026-07-28") as client:
                catalogue = await client.list_tools()
                samples.append(
                    {
                        "case": "first_process" if index == 0 else "repeat_process",
                        "seconds_to_catalogue": time.perf_counter() - started,
                        "catalogue_json_bytes": len(
                            catalogue.model_dump_json(by_alias=True, exclude_none=True).encode()
                        ),
                    }
                )
    return samples


def drawings(profile):
    if profile == "small":
        from fixture import fixture

        return fixture(), m.Metrics()
    if profile == "miette":
        from drawings import METRICS, glyphs

        return glyphs(), m.Metrics(**METRICS)
    points = [
        {
            "id": f"p{i}",
            "x": round(250 + 200 * math.cos(i * math.tau / 96), 3),
            "y": round(350 + 300 * math.sin(i * math.tau / 96), 3),
        }
        for i in range(96)
    ]
    return {
        f"g{i}": {"advance": 500, "unicodes": [0xE000 + i], "contours": [{"id": "c", "points": points}]}
        for i in range(500)
    }, m.Metrics()


def benchmark(profile, repeats):
    samples = []
    with tempfile.TemporaryDirectory(prefix="font-bench-") as folder:
        service = Service(folder)
        glyphs, metrics = drawings(profile)
        state, _ = service.execute(
            "project_create", m.ProjectCreate(metadata=m.Metadata(family="Benchmark"), metrics=metrics)
        )
        pid, revision = state.project_id, state.revision
        changes = [
            {
                "glyph_id": name,
                "create": name != "space",
                "operations": [{"op": "replace_glyph", "glyph": glyph}],
            }
            for name, glyph in glyphs.items()
        ]
        for offset in range(0, len(changes), 128):
            state, _ = service.execute(
                "font_edit",
                m.FontEdit(project_id=pid, expected_revision=revision, glyphs=changes[offset : offset + 128]),
            )
            revision = state.revision
        outline_names = [name for name, glyph in glyphs.items() if glyph.get("contours")]
        text = "".join(chr(g["unicodes"][0]) for g in glyphs.values() if g.get("unicodes"))[:24]

        def run(case, tool, request):
            with measurement() as stats:
                started = time.perf_counter()
                result, images = service.execute(tool, request)
                seconds = time.perf_counter() - started
            samples.append(
                {
                    "case": case,
                    "seconds": seconds,
                    "json_bytes": len(result.model_dump_json().encode()),
                    "image_bytes": sum(map(len, images)),
                    **stats,
                }
            )
            return result

        tracemalloc.start()
        for _ in range(repeats):
            name = outline_names[0]
            point = glyphs[name]["contours"][0]["points"][0]
            before = revision
            result = run(
                "move_point",
                "glyph_edit",
                m.GlyphEdit(
                    project_id=pid,
                    expected_revision=revision,
                    glyph_id=name,
                    operations=[
                        {"op": "move_point", "point_id": point["id"], "x": point["x"], "y": point["y"]}
                    ],
                ),
            )
            revision = result.revision
            batch = [
                {
                    "glyph_id": name,
                    "operations": [
                        {
                            "op": "move_point",
                            "point_id": glyphs[name]["contours"][0]["points"][0]["id"],
                            "x": glyphs[name]["contours"][0]["points"][0]["x"],
                            "y": glyphs[name]["contours"][0]["points"][0]["y"],
                        }
                    ],
                }
                for name in outline_names[:20]
            ]
            result = run(
                "batch_edit",
                "font_edit",
                m.FontEdit(project_id=pid, expected_revision=revision, glyphs=batch),
            )
            revision = result.revision
            run(
                "compare_glyph",
                "render_glyph",
                m.RenderGlyph(
                    project_id=pid, revision=revision, compare_revision=before, glyph_id=outline_names[0]
                ),
            )
            run("render_cold", "render_text", m.RenderText(project_id=pid, revision=revision, text=text))
            run("render_warm", "render_text", m.RenderText(project_id=pid, revision=revision, text=text))
            run("validate_warm", "font_validate", m.Validate(project_id=pid, revision=revision, corpus=text))
            run("export_warm", "font_build", m.Build(project_id=pid, revision=revision))
            run("history_page", "history_list", m.Page(project_id=pid, limit=2))
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        grouped = {}
        for case in dict.fromkeys(s["case"] for s in samples):
            selected = [s for s in samples if s["case"] == case]
            times = sorted(s["seconds"] for s in selected)
            grouped[case] = {
                "median_seconds": statistics.median(times),
                "p95_seconds": times[math.ceil(0.95 * len(times)) - 1],
                "median_json_bytes": statistics.median(s["json_bytes"] for s in selected),
                "compiler_launches": sum(s["counters"].get("compiler_launches", 0) for s in selected),
            }
        assert grouped["render_cold"]["compiler_launches"] == repeats
        assert all(
            grouped[c]["compiler_launches"] == 0 for c in ("render_warm", "validate_warm", "export_warm")
        )
        assert all(
            s["phases"]["load"]["calls"] == 1 for s in samples if s["case"] in {"move_point", "batch_edit"}
        )
        return {
            "glyphs": len(glyphs) + 2 - ("space" in glyphs),
            "python_peak_bytes": peak,
            "summary": grouped,
            "samples": samples,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--profiles", nargs="+", choices=["small", "miette", "large"], default=["small", "miette", "large"]
    )
    parser.add_argument("--output", type=Path, default=root / "test-output" / "audit-benchmark.json")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    report = {
        "version": __version__,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": hashlib.sha256(
            b"".join(
                p.name.encode() + b"\0" + p.read_bytes()
                for p in sorted((root / "src" / "font_design_mcp").glob("*.py"))
            )
        ).hexdigest(),
        "python": sys.version,
        "repeats": args.repeats,
        "notes": "Cold means unseen build key; warm means verified cache hit. Timings include tracemalloc overhead. "
        "Memory is Python allocations only, not native libraries or compiler RSS. Phases overlap. "
        "I/O counters cover controlled source hashing and snapshot writes, not all library/OS I/O. "
        "p95 is nearest-rank; JSON UTF-8 bytes are not model tokens.",
        "startup": asyncio.run(startup_samples(args.repeats)),
        "profiles": {},
    }
    for profile in args.profiles:
        report["profiles"][profile] = benchmark(profile, args.repeats)
        print(json.dumps({"profile": profile, "summary": report["profiles"][profile]["summary"]}), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), "utf-8")
