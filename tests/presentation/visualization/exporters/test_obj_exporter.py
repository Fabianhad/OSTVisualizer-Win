import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.visualization.core.mesh_generator import MeshData
from ost_visualizer.presentation.visualization.exporters.obj_exporter import OBJExporter
from tests.presentation.visualization.exporters.boolean_rule_support import (
    POSITIVE_SPAN,
    SAME_TYPE_CUT_SPAN,
    SURVIVOR_SPAN,
    consumed_positive_takeoffs,
    export_obj,
    negative_only_takeoffs,
    obj_x_span,
    other_type_negative_takeoffs,
    same_type_negative_takeoffs,
)


class OBJExporterTests(unittest.TestCase):
    def test_export_resets_indices_skips_backouts_and_writes_paired_material_file(self):
        colors = Mock()
        colors.hex_to_rgb.return_value = (1, 0, 0)
        exporter = OBJExporter(Mock(), colors, Mock())
        self.addCleanup(exporter.cleanup)
        condition = Condition("c")
        positive = Takeoff("p", "c")
        negative = Takeoff("n", "c", is_negative=True)

        def boolean_result():
            return MeshData([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.obj"
            with patch.object(
                exporter,
                "_generate_mesh_for_takeoff",
                side_effect=AssertionError("writers must not rebuild meshes"),
            ) as generate:
                for _ in range(2):
                    exporter.processed_mesh_cache.update(
                        {"p": boolean_result(), "n": boolean_result()}
                    )
                    exporter._write_output(
                        str(path),
                        {"c": [(negative, condition), (positive, condition)]},
                        {"c": ("red", "Condition", "#ff0000")},
                        {"c": condition},
                        "solid",
                    )
                    self.assertEqual(
                        path.read_text(),
                        "# Created by OST Visualizer\n"
                        "mtllib model.mtl\n\n"
                        "# Condition\n"
                        "g red\n"
                        "usemtl red\n"
                        "v 0.000000 0.000000 0.000000\n"
                        "v 1.000000 0.000000 0.000000\n"
                        "v 0.000000 0.000000 -1.000000\n"
                        "f 1 3 2\n\n",
                    )
                generate.assert_not_called()
            self.assertEqual(
                path.with_suffix(".mtl").read_text(),
                "# Created by OST Visualizer\n"
                "# Display Mode: solid\n"
                "# Materials: 1\n\n"
                "newmtl red\n"
                "# Condition\n"
                "Kd 1.000000 0.000000 0.000000\n"
                "Ka 0.200000 0.200000 0.200000\n"
                "Ks 0.500000 0.500000 0.500000\n"
                "Ns 20.000000\n"
                "Ni 1.000000\n"
                "d 1.000000\n"
                "illum 2\n\n",
            )
        colors.hex_to_rgb.assert_called_with("#ff0000")


class OBJExporterBooleanRuleTests(unittest.TestCase):
    def test_negative_of_another_condition_type_does_not_cut_the_positive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.obj"
            self.assertTrue(export_obj(other_type_negative_takeoffs(), path))
            self.assertEqual(obj_x_span(path), POSITIVE_SPAN)

    def test_negative_cuts_the_positive_of_the_same_condition_type(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.obj"
            self.assertTrue(export_obj(same_type_negative_takeoffs(), path))
            self.assertEqual(obj_x_span(path), SAME_TYPE_CUT_SPAN)

    def test_fully_consumed_positive_is_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.obj"
            self.assertTrue(export_obj(consumed_positive_takeoffs(), path))
            self.assertEqual(obj_x_span(path), SURVIVOR_SPAN)

    def test_negative_only_export_fails_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.obj"
            self.assertFalse(export_obj(negative_only_takeoffs(), path))
            self.assertEqual(sorted(Path(directory).iterdir()), [])


class OBJExporterCommentTests(unittest.TestCase):
    def test_line_breaks_in_a_condition_name_are_written_as_spaces(self):
        colors = Mock()
        colors.hex_to_rgb.return_value = (1, 0, 0)
        exporter = OBJExporter(Mock(), colors, Mock())
        self.addCleanup(exporter.cleanup)
        condition = Condition("c")
        positive = Takeoff("p", "c")
        name = "Slab\r\nv 9 9 9\rf 1 2 3\nend"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.obj"
            exporter.processed_mesh_cache["p"] = MeshData(
                [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)]
            )
            exporter._write_output(
                str(path),
                {"c": [(positive, condition)]},
                {"c": ("red", name, "#ff0000")},
                {"c": condition},
                "solid",
            )
            obj_lines = path.read_text().splitlines()
            mtl_lines = path.with_suffix(".mtl").read_text().splitlines()
        comment = "# Slab  v 9 9 9 f 1 2 3 end"
        self.assertEqual(obj_lines[3], comment)
        self.assertEqual(mtl_lines[5], comment)
        self.assertEqual(
            [line for line in obj_lines if line.startswith("v ")],
            [
                "v 0.000000 0.000000 0.000000",
                "v 1.000000 0.000000 0.000000",
                "v 0.000000 0.000000 -1.000000",
            ],
        )
        self.assertEqual(
            [line for line in obj_lines if line.startswith("f ")], ["f 1 3 2"]
        )
        self.assertEqual(
            [line for line in mtl_lines if line.startswith("Kd ")],
            ["Kd 1.000000 0.000000 0.000000"],
        )
