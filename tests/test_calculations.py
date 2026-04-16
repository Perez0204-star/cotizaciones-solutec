import unittest

from app.services.calculations import (
    adjusted_price_by_margin,
    line_financials,
    normalize_margin_percent,
    quote_totals,
    suggested_sale_price,
)


class CalculationTests(unittest.TestCase):
    def test_margin_pricing(self) -> None:
        price = suggested_sale_price(
            cost_amount=2102,
            pricing_mode="MARGIN",
            margin_pct=30,
            rounding_mode="integer",
        )
        self.assertEqual(int(price), 3003)

    def test_markup_pricing(self) -> None:
        price = suggested_sale_price(
            cost_amount=100,
            pricing_mode="MARKUP",
            markup_pct=25,
            rounding_mode="2dec",
        )
        self.assertEqual(float(price), 125.0)

    def test_line_discount_percent(self) -> None:
        line = line_financials(
            qty=2,
            price_unit=100,
            discount_type="PERCENT",
            discount_value=10,
            rounding_mode="integer",
        )
        self.assertEqual(float(line["line_total"]), 180.0)

    def test_quote_totals(self) -> None:
        totals = quote_totals(
            line_totals=[261261],
            tax_rate=19,
            rounding_mode="integer",
        )
        self.assertEqual(float(totals["tax_amount"]), 49640.0)
        self.assertEqual(float(totals["total"]), 310901.0)

    def test_margin_keeps_normal_price_at_hundred_percent(self) -> None:
        self.assertEqual(float(adjusted_price_by_margin(3000, 100, "integer")), 3000.0)

    def test_margin_increases_price_when_it_descends(self) -> None:
        self.assertEqual(float(adjusted_price_by_margin(3000, 90, "integer")), 3333.0)

    def test_margin_allows_decimal_manual_values(self) -> None:
        self.assertEqual(float(adjusted_price_by_margin(3000, 12.5, "2dec")), 24000.0)

    def test_margin_validation(self) -> None:
        with self.assertRaises(ValueError):
            normalize_margin_percent(0)
        with self.assertRaises(ValueError):
            normalize_margin_percent(101)


if __name__ == "__main__":
    unittest.main()
