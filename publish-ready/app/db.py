from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("APP_DATA_DIR", str(BASE_DIR / "data"))).resolve()
UPLOADS_DIR = DATA_DIR / "uploads"
TEMPLATE_DIR = DATA_DIR / "templates"
EXPORTS_DIR = DATA_DIR / "exports"
DB_PATH = DATA_DIR / "cotizaciones.db"

DEFAULT_SETTINGS = {
    "org_name": "Tu Empresa",
    "quote_prefix": "COT",
    "next_quote_number": 1,
    "currency_code": "COP",
    "iva_rate": 19.0,
    "rounding_mode": "integer",
    "logo_filename": None,
    "logo_mime": None,
}


def utcnow_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def ensure_storage() -> None:
    for path in (DATA_DIR, UPLOADS_DIR, TEMPLATE_DIR, EXPORTS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    ensure_storage()
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _has_column(connection: sqlite3.Connection, table: str, column: str) -> bool:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def init_db() -> None:
    ensure_storage()
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                org_name TEXT NOT NULL,
                quote_prefix TEXT NOT NULL,
                next_quote_number INTEGER NOT NULL DEFAULT 1,
                currency_code TEXT NOT NULL,
                iva_rate REAL NOT NULL DEFAULT 19,
                rounding_mode TEXT NOT NULL DEFAULT 'integer',
                logo_filename TEXT,
                logo_mime TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS catalog_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_type TEXT NOT NULL CHECK (item_type IN ('PRODUCT', 'SERVICE')),
                sku TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL,
                unit TEXT NOT NULL,
                cost_amount REAL NOT NULL DEFAULT 0,
                pricing_mode TEXT NOT NULL CHECK (pricing_mode IN ('MARGIN', 'MARKUP', 'MANUAL')),
                margin_pct REAL NOT NULL DEFAULT 0,
                markup_pct REAL NOT NULL DEFAULT 0,
                manual_price REAL NOT NULL DEFAULT 0,
                tax_rate REAL,
                active INTEGER NOT NULL DEFAULT 1,
                notes_internal TEXT,
                notes_quote TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT,
                phone TEXT,
                address TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS quotes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quote_number TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                location TEXT NOT NULL,
                client_name TEXT NOT NULL,
                client_email TEXT,
                requested_by TEXT NOT NULL,
                quote_date TEXT NOT NULL,
                currency_code TEXT NOT NULL,
                price_factor REAL NOT NULL DEFAULT 1,
                price_margin_pct REAL NOT NULL DEFAULT 100,
                tax_rate REAL NOT NULL,
                subtotal REAL NOT NULL,
                tax_amount REAL NOT NULL,
                total REAL NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS quote_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quote_id INTEGER NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
                source_item_id INTEGER REFERENCES catalog_items(id),
                sku TEXT NOT NULL,
                description TEXT NOT NULL,
                unit TEXT NOT NULL,
                qty REAL NOT NULL,
                cost_amount REAL NOT NULL,
                base_price_unit REAL NOT NULL DEFAULT 0,
                price_unit REAL NOT NULL,
                discount_type TEXT NOT NULL,
                discount_value REAL NOT NULL,
                line_subtotal REAL NOT NULL,
                line_discount REAL NOT NULL,
                line_total REAL NOT NULL,
                sort_order INTEGER NOT NULL
            );
            """
        )

        if not _has_column(conn, "quotes", "price_factor"):
            conn.execute("ALTER TABLE quotes ADD COLUMN price_factor REAL NOT NULL DEFAULT 1")
        if not _has_column(conn, "quotes", "price_margin_pct"):
            conn.execute("ALTER TABLE quotes ADD COLUMN price_margin_pct REAL NOT NULL DEFAULT 100")
        if not _has_column(conn, "quote_items", "base_price_unit"):
            conn.execute("ALTER TABLE quote_items ADD COLUMN base_price_unit REAL NOT NULL DEFAULT 0")

        conn.execute("UPDATE quotes SET price_factor = 1 WHERE price_factor IS NULL OR price_factor <= 0")
        conn.execute(
            """
            UPDATE quotes
            SET price_margin_pct = ROUND(price_factor * 100.0, 2)
            WHERE price_margin_pct IS NULL
               OR ABS(price_margin_pct - ROUND(price_factor * 100.0, 2)) > 0.0001
            """
        )
        conn.execute(
            "UPDATE quote_items SET base_price_unit = price_unit WHERE base_price_unit IS NULL OR base_price_unit <= 0"
        )

        current = conn.execute("SELECT id FROM settings WHERE id = 1").fetchone()
        if not current:
            conn.execute(
                """
                INSERT INTO settings (
                    id, org_name, quote_prefix, next_quote_number, currency_code,
                    iva_rate, rounding_mode, logo_filename, logo_mime, updated_at
                ) VALUES (1, :org_name, :quote_prefix, :next_quote_number, :currency_code,
                          :iva_rate, :rounding_mode, :logo_filename, :logo_mime, :updated_at)
                """,
                {**DEFAULT_SETTINGS, "updated_at": utcnow_iso()},
            )
        conn.commit()


def fetch_settings() -> dict[str, Any]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    return dict(row) if row else {**DEFAULT_SETTINGS}


def has_users() -> bool:
    with get_connection() as conn:
        row = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
    return row is not None


def get_user_by_id(user_id: int | None) -> dict[str, Any] | None:
    if not user_id:
        return None
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_username(username: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return dict(row) if row else None


def create_user(username: str, password_hash: str, *, is_admin: bool = True) -> int:
    now = utcnow_iso()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO users (username, password_hash, is_admin, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (username, password_hash, 1 if is_admin else 0, now, now),
        )
        conn.commit()
    return int(cursor.lastrowid)


def update_settings(payload: dict[str, Any]) -> None:
    values = {**fetch_settings(), **payload, "updated_at": utcnow_iso()}
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE settings
            SET org_name = :org_name,
                quote_prefix = :quote_prefix,
                next_quote_number = :next_quote_number,
                currency_code = :currency_code,
                iva_rate = :iva_rate,
                rounding_mode = :rounding_mode,
                logo_filename = :logo_filename,
                logo_mime = :logo_mime,
                updated_at = :updated_at
            WHERE id = 1
            """,
            values,
        )
        conn.commit()


