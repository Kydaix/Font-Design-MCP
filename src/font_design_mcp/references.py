"""Explicit, bounded PNG references from workspace/inbox. Never part of compiler UFO inputs."""

import hashlib
import io
import warnings
from pathlib import PurePosixPath

from fontTools.misc.transform import Transform
from PIL import Image

from .domain import FontError, require
from .storage import safe_path


def import_png(store, relative):
    path = PurePosixPath(relative)
    require(
        not path.is_absolute()
        and len(path.parts) >= 2
        and path.parts[0] == "inbox"
        and ".." not in path.parts
        and "\\" not in relative
        and ":" not in relative,
        "path_denied",
        "Reference must be a relative PNG path inside workspace/inbox",
    )
    source = safe_path(store.root, store.root.joinpath(*path.parts))
    require(
        source.suffix.lower() == ".png" and source.is_file(), "invalid_reference", "Expected an existing PNG"
    )
    require(source.stat().st_size <= 2_000_000, "limit_exceeded", "Reference PNG exceeds 2 MB")
    with source.open("rb") as stream:
        data = stream.read(2_000_001)
    require(len(data) <= 2_000_000, "limit_exceeded", "Reference PNG exceeds 2 MB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                require(
                    image.format == "PNG" and image.n_frames == 1,
                    "invalid_reference",
                    "Only single-frame PNG is supported",
                )
                require(
                    0 < image.width <= 2048 and 0 < image.height <= 2048,
                    "limit_exceeded",
                    "Reference exceeds 2048 pixels on an axis",
                )
                image.load()
                # Remove metadata and composite transparency against neutral paper.
                rgba = image.convert("RGBA")
                clean = Image.new("RGB", image.size, "white")
                clean.paste(rgba, (0, 0), rgba)
    except FontError:
        raise
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise FontError("invalid_reference", "Invalid or unsafe PNG reference") from exc
    return clean, hashlib.sha256(data).hexdigest()


def reference_frame(reference):
    transform = Transform(*reference.image_to_font)
    corners = [
        transform.transformPoint(p)
        for p in ((0, 0), (reference.width, 0), (0, reference.height), (reference.width, reference.height))
    ]
    return (
        min(p[0] for p in corners),
        min(p[1] for p in corners),
        max(p[0] for p in corners),
        max(p[1] for p in corners),
    )


def warped_reference(image, reference, width, height, scale, tx, ty):
    # Pixel origin is top-left/down; font origin is baseline/up. Do not auto-fit or flip sketches implicitly.
    font_to_pixel = Transform(scale, 0, 0, -scale, tx, height - ty)
    pixel_to_image = font_to_pixel.transform(Transform(*reference.image_to_font)).inverse()
    a, b, c, d, x, y = pixel_to_image
    warped = image.transform(
        (width, height),
        Image.Transform.AFFINE,
        (a, c, x, b, d, y),
        resample=Image.Resampling.BILINEAR,
        fillcolor="white",
    )
    return warped.convert("RGB")


def reference_layer(image, reference, width, height, scale, tx, ty):
    warped = warped_reference(image, reference, width, height, scale, tx, ty)
    return Image.blend(Image.new("RGB", warped.size, "white"), warped, 0.45)
