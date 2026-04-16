from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps

from app.db import UPLOADS_DIR

MAX_LOGO_SIZE = 5 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"
WEB_LOGO_MAX_SIZE = (1600, 600)
EXCEL_LOGO_SIZE = (430, 140)
EXCEL_LOGO_PADDING = (18, 12)


def _detect_format(content: bytes) -> str:
    if content.startswith(PNG_SIGNATURE):
        return "PNG"
    if content.startswith(JPEG_SIGNATURE):
        return "JPEG"
    raise ValueError("Solo se permiten logos PNG o JPEG.")


async def save_logo(upload) -> dict[str, str]:
    content = await upload.read()
    if not content:
        raise ValueError("Selecciona un archivo de logo.")
    if len(content) > MAX_LOGO_SIZE:
        raise ValueError("El logo supera el límite de 5 MB.")

    _detect_format(content)

    with Image.open(BytesIO(content)) as raw_image:
        image = ImageOps.exif_transpose(raw_image).convert("RGBA")
    image.thumbnail(WEB_LOGO_MAX_SIZE, Image.Resampling.LANCZOS)

    filename = f"logo_{uuid4().hex}.png"
    target = UPLOADS_DIR / filename
    image.save(target, format="PNG", optimize=True)
    return {"filename": filename, "mime": "image/png"}


def resolve_logo_path(filename: str | None) -> Path | None:
    if not filename:
        return None
    candidate = (UPLOADS_DIR / filename).resolve()
    if not str(candidate).startswith(str(UPLOADS_DIR.resolve())) or not candidate.exists():
        return None
    return candidate


def _make_light_background_transparent(image: Image.Image, threshold: int = 246) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            red, green, blue, alpha = pixels[x, y]
            if alpha == 0:
                continue
            if red >= threshold and green >= threshold and blue >= threshold:
                pixels[x, y] = (red, green, blue, 0)
    return rgba


def _trim_transparent_edges(image: Image.Image, padding: int = 4) -> Image.Image:
    bbox = image.getbbox()
    if not bbox:
        return image

    left = max(0, bbox[0] - padding)
    top = max(0, bbox[1] - padding)
    right = min(image.width, bbox[2] + padding)
    bottom = min(image.height, bbox[3] + padding)
    return image.crop((left, top, right, bottom))


def prepare_logo_for_excel(filename: str | None, target_size: tuple[int, int] = EXCEL_LOGO_SIZE) -> Image.Image | None:
    logo_path = resolve_logo_path(filename)
    if not logo_path:
        return None

    with Image.open(logo_path) as raw_logo:
        working = _make_light_background_transparent(raw_logo.convert("RGBA"))
        working = _trim_transparent_edges(working)

    padded_size = (
        max(1, target_size[0] - EXCEL_LOGO_PADDING[0] * 2),
        max(1, target_size[1] - EXCEL_LOGO_PADDING[1] * 2),
    )
    fitted = ImageOps.contain(working, padded_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", target_size, (255, 255, 255, 0))
    offset_x = max(0, (target_size[0] - fitted.width) // 2)
    offset_y = max(0, (target_size[1] - fitted.height) // 2)
    canvas.alpha_composite(fitted, (offset_x, offset_y))
    return canvas


def delete_logo(filename: str | None) -> None:
    path = resolve_logo_path(filename)
    if path and path.exists():
        path.unlink(missing_ok=True)
