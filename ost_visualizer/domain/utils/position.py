from typing import List
from .text_cleanup import strip_xml_newline_entities


def parse_position(position_str: str) -> List[float]:
    if not position_str:
        return []
    clean_str = strip_xml_newline_entities(position_str).strip()
    if not clean_str:
        return []
    parts = [p.strip() for p in clean_str.split(";") if p.strip()]
    position: List[float] = []
    for p in parts:
        try:
            position.append(float(p))
        except ValueError:
            return []
    return position
