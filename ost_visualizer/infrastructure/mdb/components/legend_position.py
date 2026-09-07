import math
import xml.etree.ElementTree as ET
from .serialization import POSITION_TEXT_ENCODING


def rescale_legend_position(value: bytes | bytearray | str, factor: float) -> bytes:
    text = (
        bytes(value).decode(POSITION_TEXT_ENCODING)
        if isinstance(value, (bytes, bytearray))
        else value
    )
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
    root = ET.fromstring(text, parser=parser)
    if root.tag != "Legends":
        raise ValueError("Legend Position requires a Legends XML root")
    for element in root.iter():
        if element.tag not in ("Legends", "Legend"):
            continue
        for coordinate in ("dX", "dY"):
            if coordinate not in element.attrib:
                continue
            scaled = float(element.attrib[coordinate]) * factor
            if not math.isfinite(scaled):
                raise ValueError("Legend Position coordinates must be finite")
            element.set(coordinate, f"{scaled:.3f}".rstrip("0").rstrip("."))
    return ET.tostring(root, encoding="unicode").encode(POSITION_TEXT_ENCODING)
