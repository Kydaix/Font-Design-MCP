"""Detect MCP clients and merge a local server into their user configuration."""

import json
import os
import shutil
import sys
import tempfile
import uuid
from collections.abc import MutableMapping
from pathlib import Path

import tomlkit
from filelock import FileLock

CLIENTS = ("codex", "claude-code", "cursor")


def client_paths():
    home = Path.home()
    return {
        "codex": Path(os.environ.get("CODEX_HOME", home / ".codex")).expanduser() / "config.toml",
        "claude-code": (
            Path(os.environ["CLAUDE_CONFIG_DIR"]).expanduser() / ".claude.json"
            if os.environ.get("CLAUDE_CONFIG_DIR")
            else home / ".claude.json"
        ),
        "cursor": home / ".cursor" / "mcp.json",
    }


def detect_clients(paths):
    home = Path.home()
    return [
        name
        for name, path in paths.items()
        if path.exists()
        or (name != "claude-code" and path.parent.is_dir())
        or (name == "claude-code" and (home / ".claude").is_dir())
        or shutil.which({"claude-code": "claude"}.get(name, name))
    ]


def merge_config(original, client, server):
    text = original.decode("utf-8-sig") if original else ""
    config = tomlkit.parse(text) if client == "codex" else json.loads(text) if text.strip() else {}
    if not isinstance(config, MutableMapping):
        raise ValueError("Client configuration must be an object")
    key = "mcp_servers" if client == "codex" else "mcpServers"
    if key not in config:
        config[key] = {}
    servers = config[key]
    if not isinstance(servers, MutableMapping):
        raise ValueError(f"{key} must be an object")
    aliases = [name for name in ("font-design", "font_design") if name in servers]
    if len(aliases) > 1:
        raise ValueError("Both font-design and font_design already exist; keep one before installing")
    name = aliases[0] if aliases else "font-design"
    existing = servers.get(name, {})
    if not isinstance(existing, MutableMapping) or "url" in existing:
        raise ValueError(f"{name} is not a local server configuration; rename it before installing")
    entry = dict(existing)
    entry.update(server)
    old_args = existing.get("args", [])
    if "--workspace" not in server["args"] and isinstance(old_args, list):
        for index, value in enumerate(old_args):
            if value == "--workspace" and index + 1 < len(old_args):
                entry["args"] = [*server["args"], "--workspace", old_args[index + 1]]
                break
            if isinstance(value, str) and value.startswith("--workspace="):
                entry["args"] = [*server["args"], value]
                break
    if client == "codex":
        entry.setdefault("startup_timeout_sec", 30)
        entry.setdefault("tool_timeout_sec", 180)
    elif client == "claude-code":
        entry["type"] = "stdio"
    if servers.get(name) == entry:
        return original
    servers[name] = entry
    output = (
        tomlkit.dumps(config)
        if client == "codex"
        else json.dumps(config, indent=2, ensure_ascii=False) + "\n"
    )
    return output.encode("utf-8")


def write_config(path, original, content):
    """Back up exact bytes, detect concurrent changes, then replace atomically."""
    if content == original:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".font-design.lock", timeout=5):
        current = path.read_bytes() if path.exists() else None
        if current != original:
            raise ValueError(f"{path} changed during installation; retry")
        backup = None
        if original is not None:
            backup = path.with_name(path.name + f".font-design-{uuid.uuid4().hex}.bak")
            with backup.open("xb") as stream:
                os.chmod(backup, 0o600)
                stream.write(original)
                stream.flush()
                os.fsync(stream.fileno())
        fd, temporary = tempfile.mkstemp(prefix=".font-design-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if (path.read_bytes() if path.exists() else None) != original:
                raise ValueError(f"{path} changed during installation; retry")
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return backup


def install(args):
    from .__main__ import doctor, workspace_path

    paths = client_paths()
    detected = detect_clients(paths)
    selected = args.clients
    if not selected:
        print("Detected clients: " + (", ".join(detected) or "none"))
        if args.yes or args.dry_run:
            selected = detected
        elif sys.stdin.isatty():
            print("Available clients: " + ", ".join(CLIENTS))
            answer = input("Choose clients (comma-separated; Enter = detected clients): ").strip()
            selected = [name.strip() for name in answer.split(",")] if answer else detected
        else:
            raise ValueError("Use --clients codex cursor or --yes in a non-interactive terminal")
    if not selected or any(name not in paths for name in selected):
        raise ValueError("Choose at least one supported client: " + ", ".join(CLIENTS))
    workspace = workspace_path(args.workspace)
    # Keep the venv interpreter path: resolving a POSIX symlink would select the base Python instead.
    server = {
        "command": str(Path(sys.executable).absolute()),
        "args": ["-m", "font_design_mcp", "serve"],
    }
    if args.workspace is not None or os.environ.get("FONT_DESIGN_MCP_WORKSPACE"):
        server["args"].extend(["--workspace", str(workspace)])
    plans = []
    for client in dict.fromkeys(selected):
        path = paths[client].absolute()
        if path.is_symlink():
            raise ValueError(f"Refusing to replace symlinked configuration: {path}")
        original = path.read_bytes() if path.exists() else None
        try:
            content = merge_config(original, client, server)
        except Exception as exc:
            raise ValueError(f"Cannot update {path}: {exc}") from exc
        plans.append((client, path, original, content))
    if args.dry_run:
        print(
            json.dumps(
                {
                    "workspace": str(workspace),
                    "server": server,
                    "clients": [
                        {"client": client, "path": str(path), "changed": original != content}
                        for client, path, original, content in plans
                    ],
                },
                indent=2,
            )
        )
        return
    report = doctor(build=True)
    if not report["ok"]:
        raise ValueError(
            "MCP diagnostic failed; no client configuration changed: " + json.dumps(report["errors"])
        )
    from .storage import Store

    Store(workspace)  # Validate the actual workspace before registering any client.
    for client, path, original, content in plans:
        backup = write_config(path, original, content)
        print(f"{client}: {'already configured' if original == content else 'configured'} ({path})")
        if backup:
            print(f"  Backup: {backup}")
    print("Ready. Restart the selected clients to load Font Design MCP.")
