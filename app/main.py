from __future__ import annotations

import json
import os
import base64
import binascii
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import (
    BASE_DIR,
    CATALOG_CATEGORY_LABELS,
    DEFAULT_CATALOG_CATEGORY,
    PRIMARY_PLATFORM_SLUG,
    add_catalog_item_image,
    apply_client_credit_payment,
    bind_google_identity,
    clear_password_recovery_code,
    confirm_catalog_order_payment,
    confirm_quote_invoice_payment,
    create_user,
    create_platform_workspace,
    create_catalog_order,
    current_platform_slug,
    current_uploads_dir,
    delete_client,
    delete_client_credit,
    delete_catalog_item,
    delete_platform_workspace,
    create_quote,
    delete_user,
    delete_quote,
    ensure_storage,
    fetch_settings,
    find_user_for_login,
    get_platform,
    get_catalog_item,
    get_catalog_order,
    get_client,
    get_client_credit,
    get_password_recovery_code,
    get_quote,
    get_user_by_email,
    get_user_by_id,
    get_user_by_google_subject,
    has_users,
    init_db,
    list_platforms,
    list_catalog_item_images,
    list_users,
    list_client_credits,
    list_catalog_orders,
    list_catalog_items,
    list_clients,
    list_quotes,
    link_catalog_order_quote,
    normalize_catalog_category,
    prune_expired_password_recovery_codes,
    save_catalog_item,
    save_client,
    save_client_credit,
    send_catalog_order_to_credit,
    send_quote_to_credit,
    store_password_recovery_code,
    delete_catalog_item_images,
    update_catalog_order_status,
    update_quote_status,
    update_user_password,
    update_user_profile,
    update_quote,
    update_settings,
    use_platform,
)
from app.services.auth import (
    SESSION_COOKIE_NAME,
    build_session_token,
    derive_username_from_email,
    generate_email_recovery_code,
    get_recovery_code,
    hash_ephemeral_code,
    hash_password,
    normalize_email,
    normalize_identity,
    normalize_username,
    read_session_user_id,
    session_cookie_options,
    validate_password_confirmation,
    verify_ephemeral_code,
    verify_recovery_code,
    verify_password,
)
from app.services.calculations import (
    line_financials,
    legacy_factor_from_margin,
    margin_percent_from_price,
    normalize_margin_percent,
    quote_totals,
    round_money,
    suggested_sale_price,
    to_decimal,
)
from app.services.communications import email_delivery_enabled, send_password_recovery_email
from app.services.google_oauth import (
    build_google_authorize_url,
    exchange_google_code,
    fetch_google_userinfo,
    generate_google_state,
    google_oauth_enabled,
)
from app.services.pdf_export import build_quote_pdf
from app.services.uploads import delete_logo, delete_uploaded_image, save_catalog_image, save_logo

app = FastAPI(title="Cotizaciones Web")

ensure_storage()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")

GOOGLE_STATE_COOKIE = "cotizaciones_google_state"
GOOGLE_NEXT_COOKIE = "cotizaciones_google_next"
PLATFORM_COOKIE_NAME = "cotizaciones_platform"
AUTH_PLATFORM_OPTIONAL_PATHS = {
    "/login",
    "/password-recovery",
    "/password-recovery/send-code",
    "/setup",
}
PRIMARY_PUBLIC_BRANDING = {
    "org_name": "Technological World",
    "brand_slogan": "Conectamos ideas con tecnologia",
    "logo_filename": "logo_tw_original_brand.png",
}


def money_filter(value: object, rounding_mode: str = "integer") -> str:
    amount = round_money(value, rounding_mode)
    decimals = 2 if rounding_mode == "2dec" else 0
    return f"{amount:,.{decimals}f}"


def percent_filter(value: object) -> str:
    return f"{to_decimal(value):,.2f}"


def display_date_filter(value: object) -> str:
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


def category_label_filter(value: object) -> str:
    return CATALOG_CATEGORY_LABELS.get(str(value or "").upper(), "SIN CATEGORIA")


templates.env.filters["money"] = money_filter
templates.env.filters["percent"] = percent_filter
templates.env.filters["display_date"] = display_date_filter
templates.env.filters["category_label"] = category_label_filter


@app.on_event("startup")
def startup() -> None:
    init_db()
    prune_expired_password_recovery_codes()


def enrich_catalog_item(item: dict, rounding_mode: str) -> dict:
    item = dict(item)
    item["category"] = normalize_catalog_category(item.get("category"))
    item["category_label"] = category_label_filter(item["category"])
    suggested_price = suggested_sale_price(
        cost_amount=item["cost_amount"],
        pricing_mode=item["pricing_mode"],
        margin_pct=item["margin_pct"],
        markup_pct=item["markup_pct"],
        manual_price=item["manual_price"],
        rounding_mode=rounding_mode,
    )
    item["suggested_price"] = float(suggested_price)
    item["margin_real"] = float(margin_percent_from_price(item["cost_amount"], suggested_price))
    images = []
    if item.get("id"):
        images = [
            {
                **image,
                "url": media_src(image["filename"]),
            }
            for image in list_catalog_item_images(int(item["id"]))
        ]
    legacy_filename = item.get("image_filename")
    if legacy_filename and not any(image.get("filename") == legacy_filename for image in images):
        images.insert(
            0,
            {
                "id": "",
                "item_id": item.get("id"),
                "filename": legacy_filename,
                "mime": item.get("image_mime") or "image/png",
                "sort_order": 1,
                "url": media_src(legacy_filename),
            },
        )
    item["images"] = images
    item["image_url"] = images[0]["url"] if images else None
    item["video_url"] = (item.get("video_url") or "").strip()
    item["video_embed_url"] = build_video_embed_url(item["video_url"])
    return item


def catalog_category_sections(items: list[dict]) -> list[dict]:
    sections: list[dict] = []
    for code, label in CATALOG_CATEGORY_LABELS.items():
        category_items = [item for item in items if item.get("category") == code]
        sections.append(
            {
                "code": code,
                "slug": code.lower(),
                "label": label,
                "items": category_items,
                "count": len(category_items),
            }
        )
    return sections


def catalog_category_options() -> list[dict[str, str]]:
    return [{"code": code, "label": label} for code, label in CATALOG_CATEGORY_LABELS.items()]


def whatsapp_number_from_settings(settings: dict) -> str:
    candidate = str(settings.get("company_whatsapp") or settings.get("company_phone") or "").strip()
    if not candidate:
        return ""

    try:
        parsed = urlparse(candidate)
    except ValueError:
        parsed = None

    if parsed and parsed.netloc:
        host = parsed.netloc.lower()
        query = parse_qs(parsed.query or "")
        if "wa.me" in host:
            candidate = parsed.path.strip("/")
        elif "whatsapp.com" in host:
            candidate = (query.get("phone") or [candidate])[0]

    digits = "".join(ch for ch in candidate if ch.isdigit())
    if len(digits) == 10 and digits.startswith("3"):
        return f"57{digits}"
    return digits


def decode_catalog_cart(cart_payload: str | None) -> list[dict]:
    candidate = (cart_payload or "").strip()
    if not candidate:
        return []

    try:
        padding = "=" * (-len(candidate) % 4)
        decoded = base64.urlsafe_b64decode(f"{candidate}{padding}".encode("ascii")).decode("utf-8")
        raw_items = json.loads(decoded)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error):
        return []

    if not isinstance(raw_items, list):
        return []

    items = []
    for raw_item in raw_items[:50]:
        if not isinstance(raw_item, dict):
            continue
        try:
            item_id = int(raw_item.get("id"))
        except (TypeError, ValueError):
            continue
        qty = to_decimal(raw_item.get("qty"), "1")
        if qty <= 0:
            qty = Decimal("1")
        items.append({"id": item_id, "qty": float(qty)})
    return items


def catalog_cart_to_quote_items(cart_payload: str | None, rounding_mode: str) -> list[dict]:
    quote_items = []
    for entry in decode_catalog_cart(cart_payload):
        item = get_catalog_item(entry["id"])
        if not item or not int(item.get("active") or 0):
            continue
        enriched = enrich_catalog_item(item, rounding_mode)
        price_unit = enriched["suggested_price"]
        qty = entry["qty"]
        line = line_financials(
            qty=qty,
            price_unit=price_unit,
            discount_type="PERCENT",
            discount_value=0,
            rounding_mode=rounding_mode,
        )
        quote_items.append(
            {
                "source_item_id": enriched["id"],
                "sku": enriched["sku"],
                "description": enriched["description"],
                "unit": enriched["unit"],
                "qty": float(line["qty"]),
                "cost_amount": enriched["cost_amount"],
                "base_price_unit": price_unit,
                "price_unit": float(line["price_unit"]),
                "taxable": 1 if enriched.get("taxable") else 0,
                "discount_type": "PERCENT",
                "discount_value": 0,
                "line_subtotal": float(line["line_subtotal"]),
                "line_discount": float(line["line_discount"]),
                "line_total": float(line["line_total"]),
            }
        )
    return quote_items


def catalog_order_to_quote_items(order: dict, rounding_mode: str) -> list[dict]:
    quote_items = []
    for order_item in order.get("items", []):
        line = line_financials(
            qty=order_item.get("qty") or 1,
            price_unit=order_item.get("price_unit") or 0,
            discount_type="PERCENT",
            discount_value=0,
            rounding_mode=rounding_mode,
        )
        quote_items.append(
            {
                "source_item_id": order_item.get("catalog_item_id"),
                "sku": order_item.get("sku") or "",
                "description": order_item.get("description") or "",
                "unit": order_item.get("unit") or "UND",
                "qty": float(line["qty"]),
                "cost_amount": 0,
                "base_price_unit": float(line["price_unit"]),
                "price_unit": float(line["price_unit"]),
                "taxable": 1 if order_item.get("taxable") else 0,
                "discount_type": "PERCENT",
                "discount_value": 0,
                "line_subtotal": float(line["line_subtotal"]),
                "line_discount": float(line["line_discount"]),
                "line_total": float(line["line_total"]),
            }
        )
    return quote_items


def cart_entries_to_order_items(raw_items: object, rounding_mode: str) -> list[dict]:
    if not isinstance(raw_items, list):
        raise ValueError("El carrito no tiene productos validos.")

    order_items = []
    for raw_item in raw_items[:50]:
        if not isinstance(raw_item, dict):
            continue
        try:
            item_id = int(raw_item.get("id"))
        except (TypeError, ValueError):
            continue

        item = get_catalog_item(item_id)
        if not item or not int(item.get("active") or 0):
            continue

        qty = to_decimal(raw_item.get("qty"), "1")
        if qty <= 0:
            qty = Decimal("1")
        stock = to_decimal(item.get("available_qty"), "0")
        if stock <= 0:
            raise ValueError(f"{item['description']} no tiene inventario disponible.")
        if qty > stock:
            raise ValueError(f"Solo hay {stock:g} unidades disponibles de {item['description']}.")

        enriched = enrich_catalog_item(item, rounding_mode)
        price_unit = to_decimal(enriched["suggested_price"])
        line_total = round_money(qty * price_unit, rounding_mode)
        order_items.append(
            {
                "catalog_item_id": int(enriched["id"]),
                "sku": enriched["sku"],
                "description": enriched["description"],
                "unit": enriched["unit"],
                "qty": float(qty),
                "price_unit": float(price_unit),
                "taxable": 1 if enriched.get("taxable") else 0,
                "line_total": float(line_total),
            }
        )

    if not order_items:
        raise ValueError("Debes agregar al menos un producto al pedido.")
    return order_items


