import os
import tempfile
import unittest
from collections import Counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities import shape as shapes
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.domain.services.takeoff_service_impl import TakeoffDomainService
from ost_visualizer.presentation.visualization.exporters.adapters.fbx_writer import (
    FBXMeshWriter,
)
from ost_visualizer.presentation.visualization.meshing.mesh_builder import (
    process_takeoffs_to_meshes,
)
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)
from tests.integration.geometry import test_uncut_winding_with_negatives as winding


def _count(uid, shape, width=20.0, depth=12.0):
    return Condition(
        uid=uid,
        name=uid,
        condition_type=Condition.TYPE_COUNT,
        shape=shape,
        width=width,
        depth=depth,
        height=10.0,
        display_size=100.0,
    )


def _attachment(uid):
    return Condition(
        uid=uid,
        name=uid,
        condition_type=Condition.TYPE_ATTACHMENT,
        shape=shapes.SQUARE,
        width=5.0,
        depth=5.0,
        height=5.0,
        display_size=100.0,
    )


CONDITIONS = {
    condition.uid: condition
    for condition in (
        Condition(
            uid="wall",
            name="wall",
            condition_type=Condition.TYPE_LINEAR,
            height=10.0,
            thickness=2.0,
        ),
        Condition(
            uid="curved",
            name="curved",
            condition_type=Condition.TYPE_LINEAR,
            height=10.0,
            thickness=2.0,
        ),
        Condition(
            uid="dropwall",
            name="dropwall",
            condition_type=Condition.TYPE_LINEAR,
            height=10.0,
            thickness=2.0,
            drop_run=True,
            drop_value=4.0,
        ),
        Condition(
            uid="slab", name="slab", condition_type=Condition.TYPE_AREA, thickness=4.0
        ),
        Condition(
            uid="sloped",
            name="sloped",
            condition_type=Condition.TYPE_AREA,
            thickness=4.0,
            rise=1.0,
            run=12.0,
        ),
        _count("square", shapes.SQUARE),
        _count("rectangle", shapes.RECTANGLE),
        _count("circle", shapes.CIRCLE),
        _count("ellipse", shapes.ELLIPSE),
        _count("triangle", shapes.TRIANGLE),
        _count("rhombus", shapes.RHOMBUS),
        _count("hexagon", shapes.HEXAGON),
        _count("octagon", shapes.OCTAGON),
        _attachment("attachment"),
        Condition(
            uid="hole",
            name="hole",
            condition_type=Condition.TYPE_AREA,
            thickness=4.0,
        ),
        _attachment("other"),
    )
}
_COUNT_UIDS = (
    "square",
    "rectangle",
    "circle",
    "ellipse",
    "triangle",
    "rhombus",
    "hexagon",
    "octagon",
    "attachment",
)
_BASE = (
    Takeoff(uid="wall", condition_uid="wall", position=[0.0, 0.0, 40.0, 0.0]),
    Takeoff(
        uid="curved",
        condition_uid="curved",
        position=[0.0, 100.0, 40.0, 100.0, 20.0, 90.0],
        curve=0,
    ),
    Takeoff(
        uid="dropwall", condition_uid="dropwall", position=[0.0, 200.0, 40.0, 200.0]
    ),
    Takeoff(
        uid="slab",
        condition_uid="slab",
        position=[100.0, 0.0, 160.0, 0.0, 160.0, 60.0, 100.0, 60.0],
    ),
    Takeoff(
        uid="sloped",
        condition_uid="sloped",
        position=[200.0, 0.0, 260.0, 0.0, 260.0, 60.0, 200.0, 60.0],
    ),
) + tuple(
    Takeoff(uid=uid, condition_uid=uid, position=[400.0 + 60.0 * index, 300.0])
    for index, uid in enumerate(_COUNT_UIDS)
)
SHAPE_UIDS = tuple(takeoff.uid for takeoff in _BASE)
SCENES = {
    "no negative": _BASE,
    "other-type negative apart": _BASE
    + (
        Takeoff(
            uid="n", condition_uid="other", position=[900.0, 900.0], is_negative=True
        ),
    ),
    "same-type negative cutting the slab": _BASE
    + (
        Takeoff(
            uid="n",
            condition_uid="hole",
            is_negative=True,
            position=[120.0, 20.0, 140.0, 20.0, 140.0, 40.0, 120.0, 40.0],
        ),
    ),
}
_OPTIONS = {"inactive_object_color": "#808080"}


