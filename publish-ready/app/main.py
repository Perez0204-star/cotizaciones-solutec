from __future__ import annotations

import json
import sqlite3
from datetime import date
from decimal import Decimal
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import (
    BASE_DIR,
    UPLOADS_DIR,
    create_user,
    create_quote,
    delete_quote,
    ensure_storage,
    fetch_settings,
    get_catalog_item,
    get_client,
    get_quote,
    get_user_by_id,
    get_user_by_username,
    has_users,
    init_db,
    list_catalog_items,
    list_clients,
    list_quotes,
    save_catalog_item,
    save_client,
    update_quote,
    update_settings,
)
from app.services.auth import (
    SESSION_COOKIE_NAME,
    build_session_token,
    hash_password,
    normalize_username,
    read_session_user_id,
    session_cookie_options,
    validate_password_confirmation,
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
from app.services.excel_export import build_quote_workbook, ensure_template
from app.services.pdf_export import build_quote_pdf
from app.services.uploads import delete_logo, save_logo

app = FastAPI(title="Cotizaciones Web")

ensure_storage()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")
app.mount("/media", StaticFiles(directory=str(UPLOADS_DIR)), name="media")


def money_filter(value: object, rounding_mode: str = "integer") -> str:
    amount = round_money(value, rounding_mode)
    decimals = 2 if rounding_mode == "2dec" else 0
    return f"{amount:,.{decimals}f}"


def percent_filter(value: object) -> str:
    return f"{to_decimal(value):,.2f}"


templates.env.filters["money"] = money_filter
templates.env.filters["percent"] = percent_filter


@app.on_event("startup")
def startup() -> None:
    init_db()
    ensure_template()


def enrich_catalog_item(item: dict, rounding_mode: str) -> dict:
    item = dict(item)
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
    return item


def base_context(request: Request, **context) -> dict:
    return {
        "request": request,
        "settings": fetch_settings(),
        "current_user": getattr(request.state, "current_user", None),
        **context,
    }


def is_public_path(path: str) -> bool:
    if path.startswith("/static") or path.startswith("/media"):
        return True
    return path in {"/login", "/setup", "/favicon.ico", "/healthz"}


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


@app.middleware("http")
async def authentication_guard(request: Request, call_next):
    path = request.url.path
    if is_public_path(path):
        return await call_next(request)

    user = current_user(request)
    users_exist = has_users()

    if not users_exist:
        return RedirectResponse(url="/setup", status_code=303)

    if not user:
        requested_path = path
        if request.url.query:
            requested_path = f"{requested_path}?{request.url.query}"
        login_url = f"/login?next={quote(safe_next_path(requested_path), safe='/?=&')}"
        response = RedirectResponse(url=login_url, status_code=303)
        response.delete_cookie(SESSION_COOKIE_NAME, path="/")
        return response

    return await call_next(request)


@app.get("/healthz")
def healthcheck():
    return {"status": "ok"}


def parse_catalog_payload(form, item_id: int | None = None) -> dict:
    payload = {
        "id": item_id,
        "item_type": (form.get("item_type") or "PRODUCT").upper(),
        "sku": (form.get("sku") or "").strip().upper(),
        "description": (form.get("description") or "").strip(),
        "unit": (form.get("unit") or "").strip(),
        "cost_amount": float(to_decimal(form.get("cost_amount"))),
        "pricing_mode": (form.get("pricing_mode") or "MANUAL").upper(),
        "margin_pct": float(to_decimal(form.get("margin_pct"))),
        "markup_pct": float(to_decimal(form.get("markup_pct"))),
        "manual_price": float(to_decimal(form.get("manual_price"))),
        "tax_rate": float(to_decimal(form.get("tax_rate"))),
        "active": 1 if form.get("active") else 0,
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
        "name": (form.get("name") or "").strip(),
        "email": (form.get("email") or "").strip(),
        "phone": (form.get("phone") or "").strip(),
        "address": (form.get("address") or "").strip(),
    }
    if not payload["name"]:
        raise ValueError("El nombre del cliente es obligatorio.")
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
        form.getlist("discount_type"),
        form.getlist("discount_value"),
    )
    for source_id, sku, description, unit, qty, cost_amount, base_price_unit, price_unit, discount_type, discount_value in rows:
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
    status_code: int = 200,
):
    settings = fetch_settings()
    catalog_items = [
        enrich_catalog_item(item, settings["rounding_mode"])
        for item in list_catalog_items(active_only=False if quote_id else True)
    ]
    clients = list_clients()
    return templates.TemplateResponse(
        request,
        "quote_form.html",
        base_context(
            request,
            page_id="quotes",
            form_data=form_data,
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
        ),
        status_code=status_code,
    )


