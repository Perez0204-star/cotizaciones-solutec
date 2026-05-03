from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.services.calculations import round_money
from app.services.uploads import resolve_logo_path

PAGE_WIDTH = 1754
PAGE_HEIGHT = 2480
PAGE_SIZE = (PAGE_WIDTH, PAGE_HEIGHT)
MARGIN_X = 88
ITEMS_PER_PAGE = 10

PURPLE = "#06233B"
MAGENTA = "#11B7FF"
ORANGE = "#FF9E2C"
INK = "#2A2338"
SOFT_TEXT = "#5E6078"
MUTED_TEXT = "#8588A3"
BORDER = "#E2DDEC"
CARD = "#FFFFFF"
PAGE = "#F7F4FB"


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


TITLE_FONT = _load_font(78, bold=True)
DOC_NUMBER_FONT = _load_font(50, bold=True)
BRAND_FONT = _load_font(48, bold=True)
SLOGAN_FONT = _load_font(26)
LABEL_FONT = _load_font(23, bold=True)
VALUE_FONT = _load_font(25)
SMALL_FONT = _load_font(21)
TABLE_HEAD_FONT = _load_font(23, bold=True)
TABLE_BODY_FONT = _load_font(24)
TABLE_BODY_BOLD = _load_font(24, bold=True)
TOTAL_FONT = _load_font(34, bold=True)


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[index : index + 2], 16) for index in (0, 2, 4))


