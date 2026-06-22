from ...domain.services.uom_service import is_metric_uom


def format_quantity_number(value: float, uom_code: int) -> str:
    if value == 0.0:
        return ""
    if is_metric_uom(uom_code) and abs(value) < 100.0:
        return f"{value:,.2f}"
    return f"{value:,.0f}"


def format_quantity_with_uom(value: float, uom_code: int, uom_label_fn) -> str:
    label = uom_label_fn(uom_code)
    number = format_quantity_number(value, uom_code)
    if label:
        return f"{number or '0'} {label}"
    return number