def quote_payload_from_order(order: dict, quote_items: list[dict], settings: dict) -> dict:
    totals = quote_totals(
        line_totals=[item["line_total"] for item in quote_items],
        tax_rate=settings["iva_rate"],
        rounding_mode=settings["rounding_mode"],
        taxable_flags=[item["taxable"] for item in quote_items],
    )
    return {
        "title": "COTIZACION EXPLORATORIA",
        "location": (order.get("customer_address") or "").strip(),
        "client_type": "CONSUMER",
        "client_name": (order.get("customer_name") or "Consumidor final").strip(),
        "client_document_type": "",
        "client_document_number": "",
        "client_email": "",
        "client_phone": (order.get("customer_phone") or "").strip(),
        "client_address": (order.get("customer_address") or "").strip(),
        "requested_by": "Pedido web",
        "quote_date": date.today().isoformat(),
        "currency_code": settings["currency_code"],
        "price_factor": 1,
        "price_margin_pct": 100,
        "tax_rate": float(to_decimal(settings["iva_rate"])),
        "subtotal": float(totals["subtotal"]),
        "tax_amount": float(totals["tax_amount"]),
        "total": float(totals["total"]),
        "status": "PENDING",
        "notes": f"Pedido generado automaticamente desde catalogo: {order.get('order_number')}.",
        "closing_message": "Gracias por elegirnos.",
    }


def ensure_quote_for_catalog_order(order: dict, settings: dict) -> dict:
    existing_quote_id = order.get("quote_id")
    if existing_quote_id:
        existing_quote = get_quote(int(existing_quote_id))
        if existing_quote:
            return existing_quote

    quote_items = catalog_order_to_quote_items(order, settings["rounding_mode"])
    quote_id = create_quote(quote_payload_from_order(order, quote_items, settings), quote_items)
    link_catalog_order_quote(int(order["id"]), quote_id, "QUOTED")
    quote = get_quote(quote_id)
    if not quote:
        raise ValueError("No fue posible generar la cotizacion automatica.")
    return quote


def phone_digits(value: object) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def find_or_create_client_from_order(order: dict) -> int:
    normalized_phone = phone_digits(order.get("customer_phone"))
    normalized_name = (order.get("customer_name") or "").strip().lower()
    normalized_address = (order.get("customer_address") or "").strip().lower()

    for client in list_clients():
        if normalized_phone and phone_digits(client.get("phone")) == normalized_phone:
            return int(client["id"])
        if (
            normalized_name
            and (client.get("name") or "").strip().lower() == normalized_name
            and (client.get("address") or "").strip().lower() == normalized_address
        ):
            return int(client["id"])

    return save_client(
        {
            "client_type": "CONSUMER",
            "name": order.get("customer_name") or "Consumidor final",
            "phone": order.get("customer_phone") or "",
            "address": order.get("customer_address") or "",
            "document_type": "",
            "document_number": "",
            "email": "",
        }
    )


def find_or_create_client_from_quote(quote: dict) -> int:
    normalized_document = (quote.get("client_document_number") or "").strip().lower()
    normalized_phone = phone_digits(quote.get("client_phone"))
    normalized_name = (quote.get("client_name") or "").strip().lower()
    normalized_address = (quote.get("client_address") or "").strip().lower()

    for client in list_clients():
        if normalized_document and (client.get("document_number") or "").strip().lower() == normalized_document:
            return int(client["id"])
        if normalized_phone and phone_digits(client.get("phone")) == normalized_phone:
            return int(client["id"])
        if (
            normalized_name
            and (client.get("name") or "").strip().lower() == normalized_name
            and (client.get("address") or "").strip().lower() == normalized_address
        ):
            return int(client["id"])

    return save_client(
        {
            "client_type": normalize_client_type(quote.get("client_type"), allow_consumer=True),
            "name": quote.get("client_name") or "Consumidor final",
            "phone": quote.get("client_phone") or "",
            "address": quote.get("client_address") or "",
            "document_type": quote.get("client_document_type") or "",
            "document_number": quote.get("client_document_number") or "",
            "email": quote.get("client_email") or "",
        }
    )


def order_status_label(status: str) -> str:
    labels = {
        "NEW": "Nuevo",
        "CONTACTED": "Contactado",
        "QUOTED": "Cotizado",
        "INVOICED": "Facturado",
        "PAID": "Pagado",
        "CREDIT": "Credito",
        "CLOSED": "Cerrado",
    }
    return labels.get((status or "").upper(), status or "Nuevo")


def payment_status_label(status: str) -> str:
    labels = {
        "PENDING": "Pendiente",
        "PAID": "Pagado",
        "CREDIT": "Credito",
    }
    return labels.get((status or "").upper(), status or "Pendiente")


def quote_status_label(status: str) -> str:
    labels = {
        "PENDING": "Pendiente",
        "APPROVED": "Aprobada",
        "REJECTED": "Rechazada",
        "INVOICED": "Facturada",
        "PAID": "Pagada",
        "CREDIT": "Credito",
    }
    return labels.get((status or "").upper(), status or "Pendiente")


def credit_status_label(status: str) -> str:
    labels = {
        "PENDING": "Pendiente",
        "PARTIAL": "Abono parcial",
        "PAID": "Pagado",
        "OVERDUE": "Vencido",
    }
    return labels.get((status or "").upper(), status or "Pendiente")


def build_video_embed_url(video_url: str | None) -> str | None:
    candidate = (video_url or "").strip()
    if not candidate:
        return None

    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None

    host = parsed.netloc.lower()
    path = parsed.path or ""
    query = parse_qs(parsed.query or "")

    if "youtu.be" in host:
        video_id = path.strip("/").split("/")[0]
        return f"https://www.youtube.com/embed/{video_id}" if video_id else None

    if "youtube.com" in host:
        if path == "/watch":
            video_id = (query.get("v") or [""])[0]
            return f"https://www.youtube.com/embed/{video_id}" if video_id else None
        if path.startswith("/embed/"):
            video_id = path.split("/embed/", 1)[1].split("/", 1)[0]
            return f"https://www.youtube.com/embed/{video_id}" if video_id else None
        if path.startswith("/shorts/"):
            video_id = path.split("/shorts/", 1)[1].split("/", 1)[0]
            return f"https://www.youtube.com/embed/{video_id}" if video_id else None

    if "vimeo.com" in host:
        video_id = path.strip("/").split("/")[0]
        return f"https://player.vimeo.com/video/{video_id}" if video_id else None

    return None


def normalize_video_url(video_url: str | None) -> str:
    candidate = (video_url or "").strip()
    if not candidate:
        return ""
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("El enlace del video debe iniciar con http:// o https:// y ser valido.")
    return candidate


def invoice_number_for_quote(quote: dict) -> str:
    quote_number = (quote.get("quote_number") or "").strip()
    suffix = quote_number.split("-", 1)[1] if "-" in quote_number else quote_number
    return f"FAC-{suffix or '000001'}"


def list_invoice_documents(search: str = "") -> list[dict]:
    normalized_search = (search or "").strip().lower()
    invoices: list[dict] = []
    for quote in list_quotes(limit=None, statuses=("INVOICED", "PAID", "CREDIT")):
        invoice = normalize_quote_form_data(quote)
        invoice["invoice_number"] = invoice_number_for_quote(invoice)
        haystack = " ".join(
            str(value or "")
            for value in (
                invoice["invoice_number"],
                invoice.get("quote_number"),
                invoice.get("title"),
                invoice.get("client_name"),
                invoice.get("client_phone"),
                invoice.get("client_address"),
                invoice.get("location"),
                invoice.get("quote_date"),
                invoice.get("status"),
                invoice.get("total"),
            )
        ).lower()
        if normalized_search and normalized_search not in haystack:
            continue
        invoices.append(invoice)
    return invoices


def invoice_document_payload(quote: dict) -> dict:
    invoice = dict(quote)
    invoice["title"] = "FACTURA DE VENTA"
    invoice["document_label"] = "Factura de venta"
    invoice["document_number"] = invoice_number_for_quote(quote)
    invoice["source_quote_id"] = int(quote["id"])
    return invoice


def normalize_client_type(value: str | None, *, allow_consumer: bool = False) -> str:
    candidate = (value or "").strip().upper()
    valid_values = {"BUSINESS", "PERSONAL"}
    if allow_consumer:
        valid_values.add("CONSUMER")
    return candidate if candidate in valid_values else "BUSINESS"


def is_consumer_final_value(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "on", "yes", "si"}


def normalize_quote_form_data(form_data: dict | None) -> dict:
    values = dict(form_data or {})
    client_type = normalize_client_type(
        values.get("client_type") or ("CONSUMER" if is_consumer_final_value(values.get("consumer_final")) else "BUSINESS"),
        allow_consumer=True,
    )
    values["client_type"] = client_type
    values["consumer_final"] = 1 if client_type == "CONSUMER" or is_consumer_final_value(values.get("consumer_final")) else 0
    values.setdefault("client_phone", "")
    values.setdefault("client_address", "")
    values.setdefault("client_document_type", "")
    values.setdefault("client_document_number", "")
    values.setdefault("client_email", "")
    values.setdefault("closing_message", "Gracias por su atencion.")
    return values


def client_type_label(client_type: str | None) -> str:
    normalized = normalize_client_type(client_type, allow_consumer=True)
    if normalized == "PERSONAL":
        return "Persona natural"
    if normalized == "CONSUMER":
        return "Consumidor final"
    return "Empresa"


def recoverable_admin_email(email: str) -> dict | None:
    user = get_user_by_email(email)
    if not user:
        return None
    if not user.get("is_admin"):
        return None
    if not (user.get("email") or "").strip():
        return None
    return user


def derive_brand_initials(name: str | None) -> str:
    words = [segment for segment in str(name or "").replace("-", " ").split() if segment]
    initials = "".join(word[0].upper() for word in words[:3] if word[:1].isalnum())
    if initials:
        return initials
    fallback = "".join(ch for ch in str(name or "").upper() if ch.isalnum())
    return fallback[:2] or "TW"


def resolve_request_platform_slug(request: Request) -> str:
    requested = (request.query_params.get("platform") or "").strip()
    if not requested:
        if request.url.path in AUTH_PLATFORM_OPTIONAL_PATHS:
            requested = PRIMARY_PLATFORM_SLUG
        else:
            requested = request.cookies.get(PLATFORM_COOKIE_NAME) or PRIMARY_PLATFORM_SLUG
    platform = get_platform(requested)
    return platform["slug"] if platform else PRIMARY_PLATFORM_SLUG


def current_platform_query() -> str:
    slug = current_platform_slug()
    if slug == PRIMARY_PLATFORM_SLUG:
        return ""
    return f"?platform={quote(slug)}"


def with_platform_query(path: str) -> str:
    slug = current_platform_slug()
    if slug == PRIMARY_PLATFORM_SLUG:
        return path
    separator = "&" if "?" in path else "?"
    return f"{path}{separator}platform={quote(slug)}"


def media_src(filename: str | None) -> str | None:
    if not filename:
        return None
    return with_platform_query(f"/media/{filename}")


def public_branding(settings: dict) -> dict:
    branding = {
        "org_name": settings.get("org_name") or PRIMARY_PUBLIC_BRANDING["org_name"],
        "brand_slogan": settings.get("brand_slogan") or PRIMARY_PUBLIC_BRANDING["brand_slogan"],
        "logo_filename": settings.get("logo_filename"),
    }
    if current_platform_slug() != PRIMARY_PLATFORM_SLUG:
        return branding

    primary_logo = PRIMARY_PUBLIC_BRANDING["logo_filename"]
    with use_platform(PRIMARY_PLATFORM_SLUG):
        primary_logo_exists = (current_uploads_dir() / primary_logo).exists()

    return {
        "org_name": PRIMARY_PUBLIC_BRANDING["org_name"],
        "brand_slogan": PRIMARY_PUBLIC_BRANDING["brand_slogan"],
        "logo_filename": primary_logo if primary_logo_exists else branding.get("logo_filename"),
    }


def base_context(request: Request, **context) -> dict:
    settings = fetch_settings()
    login_branding = public_branding(settings)
    return {
        "request": request,
        "settings": settings,
        "brand_initials": derive_brand_initials(settings.get("org_name")),
        "public_branding": login_branding,
        "public_brand_initials": derive_brand_initials(login_branding.get("org_name")),
        "platform_slug": current_platform_slug(),
        "platforms": list_platforms(),
        "platform_query": current_platform_query(),
        "media_src": media_src,
        "current_user": getattr(request.state, "current_user", None),
        **context,
    }


def is_public_path(path: str) -> bool:
    if path.startswith("/static") or path.startswith("/media"):
        return True
    if path.startswith("/auth/google"):
        return True
    if path.startswith("/catalog/share"):
        return True
    if path == "/catalog/orders":
        return True
    return path in {"/login", "/setup", "/password-recovery", "/password-recovery/send-code", "/favicon.ico", "/healthz"}