def _mix_color(start: tuple[int, int, int], end: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(int(start[index] + (end[index] - start[index]) * factor) for index in range(3))


def _draw_horizontal_gradient(page: Image.Image, box: tuple[int, int, int, int], colors: list[str]) -> None:
    draw = ImageDraw.Draw(page)
    left, top, right, bottom = box
    rgb_colors = [_hex_to_rgb(color) for color in colors]
    span_count = len(rgb_colors) - 1
    width = max(1, right - left)

    for offset in range(width):
        relative = offset / max(1, width - 1)
        scaled = relative * span_count
        start_index = min(span_count - 1, int(scaled))
        end_index = min(span_count, start_index + 1)
        local_factor = scaled - start_index
        color = _mix_color(rgb_colors[start_index], rgb_colors[end_index], local_factor)
        draw.line((left + offset, top, left + offset, bottom), fill=color)


def _rounded_box(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    radius: int = 28,
    fill: str = CARD,
    outline: str = BORDER,
    width: int = 2,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


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


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = str(text or "").split()
    if not words:
        return [""]

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    font: ImageFont.ImageFont,
    fill: str,
    center_x: int,
    top: int,
) -> None:
    text_box = draw.textbbox((0, 0), text, font=font)
    text_width = text_box[2] - text_box[0]
    draw.text((center_x - (text_width / 2), top), text, font=font, fill=fill)


def _format_money(value: object, rounding_mode: str) -> str:
    amount = round_money(value, rounding_mode)
    decimals = 2 if rounding_mode == "2dec" else 0
    text = f"{amount:,.{decimals}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def _format_qty(value: object) -> str:
    amount = float(value or 0)
    text = f"{amount:,.1f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def _format_date(value: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""

    try:
        moment = datetime.fromisoformat(candidate)
    except ValueError:
        return candidate

    month_names = {
        1: "Enero",
        2: "Febrero",
        3: "Marzo",
        4: "Abril",
        5: "Mayo",
        6: "Junio",
        7: "Julio",
        8: "Agosto",
        9: "Septiembre",
        10: "Octubre",
        11: "Noviembre",
        12: "Diciembre",
    }
    return f"{moment.day} de {month_names[moment.month]} de {moment.year}"


def _prepare_pdf_logo(filename: str | None) -> Image.Image | None:
    logo_path = resolve_logo_path(filename)
    if not logo_path:
        return None

    with Image.open(logo_path) as raw_logo:
        logo = ImageOps.exif_transpose(raw_logo).convert("RGBA")

    contained = ImageOps.contain(logo, (240, 240), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (240, 240), (255, 255, 255, 0))
    offset_x = (240 - contained.width) // 2
    offset_y = (240 - contained.height) // 2
    canvas.alpha_composite(contained, (offset_x, offset_y))
    return canvas


def _document_heading(quote: dict) -> str:
    label = (quote.get("document_label") or "").lower()
    return "FACTURA" if label.startswith("factura") else "COTIZACION"


def _company_lines(settings: dict) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    if settings.get("company_nit"):
        lines.append(("NIT", settings["company_nit"]))
    lines.append(("Direccion", settings.get("company_address") or "Direccion pendiente"))
    lines.append(("Telefono", settings.get("company_phone") or "Pendiente"))
    lines.append(("Correo", settings.get("company_email") or "Pendiente"))
    return lines


def _draw_background(page: Image.Image) -> None:
    _draw_horizontal_gradient(page, (74, 94, PAGE_WIDTH - 74, 198), [PURPLE, MAGENTA, ORANGE])
    draw = ImageDraw.Draw(page)
    _rounded_box(draw, (74, 126, PAGE_WIDTH - 74, PAGE_HEIGHT - 108), radius=42, fill="#FFFDFE", outline="#E9E0F1", width=2)

    draw.arc((110, 164, PAGE_WIDTH - 110, 1040), start=180, end=355, fill="#E6DDF0", width=4)
    draw.arc((130, 188, PAGE_WIDTH - 130, 1110), start=185, end=350, fill="#F0E8F7", width=2)

    for x in range(118, PAGE_WIDTH - 130, 148):
        y = 124 + ((x // 52) % 4) * 14
        draw.line((x, y, x + 88, y), fill=(255, 255, 255, 120), width=3)
        draw.ellipse((x + 82, y - 6, x + 94, y + 6), fill=(255, 255, 255, 150))


def _draw_header(page: Image.Image, quote: dict, settings: dict) -> None:
    draw = ImageDraw.Draw(page)
    logo = _prepare_pdf_logo(settings.get("logo_filename"))

    left = MARGIN_X
    top = 180
    right = PAGE_WIDTH - MARGIN_X

    brand_box = (left, top, right, 520)
    _rounded_box(draw, brand_box, radius=34)

    logo_box = (brand_box[0] + 24, brand_box[1] + 24, brand_box[0] + 230, brand_box[1] + 230)
    _rounded_box(draw, logo_box, radius=24, fill="#FCFDFF")
    if logo:
        page.alpha_composite(logo, (logo_box[0] - 4, logo_box[1] - 4))

    brand_x = logo_box[2] + 26
    info_right = brand_box[2] - 26
    info_center_x = int((brand_x + info_right) / 2)
    _draw_centered_text(
        draw,
        settings.get("org_name") or "Technological World",
        font=BRAND_FONT,
        fill=INK,
        center_x=info_center_x,
        top=brand_box[1] + 38,
    )
    _draw_centered_text(
        draw,
        settings.get("brand_slogan") or "Conectamos ideas con tecnologia",
        font=SLOGAN_FONT,
        fill=SOFT_TEXT,
        center_x=info_center_x,
        top=brand_box[1] + 94,
    )

    info_y = brand_box[1] + 142
    info_width = info_right - brand_x
    info_columns = 3
    info_gap = 10
    info_box_width = (info_width - info_gap) // info_columns
    info_box_height = 82
    company_lines = _company_lines(settings)

    for index, (label, value) in enumerate(company_lines):
        row = index // info_columns
        column = index % info_columns
        box_left = brand_x + (info_box_width + info_gap) * column
        box_top = info_y + row * (info_box_height + 12)
        box = (box_left, box_top, box_left + info_box_width, box_top + info_box_height)
        _rounded_box(draw, box, radius=18, fill="#FAFCFF", outline="#E6E1F0")
        _draw_centered_text(
            draw,
            label.upper(),
            font=SMALL_FONT,
            fill=MUTED_TEXT,
            center_x=int((box_left + box[2]) / 2),
            top=box_top + 12,
        )
        _draw_centered_text(
            draw,
            _fit_text(draw, value, VALUE_FONT, info_box_width - 28),
            font=VALUE_FONT,
            fill=INK,
            center_x=int((box_left + box[2]) / 2),
            top=box_top + 44,
        )


def _draw_summary_cards(page: Image.Image, quote: dict) -> None:
    draw = ImageDraw.Draw(page)
    left = MARGIN_X
    top = 564
    right = PAGE_WIDTH - MARGIN_X
    gap = 18
    card_width = (right - left - gap) // 2

    document_box = (left, top, left + card_width, top + 248)
    client_box = (left + card_width + gap, top, right, top + 248)
    _rounded_box(draw, document_box, radius=28)
    _rounded_box(draw, client_box, radius=28)

    heading = _document_heading(quote)
    document_number = quote.get("document_number") or quote.get("quote_number") or ""

    draw.text((document_box[0] + 22, document_box[1] + 20), heading, font=LABEL_FONT, fill=MAGENTA)
    draw.text((document_box[0] + 22, document_box[1] + 52), document_number, font=_load_font(42, bold=True), fill=INK)

    document_rows = [
        ("Fecha", _format_date(quote.get("quote_date") or "")),
    ]
    row_y = document_box[1] + 118
    for label, value in document_rows:
        draw.line((document_box[0] + 22, row_y - 8, document_box[2] - 22, row_y - 8), fill="#ECE6F3", width=2)
        draw.text((document_box[0] + 22, row_y + 4), label.upper(), font=SMALL_FONT, fill=MUTED_TEXT)
        draw.text((document_box[0] + 180, row_y + 2), value, font=VALUE_FONT, fill=INK)
        row_y += 38

    draw.text((client_box[0] + 22, client_box[1] + 20), "DATOS DEL CLIENTE", font=LABEL_FONT, fill=MUTED_TEXT)
    draw.text((client_box[0] + 22, client_box[1] + 52), _fit_text(draw, quote.get("client_name") or "No registrado", _load_font(38, bold=True), card_width - 44), font=_load_font(38, bold=True), fill=INK)

    client_document = f"{quote.get('client_document_type') or ''} {quote.get('client_document_number') or ''}".strip()
    contact_parts = [value for value in [quote.get("client_phone") or "", quote.get("client_email") or ""] if value]
    client_rows = []
    if client_document:
        client_rows.append(("Documento", client_document))
    client_rows.extend(
        [
            ("Contacto", " · ".join(contact_parts) if contact_parts else "No registrado"),
        ("Direccion", quote.get("client_address") or "Sin direccion registrada"),
        ]
    )
    row_y = client_box[1] + 112
    for label, value in client_rows:
        draw.line((client_box[0] + 22, row_y - 8, client_box[2] - 22, row_y - 8), fill="#ECE6F3", width=2)
        draw.text((client_box[0] + 22, row_y + 4), label.upper(), font=SMALL_FONT, fill=MUTED_TEXT)
        draw.text((client_box[0] + 180, row_y + 2), _fit_text(draw, value, VALUE_FONT, card_width - 222), font=VALUE_FONT, fill=INK)
        row_y += 36


def _draw_items_table(page: Image.Image, quote: dict, items: list[dict], start_y: int, rounding_mode: str) -> int:
    draw = ImageDraw.Draw(page)
    left = MARGIN_X
    right = PAGE_WIDTH - MARGIN_X
    table_width = right - left
    column_widths = [210, 620, 140, 240, 210]
    row_height = 74
    header_height = 58
    columns = ["CODIGO", "DESCRIPCION", "CANT.", "P.UNITARIO", "TOTAL"]

    x = left
    for width, heading in zip(column_widths, columns):
        _draw_horizontal_gradient(page, (x, start_y, x + width, start_y + header_height), [PURPLE, MAGENTA, ORANGE])
        draw.rectangle((x, start_y, x + width, start_y + header_height), outline="#E7E1EF", width=1)
        text_box = draw.textbbox((0, 0), heading, font=TABLE_HEAD_FONT)
        text_width = text_box[2] - text_box[0]
        draw.text((x + (width - text_width) / 2, start_y + 18), heading, font=TABLE_HEAD_FONT, fill="#FFFFFF")
        x += width

    current_y = start_y + header_height
    for item in items:
        x = left
        cells = [
            item.get("sku") or "-",
            item.get("description") or "",
            _format_qty(item.get("qty", 0)),
            _format_money(item.get("price_unit", 0), rounding_mode),
            _format_money(item.get("line_total", 0), rounding_mode),
        ]

        for index, (width, value) in enumerate(zip(column_widths, cells)):
            draw.rectangle((x, current_y, x + width, current_y + row_height), fill="#FFFFFF", outline="#E7E1EF", width=1)
            if index == 0:
                draw.text((x + 16, current_y + 24), _fit_text(draw, value, TABLE_BODY_BOLD, width - 32), font=TABLE_BODY_BOLD, fill=INK)
            elif index == 1:
                draw.text((x + 16, current_y + 14), _fit_text(draw, value, TABLE_BODY_BOLD, width - 32), font=TABLE_BODY_BOLD, fill=INK)
                unit_label = item.get("unit") or "-"
                if not item.get("taxable", 1):
                    unit_label = f"{unit_label} - SIN IVA"
                draw.text((x + 16, current_y + 44), _fit_text(draw, unit_label, SMALL_FONT, width - 32), font=SMALL_FONT, fill=MUTED_TEXT)
            else:
                text_box = draw.textbbox((0, 0), value, font=TABLE_BODY_FONT)
                text_width = text_box[2] - text_box[0]
                draw.text((x + width - 16 - text_width, current_y + 22), value, font=TABLE_BODY_FONT, fill=INK)
            x += width

        current_y += row_height

    return current_y


def _draw_footer(page: Image.Image, quote: dict, table_bottom: int, rounding_mode: str) -> None:
    draw = ImageDraw.Draw(page)
    left = MARGIN_X
    right = PAGE_WIDTH - MARGIN_X
    top = table_bottom + 22

    notes_text = str(quote.get("notes") or "").strip()
    show_notes = bool(notes_text)
    if show_notes:
        notes_box = (left, top, 1100, top + 250)
        totals_box = (1118, top, right, top + 250)
    else:
        notes_box = None
        totals_box = (right - 520, top, right, top + 250)

    if notes_box:
        _rounded_box(draw, notes_box, radius=28)
    _rounded_box(draw, totals_box, radius=28)

    if notes_box:
        _draw_horizontal_gradient(page, (notes_box[0], notes_box[1], notes_box[2], notes_box[1] + 56), [PURPLE, MAGENTA])
        draw.text((notes_box[0] + 22, notes_box[1] + 15), "OBSERVACIONES", font=TABLE_HEAD_FONT, fill="#FFFFFF")
        notes_lines = _wrap_text(draw, notes_text, VALUE_FONT, notes_box[2] - notes_box[0] - 44)
        current_y = notes_box[1] + 78
        for line in notes_lines[:6]:
            draw.text((notes_box[0] + 22, current_y), line, font=VALUE_FONT, fill=SOFT_TEXT)
            current_y += 34

    rows = [
        ("Subtotal", _format_money(quote.get("subtotal", 0), rounding_mode)),
        (f"IVA gravado ({quote.get('tax_rate', 0):.0f}%)", _format_money(quote.get("tax_amount", 0), rounding_mode)),
    ]
    current_y = totals_box[1] + 28
    for label, value in rows:
        draw.text((totals_box[0] + 22, current_y), label, font=LABEL_FONT, fill=SOFT_TEXT)
        value_box = draw.textbbox((0, 0), value, font=LABEL_FONT)
        draw.text((totals_box[2] - 22 - (value_box[2] - value_box[0]), current_y), value, font=LABEL_FONT, fill=INK)
        draw.line((totals_box[0] + 22, current_y + 38, totals_box[2] - 22, current_y + 38), fill="#E7E1EF", width=2)
        current_y += 48

    total_row = (totals_box[0] + 18, totals_box[1] + 136, totals_box[2] - 18, totals_box[1] + 214)
    _draw_horizontal_gradient(page, total_row, [PURPLE, MAGENTA, ORANGE])
    draw.rounded_rectangle(total_row, radius=18, outline="#FFFFFF", width=0)
    draw.text((total_row[0] + 18, total_row[1] + 21), "TOTAL", font=TOTAL_FONT, fill="#FFFFFF")
    total_value = _format_money(quote.get("total", 0), rounding_mode)
    value_box = draw.textbbox((0, 0), total_value, font=TOTAL_FONT)
    draw.text((total_row[2] - 18 - (value_box[2] - value_box[0]), total_row[1] + 21), total_value, font=TOTAL_FONT, fill="#FFFFFF")

    thanks = str(quote.get("closing_message") or "").strip()
    if thanks:
        thanks_box = draw.textbbox((0, 0), thanks, font=VALUE_FONT)
        draw.text(((PAGE_WIDTH - (thanks_box[2] - thanks_box[0])) / 2, top + 270), thanks, font=VALUE_FONT, fill=SOFT_TEXT)


def _render_page(quote: dict, settings: dict, page_items: list[dict], *, show_totals: bool) -> Image.Image:
    page = Image.new("RGBA", PAGE_SIZE, PAGE)
    _draw_background(page)
    _draw_header(page, quote, settings)
    rounding_mode = settings.get("rounding_mode", "integer")

    if show_totals:
        _draw_summary_cards(page, quote)
        table_top = 828
    else:
        table_top = 560

    table_bottom = _draw_items_table(page, quote, page_items, table_top, rounding_mode)

    if show_totals:
        _draw_footer(page, quote, table_bottom, rounding_mode)

    return page.convert("RGB")


def _chunk_items(items: list[dict]) -> list[list[dict]]:
    if not items:
        return [[]]

    chunks: list[list[dict]] = []
    start = 0
    while start < len(items):
        chunks.append(items[start : start + ITEMS_PER_PAGE])
        start += ITEMS_PER_PAGE
    return chunks


def build_quote_pdf(quote: dict, settings: dict) -> BytesIO:
    item_pages = _chunk_items(quote.get("items") or [])
    rendered_pages = [
        _render_page(
            quote,
            settings,
            page_items,
            show_totals=index == len(item_pages) - 1,
        )
        for index, page_items in enumerate(item_pages)
    ]

    output = BytesIO()
    first_page, *other_pages = rendered_pages
    first_page.save(output, format="PDF", resolution=200.0, save_all=True, append_images=other_pages)
    output.seek(0)
    return output
