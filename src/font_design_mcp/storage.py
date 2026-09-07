"""Immutable UFO snapshots; HEAD replacement is the transaction commit point."""

import hashlib
import json
import os
import plistlib
import stat
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from defusedxml import ElementTree
from filelock import FileLock, Timeout
from pydantic import TypeAdapter
from ufoLib2 import Font

from .domain import FontError, require, validate_font
from .models import Revision

REVISION = TypeAdapter(Revision)


def safe_path(root, path):
    root, path = Path(root).absolute(), Path(path).absolute()
    require(path.is_relative_to(root), "path_denied", "Path outside authorized workspace")
    for p in [
        root,
        *[
            root.joinpath(*path.relative_to(root).parts[:i])
            for i in range(1, len(path.relative_to(root).parts) + 1)
        ],
    ]:
        if p.exists() or p.is_symlink():
            info = p.lstat()
            require(
                not stat.S_ISLNK(info.st_mode) and not (getattr(info, "st_file_attributes", 0) & 0x400),
                "path_denied",
                "Symlinks and Windows reparse points are forbidden",
            )
            require(not p.is_file() or info.st_nlink == 1, "path_denied", "Hard links are forbidden")
    require(path.resolve().is_relative_to(root.resolve()), "path_denied", "Resolved path escapes workspace")
    return path


def files_checked(root, folder):
    folder = safe_path(root, folder)
    count, total = 0, 0
    for parent, dirs, files in os.walk(folder, followlinks=False):
        for name in dirs + files:
            path = safe_path(root, Path(parent) / name)
            count += 1
            require(count <= 4096, "limit_exceeded", "Snapshot exceeds 4096 filesystem entries")
            if path.is_file():
                size = path.stat().st_size
                total += size
                require(size <= 4_000_000 and total <= 32_000_000, "limit_exceeded", "Snapshot size limit")
                yield path