def render_auth_form(
    request: Request,
    *,
    template_name: str,
    title: str,
    intro: str,
    submit_label: str,
    next_path: str = "/",
    error: str | None = None,
    username: str = "",
    status_code: int = 200,
):
    return templates.TemplateResponse(
        request,
        template_name,
        base_context(
            request,
            page_id="auth",
            error=error,
            auth_title=title,
            auth_intro=intro,
            submit_label=submit_label,
            next_path=next_path,
            username=username,
        ),
        status_code=status_code,
    )


@app.get("/login")
def login_page(request: Request, next: str = "/"):
    if current_user(request):
        return RedirectResponse(url="/", status_code=303)
    if not has_users():
        return RedirectResponse(url="/setup", status_code=303)
    return render_auth_form(
        request,
        template_name="login.html",
        title="Ingresar a la aplicacion",
        intro="Accede con tu usuario y contrasena para administrar cotizaciones desde cualquier dispositivo.",
        submit_label="Ingresar",
        next_path=safe_next_path(next),
    )


@app.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    next_path = safe_next_path(form.get("next"))

    if not has_users():
        return RedirectResponse(url="/setup", status_code=303)

    try:
        normalized_username = normalize_username(username)
    except ValueError as error:
        return render_auth_form(
            request,
            template_name="login.html",
            title="Ingresar a la aplicacion",
            intro="Accede con tu usuario y contrasena para administrar cotizaciones desde cualquier dispositivo.",
            submit_label="Ingresar",
            next_path=next_path,
            username=username,
            error=str(error),
            status_code=400,
        )

    user = get_user_by_username(normalized_username)
    if not user or not verify_password(password, user["password_hash"]):
        return render_auth_form(
            request,
            template_name="login.html",
            title="Ingresar a la aplicacion",
            intro="Accede con tu usuario y contrasena para administrar cotizaciones desde cualquier dispositivo.",
            submit_label="Ingresar",
            next_path=next_path,
            username=username,
            error="Usuario o contrasena incorrectos.",
            status_code=401,
        )

    response = RedirectResponse(url=next_path, status_code=303)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        build_session_token(user["id"]),
        **session_cookie_options(),
    )
    return response


@app.get("/setup")
def setup_page(request: Request):
    user = current_user(request)
    if has_users():
        return RedirectResponse(url="/" if user else "/login", status_code=303)
    return render_auth_form(
        request,
        template_name="setup.html",
        title="Crear usuario administrador",
        intro="Este sera el primer acceso protegido de la aplicacion. Usa una contrasena segura para publicarla en internet.",
        submit_label="Crear acceso",
        next_path="/",
    )


@app.post("/setup")
async def setup_submit(request: Request):
    if has_users():
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    confirm_password = form.get("confirm_password") or ""

    try:
        normalized_username = normalize_username(username)
        validate_password_confirmation(password, confirm_password)
        user_id = create_user(normalized_username, hash_password(password))
    except (ValueError, sqlite3.IntegrityError) as error:
        return render_auth_form(
            request,
            template_name="setup.html",
            title="Crear usuario administrador",
            intro="Este sera el primer acceso protegido de la aplicacion. Usa una contrasena segura para publicarla en internet.",
            submit_label="Crear acceso",
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
    return response


@app.post("/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


@app.get("/")
def dashboard(request: Request):
    settings = fetch_settings()
    quotes = list_quotes(limit=999)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        base_context(
            request,
            page_id="dashboard",
            recent_quotes=quotes[:8],
            catalog_items=[enrich_catalog_item(item, settings["rounding_mode"]) for item in list_catalog_items()[:6]],
            clients=list_clients()[:6],
            stats={
                "catalog": len(list_catalog_items()),
                "clients": len(list_clients()),
                "quotes": len(quotes),
            },
        ),
    )


@app.get("/catalog")
def catalog_list(request: Request):
    settings = fetch_settings()
    items = [enrich_catalog_item(item, settings["rounding_mode"]) for item in list_catalog_items()]
    return templates.TemplateResponse(
        request,
        "catalog_list.html",
        base_context(request, page_id="catalog", items=items),
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
                "pricing_mode": "MARGIN",
                "active": 1,
                "margin_pct": 30,
                "markup_pct": 0,
                "tax_rate": fetch_settings()["iva_rate"],
            },
            error=None,
            item_id=None,
        ),
    )


@app.get("/catalog/{item_id}/edit")
def catalog_edit(request: Request, item_id: int):
    item = get_catalog_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado.")
    return templates.TemplateResponse(
        request,
        "catalog_form.html",
        base_context(request, page_id="catalog", form_data=item, error=None, item_id=item_id),
    )


