import re
from typing import Optional

IMPERIAL_FEET_INCHES = re.compile(
    r"^-?\s*\d+\s*[\'′]\s*(?:-?\s*)?\s*\d+(?:\s+\d+/\d+)?\s*\"", re.IGNORECASE
)
IMPERIAL_FEET_ONLY = re.compile(r"^-?\s*\d+\s*[\'′]\b", re.IGNORECASE)
IMPERIAL_INCHES_ONLY = re.compile(
    r"^-?\s*(?:\d+(?:\s+\d+/\d+)?|\d+/\d+)\s*\"", re.IGNORECASE
)
METRIC_M_PLUS_CM = re.compile(
    r"^-?\s*\d+(?:[\.,]\d+)?\s*m\s*(?:and|\+)?\s*-?\s*\d+(?:[\.,]\d+)?\s*cm",
    re.IGNORECASE,
)
METRIC_METERS_ONLY = re.compile(
    r"^-?\s*\d+(?:[\.,]\d+)?\s*(?:m|meters?)\b", re.IGNORECASE
)
METRIC_CM_ONLY = re.compile(
    r"^-?\s*\d+(?:[\.,]\d+)?\s*(?:cm|centimeters?)\b", re.IGNORECASE
)
ELEVATION_TEXT_PATTERNS = (
    IMPERIAL_FEET_INCHES,
    IMPERIAL_FEET_ONLY,
    IMPERIAL_INCHES_ONLY,
    METRIC_M_PLUS_CM,
    METRIC_METERS_ONLY,
    METRIC_CM_ONLY,
)
_FEET_ONLY_AT_END = re.compile(r"^-?\s*\d+\s*[\'′]\s*$")


def is_elevation_text(text: str) -> bool:
    return any(pattern.match(text) for pattern in ELEVATION_TEXT_PATTERNS)


def is_strippable_elevation_text(text: str) -> bool:
    return is_elevation_text(text) or bool(_FEET_ONLY_AT_END.match(text))


def cm_to_inches(cm: float) -> float:
    return cm / 2.54


def _fraction_value(numerator_text: str, denominator_text: str) -> float:
    numerator = float(numerator_text)
    denominator = float(denominator_text)
    if denominator == 0.0:
        raise ValueError(
            f"zero denominator in fraction {numerator_text}/{denominator_text}"
        )
    return numerator / denominator


def _parse_fractional_inches_text(inch_text: str) -> float:
    inch_text = " ".join(inch_text.split())
    negative = inch_text.startswith("-")
    if negative:
        inch_text = inch_text[1:].strip()
    if " " in inch_text:
        whole_part, frac_part = inch_text.split(None, 1)
        try:
            whole = float(whole_part)
        except ValueError:
            whole = 0.0
        if "/" in frac_part:
            num, den = frac_part.split("/", 1)
            frac = _fraction_value(num, den)
        else:
            frac = float(frac_part)
        value = whole + frac
    elif "/" in inch_text:
        num, den = inch_text.split("/", 1)
        value = _fraction_value(num, den)
    else:
        value = float(inch_text)
    return -value if negative else value


def _without_whitespace(text: str) -> str:
    return "".join(text.split())


def _parse_imperial_elevation(elevation_text: str) -> float:
    text = elevation_text.strip()
    m = re.search(
        r"(?P<feet>-?\s*\d+)\s*[\'′]\s*(?:-?\s*)?(?P<inches>\d+(?:\s+\d+/\d+)?|\d+/\d+)\s*\"",
        text,
    )
    if m:
        feet_str = _without_whitespace(m.group("feet"))
        inches_str = m.group("inches").strip()
        negative = feet_str.startswith("-")
        feet_val = abs(int(feet_str))
        inches_val = _parse_fractional_inches_text(inches_str)
        total = feet_val * 12 + inches_val
        return -total if negative else total
    m = re.search(r"(?P<feet>-?\s*\d+)\s*[\'′]\b", text)
    if m:
        feet_str = _without_whitespace(m.group("feet"))
        feet_val = int(feet_str)
        return float(feet_val * 12)
    m = re.search(r"(?P<inches>-?\s*(?:\d+(?:\s+\d+/\d+)?|\d+/\d+))\s*\"", text)
    if m:
        inches_str = m.group("inches").strip()
        return _parse_fractional_inches_text(inches_str)
    return 0.0


def _parse_metric_elevation(elevation_text: str) -> float:
    text = elevation_text.strip().lower().replace(",", ".")
    m = re.search(
        r"(-?\s*\d+(?:\.\d+)?)\s*m\s*(?:and|\+)?\s*(-?\s*\d+(?:\.\d+)?)\s*cm", text
    )
    if m:
        meter_text = _without_whitespace(m.group(1))
        meter_part = float(meter_text)
        cm_part = float(_without_whitespace(m.group(2)))
        if meter_text.startswith("-"):
            return -(abs(meter_part) * 100.0 + abs(cm_part))
        return meter_part * 100.0 + cm_part
    m = re.search(r"(-?\s*\d+(?:\.\d+)?)\s*(?:m|meters?)\b", text)
    if m:
        meter_part = float(_without_whitespace(m.group(1)))
        return meter_part * 100.0
    m = re.search(r"(-?\s*\d+(?:\.\d+)?)\s*(?:cm|centimeters?)\b", text)
    if m:
        return float(_without_whitespace(m.group(1)))
    return 0.0


def elevation_text_inches(text: str) -> Optional[float]:
    elevation_text = text.strip()
    if not is_elevation_text(elevation_text):
        return None
    lowered = elevation_text.lower()
    has_imperial = (
        ("'" in elevation_text) or ("′" in elevation_text) or ('"' in elevation_text)
    )
    has_metric = "m" in lowered or "cm" in lowered
    if has_imperial and not has_metric:
        return _parse_imperial_elevation(elevation_text)
    if has_metric and not has_imperial:
        return cm_to_inches(_parse_metric_elevation(elevation_text))
    return None
