import base64
import struct
import zlib
from PySide6.QtGui import QImage
from ...application.dtos.ai_takeoff_dtos import CropPlan
from ..visualization.utils.image_bands import convert_to_format

PNG_COMPRESSION_LEVEL = 6
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_BIT_DEPTH = 8
_COLOR_TYPE_RGBA = 6


def render_crop_png(pdf_source, plan: CropPlan) -> dict:
    image = pdf_source.render_frame(
        plan.file_path, plan.page_index, plan.scale, plan.frame_pts
    )
    result = {
        "page_uid": plan.page_uid,
        "frame_pts": list(plan.frame_pts),
        "px_to_page_pts": list(plan.px_to_page_pts),
        "page_pts_to_ost": (
            None if plan.page_pts_to_ost is None else list(plan.page_pts_to_ost)
        ),
    }
    if image is None or image.isNull():
        return {**result, "image": None, "render_status": "unavailable"}
    png = encode_png(image)
    return {
        **result,
        "image": {
            "png_base64": base64.b64encode(png).decode("ascii"),
            "width_px": image.width(),
            "height_px": image.height(),
        },
        "render_status": "ok",
    }


def encode_png(image: QImage) -> bytes:
    if image.isNull():
        raise ValueError("Cannot encode an empty image")
    rgba = convert_to_format(image, QImage.Format.Format_RGBA8888)
    width = rgba.width()
    height = rgba.height()
    stride = rgba.bytesPerLine()
    row_bytes = width * 4
    pixels = rgba.constBits()
    rows = b"".join(
        b"\x00" + bytes(pixels[row * stride : row * stride + row_bytes])
        for row in range(height)
    )
    header = struct.pack(
        ">IIBBBBB", width, height, _BIT_DEPTH, _COLOR_TYPE_RGBA, 0, 0, 0
    )
    return b"".join(
        (
            _PNG_SIGNATURE,
            _chunk(b"IHDR", header),
            _chunk(b"IDAT", zlib.compress(rows, PNG_COMPRESSION_LEVEL)),
            _chunk(b"IEND", b""),
        )
    )


def _chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)
