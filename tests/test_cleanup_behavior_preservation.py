import unittest
from unittest.mock import patch
from ost_visualizer.application.utils.quantity_display import (
    format_quantity_number,
    format_quantity_with_uom,
)
from ost_visualizer.domain.services.dimension_format_service import (
    MM_PER_INCH,
    display_to_inches,
    display_to_mm,
    inches_to_mm,
    inches_to_display,
    mm_to_inches,
    mm_to_display,
)
from ost_visualizer.domain.services.uom_service import (
    UOM_CUBIC_YARDS,
    UOM_LINEAR_FEET,
    UOM_M,
    UOM_M2,
    UOM_M3,
    UOM_MM,
    UOM_MM2,
    UOM_MM3,
    convert_to_uom,
)
from ost_visualizer.infrastructure.mdb.components.settings_reader import (
    _clean_optional_text,
)
from ost_visualizer.infrastructure.visualization_provider import (
    _ExportStrategyAdapter,
    _HtmlExportStrategyAdapter,
)
from ost_visualizer.presentation.visualization.core import ost_geometry
from ost_visualizer.presentation.visualization.core.boolean_operations import (
    boolean_union,
)
from ost_visualizer.presentation.visualization.core.mesh_generator import MeshData


class CleanupBehaviorPreservationTests(unittest.TestCase):
    def test_quantity_display_facade_replacement_preserves_exact_formatting(self):
        cases = (
            (0.0, UOM_LINEAR_FEET, ""),
            (12.4, UOM_LINEAR_FEET, "12"),
            (12.6, UOM_LINEAR_FEET, "13"),
            (-12.6, UOM_LINEAR_FEET, "-13"),
            (12.345, UOM_M, "12.35"),
            (-12.345, UOM_M, "-12.35"),
            (100.0, UOM_M, "100"),
            (1234.0, UOM_CUBIC_YARDS, "1,234"),
        )
        for value, uom, expected in cases:
            with self.subTest(value=value, uom=uom):
                self.assertEqual(format_quantity_number(value, uom), expected)
        labels = {UOM_LINEAR_FEET: "LF", UOM_M: "M"}
        label = labels.get
        self.assertEqual(format_quantity_with_uom(0.0, UOM_LINEAR_FEET, label), "0 LF")
        self.assertEqual(format_quantity_with_uom(12.345, UOM_M, label), "12.35 M")
        self.assertEqual(format_quantity_with_uom(-12.6, 999, label), "-13")

    def test_optional_text_consolidation_preserves_all_old_sentinel_behavior(self):
        unchanged_values = (
            "",
            "   ",
            "null",
            " NULL ",
            "already clean",
            "embedded\x00null",
            b"bytes",
            0,
            42,
        )
        self.assertEqual(_clean_optional_text(None), "")
        self.assertEqual(_clean_optional_text("NULL"), "")
        for value in unchanged_values:
            with self.subTest(value=value):
                self.assertIs(_clean_optional_text(value), value)

    def test_export_filename_consolidation_preserves_html_and_mesh_policy(self):
        html = _HtmlExportStrategyAdapter(object())
        obj = _ExportStrategyAdapter("OBJ", "obj", object, None, None, None)
        cases = (
            ("Bid", ["Page"], "Bid - Page"),
            ("Bid", ["One", "Two"], "Bid - One + Two"),
            ("Bid", ["One", "Two", "Three"], "Bid - One + Two + 1 more"),
            ("Bid", ["A/B:*?<>|"], "Bid - A_B______"),
            ("Bid/Phase:*?<>|", ["Page"], "Bid_Phase______ - Page"),
            ("", ["Page"], " - Page"),
            ("Bid", [""], "Bid - "),
            ("Bíd", ["Páge"], "Bíd - Páge"),
            ("Bid", ["Same", "Same"], "Bid - Same + Same"),
        )
        for bid_name, page_names, stem in cases:
            with self.subTest(bid_name=bid_name, page_names=page_names):
                self.assertEqual(
                    html.prepare_filename(bid_name, page_names), stem + ".html"
                )
                self.assertEqual(
                    obj.prepare_filename(bid_name, page_names), stem + ".obj"
                )
        self.assertEqual(html.get_dialog_title(1), "Export page as HTML")
        self.assertEqual(obj.get_dialog_title(3), "Export 3 pages as OBJ")

    def test_export_filename_consolidation_preserves_long_name_fallbacks(self):
        html = _HtmlExportStrategyAdapter(object())
        obj = _ExportStrategyAdapter("OBJ", "obj", object, None, None, None)
        long_bid = "B" * 300
        self.assertEqual(len(html.prepare_filename(long_bid, ["Page"])), 255)
        self.assertEqual(len(obj.prepare_filename(long_bid, ["Page"])), 255)
        long_page = "P" * 300
        html_filename = html.prepare_filename("Bid", [long_page])
        obj_filename = obj.prepare_filename("Bid", [long_page])
        self.assertEqual(len(html_filename), 255)
        self.assertEqual(len(obj_filename), 255)
        self.assertTrue(html_filename.endswith("....html"))
        self.assertTrue(obj_filename.endswith("....obj"))
        self.assertEqual(
            html.prepare_filename("Bid", [long_page, long_page]),
            "Export_2_pages.html",
        )

    def test_shared_unit_constant_preserves_scalar_conversion_precision(self):
        self.assertEqual(MM_PER_INCH, 25.4)
        for inches in (-1234.5, -1.0, 0.0, 1.0, 1234.5):
            with self.subTest(inches=inches):
                millimetres = inches * 25.4
                self.assertEqual(inches_to_mm(inches), millimetres)
                self.assertEqual(mm_to_inches(millimetres), inches)
                self.assertIsInstance(inches_to_mm(int(inches)), float)
        expected = {
            UOM_MM: 25.4,
            UOM_M: 0.0254,
            UOM_MM2: 25.4**2,
            UOM_M2: 25.4**2 / 1_000_000.0,
            UOM_MM3: 25.4**3,
            UOM_M3: 25.4**3 / 1_000_000_000.0,
        }
        for uom, converted in expected.items():
            with self.subTest(uom=uom):
                self.assertAlmostEqual(convert_to_uom(1.0, uom), converted)
                self.assertAlmostEqual(convert_to_uom(-1.0, uom), -converted)

    def test_dimension_text_rejects_non_finite_values_before_formatting(self):
        for text in ("nan", "inf", "-inf", "Infinity", "-Infinity"):
            with self.subTest(text=text):
                self.assertIsNone(display_to_inches(text))
                self.assertIsNone(display_to_inches(text, metric=True))
                self.assertIsNone(display_to_mm(text))
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                self.assertEqual(inches_to_display(value), "")
                self.assertEqual(inches_to_display(value, metric=True), "")
                self.assertEqual(mm_to_display(value), "")
        self.assertIsNone(display_to_inches(f"{'9' * 5000}'"))

    def test_remaining_boolean_wrapper_preserves_face_orientation_and_metadata(self):
        first = MeshData(
            vertices=[(0.0, 0.0, 0.0)],
            faces=[(0, 0, 0)],
            metadata={"source": "first"},
        )
        second = MeshData(
            vertices=[(1.0, 1.0, 1.0)],
            faces=[(0, 0, 0)],
            metadata={"source": "second"},
        )
        native_result = {
            "vertices": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            "faces": [[0, 1, 2]],
            "edges": [[0, 1]],
            "metadata": {"native": True},
        }
        with patch(
            "ost_visualizer.presentation.visualization.core.boolean_operations.ost_geometry.boolean_union",
            return_value=native_result,
        ):
            result = boolean_union(first, second, {"source": "preserved"})
        self.assertIsNotNone(result)
        self.assertEqual(result.faces, [[0, 2, 1]])
        self.assertEqual(result.edges, [[0, 1]])
        self.assertEqual(result.metadata, {"source": "preserved", "native": True})

    def test_deleted_python_boolean_wrappers_leave_native_boundary_callable(self):
        mesh = MeshData(
            vertices=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
            ],
            faces=[(0, 1, 2)],
            metadata={},
        )
        self.assertTrue(ost_geometry.is_valid(mesh))
        featured = ost_geometry.extract_feature_edges(mesh, 0.1)
        self.assertEqual(featured["vertices"], mesh.vertices)
        self.assertEqual(featured["faces"], mesh.faces)
        self.assertEqual(
            {tuple(edge) for edge in featured["edges"]},
            {(0, 1), (0, 2), (1, 2)},
        )


if __name__ == "__main__":
    unittest.main()
