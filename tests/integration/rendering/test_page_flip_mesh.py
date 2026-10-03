import unittest
from ost_visualizer.domain.entities import shape as shapes
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.infrastructure.visualization_provider import _MeshGeneratorAdapter
from ost_visualizer.presentation.visualization.factories.coordinate_transformer_factory import (
    CoordinateTransformerFactory,
)
from tests.presentation.visualization.meshing.page_flip_support import (
    PAGE_HEIGHT_POINTS as _page_flip_support_PAGE_HEIGHT_POINTS,
    PAGE_WIDTH_POINTS as _page_flip_support_PAGE_WIDTH_POINTS,
    _ColorService as _page_flip_support__ColorService,
    _TakeoffService as _page_flip_support__TakeoffService,
    _page_info as _page_flip_support__page_info,
    _xy_bounds as _page_flip_support__xy_bounds,
)


class PageFlip3DMeshTests(unittest.TestCase):
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
            CoordinateTransformerFactory(),
            _page_flip_support__ColorService(),
            _page_flip_support__TakeoffService(),
        )
        meshes, colors, _bounds = generator.generate_meshes(
            {condition.uid: condition},
            [first, second],
            inactive_object_color="#000000",
            page_infos={
                first.page_uid: _page_flip_support__page_info(flip_x=True),
                second.page_uid: _page_flip_support__page_info(flip_y=True),
            },
        )
        mesh_by_page = {
            colors[f"mesh_{index}"]["page_uid"]: mesh
            for index, mesh in enumerate(meshes)
        }
        self.assertEqual(
            _page_flip_support__xy_bounds(mesh_by_page[first.page_uid]),
            (-9.0, -7.5, 1.0, 2.0),
        )
        self.assertEqual(
            _page_flip_support__xy_bounds(mesh_by_page[second.page_uid]),
            (-2.5, -1.0, 3.0, 4.0),
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
            CoordinateTransformerFactory(),
            _page_flip_support__ColorService(),
            _page_flip_support__TakeoffService(),
        )
        scaled_page_info = _page_flip_support__page_info()
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
        self.assertEqual(
            _page_flip_support__xy_bounds(baseline[0]), (-10.0, -4.0, 4.0, 8.0)
        )
        self.assertEqual(
            _page_flip_support__xy_bounds(flipped[0]), (-36.0, -30.0, 4.0, 8.0)
        )

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
            CoordinateTransformerFactory(),
            _page_flip_support__ColorService(),
            _page_flip_support__TakeoffService(),
        )
        baseline, _colors, _bounds = generator.generate_meshes(
            {condition.uid: condition},
            [takeoff],
            inactive_object_color="#000000",
            page_infos={takeoff.page_uid: _page_flip_support__page_info()},
        )
        flipped, _colors, _bounds = generator.generate_meshes(
            {condition.uid: condition},
            [takeoff],
            inactive_object_color="#000000",
            page_infos={takeoff.page_uid: _page_flip_support__page_info(flip_x=True)},
        )
        expected = {
            (round(-10.0 - x, 6), round(y, 6), round(z, 6))
            for x, y, z in baseline[0].vertices
        }
        actual = {
            (round(x, 6), round(y, 6), round(z, 6)) for x, y, z in flipped[0].vertices
        }
        self.assertEqual(actual, expected)

    def test_flip_keeps_top_face_winding_direction_of_unflipped_mesh(self):
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
        generator = _MeshGeneratorAdapter(
            CoordinateTransformerFactory(),
            _page_flip_support__ColorService(),
            _page_flip_support__TakeoffService(),
        )

        def top_face_normal_z(flip_x, flip_y):
            meshes, _colors, _bounds = generator.generate_meshes(
                {condition.uid: condition},
                [takeoff],
                inactive_object_color="#000000",
                page_infos={
                    takeoff.page_uid: _page_flip_support__page_info(
                        flip_x=flip_x, flip_y=flip_y
                    )
                },
            )
            mesh = meshes[0]
            top_z = max(vertex[2] for vertex in mesh.vertices)
            normals = []
            for face in mesh.faces:
                a, b, c = (mesh.vertices[index] for index in face)
                if a[2] == b[2] == c[2] == top_z:
                    normals.append(
                        (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
                    )
            return normals

        baseline = top_face_normal_z(False, False)
        self.assertTrue(baseline)
        outward = 1.0 if baseline[0] > 0.0 else -1.0
        self.assertTrue(all(normal * outward > 0.0 for normal in baseline))
        # A mirrored mesh needs its faces reversed to keep facing the same way;
        # a double flip is a rotation and must not be reversed.
        for flip_x, flip_y in ((True, False), (False, True), (True, True)):
            with self.subTest(flip_x=flip_x, flip_y=flip_y):
                normals = top_face_normal_z(flip_x, flip_y)
                self.assertEqual(len(normals), len(baseline))
                self.assertTrue(all(normal * outward > 0.0 for normal in normals))
