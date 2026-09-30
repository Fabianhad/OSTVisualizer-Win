import unittest
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.domain.services.uom_service import calculate_polygon_area
from ost_visualizer.presentation.visualization.meshing.mesh_factory import MeshFactory
from tests.presentation.visualization.meshing.page_flip_support import (
    PAGE_HEIGHT_POINTS as _page_flip_support_PAGE_HEIGHT_POINTS,
    PAGE_WIDTH_POINTS as _page_flip_support_PAGE_WIDTH_POINTS,
    _area_mesh as _page_flip_support__area_mesh,
    _page_info as _page_flip_support__page_info,
    _xy_bounds as _page_flip_support__xy_bounds,
)
from ost_visualizer.domain.entities import shape as shapes
from tests.presentation.visualization.renderers.threejs.export_support import (
    _IdentityMeshCoordinateSystem as _export_support__IdentityMeshCoordinateSystem,
)


class MeshFactoryPageFlipTests(unittest.TestCase):
    def test_horizontal_flip_mirrors_asymmetric_area_mesh_and_toggles_off(self):
        baseline_takeoff, baseline_position, baseline = _page_flip_support__area_mesh()
        flipped_takeoff, flipped_position, flipped = _page_flip_support__area_mesh(
            flip_x=True
        )
        toggled_off_takeoff, toggled_off_position, toggled_off = (
            _page_flip_support__area_mesh()
        )
        self.assertEqual(
            _page_flip_support__xy_bounds(baseline), (-2.5, -1.0, 1.0, 2.0)
        )
        self.assertEqual(_page_flip_support__xy_bounds(flipped), (-9.0, -7.5, 1.0, 2.0))
        self.assertEqual(
            _page_flip_support__xy_bounds(toggled_off),
            _page_flip_support__xy_bounds(baseline),
        )
        self.assertEqual(baseline_takeoff.position, baseline_position)
        self.assertEqual(flipped_takeoff.position, flipped_position)
        self.assertEqual(toggled_off_takeoff.position, toggled_off_position)

    def test_vertical_and_combined_flips_mirror_asymmetric_area_mesh(self):
        baseline_takeoff, baseline_position, baseline = _page_flip_support__area_mesh()
        vertical_takeoff, vertical_position, vertical = _page_flip_support__area_mesh(
            flip_y=True
        )
        combined_takeoff, combined_position, combined = _page_flip_support__area_mesh(
            flip_x=True, flip_y=True
        )
        self.assertEqual(
            _page_flip_support__xy_bounds(baseline), (-2.5, -1.0, 1.0, 2.0)
        )
        self.assertEqual(
            _page_flip_support__xy_bounds(vertical), (-2.5, -1.0, 3.0, 4.0)
        )
        self.assertEqual(
            _page_flip_support__xy_bounds(combined), (-9.0, -7.5, 3.0, 4.0)
        )
        self.assertEqual(vertical_takeoff.position, vertical_position)
        self.assertEqual(combined_takeoff.position, combined_position)
        self.assertEqual(
            calculate_polygon_area(
                list(zip(baseline_position[::2], baseline_position[1::2]))
            ),
            calculate_polygon_area(
                list(zip(vertical_position[::2], vertical_position[1::2]))
            ),
        )
        self.assertEqual(baseline_takeoff.position, baseline_position)


class ThreejsExportLayerTests(unittest.TestCase):
    def test_square_count_mesh_uses_same_display_scaled_footprint_as_2d(self):
        condition = Condition(
            uid="square-count",
            condition_type=Condition.TYPE_COUNT,
            shape=shapes.SQUARE,
            width=20.0,
            depth=12.0,
            height=10.0,
            display_size=175.0,
        )
        takeoff = Takeoff(
            uid="count-1",
            condition_uid=condition.uid,
            position=[10.0, 20.0],
        )
        mesh = MeshFactory(
            _export_support__IdentityMeshCoordinateSystem()
        ).create_mesh_for_takeoff(
            takeoff,
            condition,
        )
        self.assertIsNotNone(mesh)
        x_values = [vertex[0] for vertex in mesh.vertices]
        y_values = [vertex[1] for vertex in mesh.vertices]
        self.assertAlmostEqual(max(x_values) - min(x_values), 35.0)
        self.assertAlmostEqual(max(y_values) - min(y_values), 35.0)