def safe_next_path(next_path: str | None) -> str:
    candidate = (next_path or "/").strip()
    if candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return "/"


def current_user(request: Request) -> dict | None:
    user_id = read_session_user_id(request.cookies.get(SESSION_COOKIE_NAME))
    user = get_user_by_id(user_id)
    request.state.current_user = user
    return user


def is_admin_user(user: dict | None) -> bool:
    return bool(user and user.get("is_admin"))


def ensure_request_user(request: Request) -> dict | None:
    user = getattr(request.state, "current_user", None)
    return user if user is not None else current_user(request)


def render_forbidden(request: Request, message: str = "Solo los administradores pueden acceder a esta seccion."):
    return templates.TemplateResponse(
        request,
        "error.html",
        base_context(
            request,
            page_id="error",
            error_title="Acceso restringido",
            error_message=message,
            error_action_url="/",
            error_action_label="Volver al dashboard",
        ),
        status_code=403,
    )


def short_cookie_options(max_age: int) -> dict[str, object]:
    return {**session_cookie_options(), "max_age": max_age}


def clear_google_oauth_cookies(response) -> None:
    response.delete_cookie(GOOGLE_STATE_COOKIE, path="/")
    response.delete_cookie(GOOGLE_NEXT_COOKIE, path="/")


@app.middleware("http")
async def authentication_guard(request: Request, call_next):
    path = request.url.path
    platform_slug = resolve_request_platform_slug(request)
    request.state.platform_slug = platform_slug
    request.state.platform = get_platform(platform_slug)

    with use_platform(platform_slug):
        if is_public_path(path):
            response = await call_next(request)
        else:
            user = current_user(request)
            users_exist = has_users()

            if not users_exist:
                response = RedirectResponse(url=with_platform_query("/setup"), status_code=303)
            elif not user:
                requested_path = path
                if request.url.query:
                    requested_path = f"{requested_path}?{request.url.query}"
                login_url = with_platform_query(
                    f"/login?next={quote(safe_next_path(requested_path), safe='/?=&')}"
                )
                response = RedirectResponse(url=login_url, status_code=303)
                response.delete_cookie(SESSION_COOKIE_NAME, path="/")
            else:
                response = await call_next(request)

    if request.cookies.get(PLATFORM_COOKIE_NAME) != platform_slug:
        response.set_cookie(
            PLATFORM_COOKIE_NAME,
            platform_slug,
            httponly=True,
            samesite="lax",
            secure=session_cookie_options().get("secure", False),
            path="/",
        )
    return response


@app.get("/healthz")
def healthcheck():
    return {"status": "ok"}


@app.get("/media/{filename:path}")
def media_file(request: Request, filename: str):
    candidate = (current_uploads_dir() / filename).resolve()
    uploads_dir = current_uploads_dir().resolve()
    if not str(candidate).startswith(str(uploads_dir)) or not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")
    return FileResponse(candidate)


def parse_catalog_payload(form, item_id: int | None = None) -> dict:
    taxable = 1 if form.get("taxable") else 0
    payload = {
        "id": item_id,
        "item_type": (form.get("item_type") or "PRODUCT").upper(),
        "category": normalize_catalog_category(form.get("category") or DEFAULT_CATALOG_CATEGORY),
        "sku": (form.get("sku") or "").strip().upper(),
        "description": (form.get("description") or "").strip(),
        "unit": (form.get("unit") or "").strip(),
        "cost_amount": float(to_decimal(form.get("cost_amount"))),
        "available_qty": float(to_decimal(form.get("available_qty"))),
        "pricing_mode": (form.get("pricing_mode") or "MANUAL").upper(),
        "margin_pct": float(to_decimal(form.get("margin_pct"))),
        "markup_pct": float(to_decimal(form.get("markup_pct"))),
        "manual_price": float(to_decimal(form.get("manual_price"))),
        "tax_rate": float(to_decimal(form.get("tax_rate"))) if taxable else 0.0,
        "taxable": taxable,
        "active": 1 if form.get("active") else 0,
        "video_url": normalize_video_url(form.get("video_url")),
        "notes_internal": (form.get("notes_internal") or "").strip(),
        "notes_quote": (form.get("notes_quote") or "").strip(),
    }
    if not payload["sku"] or not payload["description"] or not payload["unit"]:
        raise ValueError("SKU, descripcion y unidad son obligatorios.")
    if payload["pricing_mode"] == "MARGIN" and to_decimal(payload["margin_pct"]) >= Decimal("100"):
        raise ValueError("El margen bruto debe ser menor al 100%.")
    return payload


def parse_client_payload(form, client_id: int | None = None) -> dict:
    payload = {
        "id": client_id,
        "client_type": normalize_client_type(form.get("client_type"), allow_consumer=True),
        "name": (form.get("name") or "").strip(),
        "document_type": (form.get("document_type") or "").strip().upper(),
        "document_number": (form.get("document_number") or "").strip(),
        "email": (form.get("email") or "").strip(),
        "phone": (form.get("phone") or "").strip(),
        "address": (form.get("address") or "").strip(),
    }
    if not payload["name"]:
        raise ValueError("El nombre del cliente es obligatorio.")
    if not payload["phone"]:
        raise ValueError("El telefono del cliente es obligatorio.")
    if not payload["address"]:
        raise ValueError("La direccion o ubicacion del cliente es obligatoria.")
    if payload["client_type"] == "CONSUMER":
        payload["document_type"] = ""
        payload["document_number"] = ""
        payload["email"] = ""
    elif payload["document_number"] and not payload["document_type"]:
        payload["document_type"] = "NIT" if payload["client_type"] == "BUSINESS" else "CC"
    return payload


def parse_quote_items(form, rounding_mode: str) -> list[dict]:
    source_ids = form.getlist("source_item_id")
    skus = form.getlist("sku")
    descriptions = form.getlist("description")
    units = form.getlist("unit")
    quantities = form.getlist("qty")
    cost_amounts = form.getlist("cost_amount")
    base_price_units = form.getlist("base_price_unit")
    price_units = form.getlist("price_unit")
    taxable_values = form.getlist("taxable")
    discount_types = form.getlist("discount_type")
    discount_values = form.getlist("discount_value")

    items: list[dict] = []
    total_rows = max(len(skus), len(descriptions), len(quantities), len(price_units))

    for index in range(total_rows):
        sku = (skus[index] if index < len(skus) else "").strip()
        description = (descriptions[index] if index < len(descriptions) else "").strip()
        unit = (units[index] if index < len(units) else "").strip()
        qty = quantities[index] if index < len(quantities) else "0"
        price_unit = price_units[index] if index < len(price_units) else "0"
        base_price_unit = base_price_units[index] if index < len(base_price_units) else price_unit
        taxable = 0 if index < len(taxable_values) and str(taxable_values[index]).strip() == "0" else 1
        cost_amount = cost_amounts[index] if index < len(cost_amounts) else "0"
        discount_type = (discount_types[index] if index < len(discount_types) else "PERCENT").upper()
        discount_value = discount_values[index] if index < len(discount_values) else "0"
        source_item_id = source_ids[index] if index < len(source_ids) else ""

        if not description and to_decimal(qty) == 0 and to_decimal(price_unit) == 0:
            continue

        if not sku:
            sku = f"ADHOC-{index + 1:02d}"
        if not description or not unit:
            raise ValueError("Cada item requiere descripcion y unidad.")
        if to_decimal(qty) <= 0:
            raise ValueError("La cantidad debe ser mayor a cero.")

        financials = line_financials(
            qty=qty,
            price_unit=price_unit,
            discount_type=discount_type,
            discount_value=discount_value,
            rounding_mode=rounding_mode,
        )
        items.append(
            {
                "source_item_id": int(source_item_id) if source_item_id else None,
                "sku": sku,
                "description": description,
                "unit": unit,
                "qty": float(financials["qty"]),
                "cost_amount": float(to_decimal(cost_amount)),
                "base_price_unit": float(to_decimal(base_price_unit)),
                "price_unit": float(financials["price_unit"]),
                "taxable": taxable,
                "discount_type": discount_type,
                "discount_value": float(to_decimal(discount_value)),
                "line_subtotal": float(financials["line_subtotal"]),
                "line_discount": float(financials["line_discount"]),
                "line_total": float(financials["line_total"]),
            }
        )

    if not items:
        raise ValueError("Agrega al menos una linea a la cotizacion.")
    return items


def quote_item_seeds(items: list[dict] | None) -> list[dict]:
    if not items:
        return []
    return [
        {
            "source_item_id": item.get("source_item_id") or "",
            "sku": item.get("sku") or "",
            "description": item.get("description") or "",
            "unit": item.get("unit") or "",
            "qty": item.get("qty") or 1,
            "cost_amount": item.get("cost_amount") or 0,
            "base_price_unit": item.get("base_price_unit") or item.get("price_unit") or 0,
            "price_unit": item.get("price_unit") or 0,
            "taxable": 1 if item.get("taxable", 1) else 0,
            "discount_type": item.get("discount_type") or "PERCENT",
            "discount_value": item.get("discount_value") or 0,
        }
        for item in items
    ]


def extract_quote_items_from_form(form) -> list[dict]:
    seeds: list[dict] = []
    rows = zip(
        form.getlist("source_item_id"),
        form.getlist("sku"),
        form.getlist("description"),
        form.getlist("unit"),
        form.getlist("qty"),
        form.getlist("cost_amount"),
        form.getlist("base_price_unit"),
        form.getlist("price_unit"),
        form.getlist("taxable"),
        form.getlist("discount_type"),
        form.getlist("discount_value"),
    )
    for source_id, sku, description, unit, qty, cost_amount, base_price_unit, price_unit, taxable, discount_type, discount_value in rows:
        if not any([sku, description, unit, qty, price_unit]):
            continue
        seeds.append(
            {
                "source_item_id": source_id or "",
                "sku": sku or "",
                "description": description or "",
                "unit": unit or "",
                "qty": qty or 1,
                "cost_amount": cost_amount or 0,
                "base_price_unit": base_price_unit or price_unit or 0,
                "price_unit": price_unit or 0,
                "taxable": 0 if str(taxable).strip() == "0" else 1,
                "discount_type": discount_type or "PERCENT",
                "discount_value": discount_value or 0,
            }
        )
    return seeds


def render_quote_form(
    request: Request,
    *,
    form_data: dict,
    quote_items: list[dict] | None = None,
    error: str | None = None,
    quote_id: int | None = None,
    form_title: str = "Nueva cotización",
    form_intro: str = "Combina items del catálogo o líneas manuales y revisa los totales en tiempo real.",
    submit_label: str = "Guardar cotización",
    quote_number: str | None = None,
    document_mode: str = "quote",
    origin_order_id: int | None = None,
    status_code: int = 200,
):
    settings = fetch_settings()
    form_values = normalize_quote_form_data(form_data)
    catalog_items = [
        enrich_catalog_item(item, settings["rounding_mode"])
        for item in list_catalog_items(active_only=False if quote_id else True)
    ]
    clients = [normalize_quote_form_data(client) for client in list_clients()]
    return templates.TemplateResponse(
        request,
        "quote_form.html",
        base_context(
            request,
            page_id="quotes",
            form_data=form_values,
            catalog_json=json.dumps(catalog_items),
            clients_json=json.dumps(clients),
            quote_items_json=json.dumps(quote_item_seeds(quote_items)),
            clients=clients,
            error=error,
            quote_id=quote_id,
            form_title=form_title,
            form_intro=form_intro,
            submit_label=submit_label,
            quote_number=quote_number,
            document_mode="invoice" if document_mode == "invoice" else "quote",
            origin_order_id=origin_order_id,
        ),
        status_code=status_code,
    )


