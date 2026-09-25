import unittest
from ost_visualizer.domain.entities import shape as shapes
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.domain.services.uom_service import calculate_polygon_area
from ost_visualizer.infrastructure.visualization_provider import _MeshGeneratorAdapter
from ost_visualizer.presentation.visualization.factories.coordinate_transformer_factory import (
    CoordinateTransformerFactory,
)
from ost_visualizer.presentation.visualization.meshing.mesh_factory import MeshFactory

PAGE_WIDTH_POINTS = 720.0
PAGE_HEIGHT_POINTS = 360.0


def _page_info(*, flip_x: bool = False, flip_y: bool = False) -> dict:
    return {
        "scale_factor1": 1.0,
        "scale_factor2": 1.0,
        "rotation": 0,
        "flip_x": flip_x,
        "flip_y": flip_y,
        "width": PAGE_WIDTH_POINTS,
        "height": PAGE_HEIGHT_POINTS,
        "view_scale": 1.0,
    }


def _area_mesh(*, flip_x: bool = False, flip_y: bool = False):
    condition = Condition(
        uid="area-condition",
        condition_type=Condition.TYPE_AREA,
        thickness=1.0,
    )
    takeoff = Takeoff(
        uid="asymmetric-area",
        condition_uid=condition.uid,
        page_uid="page-1",
        position=[1.0, 1.0, 2.5, 1.0, 2.0, 2.0, 1.0, 2.0],
    )
    original_position = list(takeoff.position)
    mesh = MeshFactory(
        OSTCoordinateSystem(_page_info(flip_x=flip_x, flip_y=flip_y))
    ).create_mesh_for_takeoff(takeoff, condition)
    return takeoff, original_position, mesh


def _xy_bounds(mesh) -> tuple[float, float, float, float]:
    xs = [float(vertex[0]) for vertex in mesh.vertices]
    ys = [float(vertex[1]) for vertex in mesh.vertices]
    return min(xs), max(xs), min(ys), max(ys)


class _ColorService:
    @staticmethod
    def get_color_mapping(_conditions, _takeoffs, _display_mode, _grayscale):
        return {}, {}

    @staticmethod
    def get_color_for_takeoff(*_args, **_kwargs):
        return "#123456", 1.0


class _TakeoffService:
    @staticmethod
    def group_area_takeoffs_with_holes(takeoffs, _conditions):
        return list(takeoffs), {}

    @staticmethod
    def group_takeoffs_by_type(conditions, takeoffs):
        grouped = {}
        for takeoff in takeoffs:
            condition_type = conditions[takeoff.condition_uid].condition_type
            grouped.setdefault(condition_type, []).append(takeoff)
        return grouped


