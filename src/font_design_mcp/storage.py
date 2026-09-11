"""Immutable UFO snapshots; HEAD replacement is the transaction commit point."""

import hashlib
import json
import os
import plistlib
import re
import stat
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from defusedxml import ElementTree
from filelock import FileLock, Timeout
from pydantic import TypeAdapter
from ufoLib2 import Font

from .domain import FontError, require, validate_font
from .models import DesignState, Revision, StrokeNetwork, Variation
from .telemetry import count, phase

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


@phase("source_integrity")
def digest_tree(root, folder, inspect_ufo=False):
    digest = hashlib.sha256()
    for p in sorted(files_checked(root, folder)):
        rel = p.relative_to(folder).as_posix().encode()
        data = p.read_bytes()
        count("checked_file_reads")
        count("checked_bytes_read", len(data))
        if inspect_ufo:
            validate_ufo_file(folder, p, data)
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


@phase("ufo_safety")
def validate_ufo_files(root, ufo):
    return digest_tree(root, ufo, inspect_ufo=True)


def validate_ufo_file(ufo, p, data):
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
    rel = p.relative_to(ufo).as_posix()
    require(
        rel in allowed_plists
        or rel == "features.fea"
        or (p.parent == ufo / "glyphs" and p.suffix == ".glif"),
        "capability_unavailable",
        f"Unsupported UFO file {rel}",
    )
    if p.suffix in (".plist", ".glif"):
        tree = ElementTree.fromstring(data, forbid_entities=True, forbid_external=True)
    if p.name == "features.fea":
        require(not data.strip(), "capability_unavailable", "Raw feature code unsupported")
    if p.suffix == ".glif":
        from .construction import NETWORK_KEY

        require(
            tree.find("image") is None,
            "capability_unavailable",
            "Glyph images unsupported",
        )
        for lib in tree.findall("lib"):
            require(len(lib) == 1 and lib[0].tag == "dict", "capability_unavailable", "Invalid glyph lib")
            values = plistlib.loads(b"<plist>" + ElementTree.tostring(lib[0]) + b"</plist>")
            require(
                set(values) <= {NETWORK_KEY},
                "capability_unavailable",
                "Arbitrary glyph lib entries unsupported",
            )
            if NETWORK_KEY in values:
                StrokeNetwork.model_validate(values[NETWORK_KEY])
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

    def resource_uri(self, project_id, revision, artifact_id, filename):
        path = safe_path(self.root, self.project(project_id) / "artifacts" / artifact_id / filename)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return f"font-design://{project_id}/{revision}/{artifact_id}/{filename}?sha256={digest}"

    def save_report(self, project_id, revision, report):
        require(
            len(
                json.dumps(
                    {**report, "revision": revision}, ensure_ascii=False, allow_nan=False, indent=2
                ).encode("utf-8")
            )
            <= 4_000_000,
            "limit_exceeded",
            "Report exceeds 4 MB; reduce the requested diagnostic scope",
        )
        root = safe_path(self.root, self.project(project_id) / "artifacts")
        root.mkdir(exist_ok=True)
        identifier = uuid.uuid4().hex
        stage = safe_path(self.root, root / (".stage-" + identifier))
        stage.mkdir()
        write_json(stage / "artifact.json", {**report, "revision": revision})
        os.replace(stage, safe_path(self.root, root / identifier))
        return self.resource_uri(project_id, revision, identifier, "artifact.json")

    def read_resource(self, uri):
        match = re.fullmatch(
            r"font-design://([a-f0-9]{32})/([a-f0-9]{32})/([a-f0-9]{32})/"
            r"(artifact\.json|image\.png|font\.ttf|font\.woff2)\?sha256=([a-f0-9]{64})",
            str(uri),
        )
        require(match is not None, "path_denied", "Invalid artifact URI")
        project_id, revision, artifact, filename, digest = match.groups()
        require(
            any(e["revision"] == revision for e in self.history(project_id)),
            "missing_reference",
            "Revision is not committed",
        )
        folder = self.project(project_id) / "artifacts" / artifact
        manifest = read_json(self.root, folder / "artifact.json")
        require(manifest.get("revision") == revision, "external_modification", "Artifact revision mismatch")
        path = safe_path(self.root, folder / filename)
        require(
            path.is_file() and path.stat().st_size <= 16_000_000,
            "limit_exceeded",
            "Resource missing or oversized",
        )
        data = path.read_bytes()
        require(hashlib.sha256(data).hexdigest() == digest, "external_modification", "Resource changed")
        mime = {
            "artifact.json": "application/json",
            "image.png": "image/png",
            "font.ttf": "font/ttf",
            "font.woff2": "font/woff2",
        }[filename]
        return data.decode("utf-8") if filename == "artifact.json" else data, mime

    @contextmanager
    def lock(self, project_id):
        project = self.project(project_id)
        require(project.is_dir(), "missing_reference", "Unknown project")
        lock = FileLock(safe_path(self.root, project / ".lock"), timeout=5)
        started = time.monotonic()
        try:
            with lock:
                count("project_lock_wait_us", round((time.monotonic() - started) * 1_000_000))
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
            and manifest.get("schema") in (1, 2, 3, 4, 5),
            "external_modification",
            "Invalid revision manifest",
        )
        if "design" in manifest:
            state = DesignState.model_validate(manifest["design"])
            require(
                manifest["schema"] == state.version + 2,
                "external_modification",
                "Design state/manifest schema mismatch",
            )
            require(
                all(r.uri.startswith(f"font-design://{project_id}/") for r in state.references),
                "path_denied",
                "Drawing references must belong to this project",
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

    @phase("verify")
    def verify(self, project_id, revision=None, inspect_ufo=False):
        """Verify committed metadata and source bytes without materializing a Font."""
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
            (validate_ufo_files(self.root, ufo) if inspect_ufo else digest_tree(self.root, ufo))
            == manifest["source_sha256"],
            "external_modification",
            "UFO changed externally; restore your backup before editing",
        )
        if "variation" in manifest:
            variation = Variation.model_validate(manifest["variation"])
            list(files_checked(self.root, folder))
            for master in variation.masters:
                if master.id == "default":
                    continue
                path = folder / "masters" / f"master-{master.id}.ufo"
                digest = validate_ufo_files(self.root, path) if inspect_ufo else digest_tree(self.root, path)
                require(
                    digest == manifest["master_sha256"].get(master.id),
                    "external_modification",
                    f"Master {master.id} changed externally",
                )
        if "design" in manifest:
            for reference in DesignState.model_validate(manifest["design"]).references:
                self.read_resource(reference.uri)
                if reference.source_page_uri:
                    self.read_resource(reference.source_page_uri)
        return manifest, ufo

    @phase("load")
    def load(self, project_id, revision=None):
        manifest, ufo = self.verify(project_id, revision, inspect_ufo=True)
        font = Font.open(ufo, lazy=False, validate=True)
        validate_font(font)
        return font, manifest, ufo

    def load_masters(self, project_id, manifest, font):
        """Materialize the additional masters only when editing or compiling a variable project."""
        fonts = {"default": font}
        if "variation" in manifest:
            _, ufo = self.verify(project_id, manifest["revision"], inspect_ufo=True)
            for master in manifest["variation"]["masters"]:
                if master["id"] != "default":
                    path = ufo.parent / "masters" / f"master-{master['id']}.ufo"
                    other = Font.open(path, lazy=False, validate=True)
                    validate_font(other)
                    fonts[master["id"]] = other
        return fonts

    @phase("commit")
    def commit(self, project_id, font, extra, summary, expected=None, masters=None):
        """Caller holds project lock. Never overwrite a committed UFO."""
        validate_font(font)
        project = self.project(project_id)
        if "design" in extra:
            state = DesignState.model_validate(extra["design"])
            extra = {**extra, "design": state.model_dump()}
            require(
                set(state.composition_links) <= set(masters or {"default": font}),
                "missing_reference",
                "Linked compositions reference an unknown master",
            )
            reference_bytes = sum(r.encoded_bytes for r in state.references)
            pages = set()
            for reference in state.references:
                require(
                    reference.uri.startswith(f"font-design://{project_id}/"),
                    "path_denied",
                    "Drawing references must belong to this project",
                )
                self.read_resource(reference.uri)
                if reference.source_page_uri:
                    require(
                        reference.source_page_uri.startswith(f"font-design://{project_id}/"),
                        "path_denied",
                        "Reference page must belong to this project",
                    )
                    data, _ = self.read_resource(reference.source_page_uri)
                    if reference.source_page_uri not in pages:
                        reference_bytes += len(data)
                        pages.add(reference.source_page_uri)
            require(
                reference_bytes <= 32_000_000,
                "limit_exceeded",
                "References including preserved pages exceed 32 MB",
            )
        if expected is not None:
            require(
                self.head(project_id)["revision"] == expected, "stale_revision", "Expected revision is stale"
            )
            self.verify(project_id)  # Detect external edits before staging.
        revisions = safe_path(self.root, project / "revisions")
        revisions.mkdir(exist_ok=True)
        revision = uuid.uuid4().hex
        stage = safe_path(self.root, revisions / (".stage-" + revision))
        stage.mkdir()
        ufo = stage / "source.ufo"
        font.save(ufo, formatVersion=3, validate=True)
        master_hashes = {}
        if "variation" in extra:
            variation = Variation.model_validate(extra["variation"])
            require(
                masters is not None and set(masters) == {s.id for s in variation.masters},
                "missing_reference",
                "Expected every configured master",
            )
            (stage / "masters").mkdir()
            for master in variation.masters:
                if master.id == "default":
                    continue
                other = masters[master.id]
                validate_font(other)
                path = stage / "masters" / f"master-{master.id}.ufo"
                other.save(path, formatVersion=3, validate=True)
                master_hashes[master.id] = digest_tree(self.root, path)
                fsync_directory(path / "glyphs")
                fsync_directory(path)
            fsync_directory(stage / "masters")
        for p in files_checked(self.root, stage):
            count("source_files_written")
            count("source_bytes_written", p.stat().st_size)
            with p.open("r+b") as stream:
                os.fsync(stream.fileno())
        fsync_directory(ufo / "glyphs")
        fsync_directory(ufo)
        manifest = {
            "schema": extra["design"]["version"] + 2
            if "design" in extra
            else 2
            if "variation" in extra
            else 1,
            "project_id": project_id,
            "revision": revision,
            "parent": expected,
            "parent_manifest_sha256": self.head(project_id)["manifest_sha256"] if expected else None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "source_sha256": digest_tree(self.root, ufo),
            **extra,
            **({"master_sha256": master_hashes} if master_hashes else {}),
        }
        write_json(stage / "manifest.json", manifest)
        fsync_directory(stage)
        if expected is not None:
            require(self.head(project_id)["revision"] == expected, "stale_revision", "HEAD changed")
            self.verify(project_id)  # Recheck after staging as well.
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
