"""Controlled fontmake process and real TTF/WOFF2 artifacts."""

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from importlib.metadata import distributions, version

from filelock import FileLock, Timeout
from fontTools.ttLib import TTFont

from .binary_metadata import complete_variable_metadata
from .domain import FontError, require
from .layout import compiler_font, validate_latin_marks
from .storage import digest_tree, files_checked, read_json, safe_path, write_json
from .telemetry import count, phase
from .variable import validate_variable_binary, write_designspace

CACHE_POLICY = "fontmake-ttf-variable-languagesystems-latin-marks-stat-v5"
CACHE_LIMIT = 128_000_000


def check_cancelled():
    from anyio import from_thread

    try:
        from_thread.check_cancelled()
    except RuntimeError:
        pass  # Direct synchronous callers do not have an AnyIO cancellation scope.


@contextmanager
def build_lock(lock, timeout=150):
    started = time.monotonic()
    while True:
        check_cancelled()
        try:
            lock.acquire(timeout=0)
            break
        except Timeout:
            if time.monotonic() - started >= timeout:
                raise
            time.sleep(0.05)
    count("build_lock_wait_us", round((time.monotonic() - started) * 1_000_000))
    try:
        yield
    finally:
        lock.release()


def remove_cache_folder(store, folder):
    folder = safe_path(store.root, folder)
    require(folder.parent.name == "cache", "path_denied", "Only cache entries may be removed")
    list(files_checked(store.root, folder))
    shutil.rmtree(folder)