def render_login_page(
    request: Request,
    *,
    next_path: str = "/",
    identity: str = "",
    error: str | None = None,
    success: str | None = None,
    status_code: int = 200,
):
    settings = fetch_settings()
    branding = public_branding(settings)
    return templates.TemplateResponse(
        request,
        "login.html",
        base_context(
            request,
            page_id="auth",
            error=error,
            success=success,
            auth_title="Ingresar a la aplicacion",
            auth_intro=f"Accede a {branding['org_name']} desde cualquier dispositivo con una interfaz mas limpia, rapida y segura.",
            submit_label="Ingresar",
            next_path=next_path,
            identity=identity,
            current_platform=get_platform(current_platform_slug()),
            google_enabled=google_oauth_enabled(settings),
            google_start_url=with_platform_query(f"/auth/google/start?next={quote(next_path, safe='/?=&')}"),
            show_recovery_link=True,
        ),
        status_code=status_code,
    )


def render_setup_page(
    request: Request,
    *,
    full_name: str = "",
    email: str = "",
    username: str = "",
    error: str | None = None,
    status_code: int = 200,
):
    return templates.TemplateResponse(
        request,
        "setup.html",
        base_context(
            request,
            page_id="auth",
            error=error,
            auth_title="Crear usuario administrador",
            auth_intro="Configura el acceso principal, el correo de recuperacion y el primer perfil administrativo.",
            submit_label="Crear acceso",
            full_name=full_name,
            email=email,
            username=username,
            current_platform=get_platform(current_platform_slug()),
        ),
        status_code=status_code,
    )


def render_platform_create_page(
    request: Request,
    *,
    platform_name: str = "",
    brand_slogan: str = "",
    full_name: str = "",
    email: str = "",
    username: str = "",
    error: str | None = None,
    success: str | None = None,
    platform_login_url: str | None = None,
    created_platform_name: str | None = None,
    status_code: int = 200,
):
    primary_platform = next((platform for platform in list_platforms() if platform["slug"] == PRIMARY_PLATFORM_SLUG), None)
    return templates.TemplateResponse(
        request,
        "setup.html",
        base_context(
            request,
            page_id="auth",
            error=error,
            success=success,
            auth_title="Crear nueva plataforma",
            auth_intro="Abre una plataforma independiente con su propia marca, su propio usuario administrador y acceso separado desde el login inicial.",
            submit_label="Crear plataforma y administrador",
            full_name=full_name,
            email=email,
            username=username,
            platform_name=platform_name,
            brand_slogan=brand_slogan,
            current_platform=primary_platform,
            creation_mode="platform",
            platform_login_url=platform_login_url,
            created_platform_name=created_platform_name,
        ),
        status_code=status_code,
    )


def render_password_recovery_page(
    request: Request,
    *,
    identity: str = "",
    error: str | None = None,
    success: str | None = None,
    status_code: int = 200,
):
    return templates.TemplateResponse(
        request,
        "password_recovery.html",
        base_context(
            request,
            page_id="auth",
            error=error,
            success=success,
            auth_title="Recuperar acceso",
            auth_intro="La recuperacion por correo solo esta disponible para administradores con correo institucional registrado. Solicita el codigo y restablece tu contrasena sin salir de la plataforma.",
            submit_label="Actualizar contrasena",
            identity=identity,
            identity_label="Correo del administrador",
            smtp_enabled=email_delivery_enabled(),
            show_login_link=True,
            login_url=with_platform_query("/login"),
        ),
        status_code=status_code,
    )


def render_users_page(
    request: Request,
    *,
    error: str | None = None,
    success: str | None = None,
    form_data: dict | None = None,
    reset_user_id: int | None = None,
    status_code: int = 200,
):
    settings = fetch_settings()
    return templates.TemplateResponse(
        request,
        "admin_users.html",
        base_context(
            request,
            page_id="admin",
            users=list_users(),
            recovery_code=get_recovery_code(),
            error=error,
            success=success,
            form_data=form_data or {"is_admin": 0},
            reset_user_id=reset_user_id,
            smtp_ready=email_delivery_enabled(),
            google_ready=google_oauth_enabled(settings),
        ),
        status_code=status_code,
    )


def platform_login_url(slug: str) -> str:
    return "/login" if slug == PRIMARY_PLATFORM_SLUG else f"/login?platform={quote(slug)}"


@app.get("/login")
def login_page(request: Request, next: str = "/", recovered: int = 0, created: int = 0):
    if current_user(request):
        return RedirectResponse(url="/", status_code=303)
    if not has_users():
        return RedirectResponse(url=with_platform_query("/setup"), status_code=303)
    return render_login_page(
        request,
        next_path=safe_next_path(next),
        success=(
            "La nueva plataforma ya esta lista. Ingresa con su administrador."
            if created
            else "La contrasena se actualizo correctamente. Ya puedes iniciar sesion."
            if recovered
            else None
        ),
    )


@app.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    identity = (form.get("identity") or form.get("username") or "").strip()
    password = form.get("password") or ""
    next_path = safe_next_path(form.get("next"))

    if not has_users():
        return RedirectResponse(url=with_platform_query("/setup"), status_code=303)

    try:
        normalized_identity = normalize_identity(identity)
    except ValueError as error:
        return render_login_page(request, next_path=next_path, identity=identity, error=str(error), status_code=400)

    user = find_user_for_login(normalized_identity)
    if not user or not verify_password(password, user["password_hash"]):
        return render_login_page(
            request,
            next_path=next_path,
            identity=identity,
            error="Usuario, correo o contrasena incorrectos.",
            status_code=401,
        )

    response = RedirectResponse(url=next_path, status_code=303)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        build_session_token(user["id"]),
        **session_cookie_options(),
    )
    response.set_cookie(
        PLATFORM_COOKIE_NAME,
        current_platform_slug(),
        httponly=True,
        samesite="lax",
        secure=session_cookie_options().get("secure", False),
        path="/",
    )
    return response


@app.get("/auth/google/start")
def google_start(request: Request, next: str = "/"):
    settings = fetch_settings()
    if not has_users():
        return RedirectResponse(url=with_platform_query("/setup"), status_code=303)
    if not google_oauth_enabled(settings):
        return render_login_page(
            request,
            next_path=safe_next_path(next),
            error="El acceso con Google todavia no esta configurado en este servidor.",
            status_code=400,
        )

    state = generate_google_state()
    next_path = safe_next_path(next)
    response = RedirectResponse(url=build_google_authorize_url(request, state=state, settings=settings), status_code=303)
    response.set_cookie(GOOGLE_STATE_COOKIE, state, **short_cookie_options(600))
    response.set_cookie(GOOGLE_NEXT_COOKIE, next_path, **short_cookie_options(600))
    response.set_cookie(
        PLATFORM_COOKIE_NAME,
        current_platform_slug(),
        httponly=True,
        samesite="lax",
        secure=session_cookie_options().get("secure", False),
        path="/",
    )
    return response


@app.get("/auth/google/callback", name="google_callback")
def google_callback(request: Request, state: str = "", code: str = "", error: str = ""):
    settings = fetch_settings()
    next_path = safe_next_path(request.cookies.get(GOOGLE_NEXT_COOKIE))

    def build_error_response(message: str, status_code: int = 400):
        response = render_login_page(
            request,
            next_path=next_path,
            error=message,
            status_code=status_code,
        )
        clear_google_oauth_cookies(response)
        return response

    if error:
        return build_error_response("Google no autorizo el acceso. Intenta nuevamente.")
    if not code or not state or state != request.cookies.get(GOOGLE_STATE_COOKIE):
        return build_error_response("No fue posible validar el inicio de sesion con Google.")

    try:
        token_data = exchange_google_code(request, code, settings=settings)
        access_token = token_data.get("access_token") or ""
        if not access_token:
            raise ValueError("Google no devolvio un token de acceso valido.")

        userinfo = fetch_google_userinfo(access_token)
        google_subject = str(userinfo.get("sub") or "").strip()
        google_email = normalize_email(userinfo.get("email") or "")
        full_name = (userinfo.get("name") or "").strip()

        if not google_subject or not google_email:
            raise ValueError("La cuenta de Google no entrego un correo utilizable.")

        user = get_user_by_google_subject(google_subject)
        if not user:
            user = get_user_by_email(google_email)
            if user:
                bind_google_identity(
                    int(user["id"]),
                    google_subject=google_subject,
                    email=google_email,
                    full_name=full_name,
                )
                user = get_user_by_id(int(user["id"]))
            else:
                raise ValueError("Tu correo de Google no esta autorizado. El administrador debe registrar primero ese usuario.")

        response = RedirectResponse(url=next_path, status_code=303)
        response.set_cookie(
            SESSION_COOKIE_NAME,
            build_session_token(int(user["id"])),
            **session_cookie_options(),
        )
        response.set_cookie(
            PLATFORM_COOKIE_NAME,
            current_platform_slug(),
            httponly=True,
            samesite="lax",
            secure=session_cookie_options().get("secure", False),
            path="/",
        )
        clear_google_oauth_cookies(response)
        return response
    except (HTTPError, URLError, ValueError) as error_detail:
        return build_error_response(str(error_detail))
    except Exception:
        return build_error_response("No fue posible completar el acceso con Google en este momento.")


@app.get("/setup")
def setup_page(request: Request):
    user = current_user(request)
    if has_users():
        return RedirectResponse(url="/" if user else with_platform_query("/login"), status_code=303)
    return render_setup_page(request)


@app.post("/setup")
async def setup_submit(request: Request):
    if has_users():
        return RedirectResponse(url=with_platform_query("/login"), status_code=303)

    form = await request.form()
    full_name = (form.get("full_name") or "").strip()
    email = (form.get("email") or "").strip()
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    confirm_password = form.get("confirm_password") or ""

    try:
        if not full_name:
            raise ValueError("El nombre completo es obligatorio.")
        normalized_username = normalize_username(username)
        normalized_email = normalize_email(email)
        validate_password_confirmation(password, confirm_password)
        user_id = create_user(
            normalized_username,
            hash_password(password),
            is_admin=True,
            full_name=full_name,
            email=normalized_email,
        )
    except (ValueError, sqlite3.IntegrityError) as error:
        return render_setup_page(
            request,
            full_name=full_name,
            email=email,
            username=username,
            error="El usuario ya existe." if isinstance(error, sqlite3.IntegrityError) else str(error),
            status_code=400,
        )

    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        build_session_token(user_id),
        **session_cookie_options(),
    )
    response.set_cookie(
        PLATFORM_COOKIE_NAME,
        current_platform_slug(),
        httponly=True,
        samesite="lax",
        secure=session_cookie_options().get("secure", False),
        path="/",
    )
    return response


@app.get("/platforms/new")
def platform_create_page(request: Request, created: int = 0, platform: str = ""):
    user = current_user(request)
    if not is_admin_user(user):
        return render_forbidden(request, "Solo los administradores pueden crear plataformas nuevas.")
    created_platform = get_platform(platform.strip()) if created and platform else None
    return render_platform_create_page(
        request,
        success="La nueva plataforma ya esta lista. Ya puedes compartir su acceso independiente." if created else None,
        platform_login_url=f"/login?platform={quote(created_platform['slug'])}" if created_platform else None,
        created_platform_name=created_platform["name"] if created_platform else None,
    )


@app.post("/platforms/new")
async def platform_create_submit(request: Request):
    user = current_user(request)
    if not is_admin_user(user):
        return render_forbidden(request, "Solo los administradores pueden crear plataformas nuevas.")
    form = await request.form()
    platform_name = (form.get("platform_name") or "").strip()
    brand_slogan = (form.get("brand_slogan") or "").strip()
    full_name = (form.get("full_name") or "").strip()
    email = (form.get("email") or "").strip()
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    confirm_password = form.get("confirm_password") or ""

    try:
        if not platform_name:
            raise ValueError("El nombre de la nueva plataforma es obligatorio.")
        if not full_name:
            raise ValueError("El nombre completo del administrador es obligatorio.")
        normalized_username = normalize_username(username)
        normalized_email = normalize_email(email)
        validate_password_confirmation(password, confirm_password)
        platform = create_platform_workspace(
            platform_name=platform_name,
            brand_slogan=brand_slogan,
            admin_username=normalized_username,
            admin_password_hash=hash_password(password),
            admin_full_name=full_name,
            admin_email=normalized_email,
        )
    except (ValueError, sqlite3.IntegrityError) as error:
        return render_platform_create_page(
            request,
            platform_name=platform_name,
            brand_slogan=brand_slogan,
            full_name=full_name,
            email=email,
            username=username,
            error="El usuario administrador ya existe." if isinstance(error, sqlite3.IntegrityError) else str(error),
            status_code=400,
        )

    return RedirectResponse(
        url=f"/platforms/new?created=1&platform={quote(platform['slug'])}",
        status_code=303,
    )


