"""Controlled fontmake process and real TTF/WOFF2 artifacts."""

import hashlib
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime
from importlib.metadata import version

from fontTools.ttLib import TTFont

from .domain import FontError, require
from .storage import digest_tree, files_checked, safe_path, write_json


def run_compiler(command, cwd, timeout=60, epoch=None):
    log = cwd / "compiler.log"
    with log.open("xb") as output:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=output,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            shell=False,
            env={**os.environ, "SOURCE_DATE_EPOCH": str(epoch or 0), "PYTHONHASHSEED": "0"},
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if time.monotonic() > deadline or log.stat().st_size > 1_000_000:
                    raise FontError("build_timeout", "Compiler exceeded 60 seconds or 1 MB of logs")
                time.sleep(0.05)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
    size = log.stat().st_size
    require(size <= 1_000_000, "build_timeout", "Compiler log exceeded 1 MB")
    with log.open("rb") as stream:
        stream.seek(max(0, size - 6000))
        tail = stream.read().decode("utf-8", errors="replace")
    require(process.returncode == 0, "build_failed", tail)


def compile_font(store, project_id, font, manifest, source, formats):
    project = store.project(project_id)
    artifacts = safe_path(store.root, project / "artifacts")
    artifacts.mkdir(exist_ok=True)
    artifact_id = uuid.uuid4().hex
    stage = safe_path(store.root, artifacts / (".stage-" + artifact_id))
    stage.mkdir()
    # A private compiler input guarantees no compiler can mutate authoritative sources.
    font.save(stage / "input.ufo", formatVersion=3)
    command = [
        sys.executable,
        "-m",
        "fontmake",
        "-u",
        str(stage / "input.ufo"),
        "-o",
        "ttf",
        "--output-path",
        str(stage / "font.ttf"),
        "--no-autohint",
        "--keep-overlaps",
        "--no-production-names",
        "--validate-ufo",
        "--verbose",
        "WARNING",
    ]
    run_compiler(command, stage, epoch=int(datetime.fromisoformat(manifest["created_at"]).timestamp()))
    ttf = stage / "font.ttf"
    require(ttf.is_file() and 0 < ttf.stat().st_size <= 16_000_000, "build_failed", "Invalid compiler output")
    with TTFont(ttf, lazy=False, recalcTimestamp=False) as binary:
        required = {"head", "hhea", "maxp", "OS/2", "hmtx", "cmap", "name", "post", "glyf", "loca"}
        require(required.issubset(binary.keys()), "build_failed", "Missing required OpenType tables")
        require(binary.getGlyphOrder()[0] == ".notdef", "build_failed", "Glyph 0 must be .notdef")
        require(binary["head"].unitsPerEm == font.info.unitsPerEm, "build_failed", "UPM mismatch")
        require(
            binary.getBestCmap() == {u: g.name for g in font for u in g.unicodes},
            "build_failed",
            "Compiled Unicode mapping differs from source",
        )
        require(not font.kerning or "GPOS" in binary, "build_failed", "Kerning did not produce GPOS")
        tables = sorted(binary.keys())
        if "woff2" in formats:
            binary.flavor = "woff2"
            binary.save(stage / "font.woff2")
    if "woff2" in formats:
        with TTFont(stage / "font.woff2") as webfont:
            require(
                webfont.getBestCmap() == {u: g.name for g in font for u in g.unicodes},
                "build_failed",
                "WOFF2 roundtrip failed",
            )
    require(
        digest_tree(store.root, source) == manifest["source_sha256"],
        "external_modification",
        "Sources changed during compilation",
    )
    data = {
        "artifact_id": artifact_id,
        "revision": manifest["revision"],
        "formats": list(dict.fromkeys(formats)),
        "tables": tables,
        "engine": "fontmake + fontTools; unhinted static TrueType",
        "versions": {name: version(name) for name in ("fontmake", "fonttools", "ufoLib2", "ufo2ft")},
        "files": {
            fmt: {
                "path": f"{project_id}/artifacts/{artifact_id}/font.{fmt}",
                "sha256": hashlib.sha256((stage / f"font.{fmt}").read_bytes()).hexdigest(),
                "bytes": (stage / f"font.{fmt}").stat().st_size,
            }
            for fmt in set(formats)
        },
    }
    write_json(stage / "artifact.json", data)
    # Keep private input and compiler log for reproducibility; bounded by snapshot limits.
    list(files_checked(store.root, stage))
    final = safe_path(store.root, artifacts / artifact_id)
    os.replace(stage, final)
    return data, final / "font.ttf"
