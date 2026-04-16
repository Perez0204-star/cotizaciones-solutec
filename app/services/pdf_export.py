from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.services.calculations import round_money
from app.services.uploads import resolve_logo_path

PAGE_SIZE = (2480, 1754)
PAGE_MARGIN_X = 56
PAGE_MARGIN_Y = 35
CONTENT_WIDTH = PAGE_SIZE[0] - (PAGE_MARGIN_X * 2)

COLUMN_WIDTHS = [360, 870, 220, 240, 320, 358]
ROW_HEIGHTS = [78, 70, 70, 70, 70, 56, 74] + ([50] * 17) + ([46] * 4) + ([54] * 3)
ITEMS_PER_PAGE = 17
PDF_LOGO_SIZE = (980, 245)

COLOR_LINE = "#7FA3C8"
COLOR_HEADER = "#D9ECFA"
COLOR_TITLE = "#F7FBFF"
COLOR_TITLE_TEXT = "#1780C7"
COLOR_TEXT = "#0B2E4A"
COLOR_LABEL = "#0F4E82"
COLOR_PAGE = "#FFFFFF"


def _font_candidates(*names: str) -> list[str]:
    candidates: list[str] = []
    windows_fonts = Path("C:/Windows/Fonts")
    for name in names:
        candidates.append(name)
        candidates.append(str(windows_fonts / name))
    return candidates


def _load_font(size: int, *, bold: bool = False, serif: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if serif and bold:
        candidates = _font_candidates("georgiab.ttf", "timesbd.ttf", "DejaVuSerif-Bold.ttf")
    elif serif:
        candidates = _font_candidates("georgia.ttf", "times.ttf", "DejaVuSerif.ttf")
    elif bold:
        candidates = _font_candidates("arialbd.ttf", "calibrib.ttf", "DejaVuSans-Bold.ttf")
    else:
        candidates = _font_candidates("arial.ttf", "calibri.ttf", "DejaVuSans.ttf")

    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


TITLE_FONT = _load_font(44, bold=True, serif=True)
LABEL_FONT = _load_font(28, bold=True)
VALUE_FONT = _load_font(28)
TABLE_HEADER_FONT = _load_font(30, bold=True)
BODY_FONT = _load_font(27)
BODY_FONT_BOLD = _load_font(28, bold=True)


def _format_money(value: object, rounding_mode: str) -> str:
    amount = round_money(value, rounding_mode)
    decimals = 2 if rounding_mode == "2dec" else 0
    text = f"{amount:,.{decimals}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def _format_qty(value: object) -> str:
    amount = float(value or 0)
    text = f"{amount:,.2f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def _format_date(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%d/%m/%Y")
    except ValueError:
        return value


def _row_bounds(row_number: int) -> tuple[int, int]:
    top = PAGE_MARGIN_Y + sum(ROW_HEIGHTS[: row_number - 1])
    bottom = top + ROW_HEIGHTS[row_number - 1]
    return top, bottom


def _column_bounds(column_index: int) -> tuple[int, int]:
    left = PAGE_MARGIN_X + sum(COLUMN_WIDTHS[:column_index])
    right = left + COLUMN_WIDTHS[column_index]
    return left, right


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    content = str(text or "")
    if not content:
        return ""
    if draw.textbbox((0, 0), content, font=font)[2] <= max_width:
        return content

    ellipsis = "..."
    shortened = content
    while shortened:
        shortened = shortened[:-1]
        candidate = shortened.rstrip() + ellipsis
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            return candidate
    return ellipsis


def _draw_box(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    fill: str = COLOR_PAGE,
    width: int = 2,
) -> None:
    draw.rectangle(box, fill=fill, outline=COLOR_LINE, width=width)


def _draw_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    *,
    font: ImageFont.ImageFont,
    fill: str = COLOR_TEXT,
    align: str = "left",
    padding_x: int = 14,
) -> None:
    if not text:
        return
    bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=4)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    left, top, right, bottom = box

    if align == "center":
        x = left + ((right - left) - text_width) / 2
    elif align == "right":
        x = right - padding_x - text_width
    else:
        x = left + padding_x

    y = top + ((bottom - top) - text_height) / 2
    draw.multiline_text((x, y), text, font=font, fill=fill, spacing=4)


