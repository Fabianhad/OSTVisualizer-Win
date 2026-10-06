import re

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
