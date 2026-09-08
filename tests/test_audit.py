"""Audit acceptance: measured work, atomic batches, cache integrity and compact MCP output."""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from pydantic import ValidationError
from test_acceptance import client

from font_design_mcp import build as compiler
from font_design_mcp import models as m
from font_design_mcp.__main__ import doctor, workspace_path
from font_design_mcp.domain import FontError
from font_design_mcp.service import Service
from font_design_mcp.telemetry import measurement


def project(tmp_path):
    service = Service(tmp_path)
    state, _ = service.execute("project_create", m.ProjectCreate(metadata=m.Metadata(family="Audit")))
    return service, state.project_id, state.revision


def rectangle(name="A"):
    return {
        "glyph_id": name,
        "create": True,
        "operations": [
            {
                "op": "primitive",
                "shape": "rectangle",
                "x": 40,
                "y": 0,
                "width": 300,
                "height": 700,
                "advance": 400,
            },
        ],
    }


def test_batch_loads_once_forward_components_and_rollback(tmp_path):
    service, pid, revision = project(tmp_path)
    args = dict(project_id=pid, expected_revision=revision)
    with measurement() as stats:
        result, _ = service.execute(
            "font_edit",
            m.FontEdit(
                **args,
                glyphs=[
                    {
                        "glyph_id": "B",
                        "create": True,
                        "operations": [{"op": "put_component", "component": {"id": "base", "base": "A"}}],
                    },
                    rectangle(),
                ],
                spacing=[{"op": "advance", "glyph_id": "B", "value": 420}],
            ),
        )
    assert stats["phases"]["load"]["calls"] == 1
    assert stats["phases"]["validate"]["calls"] == 2  # loaded state + final state
    assert stats["phases"]["commit"]["calls"] == 1
    assert result.data == {"operation_count": 3}
    font, _, _ = service.store.load(pid)
    assert font["B"].getBounds(font) == font["A"].getBounds(font)
    with pytest.raises(FontError):
        service.execute(
            "font_edit",
            m.FontEdit(
                project_id=pid,
                expected_revision=result.revision,
                glyphs=[
                    rectangle("C"),
                    {
                        "glyph_id": "A",
                        "operations": [{"op": "put_component", "component": {"id": "cycle", "base": "B"}}],
                    },
                ],
            ),
        )
    font, manifest, _ = service.store.load(pid)
    assert manifest["revision"] == result.revision and "C" not in font
    with pytest.raises(FontError, match="Expected"):
        service.execute("font_edit", m.FontEdit(**args, glyphs=[rectangle("D")]))
    with pytest.raises(ValidationError):
        m.FontEdit(**args, glyphs=[rectangle(), rectangle()])


@pytest.mark.parametrize("format", ["ttf", "woff2"])
def test_compilation_shared_corruption_rebuild_and_source_check(tmp_path, monkeypatch, format):
    service, pid, revision = project(tmp_path)
    with measurement() as stats:
        service.execute("render_text", m.RenderText(project_id=pid, text=" "))
        service.execute("font_validate", m.Validate(project_id=pid))
        result, _ = service.execute("font_build", m.Build(project_id=pid))
    assert stats["counters"]["compiler_launches"] == 1
    assert stats["counters"]["cache_hits"] == 2
    assert result.data["cache_hit"]
    exported = tmp_path / result.data["files"]["ttf"]["path"]
    original = exported.read_bytes()
    entry = tmp_path / pid / "cache" / result.data["build_key"]
    (entry / f"font.{format}").write_bytes(b"corrupt")
    with measurement() as stats:
        rebuilt, _ = service.execute("font_build", m.Build(project_id=pid))
    assert stats["counters"]["compiler_launches"] == 1
    assert not rebuilt.data["cache_hit"] and exported.read_bytes() == original
    monkeypatch.setattr(compiler, "CACHE_POLICY", "new-policy")
    with measurement() as stats:
        changed, _ = service.execute("font_build", m.Build(project_id=pid))
    assert stats["counters"]["compiler_launches"] == 1
    assert changed.data["build_key"] != result.data["build_key"]
    _, _, ufo = service.store.load(pid)
    with (ufo / "fontinfo.plist").open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(FontError) as error:
        service.execute("font_build", m.Build(project_id=pid))
    assert error.value.code == "external_modification"