@phase("build")
def compile_font(store, project_id, font, manifest, source, formats, retain=False):
    """Serialize cache access across processes; return private bytes before releasing the lock."""
    identity = {
        "source": manifest["source_sha256"],
        "variation": manifest.get("variation"),
        "masters": manifest.get("master_sha256"),
        "revision": manifest["revision"],
        "created_at": manifest["created_at"],
        "policy": CACHE_POLICY,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "versions": {d.metadata["Name"]: d.version for d in distributions()},
    }
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    cache = safe_path(store.root, store.project(project_id) / "cache")
    cache.mkdir(exist_ok=True)
    try:
        # ponytail: one cache lock per project; split by key if distinct builds contend.
        with build_lock(FileLock(safe_path(store.root, cache / ".lock"))):
            store.verify(project_id, manifest["revision"])
            check_cancelled()
            entry = safe_path(store.root, cache / key)
            hit = False
            if entry.exists():
                try:
                    data = read_json(store.root, entry / "artifact.json")
                    require(data["build_key"] == key, "build_failed", "Wrong cache identity")
                    for fmt in ("ttf", "woff2"):
                        path = safe_path(store.root, entry / f"font.{fmt}")
                        require(path.stat().st_size <= 16_000_000, "build_failed", "Oversized cached font")
                        require(
                            hashlib.sha256(path.read_bytes()).hexdigest() == data["files"][fmt]["sha256"],
                            "build_failed",
                            "Corrupt cached font",
                        )
                        with TTFont(path, lazy=False) as binary:
                            validate_variable_binary(binary, manifest.get("variation"))
                            validate_latin_marks(binary, font)
                            require(
                                binary.getBestCmap() == {u: g.name for g in font for u in g.unicodes},
                                "build_failed",
                                "Cached Unicode mismatch",
                            )
                    hit = True
                except Exception:
                    remove_cache_folder(store, entry)
            if not hit:
                for abandoned in cache.glob(".stage-*"):
                    remove_cache_folder(store, abandoned)
                entries = sorted((p for p in cache.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
                sizes = [(p, sum(f.stat().st_size for f in files_checked(store.root, p))) for p in entries]
                total = sum(size for _, size in sizes)
                for p, size in sizes:
                    if total <= CACHE_LIMIT - 32_000_000:
                        break
                    remove_cache_folder(store, p)
                    total -= size
                data, _ = _compile_font(
                    store, project_id, font, manifest, source, ["ttf", "woff2"], cache, key
                )
            store.verify(project_id, manifest["revision"])
            binary_bytes = safe_path(store.root, entry / "font.ttf").read_bytes()
            count("cache_hits" if hit else "cache_misses")
            data = {
                **data,
                "cache_hit": hit,
                "formats": list(dict.fromkeys(formats)),
                "files": {fmt: data["files"][fmt] for fmt in dict.fromkeys(formats)},
            }
            if retain:
                artifacts = safe_path(store.root, store.project(project_id) / "artifacts")
                artifacts.mkdir(exist_ok=True)
                identifier = uuid.uuid4().hex
                stage = safe_path(store.root, artifacts / (".stage-" + identifier))
                stage.mkdir()
                data["artifact_id"] = identifier
                for fmt, info in data["files"].items():
                    shutil.copyfile(safe_path(store.root, entry / f"font.{fmt}"), stage / f"font.{fmt}")
                    info["path"] = f"{project_id}/artifacts/{identifier}/font.{fmt}"
                write_json(stage / "artifact.json", data)
                os.replace(stage, safe_path(store.root, artifacts / identifier))
            return data, binary_bytes
    except Timeout as exc:
        raise FontError("project_busy", "Build cache busy; retry later") from exc


@phase("compiler")
def run_compiler(command, cwd, timeout=60, epoch=None):
    log = cwd / "compiler.log"
    with log.open("xb") as output:
        count("compiler_launches")
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
                check_cancelled()
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


def _compile_font(store, project_id, font, manifest, source, formats, artifacts, build_key):
    artifacts.mkdir(exist_ok=True)
    artifact_id = uuid.uuid4().hex
    stage = safe_path(store.root, artifacts / (".stage-" + artifact_id))
    stage.mkdir()
    # A private compiler input guarantees no compiler can mutate authoritative sources.
    configuration = manifest.get("variation")
    if configuration:
        fonts = store.load_masters(project_id, manifest, font)
        input_path = write_designspace(stage, configuration, fonts)
    else:
        input_path = stage / "input.ufo"
        compiler_font(font).save(input_path, formatVersion=3)
    command = [
        sys.executable,
        "-m",
        "fontmake",
        "-m" if configuration else "-u",
        str(input_path),
        "-o",
        "variable" if configuration else "ttf",
        "--output-path",
        str(stage / "font.ttf"),
        "--no-autohint",
        "--keep-overlaps",
        "--no-production-names",
        "--validate-ufo",
        "--verbose",
        "WARNING",
    ]
    # One compiler across processes in this workspace; reads and edits use separate locks.
    with build_lock(FileLock(safe_path(store.root, store.root / ".compiler.lock"))):
        run_compiler(command, stage, epoch=int(datetime.fromisoformat(manifest["created_at"]).timestamp()))
    ttf = stage / "font.ttf"
    require(ttf.is_file() and 0 < ttf.stat().st_size <= 16_000_000, "build_failed", "Invalid compiler output")
    with TTFont(ttf, lazy=False, recalcTimestamp=False) as binary:
        complete_variable_metadata(binary, configuration)
        if configuration:
            binary.save(ttf)
        validate_variable_binary(binary, configuration)
        layout_report = validate_latin_marks(binary, font)
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
            validate_variable_binary(webfont, configuration)
            validate_latin_marks(webfont, font)
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
    store.verify(project_id, manifest["revision"])
    data = {
        "build_key": build_key,
        "artifact_id": artifact_id,
        "revision": manifest["revision"],
        "formats": list(dict.fromkeys(formats)),
        "tables": tables,
        "engine": f"fontmake + fontTools; unhinted {'variable' if configuration else 'static'} TrueType",
        "layout": layout_report,
        "variable": bool(configuration),
        "variation": configuration,
        "versions": {name: version(name) for name in ("fontmake", "fonttools", "ufoLib2", "ufo2ft")},
        "files": {
            fmt: {
                "path": f"{project_id}/cache/{build_key}/font.{fmt}",
                "sha256": hashlib.sha256((stage / f"font.{fmt}").read_bytes()).hexdigest(),
                "bytes": (stage / f"font.{fmt}").stat().st_size,
            }
            for fmt in set(formats)
        },
    }
    write_json(stage / "artifact.json", data)
    # Keep private input and compiler log for reproducibility; bounded by snapshot limits.
    list(files_checked(store.root, stage))
    final = safe_path(store.root, artifacts / build_key)
    os.replace(stage, final)
    return data, final / "font.ttf"
