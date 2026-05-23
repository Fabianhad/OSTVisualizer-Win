import re
from typing import Optional

_EIGHTHS_FRACTIONS = {
    0: "",
    1: "1/8",
    2: "1/4",
    3: "3/8",
    4: "1/2",
    5: "5/8",
    6: "3/4",
    7: "7/8",
}
_MM_PER_INCH = 25.4


def mm_to_inches(mm: float) -> float:
    return mm / _MM_PER_INCH


def inches_to_mm(inches: float) -> float:
    return inches * _MM_PER_INCH


def inches_to_display(inches: float, metric: bool = False) -> str:
    if metric:
        return mm_to_display(inches_to_mm(inches))
    if inches == 0.0:
        return ""
    sign = "-" if inches < 0 else ""
    total = abs(inches)
    eighths = round(total * 8)
    total_inches = eighths // 8
    frac = eighths % 8
    feet = total_inches // 12
    whole_inches = total_inches % 12
    frac_str = _EIGHTHS_FRACTIONS[frac]
    if feet > 0:
        if whole_inches > 0 and frac_str:
            return f"{sign}{feet}' {whole_inches} {frac_str}\""
        if whole_inches > 0:
            return f"{sign}{feet}' {whole_inches}\""
        if frac_str:
            return f"{sign}{feet}' 0 {frac_str}\""
        return f"{sign}{feet}' 0\""
    if whole_inches > 0 and frac_str:
        return f'{sign}{whole_inches} {frac_str}"'
    if whole_inches > 0:
        return f'{sign}{whole_inches}"'
    if frac_str:
        return f'{sign}{frac_str}"'
    return ""


def mm_to_display(mm: float) -> str:
    if mm == 0.0:
        return ""
    if mm == int(mm):
        return str(int(mm))
    return f"{mm:g}"


_FRACTION_MAP = {
    "1/8": 0.125,
    "1/4": 0.25,
    "3/8": 0.375,
    "1/2": 0.5,
    "5/8": 0.625,
    "3/4": 0.75,
    "7/8": 0.875,
}
_FEET_INCHES_FRAC_RE = re.compile(
    r"^\s*(-?)\s*(\d+)\s*'\s*-?\s*(\d+)\s+(\d/\d)\s*\"?\s*$"
)
_FEET_INCHES_RE = re.compile(r"^\s*(-?)\s*(\d+)\s*'\s*-?\s*(\d+(?:\.\d+)?)\s*\"?\s*$")
_FEET_FRAC_RE = re.compile(r"^\s*(-?)\s*(\d+)\s*'\s*-?\s*(\d/\d)\s*\"?\s*$")
_FEET_ONLY_RE = re.compile(r"^\s*(-?)\s*(\d+)\s*'\s*$")
_INCHES_FRAC_RE = re.compile(r"^\s*(-?)\s*(\d+)\s+(\d/\d)\s*\"?\s*$")
_FRAC_ONLY_RE = re.compile(r"^\s*(-?)\s*(\d/\d)\s*\"?\s*$")
_INCHES_ONLY_RE = re.compile(r"^\s*(-?)\s*(\d+(?:\.\d+)?)\s*\"?\s*$")


def _parse_frac(frac_str: str) -> Optional[float]:
    return _FRACTION_MAP.get(frac_str)


def display_to_mm(text: str) -> Optional[float]:
    text = text.strip()
    if not text:
        return 0.0
    cleaned = text.rstrip("m").rstrip("M").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def display_to_inches(text: str, metric: bool = False) -> Optional[float]:
    if metric:
        mm = display_to_mm(text)
        return mm_to_inches(mm) if mm is not None else None
    text = text.strip()
    if not text:
        return 0.0
    m = _FEET_INCHES_FRAC_RE.match(text)
    if m:
        sign = -1 if m.group(1) == "-" else 1
        feet = int(m.group(2))
        whole = int(m.group(3))
        frac = _parse_frac(m.group(4))
        if frac is None:
            return None
        return sign * (feet * 12 + whole + frac)
    m = _FEET_INCHES_RE.match(text)
    if m:
        sign = -1 if m.group(1) == "-" else 1
        feet = int(m.group(2))
        inches = float(m.group(3))
        return sign * (feet * 12 + inches)
    m = _FEET_FRAC_RE.match(text)
    if m:
        sign = -1 if m.group(1) == "-" else 1
        feet = int(m.group(2))
        frac = _parse_frac(m.group(3))
        if frac is None:
            return None
        return sign * (feet * 12 + frac)
    m = _FEET_ONLY_RE.match(text)
    if m:
        sign = -1 if m.group(1) == "-" else 1
        return sign * int(m.group(2)) * 12.0
    m = _INCHES_FRAC_RE.match(text)
    if m:
        sign = -1 if m.group(1) == "-" else 1
        whole = int(m.group(2))
        frac = _parse_frac(m.group(3))
        if frac is None:
            return None
        return sign * (whole + frac)
    m = _FRAC_ONLY_RE.match(text)
    if m:
        sign = -1 if m.group(1) == "-" else 1
        frac = _parse_frac(m.group(2))
        if frac is None:
            return None
        return sign * frac
    m = _INCHES_ONLY_RE.match(text)
    if m:
        sign = -1 if m.group(1) == "-" else 1
        return sign * float(m.group(2))
    try:
        return float(text)
    except ValueError:
        return None
