import json
import os
import plistlib
import subprocess
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from font_design_mcp import models as m
from font_design_mcp.domain import FontError, edit_glyph, edit_spacing, new_font, set_info, validate_font
from font_design_mcp.storage import Store, safe_path, validate_ufo_files


def base():
    return new_font(m.Metadata(family="Domain Test"), m.Metrics())


def test_embedding_default_and_explicit_value():
    font = base()
    assert font.info.openTypeOS2Type == []
    font.info.openTypeOS2Type = None
    set_info(font, m.Metadata(family="Legacy Project"))
    assert font.info.openTypeOS2Type == []
    font.info.openTypeOS2Type = [2]
    set_info(font, m.Metadata(family="Explicit Embedding Value"))
    assert font.info.openTypeOS2Type == [2]


def request(name="A", ops=None, create=True):
    return m.GlyphEdit(
        project_id="0" * 32,
        expected_revision="0" * 32,
        glyph_id=name,
        create=create,
        operations=ops
        or [
            {
                "op": "replace_glyph",
                "glyph": {
                    "contours": [
                        {
                            "id": "box",
                            "points": [
                                {"id": "p0", "x": 10, "y": 0},
                                {"id": "p1", "x": 300, "y": 0},
                                {"id": "p2", "x": 300, "y": 700},
                                {"id": "p3", "x": 10, "y": 700},
                            ],
                        }
                    ]
                },
            }
        ],
    )


def test_transform_components_anchors_and_bearings():
    font = base()
    edit_glyph(font, request())
    edit_glyph(
        font,
        request(
            "B",
            [
                {"op": "put_component", "component": {"id": "c", "base": "A"}},
                {"op": "put_anchor", "anchor": {"id": "top", "name": "top", "x": 100, "y": 700}},
            ],
        ),
    )
    edit_glyph(font, request("B", [{"op": "transform", "matrix": [1, 0, 0, 1, 20, 30]}], False))
    assert font["B"].getBounds(font) == (30, 30, 320, 730)
    assert font["B"].anchors[0].x == 120 and font["B"].width == 0
    spacing = m.SpacingEdit(
        project_id="0" * 32,
        expected_revision="0" * 32,
        operations=[{"op": "bearings", "glyph_id": "B", "left": 40, "right": 60}],
    )
    edit_spacing(font, spacing)
    assert font["B"].width == 390 and font["B"].getBounds(font)[0] == 40
    assert font["A"].getBounds(font)[0] == 10
    validate_font(font)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), 16001])
def test_nonfinite_and_large_coordinates(bad):
    with pytest.raises(ValidationError):
        m.Point(id="p", x=bad, y=0)


def test_topology_ids_and_bad_curves():
    font = base()
    edit_glyph(font, request())
    change = edit_glyph(
        font,
        request(
            ops=[
                {
                    "op": "put_contour",
                    "replace": True,
                    "contour": {
                        "id": "box",
                        "points": [
                            {"id": "new0", "x": 0, "y": 0},
                            {"id": "new1", "x": 300, "y": 0},
                            {"id": "new2", "x": 0, "y": 700},
                        ],
                    },
                }
            ],
            create=False,
        ),
    )
    assert change["removed_ids"] == ["p0", "p1", "p2", "p3"]
    validate_font(font)
    font["A"].contours[0].points[1].type = "curve"
    with pytest.raises(FontError, match="Malformed"):
        validate_font(font)
    font["A"].contours[0].points[1].type = "line"
    font["A"].contours[0].points[1].identifier = "new0"
    with pytest.raises(FontError, match="IDs must be unique"):
        validate_font(font)
    with pytest.raises(FontError, match="Ambiguous element"):
        edit_glyph(
            font, request(ops=[{"op": "move_point", "point_id": "new0", "x": 50, "y": 50}], create=False)
        )


def test_unicode_cycle_and_missing_reference():
    font = base()
    edit_glyph(font, request())
    with pytest.raises(ValidationError):
        m.Glyph(unicodes=[0xD800])
    edit_glyph(font, request("B", [{"op": "put_component", "component": {"id": "b", "base": "Absent"}}]))
    with pytest.raises(FontError) as err:
        validate_font(font)
    assert err.value.code == "missing_reference"
    font["B"].components[0].baseGlyph = "A"
    edit_glyph(font, request("A", [{"op": "put_component", "component": {"id": "a", "base": "B"}}], False))
    with pytest.raises(FontError) as err:
        validate_font(font)
    assert err.value.code == "component_cycle"