@app.post("/logout")
async def logout(request: Request):
    response = RedirectResponse(url=with_platform_query("/login"), status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


@app.get("/password-recovery")
def password_recovery_page(request: Request):
    if not has_users():
        return RedirectResponse(url=with_platform_query("/setup"), status_code=303)
    return render_password_recovery_page(request)


@app.post("/password-recovery/send-code")
async def password_recovery_send_code(request: Request):
    form = await request.form()
    identity = (form.get("identity") or form.get("email") or "").strip()

    try:
        normalized_email = normalize_email(identity)
    except ValueError as error:
        return render_password_recovery_page(request, identity=identity, error=str(error), status_code=400)

    if not email_delivery_enabled():
        return render_password_recovery_page(
            request,
            identity=identity,
            error="La recuperacion por correo necesita configurar SMTP en el servidor antes de enviar codigos.",
            status_code=400,
        )

    user = recoverable_admin_email(normalized_email)
    success_message = "Si el correo corresponde a un administrador registrado, el codigo ya fue enviado."

    if not user:
        return render_password_recovery_page(request, identity=identity, success=success_message)

    code = generate_email_recovery_code()
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).replace(microsecond=0).isoformat()

    try:
        store_password_recovery_code(int(user["id"]), hash_ephemeral_code(code), expires_at)
        send_password_recovery_email(
            user["email"],
            user.get("full_name") or user["username"],
            code,
        )
    except ValueError as error:
        return render_password_recovery_page(request, identity=identity, error=str(error), status_code=400)
    except Exception:
        return render_password_recovery_page(
            request,
            identity=identity,
            error="No se pudo enviar el correo de recuperacion. Revisa la configuracion del servidor e intenta de nuevo.",
            status_code=500,
        )

    return render_password_recovery_page(request, identity=identity, success=success_message)


@app.post("/password-recovery")
async def password_recovery_submit(request: Request):
    form = await request.form()
    identity = (form.get("identity") or form.get("email") or "").strip()
    recovery_code = (form.get("recovery_code") or "").strip()
    password = form.get("password") or ""
    confirm_password = form.get("confirm_password") or ""

    try:
        normalized_email = normalize_email(identity)
        validate_password_confirmation(password, confirm_password)
        user = recoverable_admin_email(normalized_email)
        if not user:
            raise ValueError("La recuperacion por correo solo esta disponible para administradores con correo registrado.")

        prune_expired_password_recovery_codes()
        stored_code = get_password_recovery_code(int(user["id"]))
        email_code_valid = False
        if stored_code:
            expires_at = datetime.fromisoformat(stored_code["expires_at"])
            if expires_at > datetime.now(timezone.utc) and verify_ephemeral_code(recovery_code, stored_code["code_hash"]):
                email_code_valid = True

        if not email_code_valid and not verify_recovery_code(recovery_code):
            raise ValueError("No fue posible validar la recuperacion. Revisa el codigo recibido por correo.")
        update_user_password(int(user["id"]), hash_password(password))
        clear_password_recovery_code(int(user["id"]))
    except ValueError as error:
        return render_password_recovery_page(request, identity=identity, error=str(error), status_code=400)
    return RedirectResponse(url=with_platform_query("/login?recovered=1"), status_code=303)


@app.get("/")
def dashboard(request: Request):
    settings = fetch_settings()
    quotes = list_quotes(limit=None)
    catalog = list_catalog_items()
    clients = list_clients()
    orders = []
    for order in list_catalog_orders():
        detail = get_catalog_order(int(order["id"])) or {**order, "items": []}
        detail["status_label"] = order_status_label(detail.get("status"))
        detail["payment_status_label"] = payment_status_label(detail.get("payment_status"))
        orders.append(detail)
    invoices = list_invoice_documents()
    credits = list_client_credits()
    credit_balance = sum(to_decimal(credit.get("balance")) for credit in credits)
    pending_quotes = sum(1 for quote in quotes if str(quote.get("status") or "").upper() in {"PENDING", "APPROVED"})
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        base_context(
            request,
            page_id="dashboard",
            recent_quotes=quotes[:5],
            recent_invoices=invoices[:5],
            recent_orders=orders[:5],
            catalog_items=[enrich_catalog_item(item, settings["rounding_mode"]) for item in catalog[:6]],
            clients=clients[:6],
            stats={
                "catalog": len(catalog),
                "clients": len(clients),
                "quotes": len(quotes),
                "quotes_pending": pending_quotes,
                "orders": len(orders),
                "invoices": len(invoices),
                "credits": len(credits),
                "credit_balance": float(credit_balance),
            },
            dashboard_date=date.today().isoformat(),
            quote_status_label=quote_status_label,
            credit_status_label=credit_status_label,
        ),
    )


@app.get("/quotes")
def quotes_list_page(request: Request, q: str = ""):
    quotes = list_quotes(limit=None, search=q)
    return templates.TemplateResponse(
        request,
        "quote_list.html",
        base_context(
            request,
            page_id="quotes",
            quotes=quotes,
            search_term=q,
            quote_count=len(quotes),
            quote_status_label=quote_status_label,
        ),
    )


@app.get("/invoices")
def invoices_list_page(request: Request, q: str = ""):
    invoices = list_invoice_documents(q)
    return templates.TemplateResponse(
        request,
        "invoice_list.html",
        base_context(
            request,
            page_id="invoices",
            invoices=invoices,
            search_term=q,
            invoice_count=len(invoices),
            quote_status_label=quote_status_label,
        ),
    )


@app.get("/catalog")
def catalog_list(request: Request):
    settings = fetch_settings()
    items = [enrich_catalog_item(item, settings["rounding_mode"]) for item in list_catalog_items()]
    category_sections = catalog_category_sections(items)
    share_url = f"{str(request.base_url).rstrip('/')}/catalog/share{current_platform_query()}"
    return templates.TemplateResponse(
        request,
        "catalog_list.html",
        base_context(
            request,
            page_id="catalog",
            items=items,
            share_url=share_url,
            category_sections=category_sections,
        ),
    )


@app.get("/catalog/new")
def catalog_new(request: Request):
    return templates.TemplateResponse(
        request,
        "catalog_form.html",
        base_context(
            request,
            page_id="catalog",
            form_data={
                "item_type": "PRODUCT",
                "category": DEFAULT_CATALOG_CATEGORY,
                "pricing_mode": "MARGIN",
                "active": 1,
                "margin_pct": 30,
                "markup_pct": 0,
                "tax_rate": fetch_settings()["iva_rate"],
                "available_qty": 0,
                "video_url": "",
            },
            category_options=catalog_category_options(),
            error=None,
            item_id=None,
        ),
    )


@app.get("/catalog/{item_id}/edit")
def catalog_edit(request: Request, item_id: int):
    item = get_catalog_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado.")
    settings = fetch_settings()
    return templates.TemplateResponse(
        request,
        "catalog_form.html",
        base_context(
            request,
            page_id="catalog",
            form_data=enrich_catalog_item(item, settings["rounding_mode"]),
            category_options=catalog_category_options(),
            error=None,
            item_id=item_id,
        ),
    )


@app.post("/catalog/save")
async def catalog_save(request: Request):
    form = await request.form()
    item_id = form.get("id")
    current_item = get_catalog_item(int(item_id)) if item_id else None
    uploaded_images: list[dict] = []
    try:
        payload = parse_catalog_payload(form, int(item_id) if item_id else None)
        payload["image_filename"] = current_item.get("image_filename") if current_item else None
        payload["image_mime"] = current_item.get("image_mime") if current_item else None

        gallery_uploads = list(form.getlist("images"))
        # Keep backward compatibility with the previous single-image field.
        upload = form.get("image")
        if upload and getattr(upload, "filename", ""):
            gallery_uploads.append(upload)

        for upload_item in gallery_uploads:
            if upload_item and getattr(upload_item, "filename", ""):
                uploaded_images.append(await save_catalog_image(upload_item))

        remove_image = bool(form.get("remove_image"))
        remove_gallery_ids = [
            int(value)
            for value in form.getlist("remove_gallery_image")
            if str(value).strip().isdigit()
        ]

        if uploaded_images and not payload.get("image_filename"):
            payload["image_filename"] = uploaded_images[0]["filename"]
            payload["image_mime"] = uploaded_images[0]["mime"]
        elif remove_image:
            payload["image_filename"] = None
            payload["image_mime"] = None

        saved_item_id = save_catalog_item(payload)

        for uploaded_image in uploaded_images:
            add_catalog_item_image(saved_item_id, uploaded_image["filename"], uploaded_image["mime"])

        removed_filenames = delete_catalog_item_images(remove_gallery_ids)
        for filename in removed_filenames:
            delete_uploaded_image(filename)

        if remove_image and current_item and current_item.get("image_filename"):
            delete_uploaded_image(current_item["image_filename"])

        refreshed_images = list_catalog_item_images(saved_item_id)
        if refreshed_images:
            primary = refreshed_images[0]
            if payload.get("image_filename") != primary["filename"]:
                payload["id"] = saved_item_id
                payload["image_filename"] = primary["filename"]
                payload["image_mime"] = primary.get("mime") or "image/png"
                save_catalog_item(payload)
        elif payload.get("image_filename"):
            payload["id"] = saved_item_id
            payload["image_filename"] = None
            payload["image_mime"] = None
            save_catalog_item(payload)
    except (ValueError, sqlite3.IntegrityError) as error:
        for uploaded_image in uploaded_images:
            delete_uploaded_image(uploaded_image["filename"])
        form_data = {
            "item_type": (form.get("item_type") or "PRODUCT").upper(),
            "category": normalize_catalog_category(form.get("category") or DEFAULT_CATALOG_CATEGORY),
            "sku": (form.get("sku") or "").strip().upper(),
            "description": (form.get("description") or "").strip(),
            "unit": (form.get("unit") or "").strip(),
            "cost_amount": form.get("cost_amount") or 0,
            "available_qty": form.get("available_qty") or 0,
            "pricing_mode": (form.get("pricing_mode") or "MARGIN").upper(),
            "margin_pct": form.get("margin_pct") or 0,
            "markup_pct": form.get("markup_pct") or 0,
            "manual_price": form.get("manual_price") or 0,
            "tax_rate": form.get("tax_rate") or fetch_settings()["iva_rate"],
            "taxable": 1 if form.get("taxable") else 0,
            "active": 1 if form.get("active") else 0,
            "video_url": (form.get("video_url") or "").strip(),
            "notes_internal": (form.get("notes_internal") or "").strip(),
            "notes_quote": (form.get("notes_quote") or "").strip(),
            "image_filename": current_item.get("image_filename") if current_item else None,
            "image_url": media_src(current_item["image_filename"]) if current_item and current_item.get("image_filename") else None,
            "images": enrich_catalog_item(current_item, fetch_settings()["rounding_mode"]).get("images", []) if current_item else [],
            "video_embed_url": build_video_embed_url(form.get("video_url")),
        }
        return templates.TemplateResponse(
            request,
            "catalog_form.html",
            base_context(
                request,
                page_id="catalog",
                form_data=form_data,
                category_options=catalog_category_options(),
                error="El SKU ya existe." if isinstance(error, sqlite3.IntegrityError) else str(error),
                item_id=int(item_id) if item_id else None,
            ),
            status_code=400,
        )
    return RedirectResponse(url="/catalog", status_code=303)


@app.post("/catalog/{item_id}/delete")
async def catalog_delete(item_id: int):
    try:
        filenames = delete_catalog_item(item_id)
        for filename in filenames:
            delete_uploaded_image(filename)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))
    return RedirectResponse(url="/catalog", status_code=303)