def _signed_volume(vertices, faces):
    return winding._winding(vertices, faces, 2)[0]


def _consistent(faces):
    directed = Counter(edge for a, b, c in faces for edge in ((a, b), (b, c), (c, a)))
    return all(count == 1 for count in directed.values()) and all(
        (b, a) in directed for a, b in directed
    )


def _meshes(takeoffs):
    meshes, colors, _bounds = process_takeoffs_to_meshes(
        dict(CONDITIONS),
        list(takeoffs),
        OSTCoordinateSystem(),
        ColorService(),
        TakeoffDomainService(),
        **_OPTIONS,
    )
    return {
        colors[f"mesh_{index}"]["takeoff_uid"]: mesh
        for index, mesh in enumerate(meshes)
    }


class OutwardWindingPerShapeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = folder.name
        self._conditions = winding._conditions
        self._coordinates = winding._IdentityMeshCoordinateSystem
        winding._conditions = lambda: dict(CONDITIONS)
        winding._IdentityMeshCoordinateSystem = OSTCoordinateSystem
        self.addCleanup(self._restore)

    def _restore(self):
        winding._conditions = self._conditions
        winding._IdentityMeshCoordinateSystem = self._coordinates

    def test_every_shape_is_a_closed_outward_mesh_in_the_3d_view(self):
        for scene, takeoffs in SCENES.items():
            meshes = _meshes(takeoffs)
            for uid in SHAPE_UIDS:
                with self.subTest(scene=scene, shape=uid):
                    faces = [tuple(face) for face in meshes[uid].faces]
                    self.assertTrue(_consistent(faces))
                    self.assertGreater(_signed_volume(meshes[uid].vertices, faces), 0.0)

    def test_every_shape_is_outward_in_the_html_export(self):
        for scene, takeoffs in SCENES.items():
            html, _lighting = winding._html(takeoffs, self.folder)
            for uid in SHAPE_UIDS:
                with self.subTest(scene=scene, shape=uid):
                    self.assertGreater(html[uid][0], 0.0)

    def test_every_shape_is_outward_in_the_obj_export(self):
        for scene, takeoffs in SCENES.items():
            obj = winding._obj(takeoffs, self.folder)
            self.assertEqual(len(obj), len(SHAPE_UIDS), scene)
            for name, (volume, _outward, _sides) in obj.items():
                with self.subTest(scene=scene, mesh=name):
                    self.assertGreater(volume, 0.0)

    def test_every_shape_is_outward_in_the_fbx_export(self):
        for scene, takeoffs in SCENES.items():
            meshes = _meshes(takeoffs)
            for uid in SHAPE_UIDS:
                with self.subTest(scene=scene, shape=uid):
                    mesh = meshes[uid]
                    written = FBXMeshWriter._fbx_triangles(mesh.faces)
                    self.assertGreater(_signed_volume(mesh.vertices, written), 0.0)

    def test_the_signed_volume_does_not_depend_on_a_negative_elsewhere(self):
        volumes = {
            scene: {
                uid: round(
                    _signed_volume(mesh.vertices, [tuple(f) for f in mesh.faces]), 3
                )
                for uid, mesh in _meshes(takeoffs).items()
                if uid in SHAPE_UIDS and uid != "slab"
            }
            for scene, takeoffs in SCENES.items()
        }
        self.assertEqual(volumes["other-type negative apart"], volumes["no negative"])
        self.assertEqual(
            volumes["same-type negative cutting the slab"], volumes["no negative"]
        )


if __name__ == "__main__":
    unittest.main()
