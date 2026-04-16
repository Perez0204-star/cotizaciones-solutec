import unittest
from pathlib import Path

from PIL import Image
from openpyxl import load_workbook

from app.db import UPLOADS_DIR, fetch_settings, init_db
from app.services.excel_export import build_quote_workbook
from app.services.uploads import EXCEL_LOGO_SIZE, prepare_logo_for_excel


class ExcelExportTests(unittest.TestCase):
    def test_export_contains_reusable_formulas(self) -> None:
        init_db()
        settings = fetch_settings()
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        logo_path = UPLOADS_DIR / "test_logo_excel.png"
        Image.new("RGBA", (120, 40), (15, 143, 203, 255)).save(logo_path)
        settings["logo_filename"] = logo_path.name

        quote = {
            "quote_number": "COT-000001",
            "title": "COTIZACION EXPLORATORIA",
            "location": "Bogota",
            "client_name": "Cliente Demo",
            "client_email": "demo@example.com",
            "requested_by": "Ventas",
            "quote_date": "2026-04-15",
            "currency_code": settings["currency_code"],
            "tax_rate": 19,
            "subtotal": 261261,
            "tax_amount": 49640,
            "total": 310901,
            "items": [
                {
                    "sku": "SKU-DEMO",
                    "description": "Cable UTP Cat6",
                    "unit": "Metro",
                    "qty": 87,
                    "cost_amount": 2102,
                    "price_unit": 3003,
                    "line_total": 261261,
                }
            ],
        }

        workbook = load_workbook(build_quote_workbook(quote, settings), data_only=False)
        sheet = workbook.active
        prepared_logo = prepare_logo_for_excel(settings["logo_filename"])

        self.assertEqual(sheet["C1"].value, "COTIZACION EXPLORATORIA")
        self.assertEqual(sheet["D2"].value, "Bogota")
        self.assertEqual(sheet["F4"].value, "Ventas")
        self.assertIsNone(sheet["G7"].value)
        self.assertIsNone(sheet["G8"].value)
        self.assertIsNotNone(prepared_logo)
        self.assertEqual(prepared_logo.size, EXCEL_LOGO_SIZE)
        self.assertEqual(prepared_logo.getpixel((0, 0))[3], 0)
        self.assertEqual(len(sheet._images), 1)
        self.assertIsNone(sheet.freeze_panes)
        self.assertTrue(sheet.print_options.horizontalCentered)
        self.assertEqual(sheet.page_setup.orientation, "landscape")
        self.assertEqual(sheet["F8"].value, '=IF(OR(D8="",E8=""),"",ROUND(D8*E8,0))')
        self.assertEqual(sheet["A8"].value, "SKU-DEMO")
        self.assertEqual(sheet["F29"].value, "=SUM(F8:F24)")
        self.assertTrue(str(sheet["F30"].value).startswith("=ROUND("))
        self.assertTrue(str(sheet["F31"].value).startswith("=ROUND("))
        logo_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