@app.get("/catalog/share", name="catalog_share")
def catalog_share(request: Request):
    settings = fetch_settings()
    items = [enrich_catalog_item(item, settings["rounding_mode"]) for item in list_catalog_items(active_only=True)]
    category_sections = catalog_category_sections(items)
    # The shared catalog is public, but a logged-in seller can still get private cart actions.
    current_user(request)
    return templates.TemplateResponse(
        request,
        "catalog_share.html",
        base_context(
            request,
            page_id="catalog-share",
            items=items,
            category_sections=category_sections,
            share_url=f"{str(request.base_url).rstrip('/')}/catalog/share{current_platform_query()}",
            whatsapp_number=whatsapp_number_from_settings(settings),
        ),
    )


@app.post("/catalog/orders")
async def catalog_order_create(request: Request):
    settings = fetch_settings()
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "No fue posible leer el pedido."}, status_code=400)

    customer_name = (data.get("customer_name") or "").strip() if isinstance(data, dict) else ""
    customer_phone = (data.get("customer_phone") or "").strip() if isinstance(data, dict) else ""
    customer_address = (data.get("customer_address") or "").strip() if isinstance(data, dict) else ""

    try:
        if not customer_name:
            raise ValueError("Indica tu nombre para registrar el pedido.")
        if not customer_address:
            raise ValueError("Indica la direccion o ubicacion para registrar el pedido.")

        items = cart_entries_to_order_items(data.get("items") if isinstance(data, dict) else [], settings["rounding_mode"])
        totals = quote_totals(
            line_totals=[item["line_total"] for item in items],
            tax_rate=settings["iva_rate"],
            rounding_mode=settings["rounding_mode"],
            taxable_flags=[item["taxable"] for item in items],
        )
        order_id = create_catalog_order(
            {
                "customer_name": customer_name,
                "customer_phone": customer_phone,
                "customer_address": customer_address,
                "status": "NEW",
                "payment_status": "PENDING",
                "subtotal": float(totals["subtotal"]),
                "tax_amount": float(totals["tax_amount"]),
                "total": float(totals["total"]),
            },
            items,
        )
        order = get_catalog_order(order_id)
        if not order:
            raise ValueError("No fue posible recuperar el pedido generado.")
        quote = ensure_quote_for_catalog_order(order, settings)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)

    order = get_catalog_order(order_id)
    return JSONResponse(
        {
            "order_id": order_id,
            "order_number": order["order_number"] if order else f"PED-{order_id:06d}",
            "quote_id": quote["id"],
            "quote_number": quote["quote_number"],
            "subtotal": quote["subtotal"],
            "tax_amount": quote["tax_amount"],
            "total": quote["total"],
        }
    )


@app.get("/orders")
def orders_page(request: Request, q: str = "", status: str = ""):
    orders = []
    for order in list_catalog_orders(search=q, status=status, exclude_completed=True):
        detail = get_catalog_order(int(order["id"])) or {**order, "items": []}
        detail["status_label"] = order_status_label(detail.get("status"))
        detail["payment_status_label"] = payment_status_label(detail.get("payment_status"))
        detail["quote"] = get_quote(int(detail["quote_id"])) if detail.get("quote_id") else None
        orders.append(detail)
    return templates.TemplateResponse(
        request,
        "orders.html",
        base_context(
            request,
            page_id="orders",
            orders=orders,
            search_term=q,
            status_filter=status,
            status_label=order_status_label,
            payment_status_label=payment_status_label,
        ),
    )


@app.post("/orders/{order_id}/status")
async def order_status_update(request: Request, order_id: int):
    form = await request.form()
    next_url = safe_next_path(form.get("next") or "/orders")
    try:
        update_catalog_order_status(order_id, form.get("status") or "NEW")
    except ValueError:
        return RedirectResponse(url=next_url, status_code=303)
    return RedirectResponse(url=next_url, status_code=303)


@app.post("/orders/{order_id}/mark-paid")
async def order_mark_paid(request: Request, order_id: int):
    form = await request.form()
    next_url = safe_next_path(form.get("next") or "/orders")
    settings = fetch_settings()
    try:
        order = get_catalog_order(order_id)
        if not order:
            raise ValueError("Pedido no encontrado.")
        ensure_quote_for_catalog_order(order, settings)
        confirm_catalog_order_payment(
            order_id,
            method=form.get("method") or "Pago inmediato",
            reference=form.get("reference") or "",
        )
    except ValueError:
        return RedirectResponse(url=next_url, status_code=303)
    return RedirectResponse(url=next_url, status_code=303)


@app.post("/orders/{order_id}/send-credit")
async def order_send_credit(request: Request, order_id: int):
    form = await request.form()
    next_url = safe_next_path(form.get("next") or "/orders")
    settings = fetch_settings()
    try:
        order = get_catalog_order(order_id)
        if not order:
            raise ValueError("Pedido no encontrado.")
        ensure_quote_for_catalog_order(order, settings)
        refreshed_order = get_catalog_order(order_id)
        client_id = find_or_create_client_from_order(refreshed_order or order)
        send_catalog_order_to_credit(
            order_id,
            client_id=client_id,
            due_date=form.get("due_date") or "",
        )
    except ValueError:
        return RedirectResponse(url=next_url, status_code=303)
    return RedirectResponse(url=next_url, status_code=303)


@app.get("/clients")
def clients_list(request: Request, q: str = "", success: str = ""):
    search_term = (q or "").strip().lower()
    clients = list_clients()
    if search_term:
        clients = [
            client
            for client in clients
            if search_term in (client.get("name") or "").lower()
            or search_term in (client.get("document_type") or "").lower()
            or search_term in (client.get("document_number") or "").lower()
            or search_term in (client.get("phone") or "").lower()
            or search_term in (client.get("address") or "").lower()
            or search_term in (client.get("email") or "").lower()
        ]
    return templates.TemplateResponse(
        request,
        "client_list.html",
        base_context(
            request,
            page_id="clients",
            clients=clients,
            search_term=q,
            success=success,
        ),
    )


@app.get("/clients/new")
def client_new(request: Request):
    return templates.TemplateResponse(
        request,
        "client_form.html",
        base_context(request, page_id="clients", form_data={}, error=None, client_id=None),
    )


@app.get("/clients/{client_id}/edit")
def client_edit(request: Request, client_id: int):
    client = get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    return templates.TemplateResponse(
        request,
        "client_form.html",
        base_context(request, page_id="clients", form_data=client, error=None, client_id=client_id),
    )


@app.post("/clients/save")
async def client_save(request: Request):
    form = await request.form()
    client_id = form.get("id")
    try:
        payload = parse_client_payload(form, int(client_id) if client_id else None)
        save_client(payload)
    except ValueError as error:
        return templates.TemplateResponse(
            request,
            "client_form.html",
            base_context(
                request,
                page_id="clients",
                form_data={key: value for key, value in form.items()},
                error=str(error),
                client_id=int(client_id) if client_id else None,
            ),
            status_code=400,
        )
    success = "client-updated" if client_id else "client-created"
    return RedirectResponse(url=f"/clients?success={success}", status_code=303)


@app.post("/api/clients/quick-save")
async def client_quick_save(request: Request):
    form = await request.form()
    client_id = form.get("id")
    try:
        payload = parse_client_payload(form, int(client_id) if client_id else None)
        saved_id = save_client(payload)
        client = get_client(saved_id)
        return JSONResponse({"ok": True, "client": client})
    except ValueError as error:
        return JSONResponse({"ok": False, "error": str(error)}, status_code=400)


@app.post("/clients/{client_id}/delete")
async def client_delete(request: Request, client_id: int):
    if not is_admin_user(ensure_request_user(request)):
        return render_forbidden(request, "Solo un administrador puede eliminar clientes.")

    try:
        delete_client(client_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))

    return RedirectResponse(url="/clients?success=client-deleted", status_code=303)


@app.get("/credits")
def credits_page(
    request: Request,
    q: str = "",
    success: str = "",
    error: str = "",
    client_id: int | None = None,
):
    selected_client = get_client(client_id) if client_id else None
    credits = list_client_credits(search=q, client_id=client_id)
    totals = {
        "amount": sum(to_decimal(credit.get("amount")) for credit in credits),
        "paid": sum(to_decimal(credit.get("paid_amount")) for credit in credits),
        "balance": sum(to_decimal(credit.get("balance")) for credit in credits),
    }
    return templates.TemplateResponse(
        request,
        "credit_list.html",
        base_context(
            request,
            page_id="credits",
            credits=credits,
            totals=totals,
            search_term=q,
            selected_client=selected_client,
            success_message=success or None,
            error_message=error or None,
            credit_status_label=credit_status_label,
        ),
    )


@app.get("/credits/new")
def credit_new(request: Request, client_id: int | None = None):
    return templates.TemplateResponse(
        request,
        "credit_form.html",
        base_context(
            request,
            page_id="credits",
            form_data={"client_id": client_id or "", "status": "PENDING"},
            clients=list_clients(),
            credit_id=None,
            error=None,
        ),
    )


@app.get("/credits/{credit_id}/edit")
def credit_edit(request: Request, credit_id: int):
    credit = get_client_credit(credit_id)
    if not credit:
        raise HTTPException(status_code=404, detail="Credito no encontrado.")
    return templates.TemplateResponse(
        request,
        "credit_form.html",
        base_context(
            request,
            page_id="credits",
            form_data=credit,
            clients=list_clients(),
            credit_id=credit_id,
            error=None,
        ),
    )


@app.post("/credits/save")
async def credit_save(request: Request):
    form = await request.form()
    credit_id = form.get("id")
    try:
        existing_credit = (
            get_client_credit(int(credit_id))
            if str(credit_id or "").isdigit()
            else None
        )
        client_id = int(form.get("client_id") or 0)
        if not get_client(client_id):
            raise ValueError("Selecciona un cliente guardado.")
        amount = to_decimal(form.get("amount"))
        paid_amount = to_decimal(form.get("paid_amount"))
        if amount <= 0:
            raise ValueError("El valor del credito debe ser mayor a cero.")
        if paid_amount < 0:
            raise ValueError("El valor abonado no puede ser negativo.")
        if paid_amount > amount:
            paid_amount = amount

        status = (form.get("status") or "PENDING").strip().upper()
        balance = amount - paid_amount
        if balance <= 0:
            status = "PAID"
        elif paid_amount > 0 and status == "PENDING":
            status = "PARTIAL"

        save_client_credit(
            {
                "id": int(credit_id) if credit_id else None,
                "client_id": client_id,
                "order_id": (existing_credit or {}).get("order_id"),
                "quote_id": (existing_credit or {}).get("quote_id"),
                "order_number": (existing_credit or {}).get("order_number"),
                "description": form.get("description") or "Credito comercial",
                "amount": float(amount),
                "paid_amount": float(paid_amount),
                "due_date": form.get("due_date") or "",
                "status": status,
            }
        )
    except (ValueError, TypeError) as error:
        return templates.TemplateResponse(
            request,
            "credit_form.html",
            base_context(
                request,
                page_id="credits",
                form_data={key: value for key, value in form.items()},
                clients=list_clients(),
                credit_id=int(credit_id) if str(credit_id or "").isdigit() else None,
                error=str(error),
            ),
            status_code=400,
        )
    return RedirectResponse(url="/credits", status_code=303)


@app.post("/credits/{credit_id}/delete")
async def credit_delete(request: Request, credit_id: int):
    try:
        delete_client_credit(credit_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))
    return RedirectResponse(url="/credits", status_code=303)


@app.post("/credits/{credit_id}/collect")
async def credit_collect_payment(request: Request, credit_id: int):
    form = await request.form()
    action = (form.get("action") or "partial").strip().lower()
    existing_credit = get_client_credit(credit_id)

    try:
        if action == "full":
            credit = apply_client_credit_payment(credit_id, settle_full=True)
            message = (
                f"Factura {credit.get('invoice_number') or credit_id} pagada completamente desde cartera."
            )
        else:
            payment_amount = to_decimal(form.get("payment_amount"))
            credit = apply_client_credit_payment(credit_id, float(payment_amount))
            message = (
                f"Abono aplicado por {money_filter(credit.get('applied_amount'), fetch_settings()['rounding_mode'])} "
                f"en {credit.get('invoice_number') or f'credito #{credit_id}'}."
            )
        redirect_client_id = credit.get("client_id")
        redirect_url = f"/credits?success={quote(message)}"
        if redirect_client_id:
            redirect_url += f"&client_id={redirect_client_id}"
        return RedirectResponse(url=redirect_url, status_code=303)
    except (ValueError, TypeError) as error:
        redirect_url = f"/credits?error={quote(str(error))}"
        if existing_credit and existing_credit.get("client_id"):
            redirect_url += f"&client_id={existing_credit['client_id']}"
        return RedirectResponse(url=redirect_url, status_code=303)