class PageFlip3DMeshTests(unittest.TestCase):
    def test_horizontal_flip_mirrors_asymmetric_area_mesh_and_toggles_off(self):
        baseline_takeoff, baseline_position, baseline = _area_mesh()
        flipped_takeoff, flipped_position, flipped = _area_mesh(flip_x=True)
        toggled_off_takeoff, toggled_off_position, toggled_off = _area_mesh()
        self.assertEqual(_xy_bounds(baseline), (-2.5, -1.0, 1.0, 2.0))
        self.assertEqual(_xy_bounds(flipped), (-9.0, -7.5, 1.0, 2.0))
        self.assertEqual(_xy_bounds(toggled_off), _xy_bounds(baseline))
        self.assertEqual(baseline_takeoff.position, baseline_position)
        self.assertEqual(flipped_takeoff.position, flipped_position)
        self.assertEqual(toggled_off_takeoff.position, toggled_off_position)

    def test_mesh_pipeline_selects_independent_transform_for_each_page(self):
        condition = Condition(
            uid="area-condition",
            condition_type=Condition.TYPE_AREA,
            thickness=1.0,
        )
        first = Takeoff(
            uid="first",
            condition_uid=condition.uid,
            page_uid="page-horizontal",
            position=[1.0, 1.0, 2.5, 1.0, 2.0, 2.0, 1.0, 2.0],
        )
        second = Takeoff(
            uid="second",
            condition_uid=condition.uid,
            page_uid="page-vertical",
            position=list(first.position),
        )
        generator = _MeshGeneratorAdapter(
            CoordinateTransformerFactory(), _ColorService(), _TakeoffService()
        )
        meshes, colors, _bounds = generator.generate_meshes(
            {condition.uid: condition},
            [first, second],
            inactive_object_color="#000000",
            page_infos={
                first.page_uid: _page_info(flip_x=True),
                second.page_uid: _page_info(flip_y=True),
            },
        )
        mesh_by_page = {
            colors[f"mesh_{index}"]["page_uid"]: mesh
            for index, mesh in enumerate(meshes)
        }
        self.assertEqual(
            _xy_bounds(mesh_by_page[first.page_uid]), (-9.0, -7.5, 1.0, 2.0)
        )
        self.assertEqual(
            _xy_bounds(mesh_by_page[second.page_uid]), (-2.5, -1.0, 3.0, 4.0)
        )

    def test_mesh_pipeline_preserves_model_scale_when_flipping(self):
        condition = Condition(
            uid="area-condition",
            condition_type=Condition.TYPE_AREA,
            thickness=1.0,
        )
        takeoff = Takeoff(
            uid="scaled-area",
            condition_uid=condition.uid,
            page_uid="scaled-page",
            position=[4.0, 4.0, 10.0, 4.0, 8.0, 8.0, 4.0, 8.0],
        )
        generator = _MeshGeneratorAdapter(
            CoordinateTransformerFactory(), _ColorService(), _TakeoffService()
        )
        scaled_page_info = _page_info()
        scaled_page_info["scale_factor2"] = 4.0
        baseline, _colors, _bounds = generator.generate_meshes(
            {condition.uid: condition},
            [takeoff],
            inactive_object_color="#000000",
            page_infos={takeoff.page_uid: scaled_page_info},
        )
        scaled_page_info["flip_x"] = True
        flipped, _colors, _bounds = generator.generate_meshes(
            {condition.uid: condition},
            [takeoff],
            inactive_object_color="#000000",
            page_infos={takeoff.page_uid: scaled_page_info},
        )
        self.assertEqual(_xy_bounds(baseline[0]), (-10.0, -4.0, 4.0, 8.0))
        self.assertEqual(_xy_bounds(flipped[0]), (-36.0, -30.0, 4.0, 8.0))

    def test_flip_transforms_every_point_mesh_vertex_not_only_its_anchor(self):
        condition = Condition(
            uid="triangle-condition",
            condition_type=Condition.TYPE_COUNT,
            shape=shapes.TRIANGLE,
            width=2.0,
            depth=3.0,
            height=1.0,
            display_size=100.0,
        )
        takeoff = Takeoff(
            uid="triangle-count",
            condition_uid=condition.uid,
            page_uid="page-1",
            position=[2.0, 1.0],
            rotation=0.35,
        )
        generator = _MeshGeneratorAdapter(
            CoordinateTransformerFactory(), _ColorService(), _TakeoffService()
        )
        baseline, _colors, _bounds = generator.generate_meshes(
            {condition.uid: condition},
            [takeoff],
            inactive_object_color="#000000",
            page_infos={takeoff.page_uid: _page_info()},
        )
        flipped, _colors, _bounds = generator.generate_meshes(
            {condition.uid: condition},
            [takeoff],
            inactive_object_color="#000000",
            page_infos={takeoff.page_uid: _page_info(flip_x=True)},
        )
        expected = {
            (round(-10.0 - x, 6), round(y, 6), round(z, 6))
            for x, y, z in baseline[0].vertices
        }
        actual = {
            (round(x, 6), round(y, 6), round(z, 6)) for x, y, z in flipped[0].vertices
        }
        self.assertEqual(actual, expected)

    def test_vertical_and_combined_flips_mirror_asymmetric_area_mesh(self):
        baseline_takeoff, baseline_position, baseline = _area_mesh()
        vertical_takeoff, vertical_position, vertical = _area_mesh(flip_y=True)
        combined_takeoff, combined_position, combined = _area_mesh(
            flip_x=True, flip_y=True
        )
        self.assertEqual(_xy_bounds(baseline), (-2.5, -1.0, 1.0, 2.0))
        self.assertEqual(_xy_bounds(vertical), (-2.5, -1.0, 3.0, 4.0))
        self.assertEqual(_xy_bounds(combined), (-9.0, -7.5, 3.0, 4.0))
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


if __name__ == "__main__":
    unittest.main()
