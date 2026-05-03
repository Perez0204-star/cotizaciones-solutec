import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db import (
    create_catalog_order,
    create_quote,
    create_user,
    delete_catalog_item,
    get_catalog_item,
    get_catalog_order,
    get_quote,
    init_db,
    save_catalog_item,
)
from app.main import app
from app.services.auth import hash_password


def login(client: TestClient, username: str, password: str) -> None:
    response = client.post(
        "/login",
        data={"identity": username, "password": password, "next": "/"},
        follow_redirects=False,
    )
    assert response.status_code == 303


class CatalogFeatureTests(unittest.TestCase):
    def setUp(self) -> None:
        init_db()

    def test_delete_catalog_item_preserves_quote_and_order_snapshots(self) -> None:
        token = uuid4().hex[:6].upper()
        item_id = save_catalog_item(
            {
                "item_type": "PRODUCT",
                "sku": f"SKU-{token}",
                "description": f"PRODUCTO DEMO {token}",
                "unit": "UND",
                "cost_amount": 500,
                "pricing_mode": "MANUAL",
                "margin_pct": 0,
                "markup_pct": 0,
                "manual_price": 1000,
                "tax_rate": 19,
                "taxable": 1,
                "available_qty": 5,
                "active": 1,
                "image_filename": None,
                "image_mime": None,
                "video_url": "",
                "notes_internal": "",
                "notes_quote": "",
            }
        )

        quote_id = create_quote(
            {
                "title": "COTIZACION EXPLORATORIA",
                "location": "APARTADO",
                "client_name": "CLIENTE DEMO",
                "client_email": "",
                "requested_by": "ADMIN",
                "quote_date": "2026-04-24",
                "currency_code": "COP",
                "price_factor": 1,
                "price_margin_pct": 100,
                "tax_rate": 19,
                "subtotal": 1000,
                "tax_amount": 190,
                "total": 1190,
                "notes": "",
            },
            [
                {
                    "source_item_id": item_id,
                    "sku": f"SKU-{token}",
                    "description": f"PRODUCTO DEMO {token}",
                    "unit": "UND",
                    "qty": 1,
                    "cost_amount": 500,
                    "base_price_unit": 1000,
                    "price_unit": 1000,
                    "taxable": 1,
                    "discount_type": "PERCENT",
                    "discount_value": 0,
                    "line_subtotal": 1000,
                    "line_discount": 0,
                    "line_total": 1000,
                }
            ],
        )

        order_id = create_catalog_order(
            {
                "customer_name": "CLIENTE PEDIDO",
                "customer_phone": "3000000000",
                "customer_address": "APARTADO",
                "status": "NEW",
                "payment_status": "PENDING",
                "subtotal": 1000,
                "tax_amount": 190,
                "total": 1190,
            },
            [
                {
                    "catalog_item_id": item_id,
                    "sku": f"SKU-{token}",
                    "description": f"PRODUCTO DEMO {token}",
                    "unit": "UND",
                    "qty": 1,
                    "price_unit": 1000,
                    "taxable": 1,
                    "line_total": 1000,
                }
            ],
        )

        delete_catalog_item(item_id)

        self.assertIsNone(get_catalog_item(item_id))

        quote = get_quote(quote_id)
        self.assertIsNotNone(quote)
        self.assertEqual(quote["items"][0]["sku"], f"SKU-{token}")
        self.assertIsNone(quote["items"][0]["source_item_id"])

        order = get_catalog_order(order_id)
        self.assertIsNotNone(order)
        self.assertEqual(order["items"][0]["sku"], f"SKU-{token}")
        self.assertIsNone(order["items"][0]["catalog_item_id"])

    def test_catalog_delete_route_removes_item(self) -> None:
        token = uuid4().hex[:6].upper()
        username = f"catalogo_{token.lower()}"
        password = "Catalogo123!"
        create_user(
            username,
            hash_password(password),
            is_admin=True,
            full_name="Admin Catalogo",
            email=f"{username}@demo.com",
        )

        item_id = save_catalog_item(
            {
                "item_type": "PRODUCT",
                "sku": f"DEL-{token}",
                "description": f"PRODUCTO ELIMINABLE {token}",
                "unit": "UND",
                "cost_amount": 250,
                "pricing_mode": "MANUAL",
                "margin_pct": 0,
                "markup_pct": 0,
                "manual_price": 500,
                "tax_rate": 19,
                "taxable": 1,
                "available_qty": 3,
                "active": 1,
                "image_filename": None,
                "image_mime": None,
                "video_url": "",
                "notes_internal": "",
                "notes_quote": "",
            }
        )

        client = TestClient(app)
        login(client, username, password)

        response = client.post(f"/catalog/{item_id}/delete", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/catalog")
        self.assertIsNone(get_catalog_item(item_id))

    def test_catalog_routes_render_category_sections(self) -> None:
        token = uuid4().hex[:6].upper()
        save_catalog_item(
            {
                "item_type": "PRODUCT",
                "category": "FOOD",
                "sku": f"FOOD-{token}",
                "description": f"PRODUCTO ALIMENTO {token}",
                "unit": "UND",
                "cost_amount": 1200,
                "pricing_mode": "MANUAL",
                "margin_pct": 0,
                "markup_pct": 0,
                "manual_price": 1500,
                "tax_rate": 0,
                "taxable": 0,
                "available_qty": 9,
                "active": 1,
                "image_filename": None,
                "image_mime": None,
                "video_url": "",
                "notes_internal": "",
                "notes_quote": "Linea de alimentos lista para venta.",
            }
        )

        client = TestClient(app)
        response = client.get("/catalog/share")

        self.assertEqual(response.status_code, 200)
        self.assertIn("ALIMENTOS", response.text)
        self.assertIn("TECNOLOGIA", response.text)
        self.assertIn("ROPA Y CALZADO", response.text)


if __name__ == "__main__":
    unittest.main()
