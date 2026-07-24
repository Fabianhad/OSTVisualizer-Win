import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from xml.etree.ElementTree import Element
from PySide6.QtCore import QPointF
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
from ost_visualizer.presentation.visualization.pdf.renderers.page_renderer import (
    PageRenderer,
)
from ost_visualizer.presentation.visualization.pdf.services.composite_renderer import (
    CompositeRenderer,
)

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


class OverlayCoordinateContractTests(unittest.TestCase):
    def test_overlay_units_follow_persisted_page_calibration(self):
        self.assertEqual(overlay_units_per_sheet_inch(0.1875, 12.0), 64.0)
        self.assertEqual(overlay_units_per_sheet_inch(0.125, 12.0), 96.0)
        self.assertEqual(overlay_units_per_sheet_inch(0.3, 15.0), 50.0)
        self.assertEqual(
            full_page_overlay_rect(42.0, 30.0, 0.1875, 12.0),
            "0.000000,0.000000,2688.000000,1920.000000",
        )
        self.assertEqual(
            full_page_overlay_rect(42.0, 30.0, 0.125, 12.0),
            "0.000000,0.000000,4032.000000,2880.000000",
        )

    def test_mdb_reader_loads_overlay_rect_directly(self):
        connection = _RowsConnection([_page_row(CALIBRATED_64_RECT)])
        pages = BidDataReaderMixin()._parse_bid_pages_for_bid(
            connection,
            "57895",
            {},
            _AllPageColumnsSchema(),
        )
        self.assertEqual(pages["58227"].overlay_rect, CALIBRATED_64_RECT)
        self.assertTrue(connection.statements)
        self.assertTrue(
            all(
                statement.lstrip().upper().startswith("SELECT")
                for statement in connection.statements
            )
        )

    def test_mdb_reader_exposes_malformed_rect_as_no_geometry(self):
        row = _page_row(CALIBRATED_64_RECT)
        row.OverlayRect = "0,0,not-a-width,1920"
        connection = _RowsConnection([row])
        reader = BidDataReaderMixin()
        reader.logger = _RecordingLogger()
        pages = reader._parse_bid_pages_for_bid(
            connection,
            "57895",
            {},
            _AllPageColumnsSchema(),
        )
        self.assertEqual(pages["58227"].overlay_rect, EMPTY_OVERLAY_RECT)
        self.assertEqual(len(reader.logger.warnings), 1)

    def test_mdb_reader_accepts_native_empty_rect_marker_without_warning(self):
        row = _page_row(EMPTY_OVERLAY_RECT)
        row.OverlayRect = "*"
        connection = _RowsConnection([row])
        reader = BidDataReaderMixin()
        reader.logger = _RecordingLogger()
        pages = reader._parse_bid_pages_for_bid(
            connection,
            "57895",
            {},
            _AllPageColumnsSchema(),
        )
        self.assertEqual(pages["58227"].overlay_rect, EMPTY_OVERLAY_RECT)
        self.assertEqual(reader.logger.warnings, [])

    def test_persisted_rect_converts_once_to_page_points(self):
        rect = _page(CALIBRATED_64_RECT).overlay_rect_page_points()
        self.assertAlmostEqual(rect[0], -1.24103925)
        self.assertAlmostEqual(rect[1], 0.0)
        self.assertAlmostEqual(rect[2], 3021.931600875)
        self.assertAlmostEqual(rect[3], 2159.4090285)

    def test_current_bid_uses_its_96_unit_page_calibration(self):
        rect = _page(
            CALIBRATED_96_RECT,
            scale_factor1=0.125,
            scale_factor2=12.0,
        ).overlay_rect_page_points()
        self.assertAlmostEqual(rect[0], 0.0)
        self.assertAlmostEqual(rect[1], 0.0)
        self.assertAlmostEqual(rect[2], 3023.5276305)
        self.assertAlmostEqual(rect[3], 2159.662593)

    def test_different_page_dimensions_preserve_full_page_size(self):
        rect = parse_overlay_rect_storage(
            full_page_overlay_rect(11.0, 8.5, 0.125, 12.0)
        )
        page = _page(
            rect,
            width_pts=792.0,
            height_pts=612.0,
            scale_factor1=0.125,
            scale_factor2=12.0,
        )
        self.assertEqual(page.overlay_rect_page_points(), (0.0, 0.0, 792.0, 612.0))

    def test_arbitrary_calibration_uses_the_same_full_page_path(self):
        rect = parse_overlay_rect_storage(full_page_overlay_rect(10.0, 5.0, 0.3, 15.0))
        page = _page(
            rect,
            width_pts=720.0,
            height_pts=360.0,
            scale_factor1=0.3,
            scale_factor2=15.0,
        )
        self.assertEqual(page.overlay_rect_page_points(), (0.0, 0.0, 720.0, 360.0))

    def test_page_rotation_uses_effective_destination_dimensions_once(self):
        page = _page(
            (0.0, 0.0, 1920.0, 2688.0),
            width_pts=3024.0,
            height_pts=2160.0,
            rotation=90,
        )
        self.assertEqual(page.effective_width_pts, 2160.0)
        self.assertEqual(page.effective_height_pts, 3024.0)
        self.assertEqual(page.overlay_rect_page_points(), (0.0, 0.0, 2160.0, 3024.0))

    def test_pdf_boxes_and_intrinsic_rotation_are_normalized_upstream(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "boxes.pdf"
            _write_box_pdf(pdf_path)
            renderer = PageRenderer()
            try:
                info = renderer.get_page_info(str(pdf_path), 0)
            finally:
                renderer.close()
        self.assertEqual(info["media_width_pts"], 80.0)
        self.assertEqual(info["media_height_pts"], 180.0)
        self.assertEqual(info["crop_width_pts"], 180.0)
        self.assertEqual(info["crop_height_pts"], 80.0)
        self.assertEqual(info["intrinsic_rotation"], 90)
        coordinate_ratio = overlay_units_per_sheet_inch(0.1875, 12.0)
        rect = (
            0.0,
            0.0,
            info["pdf_width"] / 72.0 * coordinate_ratio,
            info["pdf_height"] / 72.0 * coordinate_ratio,
        )
        page = _page(
            rect,
            width_pts=info["pdf_width"],
            height_pts=info["pdf_height"],
        )
        self.assertEqual(page.overlay_rect_page_points(), (0.0, 0.0, 80.0, 180.0))

    def test_nonuniform_scale_and_negative_offsets_are_preserved(self):
        page = _page((-64.0, -32.0, 1344.0, 1280.0))
        self.assertEqual(
            page.overlay_rect_page_points(),
            (-72.0, -36.0, 1512.0, 1440.0),
        )

    def test_missing_and_zero_size_rectangles_produce_no_geometry(self):
        missing = _page(())
        zero_width = _page((0.0, 0.0, 0.0, 1920.0))
        zero_height = _page((0.0, 0.0, 2688.0, 0.0))
        renderer = CompositeRenderer.__new__(CompositeRenderer)
        self.assertEqual(missing.overlay_rect_page_points(), (0.0, 0.0, 0.0, 0.0))
        self.assertIsNone(
            renderer._build_overlay_frame_context(
                zero_width, 100.0, 100.0, 1.0, 0.0, 0.0, 100.0, 100.0
            )
        )
        self.assertIsNone(
            renderer._build_overlay_frame_context(
                zero_height, 100.0, 100.0, 1.0, 0.0, 0.0, 100.0, 100.0
            )
        )

    def test_numeric_and_string_zero_parse_identically(self):
        self.assertEqual(
            parse_overlay_rect_storage("0,0,2688,1920"),
            (0.0, 0.0, 2688.0, 1920.0),
        )
        self.assertEqual(
            parse_overlay_rect_storage("0.0,0.0,0.0,0.0"),
            EMPTY_OVERLAY_RECT,
        )

    def test_absent_storage_values_produce_no_geometry(self):
        for stored_rect in (None, "", "  ", "*", " * "):
            with self.subTest(stored_rect=stored_rect):
                self.assertEqual(
                    parse_overlay_rect_storage(stored_rect),
                    EMPTY_OVERLAY_RECT,
                )

    def test_invalid_calibration_produces_no_geometry_or_full_page_rect(self):
        for scale_factor1, scale_factor2 in (
            (0.0, 12.0),
            (0.125, 0.0),
            (-0.125, 12.0),
            (0.125, -12.0),
            (float("nan"), 12.0),
            (0.125, float("inf")),
            ("invalid", 12.0),
        ):
            with self.subTest(
                scale_factor1=scale_factor1,
                scale_factor2=scale_factor2,
            ):
                self.assertIsNone(
                    overlay_units_per_sheet_inch(scale_factor1, scale_factor2)
                )
                page = _page(
                    CALIBRATED_64_RECT,
                    scale_factor1=scale_factor1,
                    scale_factor2=scale_factor2,
                )
                self.assertEqual(
                    page.overlay_rect_page_points(),
                    EMPTY_OVERLAY_RECT,
                )
                with self.assertRaises(ValueError):
                    full_page_overlay_rect(
                        42.0,
                        30.0,
                        scale_factor1,
                        scale_factor2,
                    )

    def test_malformed_storage_rect_is_rejected_without_inference(self):
        for stored_rect in (
            "0,0,2688",
            "0,0,2688,1920,extra",
            "0,0,invalid,1920",
            "0,0,-1,1920",
            "0,0,nan,1920",
        ):
            with self.subTest(stored_rect=stored_rect):
                with self.assertRaises(ValueError):
                    parse_overlay_rect_storage(stored_rect)

    def test_transform_is_forward_translate_rotate_then_scale(self):
        renderer = CompositeRenderer.__new__(CompositeRenderer)
        transform = renderer._build_transform(
            10.0,
            -5.0,
            math.pi / 2.0,
            2.0,
            3.0,
        )
        mapped_origin = transform.map(QPointF(0.0, 0.0))
        mapped_x = transform.map(QPointF(1.0, 0.0))
        mapped_y = transform.map(QPointF(0.0, 1.0))
        self.assertAlmostEqual(mapped_origin.x(), 10.0)
        self.assertAlmostEqual(mapped_origin.y(), -5.0)
        self.assertAlmostEqual(mapped_x.x(), 10.0)
        self.assertAlmostEqual(mapped_x.y(), -3.0)
        self.assertAlmostEqual(mapped_y.x(), 7.0)
        self.assertAlmostEqual(mapped_y.y(), -5.0)

    def test_rotation_and_deskew_are_combined_once(self):
        page = _page(
            (64.0, 32.0, 640.0, 320.0),
            overlay_rotation=math.pi / 4.0,
            deskew_rotation_overlay=math.pi / 4.0,
        )
        renderer = CompositeRenderer.__new__(CompositeRenderer)
        context = renderer._build_overlay_frame_context(
            page,
            640.0,
            320.0,
            1.0,
            0.0,
            0.0,
            3024.0,
            2160.0,
        )
        self.assertIsNotNone(context)
        mapped = context["transform"].map(QPointF(1.0, 0.0))
        origin = context["transform"].map(QPointF(0.0, 0.0))
        self.assertAlmostEqual(mapped.x(), origin.x())
        self.assertGreater(mapped.y(), origin.y())

    def test_overlay_move_delta_is_saved_in_calibrated_units(self):
        page = _page(CALIBRATED_64_RECT)
        delta = page.canvas_point_to_overlay_rect_units(
            72.0,
            36.0,
            3024.0,
            2160.0,
        )
        self.assertEqual(delta, (64.0, 32.0))

    def test_overlay_move_uses_current_page_calibration(self):
        page = _page(
            CALIBRATED_96_RECT,
            scale_factor1=0.125,
            scale_factor2=12.0,
        )
        delta = page.canvas_point_to_overlay_rect_units(
            72.0,
            36.0,
            3024.0,
            2160.0,
        )
        self.assertEqual(delta, (96.0, 48.0))

    def test_cached_and_uncached_paths_share_one_transform_identity(self):
        renderer = CompositeRenderer.__new__(CompositeRenderer)
        page_at_64_units = _page(CALIBRATED_64_RECT)
        page_at_96_units = _page(
            CALIBRATED_64_RECT,
            scale_factor1=0.125,
            scale_factor2=12.0,
        )
        key = renderer._build_cache_key(page_at_64_units, None, 1.0, 0)
        self.assertEqual(
            key,
            renderer._build_cache_key(page_at_64_units, None, 1.0, 0),
        )
        self.assertNotEqual(
            key,
            renderer._build_cache_key(page_at_96_units, None, 1.0, 0),
        )

    def test_ost_export_preserves_raw_overlay_columns(self):
        exporter = OstExporter.__new__(OstExporter)
        bid_element = Element("Bid")
        raw_rect = "-1.103146,0,2686.161423,1919.474692"
        exporter._build_pages_section(
            bid_element,
            {
                "BidPages": [
                    {
                        "UID": "58227",
                        "BidUID": "57895",
                        "Sequence": "1",
                        "OverlayRect": raw_rect,
                        "OverlayOffsetX": "-1.103146",
                        "OverlayOffsetY": "0",
                    }
                ]
            },
            {},
        )
        page_element = bid_element.find("./BidPages/BidPage")
        self.assertIsNotNone(page_element)
        self.assertEqual(page_element.get("OverlayRect"), raw_rect)
        self.assertEqual(page_element.get("OverlayOffsetX"), "-1.103146")
        self.assertEqual(page_element.get("OverlayOffsetY"), "0")


if __name__ == "__main__":
    unittest.main()
