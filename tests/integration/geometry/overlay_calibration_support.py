import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from xml.etree.ElementTree import Element
from ost_visualizer.domain.entities.overlay import overlay_units_per_sheet_inch
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.infrastructure.mdb.components.bid_data_reader import (
    BidDataReaderMixin,
)
from ost_visualizer.infrastructure.mdb.components.overlay_rect import (
    EMPTY_OVERLAY_RECT,
    full_page_overlay_rect,
    parse_overlay_rect_storage,
)
from ost_visualizer.infrastructure.mdb.exporters.ost_exporter import OstExporter
from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache
from ost_visualizer.presentation.visualization.pdf.renderers.page_renderer import (
    PageRenderer,
)
from ost_visualizer.presentation.visualization.pdf.services.composite_renderer import (
    CompositeRenderer,
)
from PySide6.QtCore import QPointF

CALIBRATED_64_RECT = (-1.103146, 0.0, 2686.161423, 1919.474692)
CALIBRATED_96_RECT = (0.0, 0.0, 4031.370174, 2879.550124)


def _write_box_pdf(path: Path):
    objects = [
        "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            "3 0 obj\n"
            "<< /Type /Page /Parent 2 0 R "
            "/MediaBox [10 20 210 120] /CropBox [20 30 200 110] "
            "/Rotate 90 /Contents 4 0 R >>\n"
            "endobj\n"
        ),
        "4 0 obj\n<< /Length 0 >>\nstream\nendstream\nendobj\n",
    ]
    content = b"%PDF-1.4\n"
    offsets = []
    for obj in objects:
        offsets.append(len(content))
        content += obj.encode("ascii")
    xref_offset = len(content)
    content += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    content += b"0000000000 65535 f \n"
    for offset in offsets:
        content += f"{offset:010d} 00000 n \n".encode("ascii")
    content += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")
    path.write_bytes(content)


def _page(
    overlay_rect,
    *,
    width_pts=3024.0,
    height_pts=2160.0,
    rotation=0,
    overlay_rotation=0.0,
    deskew_rotation_overlay=0.0,
    scale_factor1=0.1875,
    scale_factor2=12.0,
):
    return Page(
        uid="page",
        name="S201S.pdf",
        image_path="base.pdf",
        overlay_image_path="overlay.pdf",
        width_pts=width_pts,
        height_pts=height_pts,
        scale_factor1=scale_factor1,
        scale_factor2=scale_factor2,
        rotation=rotation,
        overlay_rect=overlay_rect,
        overlay_rotation=overlay_rotation,
        deskew_rotation_overlay=deskew_rotation_overlay,
        image_show_mode=2,
    )


class _RowsCursor:
    def __init__(self, connection):
        self._connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, *_args):
        self._connection.statements.append(statement)
        return self

    def fetchall(self):
        return list(self._connection.rows)


class _RowsConnection:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    def cursor(self):
        return _RowsCursor(self)


class _AllPageColumnsSchema:
    @staticmethod
    def order_by_existing(_table, columns, _fallback):
        return ", ".join(f"[{column}]" for column in columns)

    @staticmethod
    def optional_column(_table, column, _fallback):
        return f"[{column}]"


class _RecordingLogger:
    def __init__(self):
        self.warnings = []

    def warning(self, message, *args):
        self.warnings.append(message % args)


def _page_row(overlay_rect):
    return SimpleNamespace(
        UID=58227,
        BidPageFolderUID=None,
        Name="Copy of S201S.pdf",
        SheetNo="S201S",
        Sequence=1,
        ImagePath="base.pdf",
        Width=42.0,
        Height=30.0,
        ScaleFactor1=0.1875,
        ScaleFactor2=12.0,
        Rotation=0,
        FlipX=False,
        FlipY=False,
        Index1=1,
        Show=2,
        OverlayImagePath="overlay.pdf",
        OverlayOffsetX=overlay_rect[0],
        OverlayOffsetY=overlay_rect[1],
        OverlayRotation=0.0,
        OverlayRect=",".join(f"{value:.6f}" for value in overlay_rect),
        OverlayResized=None,
        DeskewRotationOverlay=0.0,
        ZoomFac=0.0,
        CurrentX=0.0,
        CurrentY=0.0,
        Invert=False,
        Bitonal=False,
    )
