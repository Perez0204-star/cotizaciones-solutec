import unittest

from PIL import Image

from app.db import UPLOADS_DIR, fetch_settings, init_db
from app.services.pdf_export import build_quote_pdf


class PdfExportTests(unittest.TestCase):
    def test_build_quote_pdf_generates_printable_file(self) -> None:
        init_db()
        settings = fetch_settings()
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        logo_path = UPLOADS_DIR / "test_logo_pdf.png"
        Image.new("RGBA", (320, 120), (15, 143, 203, 255)).save(logo_path)
        settings["logo_filename"] = logo_path.name

        quote = {
            "id": 5,
            "quote_number": "COT-000005",
            "title": "COTIZACION EXPLORATORIA",
            "location": "APARTADO",
            "client_name": "CN2 CUARTO CONTENEDORES VACIOS",
            "requested_by": "MILLER PANTOJA",
            "quote_date": "2026-04-15",
            "currency_code": "COP",
            "tax_rate": 19,
            "subtotal": 994874,
            "tax_amount": 189026,
            "total": 1183900,
            "notes": "Documento listo para impresion.",
            "items": [
                {
                    "sku": "0202-00304",
                    "description": "CABLE UTP CT6 INTEMPERIE",
                    "unit": "METRO",
                    "qty": 87,
                    "price_unit": 2102,
                    "line_total": 182874,
                },
                {
                    "sku": "0202-00654",
                    "description": "JACK RJ45 CT6",
                    "unit": "UNIDAD",
                    "qty": 6,
                    "price_unit": 1000,
                    "line_total": 6000,
                },
            ],
        }

        pdf_buffer = build_quote_pdf(quote, settings)
        content = pdf_buffer.getvalue()

        self.assertGreater(len(content), 5000)
        self.assertTrue(content.startswith(b"%PDF"))
        logo_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
