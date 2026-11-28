import unittest
from unittest.mock import patch
from ost_visualizer.presentation.visualization.core.boolean_operations import (
    apply_boolean_operations,
    boolean_union,
)
from ost_visualizer.presentation.visualization.core.mesh_generator import MeshData
from ost_visualizer.domain.entities import shape as shapes
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff


class BooleanMeshMetadataTests(unittest.TestCase):
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
        original_metadata = {"source": "preserved"}
        with patch(
            "ost_visualizer.presentation.visualization.core.boolean_operations.ost_geometry.boolean_union",
            return_value=native_result,
        ) as native_union:
            result = boolean_union(first, second, original_metadata)
        native_union.assert_called_once_with(first, second)
        self.assertIsNotNone(result)
        self.assertEqual(
            result.vertices, [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        )
        self.assertEqual(result.faces, [[0, 1, 2]])
        self.assertEqual(result.edges, [[0, 1]])
        self.assertEqual(result.metadata, {"source": "preserved", "native": True})
        self.assertEqual(original_metadata, {"source": "preserved"})

    def test_boolean_union_returns_none_when_native_returns_none(self):
        first = MeshData(vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)])
        second = MeshData(vertices=[(1.0, 1.0, 1.0)], faces=[(0, 0, 0)])
        with patch(
            "ost_visualizer.presentation.visualization.core.boolean_operations.ost_geometry.boolean_union",
            return_value=None,
        ):
            self.assertIsNone(boolean_union(first, second, {"source": "preserved"}))

    def test_boolean_union_logs_and_returns_none_when_native_raises(self):
        first = MeshData(vertices=[(0.0, 0.0, 0.0)], faces=[(0, 0, 0)])
        second = MeshData(vertices=[(1.0, 1.0, 1.0)], faces=[(0, 0, 0)])
        with patch(
            "ost_visualizer.presentation.visualization.core.boolean_operations.ost_geometry.boolean_union",
            side_effect=RuntimeError("manifold failed"),
        ):
            with self.assertLogs(
                "ost_visualizer.presentation.visualization.core.boolean_operations",
                level="ERROR",
            ) as logs:
                result = boolean_union(first, second)
        self.assertIsNone(result)
        self.assertIn("manifold failed", logs.output[0])


class BooleanRuleContractTests(unittest.TestCase):
    native = (
        "ost_visualizer.presentation.visualization.core.boolean_operations."
        "ost_geometry.apply_boolean_operations"
    )

    def test_mesh_without_condition_type_is_rejected_naming_the_takeoff(self):
        mesh = MeshData(vertices=[(0.0, 0.0, 0.0)] * 3, faces=[(0, 1, 2)])
        typed = {"IsNegativeQuantity": False, "condition_type": 2, "takeoff_uid": "a"}
        untyped_negative = {"IsNegativeQuantity": True, "takeoff_uid": "b"}
        untyped_positive = {"IsNegativeQuantity": False, "takeoff_uid": "c"}
        for batch, missing in (
            ([(mesh, typed), (mesh, untyped_negative)], "b"),
            ([(mesh, untyped_positive)], "c"),
        ):
            with self.subTest(missing=missing):
                with patch(self.native) as native:
                    with self.assertRaisesRegex(
                        ValueError, f"condition_type.*takeoff {missing}$"
                    ):
                        apply_boolean_operations(batch)
                native.assert_not_called()

    def test_typed_meshes_reach_the_native_rule(self):
        mesh = MeshData(vertices=[(0.0, 0.0, 0.0)] * 3, faces=[(0, 1, 2)])
        positive = {
            "IsNegativeQuantity": False,
            "condition_type": 2,
            "takeoff_uid": "a",
        }
        negative = {"IsNegativeQuantity": True, "condition_type": 3, "takeoff_uid": "b"}
        with patch(self.native, return_value=[]) as native:
            self.assertEqual(
                apply_boolean_operations([(mesh, positive), (mesh, negative)]), []
            )
        native.assert_called_once_with([(mesh, positive), (mesh, negative)])