def _prepare_pdf_logo(filename: str | None) -> Image.Image | None:
    logo_path = resolve_logo_path(filename)
    if not logo_path:
        return None

    with Image.open(logo_path) as raw_logo:
        logo = ImageOps.exif_transpose(raw_logo).convert("RGBA")

    contained = ImageOps.contain(logo, PDF_LOGO_SIZE, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", PDF_LOGO_SIZE, (255, 255, 255, 255))
    offset_x = (PDF_LOGO_SIZE[0] - contained.width) // 2
    offset_y = (PDF_LOGO_SIZE[1] - contained.height) // 2
    canvas.alpha_composite(contained, (offset_x, offset_y))
    return canvas


def _paste_logo(page: Image.Image, settings: dict) -> None:
    logo = _prepare_pdf_logo(settings.get("logo_filename"))
    if not logo:
        return

    left = _column_bounds(0)[0]
    right = _column_bounds(1)[1]
    top = _row_bounds(1)[0]
    bottom = _row_bounds(5)[1]
    box_width = right - left
    box_height = bottom - top
    offset_x = left + ((box_width - logo.width) // 2)
    offset_y = top + ((box_height - logo.height) // 2)
    page.alpha_composite(logo, (offset_x, offset_y))


def _draw_header(page: Image.Image, quote: dict, settings: dict) -> None:
    draw = ImageDraw.Draw(page)

    logo_box = (_column_bounds(0)[0], _row_bounds(1)[0], _column_bounds(1)[1], _row_bounds(5)[1])
    title_box = (_column_bounds(2)[0], _row_bounds(1)[0], _column_bounds(5)[1], _row_bounds(1)[1])
    _draw_box(draw, logo_box)
    _draw_box(draw, title_box, fill=COLOR_TITLE)
    _draw_text(draw, title_box, quote["title"], font=TITLE_FONT, fill=COLOR_TITLE_TEXT, align="center")
    _paste_logo(page, settings)

    row_2_top, row_2_bottom = _row_bounds(2)
    row_3_top, row_3_bottom = _row_bounds(3)
    row_4_top, row_4_bottom = _row_bounds(4)
    row_5_top, row_5_bottom = _row_bounds(5)
    c_left, c_right = _column_bounds(2)
    d_left, d_right = _column_bounds(3)
    e_left, e_right = _column_bounds(4)
    f_left, f_right = _column_bounds(5)

    label_value_rows = [
        (row_2_top, row_2_bottom, "Ubicacion", quote["location"], (c_left, c_right), (d_left, f_right)),
        (row_3_top, row_3_bottom, "Cliente", quote["client_name"], (c_left, c_right), (d_left, f_right)),
    ]

    for top, bottom, label, value, label_cols, value_cols in label_value_rows:
        label_box = (label_cols[0], top, label_cols[1], bottom)
        value_box = (value_cols[0], top, value_cols[1], bottom)
        _draw_box(draw, label_box, fill=COLOR_HEADER)
        _draw_box(draw, value_box)
        _draw_text(draw, label_box, label, font=LABEL_FONT, fill=COLOR_LABEL)
        _draw_text(draw, value_box, value, font=VALUE_FONT, fill=COLOR_TEXT)

    row_4_cells = [
        ((c_left, row_4_top, c_right, row_4_bottom), "Fecha", True),
        ((d_left, row_4_top, d_right, row_4_bottom), _format_date(quote["quote_date"]), False),
        ((e_left, row_4_top, e_right, row_4_bottom), "Solicitado por", True),
        ((f_left, row_4_top, f_right, row_4_bottom), quote["requested_by"], False),
    ]
    row_5_cells = [
        ((c_left, row_5_top, c_right, row_5_bottom), "Cotizacion", True),
        ((d_left, row_5_top, d_right, row_5_bottom), quote["quote_number"], False),
        ((e_left, row_5_top, e_right, row_5_bottom), "Moneda", True),
        ((f_left, row_5_top, f_right, row_5_bottom), quote["currency_code"], False),
    ]

    for box, text, is_label in row_4_cells + row_5_cells:
        _draw_box(draw, box, fill=COLOR_HEADER if is_label else COLOR_PAGE)
        _draw_text(
            draw,
            box,
            text,
            font=LABEL_FONT if is_label else VALUE_FONT,
            fill=COLOR_LABEL if is_label else COLOR_TEXT,
        )


def _draw_blank_row(draw: ImageDraw.ImageDraw, row_number: int) -> None:
    top, bottom = _row_bounds(row_number)
    for column_index in range(6):
        left, right = _column_bounds(column_index)
        _draw_box(draw, (left, top, right, bottom))


def _draw_table_header(draw: ImageDraw.ImageDraw) -> None:
    labels = ["Item", "Descripcion", "Unidad", "Cantidad", "Vr Material", "Vr Total"]
    top, bottom = _row_bounds(7)
    for column_index, label in enumerate(labels):
        left, right = _column_bounds(column_index)
        box = (left, top, right, bottom)
        _draw_box(draw, box, fill=COLOR_HEADER)
        _draw_text(draw, box, label, font=TABLE_HEADER_FONT, fill=COLOR_LABEL, align="center")


def _draw_item_row(draw: ImageDraw.ImageDraw, row_number: int, item: dict | None, rounding_mode: str) -> None:
    top, bottom = _row_bounds(row_number)
    alignments = ("left", "left", "center", "right", "right", "right")
    values = ("", "", "", "", "", "")
    if item:
        values = (
            item.get("sku", ""),
            item.get("description", ""),
            item.get("unit", ""),
            _format_qty(item.get("qty", 0)),
            _format_money(item.get("price_unit", 0), rounding_mode),
            _format_money(item.get("line_total", 0), rounding_mode),
        )

    for column_index, (value, align) in enumerate(zip(values, alignments)):
        left, right = _column_bounds(column_index)
        box = (left, top, right, bottom)
        _draw_box(draw, box)
        text = _fit_text(draw, value, BODY_FONT, max(30, (right - left) - 20))
        _draw_text(draw, box, text, font=BODY_FONT, fill=COLOR_TEXT, align=align, padding_x=10)


def _draw_totals(draw: ImageDraw.ImageDraw, quote: dict, rounding_mode: str) -> None:
    labels = (
        ("Total costos directos", quote["subtotal"]),
        ("IVA", quote["tax_amount"]),
        ("Total", quote["total"]),
    )
    for offset, (label, value) in enumerate(labels, start=29):
        top, bottom = _row_bounds(offset)
        e_left, e_right = _column_bounds(4)
        f_left, f_right = _column_bounds(5)
        label_box = (e_left, top, e_right, bottom)
        value_box = (f_left, top, f_right, bottom)
        _draw_box(draw, label_box, fill=COLOR_HEADER)
        _draw_box(draw, value_box, fill=COLOR_HEADER)
        _draw_text(draw, label_box, label, font=LABEL_FONT, fill=COLOR_LABEL, padding_x=12)
        _draw_text(
            draw,
            value_box,
            _format_money(value, rounding_mode),
            font=BODY_FONT_BOLD,
            fill=COLOR_LABEL,
            align="right",
            padding_x=12,
        )


def _chunk_items(items: list[dict]) -> list[list[dict]]:
    if not items:
        return [[]]
    chunks: list[list[dict]] = []
    start = 0
    while start < len(items):
        chunks.append(items[start : start + ITEMS_PER_PAGE])
        start += ITEMS_PER_PAGE
    return chunks


def _render_page(quote: dict, settings: dict, page_items: list[dict], *, show_totals: bool) -> Image.Image:
    rounding_mode = settings.get("rounding_mode", "integer")
    page = Image.new("RGBA", PAGE_SIZE, COLOR_PAGE)
    draw = ImageDraw.Draw(page)

    _draw_header(page, quote, settings)
    _draw_blank_row(draw, 6)
    _draw_table_header(draw)

    for row_number in range(8, 25):
        item_index = row_number - 8
        item = page_items[item_index] if item_index < len(page_items) else None
        _draw_item_row(draw, row_number, item, rounding_mode)

    for row_number in range(25, 29):
        _draw_blank_row(draw, row_number)

    if show_totals:
        _draw_totals(draw, quote, rounding_mode)
    else:
        for row_number in range(29, 32):
            _draw_blank_row(draw, row_number)

    return page.convert("RGB")


def build_quote_pdf(quote: dict, settings: dict) -> BytesIO:
    item_pages = _chunk_items(quote.get("items") or [])
    rendered_pages = [
        _render_page(quote, settings, page_items, show_totals=index == len(item_pages) - 1)
        for index, page_items in enumerate(item_pages)
    ]

    output = BytesIO()
    first_page, *other_pages = rendered_pages
    first_page.save(output, format="PDF", resolution=200.0, save_all=True, append_images=other_pages)
    output.seek(0)
    return output