def test_same_key_concurrent_and_mutation_during_build(tmp_path, monkeypatch):
    service, pid, revision = project(tmp_path)
    started, proceed = Event(), Event()
    calls = []
    original = compiler.run_compiler

    def paused(*args, **kwargs):
        calls.append(True)
        started.set()
        assert proceed.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(compiler, "run_compiler", paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.execute, "font_build", m.Build(project_id=pid, revision=revision))
        assert started.wait(10)
        second = pool.submit(service.execute, "font_build", m.Build(project_id=pid, revision=revision))
        try:
            changed, _ = service.execute(
                "project_update",
                m.ProjectUpdate(project_id=pid, expected_revision=revision, brief="while compiler runs"),
            )
            assert changed.revision != revision
        finally:
            proceed.set()
        results = [first.result(timeout=30)[0], second.result(timeout=30)[0]]
    assert len(calls) == 1
    assert all(r.revision == revision for r in results)
    assert sorted(r.data["cache_hit"] for r in results) == [False, True]


def test_failed_build_not_cached_and_quota_preserves_export(tmp_path, monkeypatch):
    service, pid, revision = project(tmp_path)
    original = compiler.run_compiler

    def fail(*args, **kwargs):
        raise FontError("build_failed", "injected")

    monkeypatch.setattr(compiler, "run_compiler", fail)
    with pytest.raises(FontError):
        service.execute("font_build", m.Build(project_id=pid))
    assert all(p.name.startswith(".") for p in (tmp_path / pid / "cache").iterdir())
    monkeypatch.setattr(compiler, "run_compiler", original)
    built, _ = service.execute("font_build", m.Build(project_id=pid))
    export = tmp_path / built.data["files"]["ttf"]["path"]
    monkeypatch.setattr(compiler, "CACHE_LIMIT", 32_000_000)
    service.execute(
        "project_update", m.ProjectUpdate(project_id=pid, expected_revision=revision, brief="new")
    )
    newer, _ = service.execute("font_build", m.Build(project_id=pid))
    assert newer.data["build_key"] != built.data["build_key"]
    assert not (tmp_path / pid / "cache" / built.data["build_key"]).exists()
    assert export.is_file()


def test_history_pagination_does_not_load_or_scan_tail(tmp_path, monkeypatch):
    service, pid, revision = project(tmp_path)
    for i in range(5):
        state, _ = service.execute(
            "project_update", m.ProjectUpdate(project_id=pid, expected_revision=revision, brief=str(i))
        )
        revision = state.revision
    original = service.store.history
    read = []

    def history(project_id):
        for item in original(project_id):
            read.append(item)
            yield item

    monkeypatch.setattr(service.store, "history", history)
    with measurement() as stats:
        page, _ = service.execute("history_list", m.Page(project_id=pid, limit=2))
    assert len(read) == 3 and "load" not in stats["phases"]
    assert "total" not in page.data and page.data["next_offset"] == 2
    total, _ = service.execute("history_list", m.Page(project_id=pid, include_total=True))
    assert total.data["total"] == 6


def test_numeric_paths_primitives_duplicate_and_anchors(tmp_path):
    service, pid, revision = project(tmp_path)
    base = rectangle()
    base["operations"].append(
        {"op": "put_anchor", "anchor": {"id": "top", "name": "top", "x": 200, "y": 700}}
    )
    state, _ = service.execute(
        "font_edit",
        m.FontEdit(
            project_id=pid,
            expected_revision=revision,
            detail="full",
            glyphs=[
                base,
                {
                    "glyph_id": "acute",
                    "create": True,
                    "operations": [
                        {"op": "stroke_path", "paths": ["M 0 0 L 100 100"], "width": 50},
                        {"op": "put_anchor", "anchor": {"id": "attach", "name": "_top", "x": 0, "y": 0}},
                    ],
                },
                {
                    "glyph_id": "Aacute",
                    "create": True,
                    "operations": [
                        {"op": "compose_accent", "base": "A", "mark": "acute"},
                        {"op": "set_unicodes", "unicodes": [193]},
                    ],
                },
                {
                    "glyph_id": "B",
                    "create": True,
                    "operations": [
                        {"op": "duplicate", "source": "A", "matrix": [1, 0, 0, 1, 40, 0]},
                    ],
                },
            ],
        ),
    )
    font, _, _ = service.store.load(pid)
    assert font["Aacute"].components[1].transformation.dx == 200
    assert font["Aacute"].unicodes == [193]
    assert font["B"].getBounds(font)[0] == 80
    assert state.data["glyphs"][0]["added_ids"]
    for path in ["<svg/>", "M 0 0 L 1e99 2", "M 0 0 A 20 20 0 0 1 30 40", "M 0 0 L 10", "L 1 1"]:
        with pytest.raises(FontError):
            service.execute(
                "glyph_edit",
                m.GlyphEdit(
                    project_id=pid,
                    expected_revision=state.revision,
                    glyph_id="bad",
                    create=True,
                    operations=[{"op": "stroke_path", "paths": [path], "width": 40}],
                ),
            )
    assert service.store.head(pid)["revision"] == state.revision