def make_project(tmp_path):
    store = Store(tmp_path)
    pid = uuid.uuid4().hex
    store.project(pid).mkdir()
    with store.lock(pid):
        state = store.commit(pid, base(), {"brief": "", "decisions": []}, "create")
    return store, pid, state


@pytest.mark.parametrize("phase", ["snapshot", "head"])
def test_commit_failure_does_not_change_head(tmp_path, monkeypatch, phase):
    store, pid, state = make_project(tmp_path)
    head = (tmp_path / pid / "HEAD.json").read_bytes()
    original = os.replace

    def fail(src, dst):
        if (phase == "snapshot" and Path(dst).parent.name == "revisions") or (
            phase == "head" and Path(dst).name == "HEAD.json"
        ):
            raise OSError("injected atomic rename failure")
        original(src, dst)

    with store.lock(pid), monkeypatch.context() as scoped:
        font, _, _ = store.load(pid)
        font["space"].width = 333
        scoped.setattr(os, "replace", fail)
        with pytest.raises(OSError):
            store.commit(pid, font, {"brief": "", "decisions": []}, "fail", state["revision"])
    assert (tmp_path / pid / "HEAD.json").read_bytes() == head
    font, _, _ = store.load(pid)
    assert font["space"].width == 250
    assert len(list(store.history(pid))) == 1


def test_history_and_source_tampering(tmp_path):
    store, pid, initial = make_project(tmp_path)
    with store.lock(pid):
        font, state, _ = store.load(pid)
        store.commit(pid, font, {"brief": "new", "decisions": []}, "second", state["revision"])
    oldmanifest = tmp_path / pid / "revisions" / initial["revision"] / "manifest.json"
    data = json.loads(oldmanifest.read_text())
    data["brief"] = "tampered"
    oldmanifest.write_text(json.dumps(data))
    with pytest.raises(FontError) as err:
        list(store.history(pid))
    assert err.value.code == "external_modification"


def test_untrusted_ufo_paths_and_xml(tmp_path):
    ufo = tmp_path / "input.ufo"
    base().save(ufo)
    validate_ufo_files(tmp_path, ufo)
    contents = ufo / "glyphs" / "contents.plist"
    original = contents.read_bytes()
    contents.write_bytes(plistlib.dumps({"A": "../../outside.glif"}))
    with pytest.raises(FontError) as err:
        validate_ufo_files(tmp_path, ufo)
    assert err.value.code == "path_denied"
    contents.write_bytes(original)
    (ufo / "features.fea").write_text("include(../../private.fea);")
    with pytest.raises(FontError) as err:
        validate_ufo_files(tmp_path, ufo)
    assert err.value.code == "capability_unavailable"
    (ufo / "features.fea").write_text("")
    contents.write_text('<!DOCTYPE plist [<!ENTITY x SYSTEM "file:///outside">]><plist>&x;</plist>')
    with pytest.raises(Exception, match="EntitiesForbidden"):
        validate_ufo_files(tmp_path, ufo)


def test_path_escape_and_link(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(FontError):
        safe_path(root, root / ".." / "outside")
    link = root / "link"
    if os.name == "nt":
        # Native PowerShell, one explicitly bounded link creation. No recursive deletion.
        command = f"New-Item -ItemType Junction -Path '{link}' -Target '{outside}' | Out-Null"
        subprocess.run(["powershell", "-NoProfile", "-Command", command], check=True, capture_output=True)
    else:
        link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(FontError) as err:
        safe_path(root, link / "secret")
    assert err.value.code == "path_denied"
    if os.name == "nt":
        os.rmdir(link)  # removes junction itself, never its target
    else:
        link.unlink()


def test_hardlink_and_executable_lib(tmp_path):
    original = tmp_path / "a"
    original.write_text("x")
    os.link(original, tmp_path / "b")
    with pytest.raises(FontError):
        safe_path(tmp_path, original)
    font = base()
    font.lib["com.github.googlei18n.ufo2ft.filters"] = [{"name": "untrusted", "namespace": "outside"}]
    with pytest.raises(FontError) as err:
        validate_font(font)
    assert err.value.code == "capability_unavailable"