@app.post("/catalog/save")
async def catalog_save(request: Request):
    form = await request.form()
    item_id = form.get("id")
    try:
        payload = parse_catalog_payload(form, int(item_id) if item_id else None)
        save_catalog_item(payload)
    except (ValueError, sqlite3.IntegrityError) as error:
        return templates.TemplateResponse(
            request,
            "catalog_form.html",
            base_context(
                request,
                page_id="catalog",
                form_data={key: value for key, value in form.items()},
                error="El SKU ya existe." if isinstance(error, sqlite3.IntegrityError) else str(error),
                item_id=int(item_id) if item_id else None,
            ),
            status_code=400,
        )
    return RedirectResponse(url="/catalog", status_code=303)


@app.get("/clients")
def clients_list(request: Request):
    return templates.TemplateResponse(
        request,
        "client_list.html",
        base_context(request, page_id="clients", clients=list_clients()),
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
    return RedirectResponse(url="/clients", status_code=303)


@app.get("/settings")
def settings_page(request: Request):
    return templates.TemplateResponse(
        request,
        "settings.html",
        base_context(request, page_id="settings", error=None, success=None),
    )


@app.post("/settings")
async def settings_save(request: Request):
    form = await request.form()
    current_settings = fetch_settings()
    values = {
        "org_name": (form.get("org_name") or current_settings["org_name"]).strip(),
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
        context = base_context(request, page_id="settings", error=str(error), success=None)
        context["settings"] = {**current_settings, **values}
        return templates.TemplateResponse(request, "settings.html", context, status_code=400)

    return templates.TemplateResponse(
        request,
        "settings.html",
        base_context(request, page_id="settings", error=None, success="Configuracion actualizada."),
    )


@app.get("/quotes/new")
def quote_new(request: Request):
    settings = fetch_settings()
    return render_quote_form(
        request,
        form_data={
            "title": "COTIZACION EXPLORATORIA",
            "quote_date": date.today().isoformat(),
            "tax_rate": settings["iva_rate"],
            "currency_code": settings["currency_code"],
            "price_margin_pct": 100,
        },
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
    try:
        price_margin_pct = float(normalize_margin_percent(form.get("price_margin_pct"), "100"))
        items = parse_quote_items(form, settings["rounding_mode"])
        totals = quote_totals(
            line_totals=[item["line_total"] for item in items],
            tax_rate=form.get("tax_rate") or settings["iva_rate"],
            rounding_mode=settings["rounding_mode"],
        )
        payload = {
            "title": (form.get("title") or "COTIZACION EXPLORATORIA").strip(),
            "location": (form.get("location") or "").strip(),
            "client_name": (form.get("client_name") or "").strip(),
            "client_email": (form.get("client_email") or "").strip(),
            "requested_by": (form.get("requested_by") or "").strip(),
            "quote_date": form.get("quote_date") or date.today().isoformat(),
            "currency_code": (form.get("currency_code") or settings["currency_code"]).strip().upper(),
            "price_factor": float(legacy_factor_from_margin(price_margin_pct)),
            "price_margin_pct": price_margin_pct,
            "tax_rate": float(to_decimal(form.get("tax_rate"), str(settings["iva_rate"]))),
            "subtotal": float(totals["subtotal"]),
            "tax_amount": float(totals["tax_amount"]),
            "total": float(totals["total"]),
            "notes": (form.get("notes") or "").strip(),
        }
        if not payload["location"] or not payload["client_name"] or not payload["requested_by"]:
            raise ValueError("Ubicacion, cliente y solicitado por son obligatorios.")
        if quote_id:
            saved_quote_id = update_quote(int(quote_id), payload, items)
        else:
            saved_quote_id = create_quote(payload, items)
    except ValueError as error:
        form_values = {}
        for key in ("title", "location", "client_name", "client_email", "requested_by", "quote_date", "currency_code", "price_margin_pct", "tax_rate", "notes"):
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
            status_code=400,
        )
    return RedirectResponse(url=f"/quotes/{saved_quote_id}", status_code=303)


@app.get("/quotes/{quote_id}")
def quote_detail(request: Request, quote_id: int):
    quote = get_quote(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail="Cotizacion no encontrada.")
    return templates.TemplateResponse(
        request,
        "quote_detail.html",
        base_context(request, page_id="quotes", quote=quote),
    )


@app.get("/quotes/{quote_id}/export")
def quote_export(quote_id: int):
    quote = get_quote(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail="Cotizacion no encontrada.")
    settings = fetch_settings()
    workbook = build_quote_workbook(quote, settings)
    filename = f"{quote['quote_number']}.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@app.get("/quotes/{quote_id}/export-pdf")
def quote_export_pdf(quote_id: int):
    quote = get_quote(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail="Cotizacion no encontrada.")
    settings = fetch_settings()
    pdf_file = build_quote_pdf(quote, settings)
    filename = f"{quote['quote_number']}.pdf"
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