def test_compact_defaults_resources_and_legacy_text(tmp_path):
    async def run():
        async with client(tmp_path) as session:
            created = (
                await session.call_tool("project_create", {"metadata": {"family": "Resources"}})
            ).structured_content
            pid = created["project_id"]
            catalog = await session.list_tools()
            assert catalog == await session.list_tools()
            for tool in catalog.tools:
                assert "title" not in tool.input_schema
            response = await session.call_tool(
                "render_text", {"project_id": pid, "text": " ", "image_mode": "resource"}
            )
            data = response.structured_content
            assert json.loads(response.content[0].text) == data
            assert all(c.type != "image" for c in response.content)
            info = data["data"]["images"][0]
            assert "positions" not in info and "build" not in info
            report = await session.read_resource(info["report_uri"])
            full = json.loads(report.contents[0].text)
            assert "positions" in full and "build" in full
            png = await session.read_resource(info["uri"])
            assert png.contents[0].mime_type == "image/png" and png.contents[0].blob
            validation = await session.call_tool("font_validate", {"project_id": pid})
            summary = validation.structured_content["data"]
            assert "observations" not in summary and summary["counts"]["information"] > 0
            image_path = tmp_path / info["path"]
            image_path.write_bytes(b"changed")
            with pytest.raises(Exception):
                await session.read_resource(info["uri"])

    asyncio.run(run())


def test_workspace_priority_and_missing_dependency(tmp_path, monkeypatch):
    monkeypatch.setenv("FONT_DESIGN_MCP_WORKSPACE", str(tmp_path / "env"))
    assert workspace_path() == tmp_path / "env"
    assert workspace_path(tmp_path / "cli") == tmp_path / "cli"
    import importlib

    original = importlib.import_module

    def missing(name):
        if name == "freetype":
            raise ImportError("injected missing native dependency")
        return original(name)

    monkeypatch.setattr(importlib, "import_module", missing)
    report = doctor()
    assert not report["ok"] and report["errors"][0]["dependency"] == "freetype-py"


