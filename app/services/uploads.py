from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps

from app.db import current_uploads_dir

MAX_LOGO_SIZE = 5 * 1024 * 1024
MAX_CATALOG_IMAGE_SIZE = 8 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"
WEB_LOGO_MAX_SIZE = (1600, 600)
CATALOG_IMAGE_MAX_SIZE = (1400, 1400)


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
    uploads_dir = current_uploads_dir()
    uploads_dir.mkdir(parents=True, exist_ok=True)
    target = uploads_dir / filename
    image.save(target, format="PNG", optimize=True)
    return {"filename": filename, "mime": "image/png"}


async def save_catalog_image(upload) -> dict[str, str]:
    content = await upload.read()
    if not content:
        raise ValueError("Selecciona una imagen para el producto.")
    if len(content) > MAX_CATALOG_IMAGE_SIZE:
        raise ValueError("La imagen del producto supera el limite de 8 MB.")

    _detect_format(content)

    with Image.open(BytesIO(content)) as raw_image:
        image = ImageOps.exif_transpose(raw_image).convert("RGBA")
    image.thumbnail(CATALOG_IMAGE_MAX_SIZE, Image.Resampling.LANCZOS)

    filename = f"catalog_{uuid4().hex}.png"
    uploads_dir = current_uploads_dir()
    uploads_dir.mkdir(parents=True, exist_ok=True)
    target = uploads_dir / filename
    image.save(target, format="PNG", optimize=True)
    return {"filename": filename, "mime": "image/png"}


def resolve_logo_path(filename: str | None) -> Path | None:
    if not filename:
        return None
    uploads_dir = current_uploads_dir().resolve()
    candidate = (uploads_dir / filename).resolve()
    if not str(candidate).startswith(str(uploads_dir)) or not candidate.exists():
        return None
    return candidate


def delete_logo(filename: str | None) -> None:
    path = resolve_logo_path(filename)
    if path and path.exists():
        path.unlink(missing_ok=True)


def delete_uploaded_image(filename: str | None) -> None:
    path = resolve_logo_path(filename)
    if path and path.exists():
        path.unlink(missing_ok=True)