@app.get("/settings")
def settings_page(request: Request, success: str = "", error: str = ""):
    if not is_admin_user(ensure_request_user(request)):
        return render_forbidden(request, "Solo un administrador puede cambiar el logo y la configuracion general.")
    success_message = None
    error_message = error or None
    if success == "platform-password-reset":
        success_message = "La contrasena del administrador de la plataforma fue actualizada."
    elif success == "platform-deleted":
        success_message = "La plataforma secundaria fue eliminada correctamente."
    return templates.TemplateResponse(
        request,
        "settings.html",
        base_context(request, page_id="settings", error=error_message, success=success_message, platform_login_url=platform_login_url),
    )


@app.post("/settings")
async def settings_save(request: Request):
    if not is_admin_user(ensure_request_user(request)):
        return render_forbidden(request, "Solo un administrador puede cambiar el logo y la configuracion general.")
    form = await request.form()
    current_settings = fetch_settings()
    values = {
        "org_name": (form.get("org_name") or current_settings["org_name"]).strip(),
        "brand_slogan": (form.get("brand_slogan") or current_settings.get("brand_slogan") or "").strip(),
        "legal_name": (form.get("legal_name") or current_settings.get("legal_name") or "").strip(),
        "company_nit": (form.get("company_nit") or current_settings.get("company_nit") or "").strip(),
        "company_email": normalize_email(form.get("company_email") or current_settings.get("company_email") or ""),
        "company_phone": (form.get("company_phone") or current_settings.get("company_phone") or "").strip(),
        "company_whatsapp": (form.get("company_whatsapp") or current_settings.get("company_whatsapp") or "").strip(),
        "company_address": (form.get("company_address") or current_settings.get("company_address") or "").strip(),
        "google_oauth_client_id": (form.get("google_oauth_client_id") or current_settings.get("google_oauth_client_id") or "").strip(),
        "google_oauth_client_secret": (form.get("google_oauth_client_secret") or current_settings.get("google_oauth_client_secret") or "").strip(),
        "google_oauth_redirect_uri": (form.get("google_oauth_redirect_uri") or current_settings.get("google_oauth_redirect_uri") or "").strip(),
        "google_oauth_prompt": (form.get("google_oauth_prompt") or current_settings.get("google_oauth_prompt") or "select_account").strip() or "select_account",
        "quote_prefix": (form.get("quote_prefix") or current_settings["quote_prefix"]).strip().upper(),
        "next_quote_number": int(to_decimal(form.get("next_quote_number"), str(current_settings["next_quote_number"]))),
        "currency_code": (form.get("currency_code") or current_settings["currency_code"]).strip().upper(),
        "iva_rate": float(to_decimal(form.get("iva_rate"), str(current_settings["iva_rate"]))),
        "rounding_mode": (form.get("rounding_mode") or current_settings["rounding_mode"]).strip(),
        "logo_filename": current_settings.get("logo_filename"),
        "logo_mime": current_settings.get("logo_mime"),
    }

    upload = form.get("logo")
    try:
        if upload and getattr(upload, "filename", ""):
            result = await save_logo(upload)
            delete_logo(current_settings.get("logo_filename"))
            values["logo_filename"] = result["filename"]
            values["logo_mime"] = result["mime"]
        update_settings(values)
    except ValueError as error:
        context = base_context(request, page_id="settings", error=str(error), success=None, platform_login_url=platform_login_url)
        context["settings"] = {**current_settings, **values}
        return templates.TemplateResponse(request, "settings.html", context, status_code=400)

    return templates.TemplateResponse(
        request,
        "settings.html",
        base_context(request, page_id="settings", error=None, success="Configuracion actualizada.", platform_login_url=platform_login_url),
    )


@app.post("/platforms/{platform_slug}/reset-password")
async def platform_reset_password(request: Request, platform_slug: str):
    if not is_admin_user(ensure_request_user(request)):
        return render_forbidden(request, "Solo un administrador puede cambiar contrasenas de plataformas.")

    form = await request.form()
    password = form.get("password") or ""
    confirm_password = form.get("confirm_password") or ""
    platform = get_platform(platform_slug)
    if not platform:
        return RedirectResponse(url="/settings?error=La%20plataforma%20solicitada%20no%20existe.", status_code=303)

    try:
        validate_password_confirmation(password, confirm_password)
        with use_platform(platform["slug"]):
            admin_user = next((user for user in list_users() if int(user.get("is_admin") or 0) == 1), None)
            if not admin_user:
                raise ValueError("La plataforma no tiene un administrador registrado.")
            update_user_password(int(admin_user["id"]), hash_password(password))
    except ValueError as error:
        return RedirectResponse(url=f"/settings?error={quote(str(error))}", status_code=303)

    return RedirectResponse(url="/settings?success=platform-password-reset", status_code=303)


@app.post("/platforms/{platform_slug}/delete")
async def platform_delete(request: Request, platform_slug: str):
    if not is_admin_user(ensure_request_user(request)):
        return render_forbidden(request, "Solo un administrador puede eliminar plataformas.")

    platform = get_platform(platform_slug)
    if not platform:
        return RedirectResponse(url="/settings?error=La%20plataforma%20solicitada%20no%20existe.", status_code=303)
    if platform["slug"] == PRIMARY_PLATFORM_SLUG:
        return RedirectResponse(url="/settings?error=La%20plataforma%20principal%20no%20se%20puede%20eliminar.", status_code=303)
    if platform["slug"] == current_platform_slug():
        return RedirectResponse(url="/settings?error=No%20puedes%20eliminar%20la%20plataforma%20que%20estas%20usando.", status_code=303)

    try:
        delete_platform_workspace(platform["slug"])
    except ValueError as error:
        return RedirectResponse(url=f"/settings?error={quote(str(error))}", status_code=303)

    return RedirectResponse(url="/settings?success=platform-deleted", status_code=303)


@app.get("/admin/users")
def admin_users_page(request: Request, success: str = ""):
    if not is_admin_user(ensure_request_user(request)):
        return render_forbidden(request, "Solo un administrador puede gestionar usuarios.")

    success_message = None
    if success == "user-created":
        success_message = "Usuario creado correctamente."
    elif success == "password-reset":
        success_message = "Contrasena actualizada correctamente."
    elif success == "user-updated":
        success_message = "Datos del usuario actualizados correctamente."
    elif success == "user-deleted":
        success_message = "Usuario eliminado correctamente."

    return render_users_page(request, success=success_message)


@app.post("/admin/users")
async def admin_users_create(request: Request):
    if not is_admin_user(ensure_request_user(request)):
        return render_forbidden(request, "Solo un administrador puede crear usuarios.")

    form = await request.form()
    full_name = (form.get("full_name") or "").strip()
    email = (form.get("email") or "").strip()
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    confirm_password = form.get("confirm_password") or ""
    is_admin = 1 if form.get("is_admin") else 0

    try:
        if not full_name:
            raise ValueError("El nombre completo es obligatorio.")
        normalized_username = normalize_username(username)
        normalized_email = normalize_email(email)
        validate_password_confirmation(password, confirm_password)
        create_user(
            normalized_username,
            hash_password(password),
            is_admin=bool(is_admin),
            full_name=full_name,
            email=normalized_email,
        )
    except (ValueError, sqlite3.IntegrityError) as error:
        message = "El usuario ya existe." if isinstance(error, sqlite3.IntegrityError) else str(error)
        return render_users_page(
            request,
            error=message,
            form_data={"full_name": full_name, "email": email, "username": username, "is_admin": is_admin},
            status_code=400,
        )

    return RedirectResponse(url="/admin/users?success=user-created", status_code=303)


@app.post("/admin/users/{user_id}/update")
async def admin_users_update(request: Request, user_id: int):
    current = ensure_request_user(request)
    if not is_admin_user(current):
        return render_forbidden(request, "Solo un administrador puede editar usuarios.")

    form = await request.form()
    full_name = (form.get("full_name") or "").strip()
    email = (form.get("email") or "").strip()
    username = (form.get("username") or "").strip()
    is_admin = 1 if form.get("is_admin") else 0

    try:
        if not full_name:
            raise ValueError("El nombre completo es obligatorio.")
        normalized_username = normalize_username(username)
        normalized_email = normalize_email(email)

        users = list_users()
        admin_count = sum(1 for user in users if user.get("is_admin"))
        target_user = next((user for user in users if int(user["id"]) == int(user_id)), None)
        if not target_user:
            raise ValueError("Usuario no encontrado.")
        if target_user.get("is_admin") and not is_admin and admin_count <= 1:
            raise ValueError("Debe existir al menos un administrador activo.")

        update_user_profile(
            user_id,
            username=normalized_username,
            full_name=full_name,
            email=normalized_email,
            is_admin=bool(is_admin),
        )
    except ValueError as error:
        return render_users_page(request, error=str(error), status_code=400)

    return RedirectResponse(url="/admin/users?success=user-updated", status_code=303)


@app.post("/admin/users/{user_id}/reset-password")
async def admin_users_reset_password(request: Request, user_id: int):
    if not is_admin_user(ensure_request_user(request)):
        return render_forbidden(request, "Solo un administrador puede restablecer contrasenas.")

    form = await request.form()
    password = form.get("password") or ""
    confirm_password = form.get("confirm_password") or ""

    try:
        validate_password_confirmation(password, confirm_password)
        update_user_password(user_id, hash_password(password))
        clear_password_recovery_code(user_id)
    except ValueError as error:
        return render_users_page(
            request,
            error=str(error),
            reset_user_id=user_id,
            status_code=400,
        )

    return RedirectResponse(url="/admin/users?success=password-reset", status_code=303)


@app.post("/admin/users/{user_id}/delete")
async def admin_users_delete(request: Request, user_id: int):
    current = ensure_request_user(request)
    if not is_admin_user(current):
        return render_forbidden(request, "Solo un administrador puede eliminar usuarios.")

    try:
        users = list_users()
        target_user = next((user for user in users if int(user["id"]) == int(user_id)), None)
        if not target_user:
            raise ValueError("Usuario no encontrado.")
        if current and int(current["id"]) == int(user_id):
            raise ValueError("No puedes eliminar el usuario con el que estas conectado.")

        admin_count = sum(1 for user in users if user.get("is_admin"))
        if target_user.get("is_admin") and admin_count <= 1:
            raise ValueError("Debe existir al menos un administrador activo.")

        clear_password_recovery_code(int(user_id))
        delete_user(int(user_id))
    except ValueError as error:
        return render_users_page(request, error=str(error), status_code=400)

    return RedirectResponse(url="/admin/users?success=user-deleted", status_code=303)