def digest_tree(root, folder):
    digest = hashlib.sha256()
    for p in sorted(files_checked(root, folder)):
        rel = p.relative_to(folder).as_posix().encode()
        data = p.read_bytes()
        digest.update(len(rel).to_bytes(4, "big") + rel + len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()


def read_json(root, path):
    path = safe_path(root, path)
    require(path.is_file(), "missing_reference", "Project or revision does not exist")
    require(path.stat().st_size <= 4_000_000, "limit_exceeded", "JSON size limit")
    return json.loads(path.read_text("utf-8"))


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def fsync_directory(path):
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def validate_ufo_files(root, ufo):
    """Reject unsafe XML, paths, alternate layers, images, data and executable lib hooks before UFOReader."""
    allowed_plists = {
        "metainfo.plist",
        "fontinfo.plist",
        "layercontents.plist",
        "groups.plist",
        "kerning.plist",
        "lib.plist",
        "glyphs/contents.plist",
        "glyphs/layerinfo.plist",
    }
    for p in files_checked(root, ufo):
        rel = p.relative_to(ufo).as_posix()
        require(
            rel in allowed_plists
            or rel == "features.fea"
            or (p.parent == ufo / "glyphs" and p.suffix == ".glif"),
            "capability_unavailable",
            f"Unsupported UFO file {rel}",
        )
        data = p.read_bytes()
        if p.suffix in (".plist", ".glif"):
            ElementTree.fromstring(data, forbid_entities=True, forbid_external=True)
        if p.name == "features.fea":
            require(not data.strip(), "capability_unavailable", "Raw feature code unsupported")
        if p.suffix == ".glif":
            tree = ElementTree.fromstring(data)
            require(
                tree.find("image") is None and tree.find("lib") is None,
                "capability_unavailable",
                "Glyph images and lib entries unsupported",
            )
        if p.name == "lib.plist":
            require(not plistlib.loads(data), "capability_unavailable", "UFO lib hooks unsupported")
        if p.name == "layercontents.plist":
            require(
                plistlib.loads(data) == [["public.default", "glyphs"]],
                "path_denied",
                "Only the default glyphs directory is permitted",
            )
        if p.name == "contents.plist":
            for filename in plistlib.loads(data).values():
                require(
                    isinstance(filename, str)
                    and Path(filename).name == filename
                    and "/" not in filename
                    and "\\" not in filename
                    and ":" not in filename
                    and filename.endswith(".glif"),
                    "path_denied",
                    "Unsafe GLIF reference",
                )


class Store:
    def __init__(self, root):
        original = Path(root).absolute()
        # Check existing ancestors before resolving the user-controlled launch root.
        for p in [original, *original.parents]:
            if p.exists():
                info = p.lstat()
                require(
                    not p.is_symlink() and not (getattr(info, "st_file_attributes", 0) & 0x400),
                    "path_denied",
                    "Workspace ancestors must not be links or junctions",
                )
        self.root = original.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def project(self, project_id):
        REVISION.validate_python(project_id)
        return safe_path(self.root, self.root / project_id)

    @contextmanager
    def lock(self, project_id):
        project = self.project(project_id)
        require(project.is_dir(), "missing_reference", "Unknown project")
        lock = FileLock(safe_path(self.root, project / ".lock"), timeout=5)
        try:
            with lock:
                yield project
        except Timeout as exc:
            raise FontError("project_busy", "Project is locked; retry later") from exc

    def head(self, project_id):
        return read_json(self.root, self.project(project_id) / "HEAD.json")

    def manifest(self, project_id, revision):
        REVISION.validate_python(revision)
        folder = self.project(project_id) / "revisions" / revision
        manifest = read_json(self.root, folder / "manifest.json")
        require(
            manifest.get("revision") == revision
            and manifest.get("project_id") == project_id
            and manifest.get("schema") == 1,
            "external_modification",
            "Invalid revision manifest",
        )
        return folder, manifest

    def history(self, project_id):
        head = self.head(project_id)
        revision, expected_hash = head["revision"], head["manifest_sha256"]
        visited = set()
        while revision:
            require(
                revision not in visited and len(visited) < 10000, "invalid_history", "History cycle/limit"
            )
            visited.add(revision)
            folder, manifest = self.manifest(project_id, revision)
            require(
                hashlib.sha256((folder / "manifest.json").read_bytes()).hexdigest() == expected_hash,
                "external_modification",
                "Committed history metadata changed externally",
            )
            yield manifest
            revision = manifest["parent"]
            expected_hash = manifest["parent_manifest_sha256"]

    def load(self, project_id, revision=None):
        head = self.head(project_id)
        revision = revision or head["revision"]
        require(
            any(item["revision"] == revision for item in self.history(project_id)),
            "missing_reference",
            "Revision is not committed in this project's history",
        )
        folder, manifest = self.manifest(project_id, revision)
        if revision == head["revision"]:
            actual = hashlib.sha256((folder / "manifest.json").read_bytes()).hexdigest()
            require(
                actual == head["manifest_sha256"],
                "external_modification",
                "Revision metadata changed externally",
            )
        ufo = folder / "source.ufo"
        require(
            digest_tree(self.root, ufo) == manifest["source_sha256"],
            "external_modification",
            "UFO changed externally; restore your backup before editing",
        )
        validate_ufo_files(self.root, ufo)
        font = Font.open(ufo, lazy=False, validate=True)
        validate_font(font)
        return font, manifest, ufo

    def commit(self, project_id, font, extra, summary, expected=None):
        """Caller holds project lock. Never overwrite a committed UFO."""
        validate_font(font)
        project = self.project(project_id)
        if expected is not None:
            require(
                self.head(project_id)["revision"] == expected, "stale_revision", "Expected revision is stale"
            )
            self.load(project_id)  # Detect external edits before staging.
        revisions = safe_path(self.root, project / "revisions")
        revisions.mkdir(exist_ok=True)
        revision = uuid.uuid4().hex
        stage = safe_path(self.root, revisions / (".stage-" + revision))
        stage.mkdir()
        ufo = stage / "source.ufo"
        font.save(ufo, formatVersion=3, validate=True)
        for p in files_checked(self.root, ufo):
            with p.open("r+b") as stream:
                os.fsync(stream.fileno())
        fsync_directory(ufo / "glyphs")
        fsync_directory(ufo)
        manifest = {
            "schema": 1,
            "project_id": project_id,
            "revision": revision,
            "parent": expected,
            "parent_manifest_sha256": self.head(project_id)["manifest_sha256"] if expected else None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "source_sha256": digest_tree(self.root, ufo),
            **extra,
        }
        write_json(stage / "manifest.json", manifest)
        fsync_directory(stage)
        if expected is not None:
            self.load(project_id)  # Recheck after staging as well.
        final = safe_path(self.root, revisions / revision)
        os.replace(stage, final)
        fsync_directory(revisions)
        head_tmp = safe_path(self.root, project / (".head-" + revision))
        write_json(
            head_tmp,
            {
                "revision": revision,
                "manifest_sha256": hashlib.sha256((final / "manifest.json").read_bytes()).hexdigest(),
            },
        )
        os.replace(head_tmp, safe_path(self.root, project / "HEAD.json"))
        fsync_directory(project)
        return manifest