def list_catalog_items(active_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM catalog_items"
    params: tuple[Any, ...] = ()
    if active_only:
        sql += " WHERE active = ?"
        params = (1,)
    sql += " ORDER BY active DESC, item_type, sku"
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def get_catalog_item(item_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM catalog_items WHERE id = ?", (item_id,)).fetchone()
    return dict(row) if row else None


def save_catalog_item(payload: dict[str, Any]) -> int:
    now = utcnow_iso()
    values = {
        "item_type": payload["item_type"],
        "sku": payload["sku"],
        "description": payload["description"],
        "unit": payload["unit"],
        "cost_amount": payload["cost_amount"],
        "pricing_mode": payload["pricing_mode"],
        "margin_pct": payload["margin_pct"],
        "markup_pct": payload["markup_pct"],
        "manual_price": payload["manual_price"],
        "tax_rate": payload["tax_rate"],
        "active": payload["active"],
        "notes_internal": payload.get("notes_internal") or "",
        "notes_quote": payload.get("notes_quote") or "",
        "updated_at": now,
    }
    with get_connection() as conn:
        if payload.get("id"):
            values["id"] = payload["id"]
            conn.execute(
                """
                UPDATE catalog_items
                SET item_type = :item_type,
                    sku = :sku,
                    description = :description,
                    unit = :unit,
                    cost_amount = :cost_amount,
                    pricing_mode = :pricing_mode,
                    margin_pct = :margin_pct,
                    markup_pct = :markup_pct,
                    manual_price = :manual_price,
                    tax_rate = :tax_rate,
                    active = :active,
                    notes_internal = :notes_internal,
                    notes_quote = :notes_quote,
                    updated_at = :updated_at
                WHERE id = :id
                """,
                values,
            )
            item_id = int(payload["id"])
        else:
            values["created_at"] = now
            cursor = conn.execute(
                """
                INSERT INTO catalog_items (
                    item_type, sku, description, unit, cost_amount, pricing_mode,
                    margin_pct, markup_pct, manual_price, tax_rate, active,
                    notes_internal, notes_quote, created_at, updated_at
                ) VALUES (
                    :item_type, :sku, :description, :unit, :cost_amount, :pricing_mode,
                    :margin_pct, :markup_pct, :manual_price, :tax_rate, :active,
                    :notes_internal, :notes_quote, :created_at, :updated_at
                )
                """,
                values,
            )
            item_id = int(cursor.lastrowid)
        conn.commit()
    return item_id


def list_clients() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM clients ORDER BY name").fetchall()
    return [dict(row) for row in rows]


def get_client(client_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    return dict(row) if row else None


def save_client(payload: dict[str, Any]) -> int:
    now = utcnow_iso()
    values = {
        "name": payload["name"],
        "email": payload.get("email") or "",
        "phone": payload.get("phone") or "",
        "address": payload.get("address") or "",
        "updated_at": now,
    }
    with get_connection() as conn:
        if payload.get("id"):
            values["id"] = payload["id"]
            conn.execute(
                """
                UPDATE clients
                SET name = :name,
                    email = :email,
                    phone = :phone,
                    address = :address,
                    updated_at = :updated_at
                WHERE id = :id
                """,
                values,
            )
            client_id = int(payload["id"])
        else:
            values["created_at"] = now
            cursor = conn.execute(
                """
                INSERT INTO clients (name, email, phone, address, created_at, updated_at)
                VALUES (:name, :email, :phone, :address, :created_at, :updated_at)
                """,
                values,
            )
            client_id = int(cursor.lastrowid)
        conn.commit()
    return client_id


def list_quotes(limit: int = 20) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM quotes ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_quote(quote_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        quote_row = conn.execute("SELECT * FROM quotes WHERE id = ?", (quote_id,)).fetchone()
        if not quote_row:
            return None
        item_rows = conn.execute(
            "SELECT * FROM quote_items WHERE quote_id = ? ORDER BY sort_order, id",
            (quote_id,),
        ).fetchall()
    return {**dict(quote_row), "items": [dict(row) for row in item_rows]}


def delete_quote(quote_id: int) -> None:
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT id FROM quotes WHERE id = ?", (quote_id,)).fetchone()
        if not existing:
            raise ValueError("Cotizacion no encontrada.")
        conn.execute("DELETE FROM quotes WHERE id = ?", (quote_id,))
        conn.commit()


def create_quote(payload: dict[str, Any], items: list[dict[str, Any]]) -> int:
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        settings = conn.execute(
            "SELECT quote_prefix, next_quote_number FROM settings WHERE id = 1"
        ).fetchone()
        prefix = settings["quote_prefix"]
        next_number = int(settings["next_quote_number"])
        quote_number = f"{prefix}-{next_number:06d}"

        created_at = utcnow_iso()
        cursor = conn.execute(
            """
            INSERT INTO quotes (
                quote_number, title, location, client_name, client_email, requested_by,
                quote_date, currency_code, price_factor, price_margin_pct, tax_rate, subtotal, tax_amount, total, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                quote_number,
                payload["title"],
                payload["location"],
                payload["client_name"],
                payload.get("client_email") or "",
                payload["requested_by"],
                payload["quote_date"],
                payload["currency_code"],
                payload["price_factor"],
                payload["price_margin_pct"],
                payload["tax_rate"],
                payload["subtotal"],
                payload["tax_amount"],
                payload["total"],
                payload.get("notes") or "",
                created_at,
            ),
        )
        quote_id = int(cursor.lastrowid)

        for sort_order, item in enumerate(items, start=1):
            conn.execute(
                """
                INSERT INTO quote_items (
                    quote_id, source_item_id, sku, description, unit, qty, cost_amount, base_price_unit,
                    price_unit, discount_type, discount_value, line_subtotal, line_discount,
                    line_total, sort_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    quote_id,
                    item.get("source_item_id"),
                    item["sku"],
                    item["description"],
                    item["unit"],
                    item["qty"],
                    item["cost_amount"],
                    item["base_price_unit"],
                    item["price_unit"],
                    item["discount_type"],
                    item["discount_value"],
                    item["line_subtotal"],
                    item["line_discount"],
                    item["line_total"],
                    sort_order,
                ),
            )

        conn.execute(
            "UPDATE settings SET next_quote_number = ?, updated_at = ? WHERE id = 1",
            (next_number + 1, utcnow_iso()),
        )
        conn.commit()
    return quote_id


def update_quote(quote_id: int, payload: dict[str, Any], items: list[dict[str, Any]]) -> int:
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT id FROM quotes WHERE id = ?",
            (quote_id,),
        ).fetchone()
        if not existing:
            raise ValueError("Cotizacion no encontrada.")

        conn.execute(
            """
            UPDATE quotes
            SET title = ?,
                location = ?,
                client_name = ?,
                client_email = ?,
                requested_by = ?,
                quote_date = ?,
                currency_code = ?,
                price_factor = ?,
                price_margin_pct = ?,
                tax_rate = ?,
                subtotal = ?,
                tax_amount = ?,
                total = ?,
                notes = ?
            WHERE id = ?
            """,
            (
                payload["title"],
                payload["location"],
                payload["client_name"],
                payload.get("client_email") or "",
                payload["requested_by"],
                payload["quote_date"],
                payload["currency_code"],
                payload["price_factor"],
                payload["price_margin_pct"],
                payload["tax_rate"],
                payload["subtotal"],
                payload["tax_amount"],
                payload["total"],
                payload.get("notes") or "",
                quote_id,
            ),
        )

        conn.execute("DELETE FROM quote_items WHERE quote_id = ?", (quote_id,))
        for sort_order, item in enumerate(items, start=1):
            conn.execute(
                """
                INSERT INTO quote_items (
                    quote_id, source_item_id, sku, description, unit, qty, cost_amount, base_price_unit,
                    price_unit, discount_type, discount_value, line_subtotal, line_discount,
                    line_total, sort_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    quote_id,
                    item.get("source_item_id"),
                    item["sku"],
                    item["description"],
                    item["unit"],
                    item["qty"],
                    item["cost_amount"],
                    item["base_price_unit"],
                    item["price_unit"],
                    item["discount_type"],
                    item["discount_value"],
                    item["line_subtotal"],
                    item["line_discount"],
                    item["line_total"],
                    sort_order,
                ),
            )
        conn.commit()
    return quote_id
