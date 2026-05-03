import unittest
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db import (
    apply_client_credit_payment,
    confirm_catalog_order_payment,
    confirm_quote_invoice_payment,
    create_catalog_order,
    create_quote,
    create_user,
    get_catalog_item,
    get_catalog_order,
    get_quote,
    init_db,
    link_catalog_order_quote,
    list_clients,
    list_client_credits,
    list_catalog_orders,
    save_catalog_item,
    save_client,
    send_catalog_order_to_credit,
    send_quote_to_credit,
)
from app.main import app, list_invoice_documents
from app.services.auth import hash_password


def login(client: TestClient, username: str, password: str) -> None:
    response = client.post(
        "/login",
        data={"identity": username, "password": password, "next": "/"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def make_catalog_item(*, stock: float, price: float) -> tuple[int, str]:
    suffix = uuid4().hex[:8].upper()
    sku = f"BILL-{suffix}"
    item_id = save_catalog_item(
        {
            "item_type": "PRODUCT",
            "sku": sku,
            "description": f"Producto facturable {suffix}",
            "unit": "UND",
            "cost_amount": 0,
            "pricing_mode": "MANUAL",
            "margin_pct": 0,
            "markup_pct": 0,
            "manual_price": price,
            "tax_rate": 0,
            "taxable": 0,
            "available_qty": stock,
            "active": 1,
        }
    )
    return item_id, sku


def make_order(*, item_id: int, sku: str, qty: float, price: float) -> int:
    total = qty * price
    return create_catalog_order(
        {
            "customer_name": f"Cliente {uuid4().hex[:6]}",
            "customer_phone": "3000000000",
            "customer_address": "Bogota",
            "status": "NEW",
            "payment_status": "PENDING",
            "subtotal": total,
            "tax_amount": 0,
            "total": total,
        },
        [
            {
                "catalog_item_id": item_id,
                "sku": sku,
                "description": "Producto facturable",
                "unit": "UND",
                "qty": qty,
                "price_unit": price,
                "taxable": 0,
                "line_total": total,
            }
        ],
    )


def make_invoice_quote(*, order_id: int, item_id: int, sku: str, qty: float, price: float) -> int:
    total = qty * price
    quote_id = create_quote(
        {
            "title": "FACTURA DE VENTA",
            "location": "Bogota",
            "client_type": "CONSUMER",
            "client_name": "Cliente facturacion",
            "client_document_type": "",
            "client_document_number": "",
            "client_email": "",
            "client_phone": "3000000000",
            "client_address": "Bogota",
            "requested_by": "Admin",
            "quote_date": date.today().isoformat(),
            "currency_code": "COP",
            "price_factor": 1,
            "price_margin_pct": 100,
            "tax_rate": 0,
            "subtotal": total,
            "tax_amount": 0,
            "total": total,
            "status": "INVOICED",
            "notes": "",
            "closing_message": "Gracias por su atencion.",
        },
        [
            {
                "source_item_id": item_id,
                "sku": sku,
                "description": "Producto facturable",
                "unit": "UND",
                "qty": qty,
                "cost_amount": 0,
                "base_price_unit": price,
                "price_unit": price,
                "taxable": 0,
                "discount_type": "PERCENT",
                "discount_value": 0,
                "line_subtotal": total,
                "line_discount": 0,
                "line_total": total,
            }
        ],
    )
    link_catalog_order_quote(order_id, quote_id, "INVOICED")
    return quote_id


def make_standalone_invoice_quote(*, item_id: int, sku: str, qty: float, price: float) -> int:
    total = qty * price
    return create_quote(
        {
            "title": "FACTURA DE VENTA",
            "location": "Bogota",
            "client_type": "CONSUMER",
            "client_name": "Cliente directo",
            "client_document_type": "",
            "client_document_number": "",
            "client_email": "",
            "client_phone": "3010000000",
            "client_address": "Bogota",
            "requested_by": "Admin",
            "quote_date": date.today().isoformat(),
            "currency_code": "COP",
            "price_factor": 1,
            "price_margin_pct": 100,
            "tax_rate": 0,
            "subtotal": total,
            "tax_amount": 0,
            "total": total,
            "status": "PENDING",
            "notes": "",
            "closing_message": "Gracias por su atencion.",
        },
        [
            {
                "source_item_id": item_id,
                "sku": sku,
                "description": "Producto facturable directo",
                "unit": "UND",
                "qty": qty,
                "cost_amount": 0,
                "base_price_unit": price,
                "price_unit": price,
                "taxable": 0,
                "discount_type": "PERCENT",
                "discount_value": 0,
                "line_subtotal": total,
                "line_discount": 0,
                "line_total": total,
            }
        ],
    )


class OrderBillingTests(unittest.TestCase):
    def setUp(self) -> None:
        init_db()

    def test_invoiced_order_disappears_from_active_order_list(self) -> None:
        item_id, sku = make_catalog_item(stock=8, price=90)
        order_id = make_order(item_id=item_id, sku=sku, qty=1, price=90)
        quote_id = make_invoice_quote(order_id=order_id, item_id=item_id, sku=sku, qty=1, price=90)

        order = get_catalog_order(order_id)
        quote = get_quote(quote_id)
        pending_orders = list_catalog_orders(search=order["order_number"], exclude_completed=True)

        self.assertEqual(quote["status"], "INVOICED")
        self.assertEqual(order["status"], "INVOICED")
        self.assertEqual(pending_orders, [])

    def test_cash_invoice_discounts_inventory_without_creating_credit(self) -> None:
        item_id, sku = make_catalog_item(stock=5, price=100)
        order_id = make_order(item_id=item_id, sku=sku, qty=2, price=100)
        quote_id = make_invoice_quote(order_id=order_id, item_id=item_id, sku=sku, qty=2, price=100)

        confirm_catalog_order_payment(order_id, method="Factura de contado")

        item = get_catalog_item(item_id)
        order = get_catalog_order(order_id)
        quote = get_quote(quote_id)
        credits = list_client_credits(search=order["order_number"])
        pending_orders = list_catalog_orders(search=order["order_number"], exclude_completed=True)
        invoices = list_invoice_documents("FAC-")

        self.assertEqual(float(item["available_qty"]), 3.0)
        self.assertEqual(order["payment_status"], "PAID")
        self.assertEqual(quote["status"], "PAID")
        self.assertEqual(credits, [])
        self.assertEqual(pending_orders, [])
        self.assertIn(quote_id, {int(invoice["id"]) for invoice in invoices})

    def test_credit_invoice_discounts_inventory_and_creates_credit(self) -> None:
        item_id, sku = make_catalog_item(stock=4, price=150)
        order_id = make_order(item_id=item_id, sku=sku, qty=1, price=150)
        quote_id = make_invoice_quote(order_id=order_id, item_id=item_id, sku=sku, qty=1, price=150)
        client_id = save_client(
            {
                "client_type": "CONSUMER",
                "name": "Cliente credito",
                "phone": "3110000000",
                "address": "Medellin",
            }
        )

        credit_id = send_catalog_order_to_credit(order_id, client_id=client_id)

        item = get_catalog_item(item_id)
        order = get_catalog_order(order_id)
        quote = get_quote(quote_id)
        invoice_number = f"FAC-{quote['quote_number'].split('-', 1)[1]}"
        credits = list_client_credits(search=invoice_number)
        pending_orders = list_catalog_orders(search=order["order_number"], exclude_completed=True)

        self.assertEqual(float(item["available_qty"]), 3.0)
        self.assertEqual(order["payment_status"], "CREDIT")
        self.assertEqual(order["credit_id"], credit_id)
        self.assertEqual(quote["status"], "CREDIT")
        self.assertEqual(len(credits), 1)
        self.assertEqual(credits[0]["invoice_number"], invoice_number)
        self.assertIn(invoice_number, credits[0]["description"])
        self.assertEqual(float(credits[0]["balance"]), 150.0)
        self.assertEqual(pending_orders, [])

    def test_cash_invoice_from_quote_discounts_inventory_without_creating_credit(self) -> None:
        item_id, sku = make_catalog_item(stock=5, price=120)
        quote_id = make_standalone_invoice_quote(item_id=item_id, sku=sku, qty=2, price=120)

        confirm_quote_invoice_payment(quote_id, method="Factura de contado")

        item = get_catalog_item(item_id)
        quote = get_quote(quote_id)
        invoice_number = f"FAC-{quote['quote_number'].split('-', 1)[1]}"
        credits = list_client_credits(search=invoice_number)

        self.assertEqual(float(item["available_qty"]), 3.0)
        self.assertEqual(quote["status"], "PAID")
        self.assertEqual(credits, [])

    def test_credit_invoice_from_quote_discounts_inventory_and_creates_credit(self) -> None:
        item_id, sku = make_catalog_item(stock=5, price=120)
        quote_id = make_standalone_invoice_quote(item_id=item_id, sku=sku, qty=1, price=120)
        client_id = save_client(
            {
                "client_type": "CONSUMER",
                "name": "Cliente directo credito",
                "phone": "3330000000",
                "address": "Bogota",
            }
        )

        credit_id = send_quote_to_credit(quote_id, client_id=client_id)

        item = get_catalog_item(item_id)
        quote = get_quote(quote_id)
        invoice_number = f"FAC-{quote['quote_number'].split('-', 1)[1]}"
        credits = list_client_credits(search=invoice_number)

        self.assertEqual(float(item["available_qty"]), 4.0)
        self.assertGreater(credit_id, 0)
        self.assertEqual(quote["status"], "CREDIT")
        self.assertEqual(len(credits), 1)
        self.assertEqual(credits[0]["invoice_number"], invoice_number)
        self.assertEqual(float(credits[0]["balance"]), 120.0)

    def test_direct_invoice_form_cash_discounts_inventory(self) -> None:
        item_id, sku = make_catalog_item(stock=6, price=250)
        username = f"invoice_{uuid4().hex[:8]}"
        password = "FacturaSegura123!"
        create_user(
            username,
            hash_password(password),
            is_admin=True,
            full_name="Admin Factura",
            email=f"{username}@demo.com",
        )

        client = TestClient(app)
        login(client, username, password)

        response = client.post(
            "/quotes",
            data={
                "document_mode": "invoice",
                "invoice_payment_mode": "cash",
                "client_type": "CONSUMER",
                "client_name": "Cliente contado",
                "client_phone": "3001112233",
                "client_address": "Bogota",
                "source_item_id": str(item_id),
                "sku": sku,
                "description": "Producto contado directo",
                "unit": "UND",
                "qty": "2",
                "cost_amount": "0",
                "base_price_unit": "250",
                "price_unit": "250",
                "taxable": "0",
                "discount_type": "PERCENT",
                "discount_value": "0",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("/quotes/", response.headers["location"])
        self.assertTrue(response.headers["location"].endswith("/invoice"))

        item = get_catalog_item(item_id)
        quote_id = int(response.headers["location"].split("/quotes/")[1].split("/")[0])
        quote = get_quote(quote_id)

        self.assertEqual(float(item["available_qty"]), 4.0)
        self.assertEqual(quote["status"], "PAID")

    def test_direct_invoice_form_credit_creates_credit_and_discounts_inventory(self) -> None:
        item_id, sku = make_catalog_item(stock=6, price=180)
        username = f"invoice_{uuid4().hex[:8]}"
        password = "FacturaSegura123!"
        create_user(
            username,
            hash_password(password),
            is_admin=True,
            full_name="Admin Factura",
            email=f"{username}@demo.com",
        )

        client = TestClient(app)
        login(client, username, password)

        response = client.post(
            "/quotes",
            data={
                "document_mode": "invoice",
                "invoice_payment_mode": "credit",
                "client_type": "CONSUMER",
                "client_name": "Cliente credito",
                "client_phone": "3004445566",
                "client_address": "Medellin",
                "source_item_id": str(item_id),
                "sku": sku,
                "description": "Producto credito directo",
                "unit": "UND",
                "qty": "1",
                "cost_amount": "0",
                "base_price_unit": "180",
                "price_unit": "180",
                "taxable": "0",
                "discount_type": "PERCENT",
                "discount_value": "0",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("/quotes/", response.headers["location"])
        self.assertIn("/invoice", response.headers["location"])

        quote_id = int(response.headers["location"].split("/quotes/")[1].split("/")[0])
        quote = get_quote(quote_id)
        invoice_number = f"FAC-{quote['quote_number'].split('-', 1)[1]}"
        item = get_catalog_item(item_id)
        credits = list_client_credits(search=invoice_number)

        self.assertEqual(float(item["available_qty"]), 5.0)
        self.assertEqual(quote["status"], "CREDIT")
        self.assertEqual(len(credits), 1)
        self.assertEqual(credits[0]["invoice_number"], invoice_number)

    def test_partial_payment_from_credit_updates_balance_but_keeps_invoice_on_credit(self) -> None:
        item_id, sku = make_catalog_item(stock=4, price=150)
        order_id = make_order(item_id=item_id, sku=sku, qty=1, price=150)
        quote_id = make_invoice_quote(order_id=order_id, item_id=item_id, sku=sku, qty=1, price=150)
        client_id = save_client(
            {
                "client_type": "CONSUMER",
                "name": "Cliente abono",
                "phone": "3220000000",
                "address": "Bogota",
            }
        )

        credit_id = send_catalog_order_to_credit(order_id, client_id=client_id)
        updated_credit = apply_client_credit_payment(credit_id, 50)

        order = get_catalog_order(order_id)
        quote = get_quote(quote_id)

        self.assertEqual(updated_credit["status"], "PARTIAL")
        self.assertEqual(float(updated_credit["paid_amount"]), 50.0)
        self.assertEqual(float(updated_credit["balance"]), 100.0)
        self.assertEqual(order["payment_status"], "CREDIT")
        self.assertEqual(quote["status"], "CREDIT")

    def test_full_payment_from_credit_marks_invoice_and_order_paid(self) -> None:
        item_id, sku = make_catalog_item(stock=4, price=150)
        order_id = make_order(item_id=item_id, sku=sku, qty=1, price=150)
        quote_id = make_invoice_quote(order_id=order_id, item_id=item_id, sku=sku, qty=1, price=150)
        client_id = save_client(
            {
                "client_type": "CONSUMER",
                "name": "Cliente pago total",
                "phone": "3230000000",
                "address": "Bogota",
            }
        )

        credit_id = send_catalog_order_to_credit(order_id, client_id=client_id)
        updated_credit = apply_client_credit_payment(credit_id, settle_full=True)

        order = get_catalog_order(order_id)
        quote = get_quote(quote_id)

        self.assertEqual(updated_credit["status"], "PAID")
        self.assertEqual(float(updated_credit["paid_amount"]), 150.0)
        self.assertEqual(float(updated_credit["balance"]), 0.0)
        self.assertEqual(order["payment_status"], "PAID")
        self.assertEqual(quote["status"], "PAID")

    def test_fully_paid_credit_disappears_from_default_credit_list(self) -> None:
        item_id, sku = make_catalog_item(stock=4, price=150)
        order_id = make_order(item_id=item_id, sku=sku, qty=1, price=150)
        quote_id = make_invoice_quote(order_id=order_id, item_id=item_id, sku=sku, qty=1, price=150)
        client_id = save_client(
            {
                "client_type": "CONSUMER",
                "name": "Cliente filtrado",
                "phone": "3240000000",
                "address": "Bogota",
            }
        )

        credit_id = send_catalog_order_to_credit(order_id, client_id=client_id)
        invoice_number = f"FAC-{get_quote(quote_id)['quote_number'].split('-', 1)[1]}"

        self.assertEqual(len(list_client_credits(search=invoice_number)), 1)

        apply_client_credit_payment(credit_id, settle_full=True)

        self.assertEqual(list_client_credits(search=invoice_number), [])
        self.assertEqual(len(list_client_credits(search=invoice_number, include_paid=True)), 1)

    def test_client_list_shows_only_pending_credit_balance(self) -> None:
        item_id, sku = make_catalog_item(stock=6, price=200)
        client_id = save_client(
            {
                "client_type": "CONSUMER",
                "name": "Cliente cartera visible",
                "phone": "3250000000",
                "address": "Medellin",
            }
        )

        first_order_id = make_order(item_id=item_id, sku=sku, qty=1, price=200)
        first_quote_id = make_invoice_quote(order_id=first_order_id, item_id=item_id, sku=sku, qty=1, price=200)
        first_credit_id = send_catalog_order_to_credit(first_order_id, client_id=client_id)

        second_order_id = make_order(item_id=item_id, sku=sku, qty=1, price=200)
        second_quote_id = make_invoice_quote(order_id=second_order_id, item_id=item_id, sku=sku, qty=1, price=200)
        second_credit_id = send_catalog_order_to_credit(second_order_id, client_id=client_id)

        apply_client_credit_payment(second_credit_id, settle_full=True)

        clients = list_clients()
        client_row = next(client for client in clients if int(client["id"]) == client_id)
        client_credits = list_client_credits(client_id=client_id)
        paid_history = list_client_credits(client_id=client_id, include_paid=True)

        self.assertGreater(first_quote_id, 0)
        self.assertGreater(second_quote_id, 0)
        self.assertEqual(len(client_credits), 1)
        self.assertEqual(int(client_row["open_credit_count"]), 1)
        self.assertEqual(float(client_row["open_credit_balance"]), 200.0)
        self.assertEqual(len(paid_history), 2)
        self.assertEqual({credit["id"] for credit in paid_history}, {first_credit_id, second_credit_id})


if __name__ == "__main__":
    unittest.main()