@app.get("/quotes/new")
def quote_new(
    request: Request,
    cart: str = "",
    mode: str = "quote",
    order_id: int | None = None,
    payment: str = "cash",
):
    settings = fetch_settings()
    user = ensure_request_user(request)
    requested_by = ""
    if user:
        requested_by = (user.get("full_name") or user.get("username") or "").strip()
    document_mode = "invoice" if mode == "invoice" else "quote"
    invoice_payment_mode = "credit" if (payment or "").strip().lower() == "credit" else "cash"
    order = get_catalog_order(order_id) if order_id else None
    if order_id and not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado.")
    quote_items = (
        catalog_order_to_quote_items(order, settings["rounding_mode"])
        if order
        else catalog_cart_to_quote_items(cart, settings["rounding_mode"])
    )
    form_data = {
        "title": "FACTURA DE VENTA" if document_mode == "invoice" else "COTIZACION EXPLORATORIA",
        "quote_date": date.today().isoformat(),
        "requested_by": requested_by,
        "tax_rate": settings["iva_rate"],
        "currency_code": settings["currency_code"],
        "price_margin_pct": 100,
        "closing_message": "Gracias por su atencion.",
        "client_type": "CONSUMER",
        "consumer_final": 1,
        "invoice_payment_mode": invoice_payment_mode,
    }
    if order:
        form_data.update(
            {
                "client_name": order.get("customer_name") or "",
                "client_phone": order.get("customer_phone") or "",
                "client_address": order.get("customer_address") or "",
                "location": order.get("customer_address") or "",
                "notes": f"Pedido de catalogo {order.get('order_number')}.",
            }
        )
    return render_quote_form(
        request,
        form_data=form_data,
        quote_items=quote_items,
        form_title=(
            "Factura a credito desde pedido"
            if document_mode == "invoice" and invoice_payment_mode == "credit" and quote_items
            else "Factura de contado desde pedido"
            if document_mode == "invoice" and quote_items
            else "Nueva cotizacion desde pedido"
            if quote_items
            else "Nueva cotizacion"
        ),
        form_intro=(
            "Al guardar, se genera la factura, se descuenta inventario y el pedido pasa automaticamente a cartera."
            if document_mode == "invoice" and invoice_payment_mode == "credit" and order
            else "Al guardar, se genera la factura de contado y se descuenta inventario sin crear cartera."
            if document_mode == "invoice" and order
            else "Productos cargados desde el pedido guardado. Revisa los datos y guarda la cotizacion."
            if order
            else "Productos cargados desde el carrito del catalogo. Completa los datos del cliente y guarda para abrir la factura."
            if document_mode == "invoice" and quote_items
            else "Productos cargados desde el carrito del catalogo. Completa los datos del cliente y guarda la cotizacion."
            if quote_items
            else "Combina items del catalogo o lineas manuales y revisa los totales en tiempo real."
        ),
        submit_label="Guardar y ver factura" if document_mode == "invoice" else "Guardar cotizacion",
        document_mode=document_mode,
        origin_order_id=int(order_id) if order else None,
    )


@app.get("/quotes/{quote_id}/edit")
def quote_edit(request: Request, quote_id: int):
    quote = get_quote(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail="Cotizacion no encontrada.")
    return render_quote_form(
        request,
        form_data=quote,
        quote_items=quote["items"],
        quote_id=quote_id,
        form_title="Editar cotización",
        form_intro="Ajusta cantidades, agrega productos o corrige valores y luego vuelve a exportar el mismo documento.",
        submit_label="Guardar cambios",
        quote_number=quote["quote_number"],
    )


@app.post("/quotes")
async def quote_save(request: Request):
    form = await request.form()
    settings = fetch_settings()
    quote_id = form.get("quote_id")
    origin_order_id = form.get("origin_order_id")
    document_mode = "invoice" if form.get("document_mode") == "invoice" else "quote"
    invoice_payment_mode = "credit" if (form.get("invoice_payment_mode") or "").strip().lower() == "credit" else "cash"
    user = ensure_request_user(request)
    current_quote = get_quote(int(quote_id)) if str(quote_id or "").isdigit() else None
    try:
        price_margin_pct = float(normalize_margin_percent(form.get("price_margin_pct"), "100"))
        client_type = normalize_client_type(
            form.get("client_type") or ("CONSUMER" if is_consumer_final_value(form.get("consumer_final")) else "BUSINESS"),
            allow_consumer=True,
        )
        consumer_final = client_type == "CONSUMER"
        client_name = (form.get("client_name") or "").strip()
        client_document_type = (form.get("client_document_type") or "").strip().upper()
        client_document_number = (form.get("client_document_number") or "").strip()
        client_email = "" if consumer_final else (form.get("client_email") or "").strip()
        client_phone = (form.get("client_phone") or "").strip()
        client_address = (form.get("client_address") or "").strip()

        if consumer_final:
            client_document_type = ""
            client_document_number = ""
        elif client_document_number and not client_document_type:
            client_document_type = "NIT" if client_type == "BUSINESS" else "CC"

        items = parse_quote_items(form, settings["rounding_mode"])
        totals = quote_totals(
            line_totals=[item["line_total"] for item in items],
            tax_rate=form.get("tax_rate") or settings["iva_rate"],
            rounding_mode=settings["rounding_mode"],
            taxable_flags=[item["taxable"] for item in items],
        )
        payload = {
            "title": (form.get("title") or "COTIZACION EXPLORATORIA").strip(),
            "location": (form.get("location") or client_address or "").strip(),
            "client_type": client_type,
            "client_name": client_name,
            "client_document_type": client_document_type,
            "client_document_number": client_document_number,
            "client_email": client_email,
            "client_phone": client_phone,
            "client_address": client_address,
            "requested_by": (form.get("requested_by") or user.get("full_name") or user.get("username") or "").strip() if user else (form.get("requested_by") or "").strip(),
            "quote_date": form.get("quote_date") or date.today().isoformat(),
            "currency_code": (form.get("currency_code") or settings["currency_code"]).strip().upper(),
            "price_factor": float(legacy_factor_from_margin(price_margin_pct)),
            "price_margin_pct": price_margin_pct,
            "tax_rate": float(to_decimal(form.get("tax_rate"), str(settings["iva_rate"]))),
            "subtotal": float(totals["subtotal"]),
            "tax_amount": float(totals["tax_amount"]),
            "total": float(totals["total"]),
            "status": (form.get("status") or (current_quote or {}).get("status") or "PENDING").strip().upper(),
            "notes": (form.get("notes") or "").strip(),
            "closing_message": (form.get("closing_message") or "").strip(),
        }
        if not payload["client_name"]:
            raise ValueError("Debes indicar el nombre del cliente.")
        if not payload["client_phone"]:
            raise ValueError("Debes indicar el telefono del cliente.")
        if not payload["client_address"]:
            raise ValueError("Debes indicar la direccion o ubicacion del cliente.")
        if quote_id:
            saved_quote_id = update_quote(int(quote_id), payload, items)
        else:
            saved_quote_id = create_quote(payload, items)
    except ValueError as error:
        form_values = {}
        for key in (
            "title",
            "location",
            "client_type",
            "consumer_final",
            "client_name",
            "client_document_type",
            "client_document_number",
            "client_email",
            "client_phone",
            "client_address",
            "requested_by",
            "quote_date",
            "currency_code",
            "price_margin_pct",
            "tax_rate",
            "notes",
            "closing_message",
            "invoice_payment_mode",
        ):
            form_values[key] = form.get(key) or ""
        return render_quote_form(
            request,
            form_data=form_values,
            quote_items=extract_quote_items_from_form(form),
            error=str(error),
            quote_id=int(quote_id) if quote_id else None,
            form_title="Editar cotización" if quote_id else "Nueva cotización",
            form_intro="Ajusta cantidades, agrega productos o corrige valores y luego vuelve a exportar el mismo documento." if quote_id else "Combina items del catálogo o líneas manuales y revisa los totales en tiempo real.",
            submit_label="Guardar cambios" if quote_id else "Guardar cotización",
            quote_number=(get_quote(int(quote_id)) or {}).get("quote_number") if quote_id else None,
            document_mode=document_mode,
            origin_order_id=int(origin_order_id) if str(origin_order_id or "").isdigit() else None,
            status_code=400,
        )
    if origin_order_id and str(origin_order_id).isdigit() and not quote_id:
        try:
            order_id = int(origin_order_id)
            link_catalog_order_quote(
                order_id,
                saved_quote_id,
                "INVOICED" if document_mode == "invoice" else "QUOTED",
            )
            if document_mode == "invoice":
                if invoice_payment_mode == "credit":
                    order = get_catalog_order(order_id)
                    if not order:
                        raise ValueError("Pedido no encontrado.")
                    client_id = find_or_create_client_from_order(order)
                    send_catalog_order_to_credit(order_id, client_id=client_id)
                else:
                    confirm_catalog_order_payment(
                        order_id,
                        method="Factura de contado",
                        reference=f"Factura {invoice_number_for_quote(get_quote(saved_quote_id) or {'quote_number': ''})}",
                    )
        except ValueError:
            pass
    elif document_mode == "invoice" and not quote_id:
        try:
            saved_quote = get_quote(saved_quote_id)
            if not saved_quote:
                raise ValueError("No fue posible cargar la factura generada.")
            if invoice_payment_mode == "credit":
                client_id = find_or_create_client_from_quote(saved_quote)
                send_quote_to_credit(saved_quote_id, client_id=client_id)
            else:
                confirm_quote_invoice_payment(
                    saved_quote_id,
                    method="Factura de contado",
                    reference=invoice_number_for_quote(saved_quote),
                )
        except ValueError as error:
            return RedirectResponse(
                url=f"/quotes/{saved_quote_id}?error={quote(str(error))}",
                status_code=303,
            )
    if document_mode == "invoice" and not quote_id:
        return RedirectResponse(url=f"/quotes/{saved_quote_id}/invoice", status_code=303)
    return RedirectResponse(url=f"/quotes/{saved_quote_id}", status_code=303)


@app.get("/quotes/{quote_id}")
def quote_detail(request: Request, quote_id: int):
    quote = get_quote(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail="Cotizacion no encontrada.")
    quote = normalize_quote_form_data(quote)
    return templates.TemplateResponse(
        request,
        "quote_detail.html",
        base_context(
            request,
            page_id="quotes",
            quote=quote,
            client_type_label=client_type_label,
            quote_status_label=quote_status_label,
            is_invoice=False,
            invoice_number=invoice_number_for_quote(quote),
        ),
    )


@app.post("/quotes/{quote_id}/issue-invoice")
async def quote_issue_invoice(request: Request, quote_id: int):
    form = await request.form()
    payment_mode = "credit" if (form.get("payment_mode") or "").strip().lower() == "credit" else "cash"
    due_date = (form.get("due_date") or "").strip()
    quote_data = get_quote(quote_id)
    if not quote_data:
        raise HTTPException(status_code=404, detail="Cotizacion no encontrada.")

    try:
        if payment_mode == "credit":
            client_id = find_or_create_client_from_quote(quote_data)
            send_quote_to_credit(quote_id, client_id=client_id, due_date=due_date)
            message = "Factura enviada a cartera."
        else:
            confirm_quote_invoice_payment(
                quote_id,
                method="Factura de contado",
                reference=invoice_number_for_quote(quote_data),
            )
            message = "Factura de contado generada."
    except ValueError as error:
        return RedirectResponse(
            url=f"/quotes/{quote_id}?error={quote(str(error))}",
            status_code=303,
        )

    return RedirectResponse(
        url=f"/quotes/{quote_id}/invoice?success={quote(message)}",
        status_code=303,
    )


@app.get("/quotes/{quote_id}/invoice")
def invoice_detail(request: Request, quote_id: int):
    quote = get_quote(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail="Cotizacion no encontrada.")
    invoice = normalize_quote_form_data(invoice_document_payload(quote))
    return templates.TemplateResponse(
        request,
        "quote_detail.html",
        base_context(
            request,
            page_id="quotes",
            quote=invoice,
            client_type_label=client_type_label,
            quote_status_label=quote_status_label,
            is_invoice=True,
            source_quote=quote,
            invoice_number=invoice["document_number"],
        ),
    )


@app.get("/quotes/{quote_id}/export-pdf")
def quote_export_pdf(quote_id: int):
    quote = get_quote(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail="Cotizacion no encontrada.")
    quote = normalize_quote_form_data(quote)
    settings = fetch_settings()
    pdf_file = build_quote_pdf(quote, settings)
    filename = f"{quote['quote_number']}.pdf"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        pdf_file,
        media_type="application/pdf",
        headers=headers,
    )


@app.get("/quotes/{quote_id}/invoice/export-pdf")
def invoice_export_pdf(quote_id: int):
    quote = get_quote(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail="Cotizacion no encontrada.")
    settings = fetch_settings()
    invoice = normalize_quote_form_data(invoice_document_payload(quote))
    pdf_file = build_quote_pdf(invoice, settings)
    filename = f"{invoice['document_number']}.pdf"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        pdf_file,
        media_type="application/pdf",
        headers=headers,
    )


@app.post("/quotes/{quote_id}/delete")
async def quote_delete(request: Request, quote_id: int):
    form = await request.form()
    next_url = (form.get("next") or "/").strip() or "/"
    try:
        delete_quote(quote_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))
    return RedirectResponse(url=next_url, status_code=303)
