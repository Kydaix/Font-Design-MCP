import asyncio
import os
import subprocess
import sys
import uuid

import pytest
from test_acceptance import call, client

from font_design_mcp.build import run_compiler
from font_design_mcp.domain import FontError


@pytest.mark.parametrize("script", ["import time; time.sleep(10)", "print('x' * 1100000)"])
def test_compiler_deadline_and_log_limit(tmp_path, script):
    program = tmp_path / "bounded_child.py"
    program.write_text(script)
    with pytest.raises(FontError) as error:
        run_compiler([sys.executable, str(program)], tmp_path, timeout=0.1 if "sleep" in script else 5)
    assert error.value.code == "build_timeout"


def test_two_server_processes_cannot_lose_an_update(tmp_path):
    async def run():
        async with client(tmp_path) as first, client(tmp_path) as second:
            created, _ = await call(first, "project_create", metadata={"family": "Concurrent Test"})
            args = {"project_id": created["project_id"], "expected_revision": created["revision"]}
            responses = await asyncio.gather(
                first.call_tool("project_update", {**args, "brief": "first"}),
                second.call_tool("project_update", {**args, "brief": "second"}),
            )
            assert sum(not r.isError for r in responses) == 1
            failed = next(r for r in responses if r.isError)
            assert failed.structuredContent["error"]["code"] == "stale_revision"
            history, _ = await call(first, "history_list", project_id=created["project_id"])
            assert history["data"]["total"] == 2

    asyncio.run(run())


def test_stdio_rejects_oversized_line_before_json_parsing(tmp_path):
    process = subprocess.run(
        [sys.executable, "-m", "font_design_mcp", "serve", "--workspace", str(tmp_path)],
        input=b" " * 2_000_001 + b"\n",
        capture_output=True,
        timeout=15,
    )
    assert process.returncode != 0
    assert process.stdout == b""
    assert b"MCP input line exceeds 2 MB" in process.stderr


def test_project_junction_is_rejected_via_mcp(tmp_path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (outside / "sentinel").write_text("Unchanged")
    link = workspace / uuid.uuid4().hex
    if os.name == "nt":
        command = "New-Item -ItemType Junction -Path '{}' -Target '{}' | Out-Null".format(
            str(link).replace("'", "''"), str(outside).replace("'", "''")
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", command], check=True, capture_output=True)
    else:
        link.symlink_to(outside, target_is_directory=True)

    async def run():
        async with client(workspace) as session:
            await call(session, "project_open", error="path_denied", project_id=link.name)

    try:
        asyncio.run(run())
        assert list(outside.iterdir()) == [outside / "sentinel"]
        assert (outside / "sentinel").read_text() == "Unchanged"
    finally:
        assert link.absolute().is_relative_to(workspace.absolute())
        if os.name == "nt":
            os.rmdir(link)
        else:
            link.unlink()
