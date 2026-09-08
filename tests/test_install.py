"""Client configuration updates use temporary profiles, never developer settings."""

import json
import os
import subprocess
import sys
import tomllib
from argparse import Namespace
from pathlib import Path

import pytest

from font_design_mcp import install as setup


def test_merge_preserves_clients_permissions_comments_and_backups(tmp_path):
    server = {"command": "C:/Python With Spaces/python.exe", "args": ["-m", "font_design_mcp", "serve"]}
    for client, original in [
        (
            "codex",
            b'# Keep this comment\nmodel = "chosen-model"\n[mcp_servers.other]\ncommand = "other"\n'
            b'[mcp_servers.font_design]\ncommand = "old"\ntool_timeout_sec = 240\n'
            b'disabled_tools = ["font_build"]\n[mcp_servers.font_design.env]\nCUSTOM = "keep"\n',
        ),
        ("claude-code", b'{"projects":{"existing":{}},"mcpServers":{"other":{"command":"other"}}}'),
        ("cursor", b'{"mcpServers":{"other":{"command":"other"}}}'),
    ]:
        path = tmp_path / client / ("config.toml" if client == "codex" else "config.json")
        path.parent.mkdir()
        path.write_bytes(original)
        content = setup.merge_config(original, client, server)
        backup = setup.write_config(path, original, content)
        assert backup.read_bytes() == original and path.read_bytes() == content
        parsed = tomllib.loads(content.decode()) if client == "codex" else json.loads(content)
        servers = parsed["mcp_servers" if client == "codex" else "mcpServers"]
        assert servers["other"]["command"] == "other"
        installed = servers["font_design" if client == "codex" else "font-design"]
        assert installed["command"] == server["command"]
        assert installed["args"] == server["args"]
        if client == "codex":
            assert content.startswith(b"# Keep this comment")
            assert parsed["model"] == "chosen-model"
            assert installed["tool_timeout_sec"] == 240
            assert installed["disabled_tools"] == ["font_build"]
            assert installed["env"] == {"CUSTOM": "keep"}
        if client == "claude-code":
            assert parsed["projects"] == {"existing": {}}
            assert installed["type"] == "stdio"
        assert setup.merge_config(content, client, server) == content
        assert setup.write_config(path, content, content) is None
        path.write_bytes(b"concurrent edit")
        with pytest.raises(ValueError, match="changed"):
            setup.write_config(path, content, original)
        assert path.read_bytes() == b"concurrent edit"

    old = b'{"mcpServers":{"font-design":{"command":"old","args":["serve","--workspace","/my/fonts"]}}}'
    kept = json.loads(setup.merge_config(old, "cursor", server))
    assert kept["mcpServers"]["font-design"]["args"][-2:] == ["--workspace", "/my/fonts"]
    explicit = {**server, "args": [*server["args"], "--workspace", "/new/fonts"]}
    moved = json.loads(setup.merge_config(old, "cursor", explicit))
    assert moved["mcpServers"]["font-design"]["args"] == explicit["args"]


def test_detection_dry_run_and_preflight(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "custom-codex"))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(setup.shutil, "which", lambda name: None)
    paths = setup.client_paths()
    assert not setup.detect_clients(paths)
    paths["codex"].parent.mkdir()
    paths["cursor"].parent.mkdir()
    paths["claude-code"].write_text('{"existing":"keep"}', encoding="utf-8")
    assert setup.detect_clients(paths) == list(setup.CLIENTS)
    args = Namespace(clients=None, yes=True, dry_run=True, workspace=tmp_path / "fonts")
    setup.install(args)
    assert not args.workspace.exists()
    assert not paths["codex"].exists()
    assert not paths["cursor"].exists()
    assert '"changed": true' in capsys.readouterr().out
    paths["cursor"].write_text("broken JSON", encoding="utf-8")
    args.dry_run = False
    with pytest.raises(ValueError, match="Cannot update"):
        setup.install(args)
    assert not paths["codex"].exists()
    assert paths["claude-code"].read_text() == '{"existing":"keep"}'


def test_atomic_failure_and_conflicting_server(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_bytes(b"original")

    def failed(*args):
        raise OSError("injected replace failure")

    monkeypatch.setattr(setup.os, "replace", failed)
    with pytest.raises(OSError, match="injected"):
        setup.write_config(path, b"original", b"new")
    assert path.read_bytes() == b"original"
    assert not list(tmp_path.glob(".font-design-*"))
    assert next(tmp_path.glob("*.bak")).read_bytes() == b"original"
    for content in [
        b"[]",
        b'{"mcpServers":[]}',
        b'{"mcpServers":{"font-design":{"url":"https://example.com"}}}',
        b'{"mcpServers":{"font_design":{},"font-design":{}}}',
    ]:
        with pytest.raises(ValueError):
            setup.merge_config(content, "cursor", {"command": "python", "args": []})


def test_cli_registers_working_mcp_in_isolated_profile(tmp_path):
    root = tmp_path.resolve()
    env = {
        **os.environ,
        "HOME": str(root),
        "USERPROFILE": str(root),
        "CODEX_HOME": str(root / ".codex"),
        "CLAUDE_CONFIG_DIR": str(root / ".claude"),
    }
    subprocess.run(
        [
            sys.executable,
            "-m",
            "font_design_mcp",
            "install",
            "--clients",
            "codex",
            "claude-code",
            "cursor",
            "--workspace",
            str(root / "fonts"),
        ],
        env=env,
        check=True,
        capture_output=True,
        timeout=90,
    )
    config = tomllib.loads((root / ".codex" / "config.toml").read_text("utf-8"))
    server = config["mcp_servers"]["font-design"]
    result = subprocess.run(
        [server["command"], "-m", "font_design_mcp", "--version"], check=True, capture_output=True, text=True
    )
    from font_design_mcp import __version__

    assert result.stdout.strip() == __version__
    assert (root / "fonts").is_dir()
    for path in [root / ".claude" / ".claude.json", root / ".cursor" / "mcp.json"]:
        assert json.loads(path.read_text())["mcpServers"]["font-design"]["command"] == server["command"]
