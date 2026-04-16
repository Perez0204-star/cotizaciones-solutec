from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def to_decimal(value: object, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip().replace(",", "")
    if not text:
        return Decimal(default)
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal(default)


def normalize_percent(value: object) -> Decimal:
    return to_decimal(value) / Decimal("100")


def normalize_margin_percent(value: object, default: str = "0") -> Decimal:
    margin = to_decimal(value, default)
    if margin < Decimal("1") or margin > Decimal("100"):
        raise ValueError("El margen global debe estar entre 1% y 100%.")
    return margin


def round_money(value: object, mode: str = "integer") -> Decimal:
    amount = to_decimal(value)
    if mode == "2dec":
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if mode == "nearest10":
        return (amount / Decimal("10")).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal("10")
    if mode == "nearest100":
        return (amount / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal("100")
    return amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def margin_factor_from_percent(
    margin_percent: object,
) -> Decimal:
    margin_value = normalize_margin_percent(margin_percent)
    return (margin_value / Decimal("100")).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def adjusted_price_by_margin(
    base_price: object,
    margin_percent: object,
    rounding_mode: str = "integer",
) -> Decimal:
    factor_value = margin_factor_from_percent(margin_percent)
    price_value = to_decimal(base_price)
    return round_money(price_value / factor_value, rounding_mode)


def base_price_from_margin(
    adjusted_price: object,
    margin_percent: object,
    rounding_mode: str = "integer",
) -> Decimal:
    factor_value = margin_factor_from_percent(margin_percent)
    price_value = to_decimal(adjusted_price)
    return round_money(price_value * factor_value, rounding_mode)


def legacy_factor_from_margin(
    margin_percent: object,
) -> Decimal:
    return margin_factor_from_percent(margin_percent)


def suggested_sale_price(
    *,
    cost_amount: object,
    pricing_mode: str,
    margin_pct: object = 0,
    markup_pct: object = 0,
    manual_price: object = 0,
    fx_rate: object = 1,
    rounding_mode: str = "integer",
) -> Decimal:
    cost_value = to_decimal(cost_amount) * to_decimal(fx_rate, "1")
    pricing_mode = (pricing_mode or "MANUAL").upper()

    if pricing_mode == "MARGIN":
        margin = normalize_percent(margin_pct)
        if margin >= Decimal("1"):
            raise ValueError("El margen bruto debe ser menor al 100%.")
        result = Decimal("0") if cost_value == 0 else cost_value / (Decimal("1") - margin)
        return round_money(result, rounding_mode)

    if pricing_mode == "MARKUP":
        markup = normalize_percent(markup_pct)
        result = cost_value * (Decimal("1") + markup)
        return round_money(result, rounding_mode)

    return round_money(manual_price, rounding_mode)


def margin_percent_from_price(cost_amount: object, price_unit: object) -> Decimal:
    cost_value = to_decimal(cost_amount)
    price_value = to_decimal(price_unit)
    if price_value <= 0:
        return Decimal("0")
    return ((price_value - cost_value) / price_value * Decimal("100")).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def line_financials(
    *,
    qty: object,
    price_unit: object,
    discount_type: str = "PERCENT",
    discount_value: object = 0,
    rounding_mode: str = "integer",
) -> dict[str, Decimal]:
    quantity = to_decimal(qty)
    unit_price = to_decimal(price_unit)
    raw_subtotal = quantity * unit_price
    subtotal = round_money(raw_subtotal, rounding_mode)

    discount_mode = (discount_type or "PERCENT").upper()
    if discount_mode == "VALUE":
        discount = to_decimal(discount_value)
    else:
        discount = raw_subtotal * normalize_percent(discount_value)

    if discount > raw_subtotal:
        discount = raw_subtotal

    discount = round_money(discount, rounding_mode)
    total = round_money(subtotal - discount, rounding_mode)

    return {
        "qty": quantity,
        "price_unit": round_money(unit_price, rounding_mode),
        "line_subtotal": subtotal,
        "line_discount": discount,
        "line_total": total,
    }


def quote_totals(
    *,
    line_totals: list[object],
    tax_rate: object,
    rounding_mode: str = "integer",
) -> dict[str, Decimal]:
    subtotal = round_money(sum((to_decimal(value) for value in line_totals), Decimal("0")), rounding_mode)
    tax_amount = round_money(subtotal * normalize_percent(tax_rate), rounding_mode)
    total = round_money(subtotal + tax_amount, rounding_mode)
    return {
        "subtotal": subtotal,
        "tax_amount": tax_amount,
        "total": total,
    }
