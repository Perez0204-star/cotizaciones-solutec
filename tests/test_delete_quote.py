import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db import create_quote, create_user, get_quote, init_db
from app.main import app
from app.services.auth import hash_password


class DeleteQuoteTests(unittest.TestCase):
    def test_delete_quote_removes_header_and_items(self) -> None:
        init_db()
        payload = {
            "title": "COTIZACION EXPLORATORIA",
            "location": "APARTADO",
            "client_name": "CLIENTE DEMO",
            "client_email": "",
            "requested_by": "MILLER PANTOJA",
            "quote_date": "2026-04-16",
            "currency_code": "COP",
            "price_factor": 1,
            "price_margin_pct": 100,
            "tax_rate": 19,
            "subtotal": 188874,
            "tax_amount": 35886,
            "total": 224760,
            "notes": "",
        }
        items = [
            {
                "source_item_id": None,
                "sku": "0202-00304",
                "description": "CABLE UTP CT6 INTEMPERIE",
                "unit": "METRO",
                "qty": 87,
                "cost_amount": 0,
                "base_price_unit": 2102,
                "price_unit": 2102,
                "discount_type": "PERCENT",
                "discount_value": 0,
                "line_subtotal": 182874,
                "line_discount": 0,
                "line_total": 182874,
            }
        ]
        quote_id = create_quote(payload, items)

        self.assertIsNotNone(get_quote(quote_id))

        client = TestClient(app)
        username = f"delete_{uuid4().hex[:8]}"
        password = "Segura123!"
        create_user(username, hash_password(password))
        login_response = client.post(
            "/login",
            data={"username": username, "password": password, "next": "/"},
            follow_redirects=False,
        )
        self.assertEqual(login_response.status_code, 303)

        response = client.post(
            f"/quotes/{quote_id}/delete",
            data={"next": "/"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/")
        self.assertIsNone(get_quote(quote_id))


if __name__ == "__main__":
    unittest.main()
