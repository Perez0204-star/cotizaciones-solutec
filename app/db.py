from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("APP_DATA_DIR", str(BASE_DIR / "data"))).resolve()
UPLOADS_DIR = DATA_DIR / "uploads"
TEMPLATE_DIR = DATA_DIR / "templates"
EXPORTS_DIR = DATA_DIR / "exports"
DB_PATH = DATA_DIR / "cotizaciones.db"
PLATFORMS_DIR = DATA_DIR / "platforms"
PLATFORMS_REGISTRY_PATH = DATA_DIR / "platforms.json"
PRIMARY_PLATFORM_SLUG = "principal"
PLATFORM_SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,46}[a-z0-9])?$")
_CURRENT_PLATFORM: ContextVar[str] = ContextVar("current_platform", default=PRIMARY_PLATFORM_SLUG)

DEFAULT_SETTINGS = {
    "org_name": "Technological World",
    "brand_slogan": "Conectamos ideas con tecnologia",
    "legal_name": "",
    "company_nit": "",
    "company_email": "",
    "company_phone": "",
    "company_whatsapp": "",
    "company_address": "",
    "google_oauth_client_id": "",
    "google_oauth_client_secret": "",
    "google_oauth_redirect_uri": "",
    "google_oauth_prompt": "select_account",
    "quote_prefix": "COT",
    "next_quote_number": 1,
    "currency_code": "COP",
    "iva_rate": 19.0,
    "rounding_mode": "integer",
    "logo_filename": None,
    "logo_mime": None,
}