def _signed_volume(mesh):
    total = 0.0
    for a, b, c in mesh.faces:
        ax, ay, az = mesh.vertices[a]
        bx, by, bz = mesh.vertices[b]
        cx, cy, cz = mesh.vertices[c]
        total += (
            ax * (by * cz - bz * cy)
            - ay * (bx * cz - bz * cx)
            + az * (bx * cy - by * cx)
        ) / 6.0
    return total


class UncutPositiveWindingTests(unittest.TestCase):
    def setUp(self):
        from ost_visualizer.domain.services.coordinate_transformation_service import (
            OSTCoordinateSystem,
        )
        from ost_visualizer.presentation.visualization.meshing.mesh_factory import (
            MeshFactory,
        )
        from tests.presentation.visualization.meshing.page_flip_support import (
            _page_info,
        )

        self.factory = MeshFactory(OSTCoordinateSystem(_page_info()))

    def _mesh(self, condition, position, negative=False):
        return self.factory.create_mesh_for_takeoff(
            Takeoff(
                uid="n" if negative else "t",
                condition_uid=condition.uid,
                position=position,
                is_negative=negative,
            ),
            condition,
        )

    def _negative(self, condition_type, position, z_value=-20.0):
        block = Condition(
            uid="n",
            condition_type=Condition.TYPE_COUNT,
            shape=shapes.SQUARE,
            width=1.0,
            depth=1.0,
            height=50.0,
            display_size=100.0,
        )
        block.z_value = z_value
        return (
            self._mesh(block, position, negative=True),
            {"IsNegativeQuantity": True, "condition_type": condition_type},
        )

    @staticmethod
    def _touching_negative(mesh, condition_type):
        x_max = max(vertex[0] for vertex in mesh.vertices)
        y_values = [vertex[1] for vertex in mesh.vertices]
        z_values = [vertex[2] for vertex in mesh.vertices]
        y0, y1, z0, z1 = min(y_values), max(y_values), min(z_values), max(z_values)
        vertices = [
            (x, y, z)
            for z in (z0, z1)
            for x, y in ((x_max, y0), (x_max + 5.0, y0), (x_max + 5.0, y1), (x_max, y1))
        ]
        faces = [
            (0, 2, 1),
            (0, 3, 2),
            (4, 5, 6),
            (4, 6, 7),
            (0, 1, 5),
            (0, 5, 4),
            (1, 2, 6),
            (1, 6, 5),
            (2, 3, 7),
            (2, 7, 6),
            (3, 0, 4),
            (3, 4, 7),
        ]
        return (
            MeshData(vertices=vertices, faces=faces),
            {"IsNegativeQuantity": True, "condition_type": condition_type},
        )

    def _cases(self):
        wall = Condition(
            uid="wall", condition_type=Condition.TYPE_LINEAR, height=10.0, thickness=2.0
        )
        rhombus = Condition(
            uid="rhombus",
            condition_type=Condition.TYPE_COUNT,
            shape=shapes.RHOMBUS,
            width=20.0,
            depth=12.0,
            height=10.0,
            display_size=100.0,
        )
        return (
            ("wall", wall, [1.0, 1.0, 4.0, 1.0], [2.5, 1.0]),
            ("rhombus", rhombus, [2.0, 2.0], [2.0, 2.0]),
        )

    def test_an_uncut_positive_keeps_its_winding_when_the_scene_holds_a_negative(
        self,
    ):
        for name, condition, position, _inside in self._cases():
            mesh = self._mesh(condition, position)
            meta = {
                "IsNegativeQuantity": False,
                "condition_type": condition.condition_type,
            }
            ((alone, _),) = apply_boolean_operations([(mesh, dict(meta))])
            for label, negative in (
                (
                    "other type",
                    self._negative((condition.condition_type + 1) % 4, [900.0, 900.0]),
                ),
                (
                    "same type, apart",
                    self._negative(condition.condition_type, [900.0, 900.0]),
                ),
                (
                    "other type, overlapping",
                    self._negative((condition.condition_type + 1) % 4, _inside),
                ),
                (
                    "same type, above",
                    self._negative(condition.condition_type, _inside, 500.0),
                ),
                (
                    "same type, empty",
                    (
                        MeshData(vertices=[], faces=[]),
                        {
                            "IsNegativeQuantity": True,
                            "condition_type": condition.condition_type,
                        },
                    ),
                ),
                (
                    "same type, touching",
                    self._touching_negative(mesh, condition.condition_type),
                ),
            ):
                with self.subTest(mesh=name, negative=label), self.assertNoLogs(
                    "ost_visualizer.presentation.visualization.core.boolean_operations",
                    level="ERROR",
                ):
                    ((uncut, _),) = apply_boolean_operations(
                        [(mesh, dict(meta)), negative]
                    )
                    self.assertEqual(
                        [tuple(face) for face in uncut.faces],
                        [tuple(face) for face in alone.faces],
                    )
                    self.assertEqual(uncut.vertices, alone.vertices)
                    self.assertAlmostEqual(_signed_volume(uncut), _signed_volume(alone))

    def test_a_cut_positive_comes_out_outward(self):
        for name, condition, position, inside in self._cases():
            with self.subTest(mesh=name):
                mesh = self._mesh(condition, position)
                meta = {
                    "IsNegativeQuantity": False,
                    "condition_type": condition.condition_type,
                }
                ((cut, _),) = apply_boolean_operations(
                    [(mesh, meta), self._negative(condition.condition_type, inside)]
                )
                self.assertGreater(_signed_volume(cut), 0.0)
                self.assertLess(_signed_volume(cut), _signed_volume(mesh))

    def test_an_empty_positive_does_not_break_the_batch(self):
        _name, condition, position, inside = self._cases()[0]
        mesh = self._mesh(condition, position)
        meta = {"IsNegativeQuantity": False, "condition_type": condition.condition_type}
        empty = MeshData(vertices=[], faces=[])
        with self.assertNoLogs(
            "ost_visualizer.presentation.visualization.core.boolean_operations",
            level="ERROR",
        ):
            results = apply_boolean_operations(
                [
                    (
                        empty,
                        {
                            "IsNegativeQuantity": False,
                            "condition_type": condition.condition_type,
                        },
                    ),
                    (mesh, meta),
                    self._negative(condition.condition_type, inside),
                ]
            )
        self.assertIs(results[-1][1], meta)
        self.assertGreater(_signed_volume(results[-1][0]), 0.0)

    def test_an_uncut_positive_after_a_consumed_one_keeps_its_own_winding(self):
        _name, wall, wall_position, _inside = self._cases()[0]
        _name, rhombus, rhombus_position, _inside = self._cases()[1]
        consumed = self._mesh(wall, wall_position)
        uncut = self._mesh(rhombus, rhombus_position)
        swallow = Condition(
            uid="n",
            condition_type=Condition.TYPE_COUNT,
            shape=shapes.SQUARE,
            width=40.0,
            depth=40.0,
            height=100.0,
            display_size=100.0,
        )
        swallow.z_value = -50.0
        negative = (
            self._mesh(swallow, [2.5, 1.0], negative=True),
            {"IsNegativeQuantity": True, "condition_type": wall.condition_type},
        )
        uncut_meta = {
            "IsNegativeQuantity": False,
            "condition_type": rhombus.condition_type,
        }
        results = apply_boolean_operations(
            [
                (
                    consumed,
                    {
                        "IsNegativeQuantity": False,
                        "condition_type": wall.condition_type,
                    },
                ),
                (uncut, uncut_meta),
                negative,
            ]
        )
        self.assertEqual(len(results), 1)
        self.assertIs(results[0][0], uncut)
        self.assertIs(results[0][1], uncut_meta)
