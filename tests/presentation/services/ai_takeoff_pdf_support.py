from pathlib import Path


def write_takeoff_pdf(
    path: Path,
    width: float = 612.0,
    height: float = 792.0,
    lines=(),
    texts=(),
    rectangles=(),
    page_boxes: str = "",
) -> Path:
    commands = []
    for red, green, blue, x, y, w, h in rectangles:
        commands.append(f"{red} {green} {blue} rg {x} {y} {w} {h} re f")
    for x1, y1, x2, y2 in lines:
        commands.append(f"0 0 0 RG 1 w {x1} {y1} m {x2} {y2} l S")
    for x, y, size, text in texts:
        commands.append(f"BT /F1 {size} Tf {x} {y} Td ({text}) Tj ET")
    return write_content_pdf(
        path,
        "\n".join(commands) + "\n",
        width=width,
        height=height,
        page_boxes=page_boxes,
    )


def _stream(dictionary: str, content: str) -> bytes:
    data = content.encode("latin-1")
    return (
        f"<< {dictionary} /Length {len(data)} >>\nstream\n".encode("latin-1")
        + data
        + b"endstream"
    )


def write_content_pdf(
    path: Path,
    content: str,
    width: float = 612.0,
    height: float = 792.0,
    page_boxes: str = "",
    forms=(),
) -> Path:
    boxes = page_boxes or f"/MediaBox [0 0 {width} {height}]"
    first_form = 6
    form_names = " ".join(
        f"/{name} {first_form + index} 0 R"
        for index, (name, _m, _c) in enumerate(forms)
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            f"<< /Type /Page /Parent 2 0 R {boxes} "
            f"/Resources << /Font << /F1 5 0 R >> /XObject << {form_names} >> >> "
            "/Contents 4 0 R >>"
        ).encode("latin-1"),
        _stream("", content),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for name, matrix, form_content in forms:
        objects.append(
            _stream(
                "/Type /XObject /Subtype /Form /BBox [-10000 -10000 10000 10000] "
                f"/Matrix [{matrix}] /Resources << /XObject << {form_names} >> >>",
                form_content,
            )
        )
    output = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_offset = len(output)
    output += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        output += f"{offset:010d} 00000 n \n".encode()
    output += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()
    path = Path(path)
    path.write_bytes(bytes(output))
    return path