DEFAULT_CLOSING_MESSAGE = "Gracias por su atencion."
DEFAULT_CATALOG_CATEGORY = "TECHNOLOGY"
CATALOG_CATEGORY_LABELS = {
    "TECHNOLOGY": "TECNOLOGIA",
    "FOOD": "ALIMENTOS",
    "FASHION": "ROPA Y CALZADO",
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_catalog_category(value: str | None) -> str:
    candidate = (value or "").strip().upper()
    if not candidate:
        return DEFAULT_CATALOG_CATEGORY
    if candidate not in CATALOG_CATEGORY_LABELS:
        raise ValueError("La categoria del catalogo no es valida.")
    return candidate


def normalize_platform_slug(value: str | None) -> str:
    raw = (value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    normalized = re.sub(r"-{2,}", "-", normalized)
    if not normalized:
        normalized = PRIMARY_PLATFORM_SLUG
    if len(normalized) > 48:
        normalized = normalized[:48].rstrip("-")
    if not PLATFORM_SLUG_PATTERN.fullmatch(normalized):
        raise ValueError("El identificador de la plataforma solo puede usar letras, numeros y guiones.")
    return normalized


def current_platform_slug() -> str:
    return normalize_platform_slug(_CURRENT_PLATFORM.get(PRIMARY_PLATFORM_SLUG))


def current_is_primary_platform() -> bool:
    return current_platform_slug() == PRIMARY_PLATFORM_SLUG


def current_data_dir() -> Path:
    slug = current_platform_slug()
    if slug == PRIMARY_PLATFORM_SLUG:
        return DATA_DIR
    return PLATFORMS_DIR / slug


def current_uploads_dir() -> Path:
    return current_data_dir() / "uploads"


def current_template_dir() -> Path:
    return current_data_dir() / "templates"


def current_exports_dir() -> Path:
    return current_data_dir() / "exports"


def current_db_path() -> Path:
    return current_data_dir() / "cotizaciones.db"


@contextmanager
def use_platform(slug: str):
    token = _CURRENT_PLATFORM.set(normalize_platform_slug(slug))
    try:
        yield
    finally:
        _CURRENT_PLATFORM.reset(token)


def _read_platform_registry() -> list[dict[str, Any]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PLATFORMS_DIR.mkdir(parents=True, exist_ok=True)
    if not PLATFORMS_REGISTRY_PATH.exists():
        registry = [
            {
                "slug": PRIMARY_PLATFORM_SLUG,
                "name": "Plataforma principal",
                "brand_slogan": "Conectamos ideas con tecnologia",
                "created_at": utcnow_iso(),
                "is_primary": True,
            }
        ]
        PLATFORMS_REGISTRY_PATH.write_text(
            json.dumps(registry, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        return registry
    try:
        raw = json.loads(PLATFORMS_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        raw = []
    if not isinstance(raw, list):
        raw = []
    normalized_entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            slug = normalize_platform_slug(entry.get("slug"))
        except ValueError:
            continue
        if slug in seen:
            continue
        seen.add(slug)
        normalized_entries.append(
            {
                "slug": slug,
                "name": str(entry.get("name") or ("Plataforma principal" if slug == PRIMARY_PLATFORM_SLUG else slug.title())).strip(),
                "brand_slogan": str(entry.get("brand_slogan") or "").strip(),
                "created_at": str(entry.get("created_at") or utcnow_iso()),
                "is_primary": bool(entry.get("is_primary")) or slug == PRIMARY_PLATFORM_SLUG,
            }
        )
    if PRIMARY_PLATFORM_SLUG not in seen:
        normalized_entries.insert(
            0,
            {
                "slug": PRIMARY_PLATFORM_SLUG,
                "name": "Plataforma principal",
                "brand_slogan": "Conectamos ideas con tecnologia",
                "created_at": utcnow_iso(),
                "is_primary": True,
            },
        )
    PLATFORMS_REGISTRY_PATH.write_text(
        json.dumps(normalized_entries, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    return normalized_entries


def _write_platform_registry(entries: list[dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PLATFORMS_DIR.mkdir(parents=True, exist_ok=True)
    PLATFORMS_REGISTRY_PATH.write_text(
        json.dumps(entries, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def list_platforms() -> list[dict[str, Any]]:
    entries = _read_platform_registry()
    platforms: list[dict[str, Any]] = []
    for entry in entries:
        platform = dict(entry)
        platform["admin_full_name"] = ""
        platform["admin_username"] = ""
        platform["admin_email"] = ""
        platform["admin_count"] = 0
        try:
            with use_platform(platform["slug"]):
                if current_db_path().exists():
                    settings = fetch_settings()
                    platform["name"] = settings.get("org_name") or platform["name"]
                    platform["brand_slogan"] = settings.get("brand_slogan") or platform.get("brand_slogan") or ""
                    admin_users = [user for user in list_users() if int(user.get("is_admin") or 0) == 1]
                    platform["admin_count"] = len(admin_users)
                    if admin_users:
                        primary_admin = admin_users[0]
                        platform["admin_full_name"] = (primary_admin.get("full_name") or "").strip()
                        platform["admin_username"] = (primary_admin.get("username") or "").strip()
                        platform["admin_email"] = (primary_admin.get("email") or "").strip()
        except Exception:
            pass
        platforms.append(platform)
    return platforms


def get_platform(slug: str | None) -> dict[str, Any] | None:
    normalized = normalize_platform_slug(slug)
    for entry in list_platforms():
        if entry["slug"] == normalized:
            return entry
    return None


def platform_exists(slug: str | None) -> bool:
    return get_platform(slug) is not None


def delete_platform_workspace(slug: str) -> None:
    normalized = normalize_platform_slug(slug)
    if normalized == PRIMARY_PLATFORM_SLUG:
        raise ValueError("La plataforma principal no se puede eliminar.")

    registry = _read_platform_registry()
    if not any(entry["slug"] == normalized for entry in registry):
        raise ValueError("La plataforma solicitada no existe.")

    platform_dir = PLATFORMS_DIR / normalized
    if platform_dir.exists():
        shutil.rmtree(platform_dir)

    _write_platform_registry([entry for entry in registry if entry["slug"] != normalized])


def ensure_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PLATFORMS_DIR.mkdir(parents=True, exist_ok=True)
    for path in (current_data_dir(), current_uploads_dir(), current_template_dir(), current_exports_dir()):
        path.mkdir(parents=True, exist_ok=True)


@contextmanager
def get_connection():
    ensure_storage()
    connection = sqlite3.connect(current_db_path())
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
    finally:
        connection.close()


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
                brand_slogan TEXT NOT NULL DEFAULT 'Conectamos ideas con tecnologia',
                legal_name TEXT NOT NULL DEFAULT '',
                company_nit TEXT NOT NULL DEFAULT '',
                company_email TEXT NOT NULL DEFAULT '',
                company_phone TEXT NOT NULL DEFAULT '',
                company_whatsapp TEXT NOT NULL DEFAULT '',
                company_address TEXT NOT NULL DEFAULT '',
                google_oauth_client_id TEXT NOT NULL DEFAULT '',
                google_oauth_client_secret TEXT NOT NULL DEFAULT '',
                google_oauth_redirect_uri TEXT NOT NULL DEFAULT '',
                google_oauth_prompt TEXT NOT NULL DEFAULT 'select_account',
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
                category TEXT NOT NULL DEFAULT 'TECHNOLOGY',
                sku TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL,
                unit TEXT NOT NULL,
                cost_amount REAL NOT NULL DEFAULT 0,
                pricing_mode TEXT NOT NULL CHECK (pricing_mode IN ('MARGIN', 'MARKUP', 'MANUAL')),
                margin_pct REAL NOT NULL DEFAULT 0,
                markup_pct REAL NOT NULL DEFAULT 0,
                manual_price REAL NOT NULL DEFAULT 0,
                tax_rate REAL,
                taxable INTEGER NOT NULL DEFAULT 1,
                available_qty REAL NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                image_filename TEXT,
                image_mime TEXT,
                video_url TEXT,
                notes_internal TEXT,
                notes_quote TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS catalog_item_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL REFERENCES catalog_items(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                mime TEXT NOT NULL DEFAULT 'image/png',
                sort_order INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS catalog_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_number TEXT NOT NULL UNIQUE,
                quote_id INTEGER REFERENCES quotes(id) ON DELETE SET NULL,
                credit_id INTEGER REFERENCES client_credits(id) ON DELETE SET NULL,
                customer_name TEXT NOT NULL,
                customer_phone TEXT,
                customer_address TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'NEW',
                payment_status TEXT NOT NULL DEFAULT 'PENDING',
                payment_method TEXT,
                tax_amount REAL NOT NULL DEFAULT 0,
                subtotal REAL NOT NULL DEFAULT 0,
                total REAL NOT NULL DEFAULT 0,
                paid_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS catalog_order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES catalog_orders(id) ON DELETE CASCADE,
                catalog_item_id INTEGER REFERENCES catalog_items(id),
                sku TEXT NOT NULL,
                description TEXT NOT NULL,
                unit TEXT NOT NULL,
                qty REAL NOT NULL,
                price_unit REAL NOT NULL,
                taxable INTEGER NOT NULL DEFAULT 1,
                line_total REAL NOT NULL,
                sort_order INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_type TEXT NOT NULL DEFAULT 'BUSINESS',
                name TEXT NOT NULL,
                document_type TEXT,
                document_number TEXT,
                email TEXT,
                phone TEXT,
                address TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS client_credits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                order_id INTEGER REFERENCES catalog_orders(id) ON DELETE SET NULL,
                quote_id INTEGER REFERENCES quotes(id) ON DELETE SET NULL,
                order_number TEXT,
                description TEXT NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                paid_amount REAL NOT NULL DEFAULT 0,
                due_date TEXT,
                status TEXT NOT NULL DEFAULT 'PENDING',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS quotes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quote_number TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                location TEXT NOT NULL,
                client_type TEXT NOT NULL DEFAULT 'BUSINESS',
                client_name TEXT NOT NULL,
                client_document_type TEXT,
                client_document_number TEXT,
                client_email TEXT,
                client_phone TEXT,
                client_address TEXT,
                requested_by TEXT NOT NULL,
                quote_date TEXT NOT NULL,
                currency_code TEXT NOT NULL,
                price_factor REAL NOT NULL DEFAULT 1,
                price_margin_pct REAL NOT NULL DEFAULT 100,
                tax_rate REAL NOT NULL,
                subtotal REAL NOT NULL,
                tax_amount REAL NOT NULL,
                total REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                notes TEXT,
                closing_message TEXT NOT NULL DEFAULT 'Gracias por su atencion.',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER REFERENCES catalog_orders(id) ON DELETE SET NULL,
                quote_id INTEGER REFERENCES quotes(id) ON DELETE SET NULL,
                order_number TEXT,
                client_name TEXT NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                method TEXT NOT NULL DEFAULT 'Pago inmediato',
                reference TEXT,
                status TEXT NOT NULL DEFAULT 'PAID',
                paid_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 1,
                full_name TEXT NOT NULL DEFAULT '',
                email TEXT,
                google_subject TEXT,
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
                taxable INTEGER NOT NULL DEFAULT 1,
                discount_type TEXT NOT NULL,
                discount_value REAL NOT NULL,
                line_subtotal REAL NOT NULL,
                line_discount REAL NOT NULL,
                line_total REAL NOT NULL,
                sort_order INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS password_recovery_codes (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                code_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

        if not _has_column(conn, "quotes", "price_factor"):
            conn.execute("ALTER TABLE quotes ADD COLUMN price_factor REAL NOT NULL DEFAULT 1")
        if not _has_column(conn, "quotes", "price_margin_pct"):
            conn.execute("ALTER TABLE quotes ADD COLUMN price_margin_pct REAL NOT NULL DEFAULT 100")
        if not _has_column(conn, "quotes", "status"):
            conn.execute("ALTER TABLE quotes ADD COLUMN status TEXT NOT NULL DEFAULT 'PENDING'")
        if not _has_column(conn, "quote_items", "base_price_unit"):
            conn.execute("ALTER TABLE quote_items ADD COLUMN base_price_unit REAL NOT NULL DEFAULT 0")
        if not _has_column(conn, "quote_items", "taxable"):
            conn.execute("ALTER TABLE quote_items ADD COLUMN taxable INTEGER NOT NULL DEFAULT 1")
        if not _has_column(conn, "users", "full_name"):
            conn.execute("ALTER TABLE users ADD COLUMN full_name TEXT NOT NULL DEFAULT ''")
        if not _has_column(conn, "users", "email"):
            conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
        if not _has_column(conn, "users", "google_subject"):
            conn.execute("ALTER TABLE users ADD COLUMN google_subject TEXT")
        if not _has_column(conn, "catalog_items", "image_filename"):
            conn.execute("ALTER TABLE catalog_items ADD COLUMN image_filename TEXT")
        if not _has_column(conn, "catalog_items", "image_mime"):
            conn.execute("ALTER TABLE catalog_items ADD COLUMN image_mime TEXT")
        if not _has_column(conn, "catalog_items", "video_url"):
            conn.execute("ALTER TABLE catalog_items ADD COLUMN video_url TEXT")
        if not _has_column(conn, "catalog_items", "category"):
            conn.execute(
                "ALTER TABLE catalog_items ADD COLUMN category TEXT NOT NULL DEFAULT 'TECHNOLOGY'"
            )
        if not _has_column(conn, "catalog_items", "taxable"):
            conn.execute("ALTER TABLE catalog_items ADD COLUMN taxable INTEGER NOT NULL DEFAULT 1")
        if not _has_column(conn, "catalog_items", "available_qty"):
            conn.execute("ALTER TABLE catalog_items ADD COLUMN available_qty REAL NOT NULL DEFAULT 0")
        if not _has_column(conn, "clients", "client_type"):
            conn.execute("ALTER TABLE clients ADD COLUMN client_type TEXT NOT NULL DEFAULT 'BUSINESS'")
        if not _has_column(conn, "clients", "document_type"):
            conn.execute("ALTER TABLE clients ADD COLUMN document_type TEXT")
        if not _has_column(conn, "clients", "document_number"):
            conn.execute("ALTER TABLE clients ADD COLUMN document_number TEXT")
        if not _has_column(conn, "quotes", "client_type"):
            conn.execute("ALTER TABLE quotes ADD COLUMN client_type TEXT NOT NULL DEFAULT 'BUSINESS'")
        if not _has_column(conn, "quotes", "client_document_type"):
            conn.execute("ALTER TABLE quotes ADD COLUMN client_document_type TEXT")
        if not _has_column(conn, "quotes", "client_document_number"):
            conn.execute("ALTER TABLE quotes ADD COLUMN client_document_number TEXT")
        if not _has_column(conn, "quotes", "client_phone"):
            conn.execute("ALTER TABLE quotes ADD COLUMN client_phone TEXT")
        if not _has_column(conn, "quotes", "client_address"):
            conn.execute("ALTER TABLE quotes ADD COLUMN client_address TEXT")
        if not _has_column(conn, "settings", "legal_name"):
            conn.execute("ALTER TABLE settings ADD COLUMN legal_name TEXT NOT NULL DEFAULT ''")
        if not _has_column(conn, "settings", "brand_slogan"):
            conn.execute(
                "ALTER TABLE settings ADD COLUMN brand_slogan TEXT NOT NULL DEFAULT 'Conectamos ideas con tecnologia'"
            )
        if not _has_column(conn, "settings", "company_nit"):
            conn.execute("ALTER TABLE settings ADD COLUMN company_nit TEXT NOT NULL DEFAULT ''")
        if not _has_column(conn, "settings", "company_email"):
            conn.execute("ALTER TABLE settings ADD COLUMN company_email TEXT NOT NULL DEFAULT ''")
        if not _has_column(conn, "settings", "company_phone"):
            conn.execute("ALTER TABLE settings ADD COLUMN company_phone TEXT NOT NULL DEFAULT ''")
        if not _has_column(conn, "settings", "company_whatsapp"):
            conn.execute("ALTER TABLE settings ADD COLUMN company_whatsapp TEXT NOT NULL DEFAULT ''")
        if not _has_column(conn, "settings", "company_address"):
            conn.execute("ALTER TABLE settings ADD COLUMN company_address TEXT NOT NULL DEFAULT ''")
        if not _has_column(conn, "settings", "google_oauth_client_id"):
            conn.execute("ALTER TABLE settings ADD COLUMN google_oauth_client_id TEXT NOT NULL DEFAULT ''")
        if not _has_column(conn, "settings", "google_oauth_client_secret"):
            conn.execute("ALTER TABLE settings ADD COLUMN google_oauth_client_secret TEXT NOT NULL DEFAULT ''")
        if not _has_column(conn, "settings", "google_oauth_redirect_uri"):
            conn.execute("ALTER TABLE settings ADD COLUMN google_oauth_redirect_uri TEXT NOT NULL DEFAULT ''")
        if not _has_column(conn, "settings", "google_oauth_prompt"):
            conn.execute(
                "ALTER TABLE settings ADD COLUMN google_oauth_prompt TEXT NOT NULL DEFAULT 'select_account'"
            )
        if not _has_column(conn, "quotes", "closing_message"):
            conn.execute(
                "ALTER TABLE quotes ADD COLUMN closing_message TEXT NOT NULL DEFAULT 'Gracias por su atencion.'"
            )
        if not _has_column(conn, "catalog_orders", "quote_id"):
            conn.execute("ALTER TABLE catalog_orders ADD COLUMN quote_id INTEGER REFERENCES quotes(id) ON DELETE SET NULL")
        if not _has_column(conn, "catalog_orders", "credit_id"):
            conn.execute("ALTER TABLE catalog_orders ADD COLUMN credit_id INTEGER REFERENCES client_credits(id) ON DELETE SET NULL")
        if not _has_column(conn, "catalog_orders", "payment_status"):
            conn.execute("ALTER TABLE catalog_orders ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'PENDING'")
        if not _has_column(conn, "catalog_orders", "payment_method"):
            conn.execute("ALTER TABLE catalog_orders ADD COLUMN payment_method TEXT")
        if not _has_column(conn, "catalog_orders", "tax_amount"):
            conn.execute("ALTER TABLE catalog_orders ADD COLUMN tax_amount REAL NOT NULL DEFAULT 0")
        if not _has_column(conn, "catalog_orders", "paid_at"):
            conn.execute("ALTER TABLE catalog_orders ADD COLUMN paid_at TEXT")
        if not _has_column(conn, "client_credits", "order_id"):
            conn.execute("ALTER TABLE client_credits ADD COLUMN order_id INTEGER REFERENCES catalog_orders(id) ON DELETE SET NULL")
        if not _has_column(conn, "client_credits", "quote_id"):
            conn.execute("ALTER TABLE client_credits ADD COLUMN quote_id INTEGER REFERENCES quotes(id) ON DELETE SET NULL")
        if not _has_column(conn, "client_credits", "order_number"):
            conn.execute("ALTER TABLE client_credits ADD COLUMN order_number TEXT")

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
        conn.execute(
            "UPDATE catalog_items SET category = ? WHERE category IS NULL OR TRIM(category) = ''",
            (DEFAULT_CATALOG_CATEGORY,),
        )
        conn.execute("UPDATE catalog_items SET taxable = 0 WHERE COALESCE(tax_rate, 0) <= 0")
        conn.execute("UPDATE users SET full_name = '' WHERE full_name IS NULL")
        conn.execute("UPDATE users SET email = LOWER(TRIM(email)) WHERE email IS NOT NULL")
        conn.execute("UPDATE clients SET client_type = 'BUSINESS' WHERE client_type IS NULL OR TRIM(client_type) = ''")
        conn.execute("UPDATE quotes SET client_type = 'BUSINESS' WHERE client_type IS NULL OR TRIM(client_type) = ''")
        conn.execute("UPDATE quotes SET status = 'PENDING' WHERE status IS NULL OR TRIM(status) = ''")
        conn.execute("UPDATE catalog_orders SET payment_status = 'PENDING' WHERE payment_status IS NULL OR TRIM(payment_status) = ''")
        conn.execute(
            "UPDATE quotes SET closing_message = ? WHERE closing_message IS NULL",
            (DEFAULT_CLOSING_MESSAGE,),
        )
        conn.execute(
            """
            INSERT INTO catalog_item_images (item_id, filename, mime, sort_order, created_at)
            SELECT
                catalog_items.id,
                catalog_items.image_filename,
                COALESCE(catalog_items.image_mime, 'image/png'),
                COALESCE(
                    (
                        SELECT MAX(existing.sort_order) + 1
                        FROM catalog_item_images AS existing
                        WHERE existing.item_id = catalog_items.id
                    ),
                    1
                ),
                ?
            FROM catalog_items
            WHERE catalog_items.image_filename IS NOT NULL
              AND TRIM(catalog_items.image_filename) <> ''
              AND NOT EXISTS (
                  SELECT 1
                  FROM catalog_item_images
                  WHERE catalog_item_images.item_id = catalog_items.id
                    AND catalog_item_images.filename = catalog_items.image_filename
              )
            """,
            (utcnow_iso(),),
        )

        current = conn.execute("SELECT id FROM settings WHERE id = 1").fetchone()
        if not current:
            conn.execute(
                """
                INSERT INTO settings (
                    id, org_name, brand_slogan, legal_name, company_nit, company_email, company_phone, company_whatsapp, company_address,
                    google_oauth_client_id, google_oauth_client_secret, google_oauth_redirect_uri, google_oauth_prompt,
                    quote_prefix, next_quote_number, currency_code,
                    iva_rate, rounding_mode, logo_filename, logo_mime, updated_at
                ) VALUES (1, :org_name, :brand_slogan, :legal_name, :company_nit, :company_email, :company_phone, :company_whatsapp, :company_address,
                          :google_oauth_client_id, :google_oauth_client_secret, :google_oauth_redirect_uri, :google_oauth_prompt,
                          :quote_prefix, :next_quote_number, :currency_code,
                          :iva_rate, :rounding_mode, :logo_filename, :logo_mime, :updated_at)
                """,
                {**DEFAULT_SETTINGS, "updated_at": utcnow_iso()},
            )

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_google_subject ON users(google_subject)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_catalog_item_images_item_id ON catalog_item_images(item_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_catalog_orders_status ON catalog_orders(status, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_catalog_order_items_order_id ON catalog_order_items(order_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_client_credits_client_id ON client_credits(client_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_client_credits_order_id ON client_credits(order_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_payments_order_id ON payments(order_id)"
        )
        conn.commit()


def fetch_settings() -> dict[str, Any]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    return {**DEFAULT_SETTINGS, **dict(row)} if row else {**DEFAULT_SETTINGS}


def has_users() -> bool:
    with get_connection() as conn:
        row = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
    return row is not None


def _normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def _ensure_unique_user_fields(
    conn: sqlite3.Connection,
    *,
    username: str,
    email: str = "",
    google_subject: str = "",
    exclude_user_id: int | None = None,
) -> None:
    row = conn.execute(
        "SELECT id FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    if row and int(row["id"]) != int(exclude_user_id or 0):
        raise ValueError("El nombre de usuario ya existe.")

    normalized_email = _normalize_email(email)
    if normalized_email:
        row = conn.execute(
            "SELECT id FROM users WHERE LOWER(COALESCE(email, '')) = ?",
            (normalized_email,),
        ).fetchone()
        if row and int(row["id"]) != int(exclude_user_id or 0):
            raise ValueError("El correo electronico ya esta asignado a otro usuario.")

    normalized_google_subject = (google_subject or "").strip()
    if normalized_google_subject:
        row = conn.execute(
            "SELECT id FROM users WHERE google_subject = ?",
            (normalized_google_subject,),
        ).fetchone()
        if row and int(row["id"]) != int(exclude_user_id or 0):
            raise ValueError("La cuenta de Google ya esta vinculada a otro usuario.")


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


def get_user_by_email(email: str) -> dict[str, Any] | None:
    normalized_email = _normalize_email(email)
    if not normalized_email:
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE LOWER(COALESCE(email, '')) = ?",
            (normalized_email,),
        ).fetchone()
    return dict(row) if row else None


def get_user_by_google_subject(google_subject: str) -> dict[str, Any] | None:
    subject = (google_subject or "").strip()
    if not subject:
        return None
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE google_subject = ?", (subject,)).fetchone()
    return dict(row) if row else None


def find_user_for_login(identity: str) -> dict[str, Any] | None:
    candidate = (identity or "").strip().lower()
    if not candidate:
        return None
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM users
            WHERE username = ?
               OR LOWER(COALESCE(email, '')) = ?
            LIMIT 1
            """,
            (candidate, candidate),
        ).fetchone()
    return dict(row) if row else None


def create_user(
    username: str,
    password_hash: str,
    *,
    is_admin: bool = True,
    full_name: str = "",
    email: str = "",
    google_subject: str = "",
) -> int:
    now = utcnow_iso()
    cleaned_email = _normalize_email(email)
    with get_connection() as conn:
        _ensure_unique_user_fields(
            conn,
            username=username,
            email=cleaned_email,
            google_subject=google_subject,
        )
        cursor = conn.execute(
            """
            INSERT INTO users (
                username, password_hash, is_admin, full_name, email, google_subject, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                password_hash,
                1 if is_admin else 0,
                (full_name or "").strip(),
                cleaned_email or None,
                (google_subject or "").strip() or None,
                now,
                now,
            ),
        )
        conn.commit()
    return int(cursor.lastrowid)


def list_users() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY is_admin DESC, COALESCE(NULLIF(full_name, ''), username) ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def delete_user(user_id: int) -> None:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    if cursor.rowcount == 0:
        raise ValueError("Usuario no encontrado.")


def update_user_password(user_id: int, password_hash: str) -> None:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE users
            SET password_hash = ?, updated_at = ?
            WHERE id = ?
            """,
            (password_hash, utcnow_iso(), user_id),
        )
        conn.commit()
    if cursor.rowcount == 0:
        raise ValueError("Usuario no encontrado.")


def update_user_profile(
    user_id: int,
    *,
    username: str,
    full_name: str,
    email: str,
    is_admin: bool,
) -> None:
    cleaned_email = _normalize_email(email)
    with get_connection() as conn:
        _ensure_unique_user_fields(
            conn,
            username=username,
            email=cleaned_email,
            exclude_user_id=user_id,
        )
        cursor = conn.execute(
            """
            UPDATE users
            SET username = ?,
                full_name = ?,
                email = ?,
                is_admin = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                username,
                (full_name or "").strip(),
                cleaned_email or None,
                1 if is_admin else 0,
                utcnow_iso(),
                user_id,
            ),
        )
        conn.commit()
    if cursor.rowcount == 0:
        raise ValueError("Usuario no encontrado.")


def bind_google_identity(user_id: int, *, google_subject: str, email: str, full_name: str = "") -> None:
    cleaned_email = _normalize_email(email)
    with get_connection() as conn:
        existing = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not existing:
            raise ValueError("Usuario no encontrado.")
        existing_data = dict(existing)
        _ensure_unique_user_fields(
            conn,
            username=existing_data["username"],
            email=cleaned_email or existing_data.get("email") or "",
            google_subject=google_subject,
            exclude_user_id=user_id,
        )
        conn.execute(
            """
            UPDATE users
            SET email = COALESCE(?, email),
                full_name = CASE
                    WHEN COALESCE(full_name, '') = '' AND ? <> '' THEN ?
                    ELSE full_name
                END,
                google_subject = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                cleaned_email or None,
                (full_name or "").strip(),
                (full_name or "").strip(),
                (google_subject or "").strip(),
                utcnow_iso(),
                user_id,
            ),
        )
        conn.commit()


def store_password_recovery_code(user_id: int, code_hash: str, expires_at: str) -> None:
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute("DELETE FROM password_recovery_codes WHERE user_id = ?", (user_id,))
        conn.execute(
            """
            INSERT INTO password_recovery_codes (user_id, code_hash, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, code_hash, expires_at, now),
        )
        conn.commit()


def get_password_recovery_code(user_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM password_recovery_codes WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def clear_password_recovery_code(user_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM password_recovery_codes WHERE user_id = ?", (user_id,))
        conn.commit()


def prune_expired_password_recovery_codes() -> None:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM password_recovery_codes WHERE expires_at <= ?",
            (utcnow_iso(),),
        )
        conn.commit()


def update_settings(payload: dict[str, Any]) -> None:
    values = {**fetch_settings(), **payload, "updated_at": utcnow_iso()}
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE settings
            SET org_name = :org_name,
                brand_slogan = :brand_slogan,
                legal_name = :legal_name,
                company_nit = :company_nit,
                company_email = :company_email,
                company_phone = :company_phone,
                company_whatsapp = :company_whatsapp,
                company_address = :company_address,
                google_oauth_client_id = :google_oauth_client_id,
                google_oauth_client_secret = :google_oauth_client_secret,
                google_oauth_redirect_uri = :google_oauth_redirect_uri,
                google_oauth_prompt = :google_oauth_prompt,
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

    if current_platform_slug() != PRIMARY_PLATFORM_SLUG:
        registry = _read_platform_registry()
        changed = False
        for entry in registry:
            if entry["slug"] != current_platform_slug():
                continue
            entry["name"] = values.get("org_name") or entry.get("name") or current_platform_slug().title()
            entry["brand_slogan"] = values.get("brand_slogan") or entry.get("brand_slogan") or ""
            changed = True
            break
        if changed:
            _write_platform_registry(registry)


def create_platform_workspace(
    *,
    platform_name: str,
    brand_slogan: str,
    admin_username: str,
    admin_password_hash: str,
    admin_full_name: str,
    admin_email: str = "",
) -> dict[str, Any]:
    slug = normalize_platform_slug(platform_name)
    if slug == PRIMARY_PLATFORM_SLUG:
        raise ValueError("La plataforma principal ya existe. Usa otro nombre para la nueva empresa.")
    if platform_exists(slug):
        raise ValueError("Ya existe una plataforma con ese nombre. Usa un nombre diferente.")

    registry = _read_platform_registry()
    registry.append(
        {
            "slug": slug,
            "name": (platform_name or slug).strip(),
            "brand_slogan": (brand_slogan or "").strip(),
            "created_at": utcnow_iso(),
            "is_primary": False,
        }
    )
    _write_platform_registry(registry)

    try:
        with use_platform(slug):
            init_db()
            update_settings(
                {
                    "org_name": (platform_name or slug).strip(),
                    "brand_slogan": (brand_slogan or DEFAULT_SETTINGS["brand_slogan"]).strip(),
                }
            )
            create_user(
                admin_username,
                admin_password_hash,
                is_admin=True,
                full_name=admin_full_name,
                email=admin_email,
            )
            settings = fetch_settings()
    except Exception:
        registry = [entry for entry in _read_platform_registry() if entry["slug"] != slug]
        _write_platform_registry(registry)
        platform_dir = PLATFORMS_DIR / slug
        if platform_dir.exists():
            for child in sorted(platform_dir.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink(missing_ok=True)
                else:
                    child.rmdir()
            platform_dir.rmdir()
        raise

    return {
        "slug": slug,
        "name": settings.get("org_name") or platform_name,
        "brand_slogan": settings.get("brand_slogan") or brand_slogan,
    }


def list_catalog_items(active_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM catalog_items"
    params: tuple[Any, ...] = ()
    if active_only:
        sql += " WHERE active = ?"
        params = (1,)
    sql += " ORDER BY active DESC, category, item_type, sku"
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def get_catalog_item(item_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM catalog_items WHERE id = ?", (item_id,)).fetchone()
    return dict(row) if row else None


def list_catalog_item_images(item_id: int) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM catalog_item_images
            WHERE item_id = ?
            ORDER BY sort_order, id
            """,
            (item_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def add_catalog_item_image(item_id: int, filename: str, mime: str = "image/png") -> int:
    now = utcnow_iso()
    with get_connection() as conn:
        current = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) AS max_order FROM catalog_item_images WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        sort_order = int(current["max_order"] or 0) + 1
        cursor = conn.execute(
            """
            INSERT INTO catalog_item_images (item_id, filename, mime, sort_order, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (item_id, filename, mime, sort_order, now),
        )
        conn.commit()
    return int(cursor.lastrowid)


def delete_catalog_item_images(image_ids: list[int]) -> list[str]:
    if not image_ids:
        return []
    placeholders = ",".join("?" for _ in image_ids)
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT id, filename FROM catalog_item_images WHERE id IN ({placeholders})",
            tuple(image_ids),
        ).fetchall()
        filenames = [row["filename"] for row in rows]
        conn.execute(
            f"DELETE FROM catalog_item_images WHERE id IN ({placeholders})",
            tuple(image_ids),
        )
        conn.commit()
    return filenames


def save_catalog_item(payload: dict[str, Any]) -> int:
    now = utcnow_iso()
    values = {
        "item_type": payload["item_type"],
        "category": normalize_catalog_category(payload.get("category")),
        "sku": payload["sku"],
        "description": payload["description"],
        "unit": payload["unit"],
        "cost_amount": payload["cost_amount"],
        "pricing_mode": payload["pricing_mode"],
        "margin_pct": payload["margin_pct"],
        "markup_pct": payload["markup_pct"],
        "manual_price": payload["manual_price"],
        "tax_rate": payload["tax_rate"],
        "taxable": payload["taxable"],
        "available_qty": payload.get("available_qty", 0),
        "active": payload["active"],
        "image_filename": payload.get("image_filename"),
        "image_mime": payload.get("image_mime"),
        "video_url": payload.get("video_url") or "",
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
                    category = :category,
                    sku = :sku,
                    description = :description,
                    unit = :unit,
                    cost_amount = :cost_amount,
                    pricing_mode = :pricing_mode,
                    margin_pct = :margin_pct,
                    markup_pct = :markup_pct,
                    manual_price = :manual_price,
                    tax_rate = :tax_rate,
                    taxable = :taxable,
                    available_qty = :available_qty,
                    active = :active,
                    image_filename = :image_filename,
                    image_mime = :image_mime,
                    video_url = :video_url,
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
                    item_type, category, sku, description, unit, cost_amount, pricing_mode,
                    margin_pct, markup_pct, manual_price, tax_rate, taxable, available_qty, active, image_filename, image_mime, video_url,
                    notes_internal, notes_quote, created_at, updated_at
                ) VALUES (
                    :item_type, :category, :sku, :description, :unit, :cost_amount, :pricing_mode,
                    :margin_pct, :markup_pct, :manual_price, :tax_rate, :taxable, :available_qty, :active, :image_filename, :image_mime, :video_url,
                    :notes_internal, :notes_quote, :created_at, :updated_at
                )
                """,
                values,
            )
            item_id = int(cursor.lastrowid)
        conn.commit()
    return item_id


def delete_catalog_item(item_id: int) -> list[str]:
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        item_row = conn.execute(
            "SELECT id, image_filename FROM catalog_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if not item_row:
            raise ValueError("Producto no encontrado.")

        image_rows = conn.execute(
            "SELECT filename FROM catalog_item_images WHERE item_id = ?",
            (item_id,),
        ).fetchall()
        filenames = {
            row["filename"]
            for row in image_rows
            if row["filename"]
        }
        if item_row["image_filename"]:
            filenames.add(item_row["image_filename"])

        conn.execute(
            "UPDATE quote_items SET source_item_id = NULL WHERE source_item_id = ?",
            (item_id,),
        )
        conn.execute(
            "UPDATE catalog_order_items SET catalog_item_id = NULL WHERE catalog_item_id = ?",
            (item_id,),
        )
        cursor = conn.execute("DELETE FROM catalog_items WHERE id = ?", (item_id,))
        conn.commit()

    if cursor.rowcount == 0:
        raise ValueError("Producto no encontrado.")
    return sorted(filenames)


def list_clients() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                clients.*,
                COALESCE(credit_summary.open_credit_count, 0) AS open_credit_count,
                COALESCE(credit_summary.open_credit_balance, 0) AS open_credit_balance
            FROM clients
            LEFT JOIN (
                SELECT
                    client_id,
                    COUNT(*) AS open_credit_count,
                    ROUND(
                        SUM(
                            CASE
                                WHEN (amount - paid_amount) > 0.000001 THEN (amount - paid_amount)
                                ELSE 0
                            END
                        ),
                        2
                    ) AS open_credit_balance
                FROM client_credits
                WHERE COALESCE(status, 'PENDING') <> 'PAID'
                  AND (amount - paid_amount) > 0.000001
                GROUP BY client_id
            ) AS credit_summary ON credit_summary.client_id = clients.id
            ORDER BY clients.name
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_client(client_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    return dict(row) if row else None


def save_client(payload: dict[str, Any]) -> int:
    now = utcnow_iso()
    values = {
        "client_type": payload.get("client_type") or "BUSINESS",
        "name": payload["name"],
        "document_type": payload.get("document_type") or "",
        "document_number": payload.get("document_number") or "",
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
                SET client_type = :client_type,
                    name = :name,
                    document_type = :document_type,
                    document_number = :document_number,
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
                INSERT INTO clients (
                    client_type, name, document_type, document_number, email, phone, address, created_at, updated_at
                )
                VALUES (
                    :client_type, :name, :document_type, :document_number, :email, :phone, :address, :created_at, :updated_at
                )
                """,
                values,
            )
            client_id = int(cursor.lastrowid)
        conn.commit()
    return client_id


def delete_client(client_id: int) -> None:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
        conn.commit()
    if cursor.rowcount == 0:
        raise ValueError("Cliente no encontrado.")


def create_catalog_order(payload: dict[str, Any], items: list[dict[str, Any]]) -> int:
    now = utcnow_iso()
    temp_number = f"PED-TMP-{secrets.token_hex(6).upper()}"
    values = {
        "order_number": temp_number,
        "quote_id": payload.get("quote_id"),
        "credit_id": payload.get("credit_id"),
        "customer_name": (payload.get("customer_name") or "").strip(),
        "customer_phone": (payload.get("customer_phone") or "").strip(),
        "customer_address": (payload.get("customer_address") or "").strip(),
        "status": payload.get("status") or "NEW",
        "payment_status": payload.get("payment_status") or "PENDING",
        "payment_method": (payload.get("payment_method") or "").strip(),
        "tax_amount": payload.get("tax_amount") or 0,
        "subtotal": payload.get("subtotal") or 0,
        "total": payload.get("total") or 0,
        "paid_at": payload.get("paid_at") or "",
        "created_at": now,
        "updated_at": now,
    }
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            INSERT INTO catalog_orders (
                order_number, quote_id, credit_id, customer_name, customer_phone, customer_address,
                status, payment_status, payment_method, tax_amount, subtotal, total, paid_at, created_at, updated_at
            ) VALUES (
                :order_number, :quote_id, :credit_id, :customer_name, :customer_phone, :customer_address,
                :status, :payment_status, :payment_method, :tax_amount, :subtotal, :total, :paid_at, :created_at, :updated_at
            )
            """,
            values,
        )
        order_id = int(cursor.lastrowid)
        order_number = f"PED-{order_id:06d}"
        conn.execute(
            "UPDATE catalog_orders SET order_number = ? WHERE id = ?",
            (order_number, order_id),
        )

        for sort_order, item in enumerate(items, start=1):
            conn.execute(
                """
                INSERT INTO catalog_order_items (
                    order_id, catalog_item_id, sku, description, unit, qty,
                    price_unit, taxable, line_total, sort_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    item.get("catalog_item_id"),
                    item["sku"],
                    item["description"],
                    item["unit"],
                    item["qty"],
                    item["price_unit"],
                    item.get("taxable", 1),
                    item["line_total"],
                    sort_order,
                ),
            )
        conn.commit()
    return order_id


def list_catalog_orders(
    search: str | None = None,
    status: str | None = None,
    *,
    exclude_completed: bool = False,
) -> list[dict[str, Any]]:
    query = """
        SELECT
            catalog_orders.*,
            COUNT(catalog_order_items.id) AS item_count
        FROM catalog_orders
        LEFT JOIN catalog_order_items ON catalog_order_items.order_id = catalog_orders.id
    """
    where: list[str] = []
    params: list[Any] = []
    normalized_search = (search or "").strip()
    normalized_status = (status or "").strip().upper()

    if normalized_search:
        like_term = f"%{normalized_search}%"
        where.append(
            """
            (
                catalog_orders.order_number LIKE ?
                OR catalog_orders.customer_name LIKE ?
                OR catalog_orders.customer_phone LIKE ?
                OR catalog_orders.customer_address LIKE ?
            )
            """
        )
        params.extend([like_term, like_term, like_term, like_term])
    if normalized_status:
        where.append("catalog_orders.status = ?")
        params.append(normalized_status)
    if exclude_completed:
        where.append(
            """
            COALESCE(catalog_orders.status, 'NEW') NOT IN ('INVOICED', 'PAID', 'CREDIT')
            AND COALESCE(catalog_orders.payment_status, 'PENDING') NOT IN ('PAID', 'CREDIT')
            """
        )

    if where:
        query += " WHERE " + " AND ".join(where)
    query += " GROUP BY catalog_orders.id ORDER BY catalog_orders.id DESC"

    with get_connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return [dict(row) for row in rows]


def get_catalog_order(order_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        order_row = conn.execute("SELECT * FROM catalog_orders WHERE id = ?", (order_id,)).fetchone()
        if not order_row:
            return None
        item_rows = conn.execute(
            "SELECT * FROM catalog_order_items WHERE order_id = ? ORDER BY sort_order, id",
            (order_id,),
        ).fetchall()
    return {**dict(order_row), "items": [dict(row) for row in item_rows]}


def update_catalog_order_status(order_id: int, status: str) -> None:
    normalized_status = (status or "NEW").strip().upper()
    allowed = {"NEW", "CONTACTED", "QUOTED", "INVOICED", "PAID", "CREDIT", "CLOSED"}
    if normalized_status not in allowed:
        raise ValueError("Estado de pedido invalido.")
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE catalog_orders SET status = ?, updated_at = ? WHERE id = ?",
            (normalized_status, utcnow_iso(), order_id),
        )
        conn.commit()
    if cursor.rowcount == 0:
        raise ValueError("Pedido no encontrado.")


def link_catalog_order_quote(order_id: int, quote_id: int, status: str = "QUOTED") -> None:
    normalized_status = (status or "QUOTED").strip().upper()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE catalog_orders
            SET quote_id = ?,
                status = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (quote_id, normalized_status, utcnow_iso(), order_id),
        )
        conn.commit()
    if cursor.rowcount == 0:
        raise ValueError("Pedido no encontrado.")


def update_quote_status(quote_id: int, status: str) -> None:
    normalized_status = (status or "PENDING").strip().upper()
    allowed = {"PENDING", "APPROVED", "REJECTED", "INVOICED", "PAID", "CREDIT"}
    if normalized_status not in allowed:
        raise ValueError("Estado de cotizacion invalido.")
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE quotes SET status = ? WHERE id = ?",
            (normalized_status, quote_id),
        )
        conn.commit()
    if cursor.rowcount == 0:
        raise ValueError("Cotizacion no encontrada.")


def _validate_and_discount_order_inventory(conn: sqlite3.Connection, order_id: int) -> None:
    items = conn.execute(
        """
        SELECT catalog_item_id, sku, description, qty
        FROM catalog_order_items
        WHERE order_id = ?
          AND catalog_item_id IS NOT NULL
        """,
        (order_id,),
    ).fetchall()
    for item in items:
        catalog_row = conn.execute(
            "SELECT available_qty FROM catalog_items WHERE id = ?",
            (item["catalog_item_id"],),
        ).fetchone()
        if not catalog_row:
            continue
        available_qty = float(catalog_row["available_qty"] or 0)
        requested_qty = float(item["qty"] or 0)
        if requested_qty > available_qty:
            raise ValueError(
                f"Stock insuficiente para {item['sku']} - {item['description']}. Disponible: {available_qty:g}."
            )

    for item in items:
        conn.execute(
            """
            UPDATE catalog_items
            SET available_qty = available_qty - ?,
                updated_at = ?
            WHERE id = ?
            """,
            (float(item["qty"] or 0), utcnow_iso(), item["catalog_item_id"]),
        )


def _invoice_number_from_quote_number(quote_number: str | None) -> str:
    candidate = (quote_number or "").strip()
    if not candidate:
        return ""
    suffix = candidate.split("-", 1)[1] if "-" in candidate else candidate
    return f"FAC-{suffix or '000001'}"


def _validate_and_discount_quote_inventory(conn: sqlite3.Connection, quote_id: int) -> None:
    items = conn.execute(
        """
        SELECT source_item_id, sku, description, qty
        FROM quote_items
        WHERE quote_id = ?
          AND source_item_id IS NOT NULL
        """,
        (quote_id,),
    ).fetchall()
    for item in items:
        catalog_row = conn.execute(
            "SELECT available_qty FROM catalog_items WHERE id = ?",
            (item["source_item_id"],),
        ).fetchone()
        if not catalog_row:
            continue
        available_qty = float(catalog_row["available_qty"] or 0)
        requested_qty = float(item["qty"] or 0)
        if requested_qty > available_qty:
            raise ValueError(
                f"Stock insuficiente para {item['sku']} - {item['description']}. Disponible: {available_qty:g}."
            )

    for item in items:
        conn.execute(
            """
            UPDATE catalog_items
            SET available_qty = available_qty - ?,
                updated_at = ?
            WHERE id = ?
            """,
            (float(item["qty"] or 0), utcnow_iso(), item["source_item_id"]),
        )


def confirm_catalog_order_payment(
    order_id: int,
    *,
    method: str = "Pago inmediato",
    reference: str = "",
) -> int:
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        order = conn.execute("SELECT * FROM catalog_orders WHERE id = ?", (order_id,)).fetchone()
        if not order:
            raise ValueError("Pedido no encontrado.")
        if (order["payment_status"] or "").upper() in {"PAID", "CREDIT"}:
            raise ValueError("Este pedido ya fue confirmado y no puede descontar inventario dos veces.")

        _validate_and_discount_order_inventory(conn, order_id)
        cursor = conn.execute(
            """
            INSERT INTO payments (
                order_id, quote_id, order_number, client_name, amount, method, reference, status, paid_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PAID', ?, ?)
            """,
            (
                order_id,
                order["quote_id"],
                order["order_number"],
                order["customer_name"],
                order["total"],
                (method or "Pago inmediato").strip(),
                (reference or "").strip(),
                now,
                now,
            ),
        )
        payment_id = int(cursor.lastrowid)
        conn.execute(
            """
            UPDATE catalog_orders
            SET status = 'PAID',
                payment_status = 'PAID',
                payment_method = ?,
                paid_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            ((method or "Pago inmediato").strip(), now, now, order_id),
        )
        if order["quote_id"]:
            conn.execute("UPDATE quotes SET status = 'PAID' WHERE id = ?", (order["quote_id"],))
        conn.commit()
    return payment_id


def send_catalog_order_to_credit(
    order_id: int,
    *,
    client_id: int,
    due_date: str = "",
) -> int:
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        order = conn.execute("SELECT * FROM catalog_orders WHERE id = ?", (order_id,)).fetchone()
        if not order:
            raise ValueError("Pedido no encontrado.")
        if (order["payment_status"] or "").upper() in {"PAID", "CREDIT"}:
            raise ValueError("Este pedido ya fue confirmado y no puede descontar inventario dos veces.")

        client = conn.execute("SELECT id FROM clients WHERE id = ?", (client_id,)).fetchone()
        if not client:
            raise ValueError("Cliente no encontrado para enviar a cartera.")

        quote = None
        invoice_number = ""
        if order["quote_id"]:
            quote = conn.execute(
                "SELECT id, quote_number FROM quotes WHERE id = ?",
                (order["quote_id"],),
            ).fetchone()
            invoice_number = _invoice_number_from_quote_number(quote["quote_number"] if quote else "")

        _validate_and_discount_order_inventory(conn, order_id)
        cursor = conn.execute(
            """
            INSERT INTO client_credits (
                client_id, order_id, quote_id, order_number, description, amount, paid_amount, due_date,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, 'PENDING', ?, ?)
            """,
            (
                client_id,
                order_id,
                order["quote_id"],
                order["order_number"],
                (
                    f"Factura a credito {invoice_number}"
                    if invoice_number
                    else f"Credito generado desde pedido {order['order_number']}"
                ),
                order["total"],
                (due_date or "").strip(),
                now,
                now,
            ),
        )
        credit_id = int(cursor.lastrowid)
        conn.execute(
            """
            UPDATE catalog_orders
            SET status = 'CREDIT',
                payment_status = 'CREDIT',
                credit_id = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (credit_id, now, order_id),
        )
        if order["quote_id"]:
            conn.execute("UPDATE quotes SET status = 'CREDIT' WHERE id = ?", (order["quote_id"],))
        conn.commit()
    return credit_id


def confirm_quote_invoice_payment(
    quote_id: int,
    *,
    method: str = "Factura de contado",
    reference: str = "",
) -> int:
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        quote = conn.execute("SELECT * FROM quotes WHERE id = ?", (quote_id,)).fetchone()
        if not quote:
            raise ValueError("Cotizacion no encontrada.")
        if (quote["status"] or "").upper() in {"PAID", "CREDIT"}:
            raise ValueError("Esta factura ya fue confirmada y no puede descontar inventario dos veces.")

        invoice_number = _invoice_number_from_quote_number(quote["quote_number"])
        _validate_and_discount_quote_inventory(conn, quote_id)
        cursor = conn.execute(
            """
            INSERT INTO payments (
                order_id, quote_id, order_number, client_name, amount, method, reference, status, paid_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PAID', ?, ?)
            """,
            (
                None,
                quote_id,
                invoice_number,
                quote["client_name"],
                quote["total"],
                (method or "Factura de contado").strip(),
                (reference or invoice_number).strip(),
                now,
                now,
            ),
        )
        payment_id = int(cursor.lastrowid)
        conn.execute(
            "UPDATE quotes SET status = 'PAID' WHERE id = ?",
            (quote_id,),
        )
        conn.commit()
    return payment_id


def send_quote_to_credit(
    quote_id: int,
    *,
    client_id: int,
    due_date: str = "",
) -> int:
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        quote = conn.execute("SELECT * FROM quotes WHERE id = ?", (quote_id,)).fetchone()
        if not quote:
            raise ValueError("Cotizacion no encontrada.")
        if (quote["status"] or "").upper() in {"PAID", "CREDIT"}:
            raise ValueError("Esta factura ya fue confirmada y no puede descontar inventario dos veces.")

        client = conn.execute("SELECT id FROM clients WHERE id = ?", (client_id,)).fetchone()
        if not client:
            raise ValueError("Cliente no encontrado para enviar a cartera.")

        invoice_number = _invoice_number_from_quote_number(quote["quote_number"])
        _validate_and_discount_quote_inventory(conn, quote_id)
        cursor = conn.execute(
            """
            INSERT INTO client_credits (
                client_id, order_id, quote_id, order_number, description, amount, paid_amount, due_date,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, 'PENDING', ?, ?)
            """,
            (
                client_id,
                None,
                quote_id,
                invoice_number,
                f"Factura a credito {invoice_number}" if invoice_number else "Factura a credito",
                quote["total"],
                (due_date or "").strip(),
                now,
                now,
            ),
        )
        credit_id = int(cursor.lastrowid)
        conn.execute("UPDATE quotes SET status = 'CREDIT' WHERE id = ?", (quote_id,))
        conn.commit()
    return credit_id


def list_client_credits(
    search: str | None = None,
    *,
    client_id: int | None = None,
    include_paid: bool = False,
) -> list[dict[str, Any]]:
    query = """
        SELECT
            client_credits.*,
            clients.name AS client_name,
            clients.phone AS client_phone,
            clients.address AS client_address,
            quotes.quote_number AS quote_number,
            quotes.quote_date AS quote_date
        FROM client_credits
        JOIN clients ON clients.id = client_credits.client_id
        LEFT JOIN quotes ON quotes.id = client_credits.quote_id
    """
    where: list[str] = []
    params: list[Any] = []
    normalized_search = (search or "").strip()
    if client_id:
        where.append("client_credits.client_id = ?")
        params.append(int(client_id))
    if not include_paid:
        where.append(
            """
            COALESCE(client_credits.status, 'PENDING') <> 'PAID'
            AND (client_credits.amount - client_credits.paid_amount) > 0.000001
            """
        )
    if normalized_search:
        like_term = f"%{normalized_search}%"
        where.append(
            """
            (
                clients.name LIKE ?
                OR clients.phone LIKE ?
                OR clients.address LIKE ?
                OR client_credits.description LIKE ?
                OR client_credits.order_number LIKE ?
                OR quotes.quote_number LIKE ?
                OR REPLACE(quotes.quote_number, 'COT-', 'FAC-') LIKE ?
                OR client_credits.status LIKE ?
            )
            """
        )
        params.extend([like_term, like_term, like_term, like_term, like_term, like_term, like_term, like_term])
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY client_credits.id DESC"

    with get_connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    credits = []
    for row in rows:
        credit = dict(row)
        credit["balance"] = float(credit.get("amount") or 0) - float(credit.get("paid_amount") or 0)
        credit["invoice_number"] = _invoice_number_from_quote_number(credit.get("quote_number"))
        credits.append(credit)
    return credits


def get_client_credit(credit_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                client_credits.*,
                clients.name AS client_name,
                clients.phone AS client_phone,
                quotes.quote_number AS quote_number,
                quotes.quote_date AS quote_date
            FROM client_credits
            JOIN clients ON clients.id = client_credits.client_id
            LEFT JOIN quotes ON quotes.id = client_credits.quote_id
            WHERE client_credits.id = ?
            """,
            (credit_id,),
        ).fetchone()
    if not row:
        return None
    credit = dict(row)
    credit["balance"] = float(credit.get("amount") or 0) - float(credit.get("paid_amount") or 0)
    credit["invoice_number"] = _invoice_number_from_quote_number(credit.get("quote_number"))
    return credit


def save_client_credit(payload: dict[str, Any]) -> int:
    now = utcnow_iso()
    values = {
        "client_id": int(payload["client_id"]),
        "order_id": int(payload["order_id"]) if payload.get("order_id") else None,
        "quote_id": int(payload["quote_id"]) if payload.get("quote_id") else None,
        "order_number": (payload.get("order_number") or "").strip(),
        "description": (payload.get("description") or "").strip(),
        "amount": float(payload.get("amount") or 0),
        "paid_amount": float(payload.get("paid_amount") or 0),
        "due_date": (payload.get("due_date") or "").strip(),
        "status": (payload.get("status") or "PENDING").strip().upper(),
        "updated_at": now,
    }
    with get_connection() as conn:
        if payload.get("id"):
            values["id"] = int(payload["id"])
            cursor = conn.execute(
                """
                UPDATE client_credits
                SET client_id = :client_id,
                    order_id = :order_id,
                    quote_id = :quote_id,
                    order_number = :order_number,
                    description = :description,
                    amount = :amount,
                    paid_amount = :paid_amount,
                    due_date = :due_date,
                    status = :status,
                    updated_at = :updated_at
                WHERE id = :id
                """,
                values,
            )
            credit_id = int(payload["id"])
            if cursor.rowcount == 0:
                raise ValueError("Credito no encontrado.")
        else:
            values["created_at"] = now
            cursor = conn.execute(
                """
                INSERT INTO client_credits (
                    client_id, order_id, quote_id, order_number, description, amount, paid_amount, due_date, status, created_at, updated_at
                ) VALUES (
                    :client_id, :order_id, :quote_id, :order_number, :description, :amount, :paid_amount, :due_date, :status, :created_at, :updated_at
                )
                """,
                values,
            )
            credit_id = int(cursor.lastrowid)
        conn.commit()
    return credit_id


def apply_client_credit_payment(
    credit_id: int,
    payment_amount: float | int | None = None,
    *,
    settle_full: bool = False,
) -> dict[str, Any]:
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        credit_row = conn.execute(
            "SELECT * FROM client_credits WHERE id = ?",
            (credit_id,),
        ).fetchone()
        if not credit_row:
            raise ValueError("Credito no encontrado.")

        credit = dict(credit_row)
        amount = float(credit.get("amount") or 0)
        paid_amount = float(credit.get("paid_amount") or 0)
        balance = max(amount - paid_amount, 0)
        if balance <= 0:
            raise ValueError("Esta factura ya se encuentra pagada.")

        if settle_full:
            applied_amount = balance
        else:
            applied_amount = float(payment_amount or 0)
            if applied_amount <= 0:
                raise ValueError("El abono debe ser mayor a cero.")
            if applied_amount > balance:
                applied_amount = balance

        new_paid_amount = round(paid_amount + applied_amount, 2)
        new_balance = max(amount - new_paid_amount, 0)
        new_status = "PAID" if new_balance <= 0.000001 else "PARTIAL"

        conn.execute(
            """
            UPDATE client_credits
            SET paid_amount = ?,
                status = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (new_paid_amount, new_status, now, credit_id),
        )

        quote_number = ""
        if credit.get("quote_id"):
            quote_row = conn.execute(
                "SELECT quote_number FROM quotes WHERE id = ?",
                (credit["quote_id"],),
            ).fetchone()
            quote_number = (quote_row["quote_number"] if quote_row else "") or ""
            conn.execute(
                "UPDATE quotes SET status = ? WHERE id = ?",
                ("PAID" if new_status == "PAID" else "CREDIT", credit["quote_id"]),
            )

        if credit.get("order_id"):
            if new_status == "PAID":
                conn.execute(
                    """
                    UPDATE catalog_orders
                    SET status = 'PAID',
                        payment_status = 'PAID',
                        paid_at = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (now, now, credit["order_id"]),
                )
            else:
                conn.execute(
                    """
                    UPDATE catalog_orders
                    SET status = 'CREDIT',
                        payment_status = 'CREDIT',
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (now, credit["order_id"]),
                )

        payment_reference = _invoice_number_from_quote_number(quote_number) or credit.get("order_number") or f"CRED-{credit_id:06d}"
        payment_method = "Pago total desde cartera" if new_status == "PAID" and abs(applied_amount - balance) < 0.000001 else "Abono desde cartera"

        conn.execute(
            """
            INSERT INTO payments (
                order_id, quote_id, order_number, client_name, amount, method, reference, status, paid_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PAID', ?, ?)
            """,
            (
                credit.get("order_id"),
                credit.get("quote_id"),
                credit.get("order_number") or "",
                conn.execute("SELECT name FROM clients WHERE id = ?", (credit["client_id"],)).fetchone()["name"],
                applied_amount,
                payment_method,
                payment_reference,
                now,
                now,
            ),
        )

        conn.commit()

    updated_credit = get_client_credit(credit_id)
    if not updated_credit:
        raise ValueError("No fue posible actualizar el credito.")
    updated_credit["applied_amount"] = applied_amount
    return updated_credit


def delete_client_credit(credit_id: int) -> None:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM client_credits WHERE id = ?", (credit_id,))
        conn.commit()
    if cursor.rowcount == 0:
        raise ValueError("Credito no encontrado.")


def list_quotes(
    limit: int | None = 20,
    search: str | None = None,
    statuses: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    query = """
        SELECT *
        FROM quotes
    """
    params: list[Any] = []
    normalized_search = (search or "").strip()

    where: list[str] = []

    if normalized_search:
        like_term = f"%{normalized_search}%"
        where.append(
            """
            (
                quote_number LIKE ?
                OR title LIKE ?
                OR location LIKE ?
                OR client_name LIKE ?
                OR requested_by LIKE ?
            )
            """
        )
        params.extend([like_term, like_term, like_term, like_term, like_term])
    normalized_statuses = [
        str(status).strip().upper()
        for status in (statuses or [])
        if str(status or "").strip()
    ]
    if normalized_statuses:
        placeholders = ", ".join("?" for _ in normalized_statuses)
        where.append(f"status IN ({placeholders})")
        params.extend(normalized_statuses)

    if where:
        query += " WHERE " + " AND ".join(where)

    query += " ORDER BY id DESC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
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
                quote_number, title, location, client_type, client_name, client_document_type, client_document_number,
                client_email, client_phone, client_address, requested_by, quote_date, currency_code,
                price_factor, price_margin_pct, tax_rate, subtotal, tax_amount, total, status, notes, closing_message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                quote_number,
                payload["title"],
                payload["location"],
                payload.get("client_type") or "BUSINESS",
                payload["client_name"],
                payload.get("client_document_type") or "",
                payload.get("client_document_number") or "",
                payload.get("client_email") or "",
                payload.get("client_phone") or "",
                payload.get("client_address") or "",
                payload["requested_by"],
                payload["quote_date"],
                payload["currency_code"],
                payload["price_factor"],
                payload["price_margin_pct"],
                payload["tax_rate"],
                payload["subtotal"],
                payload["tax_amount"],
                payload["total"],
                (payload.get("status") or "PENDING").strip().upper(),
                payload.get("notes") or "",
                payload.get("closing_message") or "",
                created_at,
            ),
        )
        quote_id = int(cursor.lastrowid)

        for sort_order, item in enumerate(items, start=1):
            conn.execute(
                """
                INSERT INTO quote_items (
                    quote_id, source_item_id, sku, description, unit, qty, cost_amount, base_price_unit,
                    price_unit, taxable, discount_type, discount_value, line_subtotal, line_discount,
                    line_total, sort_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    item.get("taxable", 1),
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
                client_type = ?,
                client_name = ?,
                client_document_type = ?,
                client_document_number = ?,
                client_email = ?,
                client_phone = ?,
                client_address = ?,
                requested_by = ?,
                quote_date = ?,
                currency_code = ?,
                price_factor = ?,
                price_margin_pct = ?,
                tax_rate = ?,
                subtotal = ?,
                tax_amount = ?,
                total = ?,
                status = ?,
                notes = ?,
                closing_message = ?
            WHERE id = ?
            """,
            (
                payload["title"],
                payload["location"],
                payload.get("client_type") or "BUSINESS",
                payload["client_name"],
                payload.get("client_document_type") or "",
                payload.get("client_document_number") or "",
                payload.get("client_email") or "",
                payload.get("client_phone") or "",
                payload.get("client_address") or "",
                payload["requested_by"],
                payload["quote_date"],
                payload["currency_code"],
                payload["price_factor"],
                payload["price_margin_pct"],
                payload["tax_rate"],
                payload["subtotal"],
                payload["tax_amount"],
                payload["total"],
                (payload.get("status") or "PENDING").strip().upper(),
                payload.get("notes") or "",
                payload.get("closing_message") or "",
                quote_id,
            ),
        )

        conn.execute("DELETE FROM quote_items WHERE quote_id = ?", (quote_id,))
        for sort_order, item in enumerate(items, start=1):
            conn.execute(
                """
                INSERT INTO quote_items (
                    quote_id, source_item_id, sku, description, unit, qty, cost_amount, base_price_unit,
                    price_unit, taxable, discount_type, discount_value, line_subtotal, line_discount,
                    line_total, sort_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    item.get("taxable", 1),
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
