from dataclasses import dataclass


@dataclass
class ElevationParts:
    base_name: str = ""
    type: int = 0
    value: str = ""


def parse_elevation(name: str) -> ElevationParts:
    parts = ElevationParts()
    if not name:
        return parts
    pos_t = name.rfind(" @T")
    pos_b = name.rfind(" @B")
    pos = -1
    marker_len = 3
    if pos_t != -1 and pos_b != -1:
        pos = max(pos_t, pos_b)
        parts.type = 1 if pos == pos_b else 0
    elif pos_t != -1:
        pos = pos_t
        parts.type = 0
    elif pos_b != -1:
        pos = pos_b
        parts.type = 1
    if pos == -1:
        pos_at = name.rfind(" @ ")
        if pos_at == -1:
            pos_at = name.rfind(" @")
        if pos_at != -1:
            pos = pos_at
            parts.type = 1
            marker_len = 2
    if pos == -1:
        parts.base_name = name
        parts.value = ""
        return parts
    parts.base_name = name[:pos]
    val_start = pos + marker_len
    if val_start < len(name) and name[val_start] == " ":
        val_start += 1
    parts.value = name[val_start:] if val_start < len(name) else ""
    return parts


def reassemble_elevation(base_name: str, elev_type: int, value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        return base_name
    tag = " @T " if elev_type == 0 else " @B "
    return base_name + tag + trimmed