def test_doctor_build_with_linked_temp_directory(tmp_path, monkeypatch):
    target = tmp_path / "real-temp"
    target.mkdir()
    link = tmp_path / "linked-temp"
    if os.name == "nt":
        command = (
            "New-Item -ItemType Junction -Path '"
            + str(link).replace("'", "''")
            + "' -Target '"
            + str(target).replace("'", "''")
            + "' | Out-Null"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", command], check=True, capture_output=True)
    else:
        link.symlink_to(target, target_is_directory=True)
    try:
        monkeypatch.setattr(tempfile, "tempdir", str(link))
        with pytest.raises(FontError, match="Workspace ancestors"):
            Service(link / "workspace")
        report = doctor(build=True)
        assert report["ok"], report
        assert set(report["build"]) == {"ttf", "woff2"}
        assert not list(target.iterdir())
    finally:
        if os.name == "nt":
            os.rmdir(link)
        else:
            link.unlink()


def test_new_protocol_client(tmp_path):
    from mcp import Client, StdioServerParameters

    async def run():
        parameters = StdioServerParameters(
            command=sys.executable, args=["-m", "font_design_mcp", "serve", "--workspace", str(tmp_path)]
        )
        async with Client(parameters, mode="2026-07-28") as session:
            tools = await session.list_tools()
            assert len(tools.tools) == 14
            result = await session.call_tool("project_create", {"metadata": {"family": "Modern"}})
            assert result.structured_content["ok"]

    asyncio.run(run())


def test_cross_process_build_deduplication(tmp_path):
    async def run():
        async with client(tmp_path) as first, client(tmp_path) as second:
            created = await first.call_tool("project_create", {"metadata": {"family": "Build race"}})
            pid = created.structured_content["project_id"]
            results = await asyncio.gather(
                first.call_tool("font_build", {"project_id": pid}),
                second.call_tool("font_build", {"project_id": pid}),
            )
            assert all(not r.is_error for r in results)
            assert sorted(r.structured_content["data"]["cache_hit"] for r in results) == [False, True]
            assert len({r.structured_content["data"]["build_key"] for r in results}) == 1

    asyncio.run(run())


def test_cancelled_compiler_releases_workspace_lock(tmp_path):
    from filelock import FileLock

    async def run():
        async with client(tmp_path, fault="slowcompiler") as session:
            created = await session.call_tool("project_create", {"metadata": {"family": "Cancel"}})
            pid = created.structured_content["project_id"]
            pending = asyncio.create_task(session.call_tool("font_build", {"project_id": pid}))
            try:
                for _ in range(100):
                    if list((tmp_path / pid / "cache").glob(".stage-*/child.pid")):
                        break
                    await asyncio.sleep(0.05)
                else:
                    pytest.fail("Compiler did not start")
            finally:
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending

            # Compiler lock is released only after the killed subprocess has been reaped.
            def lock_released():
                with FileLock(tmp_path / ".compiler.lock", timeout=3):
                    pass

            await asyncio.to_thread(lock_released)
            assert not any(p.name[0] != "." for p in (tmp_path / pid / "cache").iterdir())
            opened = await session.call_tool("project_open", {"project_id": pid})
            assert opened.structured_content["revision"] == created.structured_content["revision"]

    asyncio.run(run())


def test_component_memo_preserves_depth_limit(tmp_path):
    service, pid, revision = project(tmp_path)
    # Leaf-first insertion forces the shared subtree to be cached before its ancestors.
    glyphs = [rectangle("leaf")]
    for i in range(16):
        glyphs.append(
            {
                "glyph_id": f"g{i}",
                "create": True,
                "operations": [
                    {
                        "op": "put_component",
                        "component": {"id": "base", "base": "leaf" if i == 0 else f"g{i - 1}"},
                    }
                ],
            }
        )
    with pytest.raises(FontError, match="depth"):
        service.execute("font_edit", m.FontEdit(project_id=pid, expected_revision=revision, glyphs=glyphs))
    assert service.store.head(pid)["revision"] == revision


def test_source_change_during_render_is_not_published(tmp_path, monkeypatch):
    from font_design_mcp import service as module

    service, pid, _ = project(tmp_path)
    _, _, source = service.store.load(pid)
    original = module.glyph_view

    def changed(*args, **kwargs):
        image = original(*args, **kwargs)
        with (source / "fontinfo.plist").open("ab") as stream:
            stream.write(b" ")
        return image

    monkeypatch.setattr(module, "glyph_view", changed)
    with pytest.raises(FontError) as error:
        service.execute("render_glyph", m.RenderGlyph(project_id=pid, glyph_id=".notdef"))
    assert error.value.code == "external_modification"
    assert not (tmp_path / pid / "artifacts").exists()


def test_summary_diagnostics_are_bounded_and_full_report_remains(tmp_path):
    service, pid, _ = project(tmp_path)
    result, _ = service.execute(
        "font_validate", m.Validate(project_id=pid, corpus="abcdefghijklmnopqrstuvwxyz")
    )
    assert len(result.warnings) == 10 and result.data["truncated"]
    assert len(result.data["missing_codepoints"]) == 10
    report, _ = service.store.read_resource(result.data["report_uri"])
    assert len(json.loads(report)["missing_codepoints"]) == 26
    assert len(json.loads(report)["warnings"]) == 27
