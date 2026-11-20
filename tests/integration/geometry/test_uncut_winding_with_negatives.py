import json
import math
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities import shape as shapes
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.takeoff_service_impl import TakeoffDomainService
from ost_visualizer.presentation.visualization.exporters.obj_exporter import OBJExporter
from ost_visualizer.presentation.visualization.meshing.mesh_builder import (
    process_takeoffs_to_meshes,
)
from ost_visualizer.presentation.visualization.renderers.threejs.threejs_renderer import (
    visualize_with_threejs,
)
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)
from tests.presentation.visualization.renderers.threejs.export_support import (
    _IdentityMeshCoordinateSystem,
)

_HTML_AMBIENT = 0.55
_HTML_LIGHTS = (
    (0.45, (500.0, 500.0, 500.0)),
    (0.35, (-500.0, 500.0, -500.0)),
    (0.2, (0.0, -500.0, -500.0)),
)
_OPTIONS = {"inactive_object_color": Config.DEFAULT_INACTIVE_OBJECT_COLOR}


def _conditions():
    wall = Condition(
        uid="wall",
        name="wall",
        condition_type=Condition.TYPE_LINEAR,
        height=10.0,
        thickness=2.0,
    )
    rhombus = Condition(
        uid="rhombus",
        name="rhombus",
        condition_type=Condition.TYPE_COUNT,
        shape=shapes.RHOMBUS,
        width=20.0,
        depth=12.0,
        height=10.0,
        display_size=100.0,
    )
    block = Condition(
        uid="block",
        name="block",
        condition_type=Condition.TYPE_ATTACHMENT,
        shape=shapes.SQUARE,
        width=5.0,
        depth=5.0,
        height=5.0,
        display_size=100.0,
    )
    hole = Condition(
        uid="hole",
        name="hole",
        condition_type=Condition.TYPE_LINEAR,
        height=10.0,
        thickness=2.0,
    )
    return {c.uid: c for c in (wall, rhombus, block, hole)}


_BASE = (
    Takeoff(uid="w", condition_uid="wall", position=[0.0, 0.0, 40.0, 0.0]),
    Takeoff(uid="r", condition_uid="rhombus", position=[80.0, 0.0]),
)
_SCENES = {
    "no negative": _BASE,
    "other-type negative": _BASE
    + (
        Takeoff(
            uid="n", condition_uid="block", position=[500.0, 500.0], is_negative=True
        ),
    ),
    "same-type negative apart": _BASE
    + (
        Takeoff(
            uid="n",
            condition_uid="hole",
            position=[500.0, 500.0, 540.0, 500.0],
            is_negative=True,
        ),
    ),
}


def _unit(vector):
    length = math.sqrt(sum(component * component for component in vector)) or 1.0
    return tuple(component / length for component in vector)


def _winding(vertices, triangles, up_axis):
    volume = 0.0
    for a, b, c in triangles:
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = vertices[a], vertices[b], vertices[c]
        volume += (
            ax * (by * cz - bz * cy)
            - ay * (bx * cz - bz * cx)
            + az * (bx * cy - by * cx)
        ) / 6.0
    used = sorted({index for triangle in triangles for index in triangle})
    centre = [sum(vertices[i][axis] for i in used) / len(used) for axis in range(3)]
    outward = sides = 0
    for a, b, c in triangles:
        e1 = [vertices[b][k] - vertices[a][k] for k in range(3)]
        e2 = [vertices[c][k] - vertices[a][k] for k in range(3)]
        normal = _unit(
            (
                e1[1] * e2[2] - e1[2] * e2[1],
                e1[2] * e2[0] - e1[0] * e2[2],
                e1[0] * e2[1] - e1[1] * e2[0],
            )
        )
        if abs(normal[up_axis]) > 0.9:
            continue
        middle = [
            (vertices[a][k] + vertices[b][k] + vertices[c][k]) / 3 for k in range(3)
        ]
        sides += 1
        if sum(normal[k] * (middle[k] - centre[k]) for k in range(3)) > 0:
            outward += 1
    return round(volume, 6), outward, sides


def _view(takeoffs):
    meshes, colors, _bounds = process_takeoffs_to_meshes(
        _conditions(),
        list(takeoffs),
        _IdentityMeshCoordinateSystem(),
        ColorService(),
        TakeoffDomainService(),
        **_OPTIONS,
    )
    return {
        colors[f"mesh_{index}"]["takeoff_uid"]: _winding(
            mesh.vertices, [tuple(face) for face in mesh.faces], 2
        )
        for index, mesh in enumerate(meshes)
    }


def _obj(takeoffs, folder):
    path = Path(folder) / "scene.obj"
    OBJExporter(
        _IdentityMeshCoordinateSystem(), ColorService(), TakeoffDomainService()
    ).export(_conditions(), list(takeoffs), str(path), **_OPTIONS)
    objects, vertices, current = {}, [], None
    for line in path.read_text().splitlines():
        if line.startswith("v "):
            vertices.append(tuple(float(value) for value in line.split()[1:4]))
        elif line.startswith(("o ", "g ")):
            current = line.split(None, 1)[1]
        elif line.startswith("f "):
            objects.setdefault(current, []).append(
                tuple(int(item.split("/")[0]) - 1 for item in line.split()[1:4])
            )
    return {name: _winding(vertices, faces, 2) for name, faces in objects.items()}


def _html(takeoffs, folder):
    path = Path(folder) / "scene.html"
    visualize_with_threejs(
        _conditions(),
        list(takeoffs),
        _IdentityMeshCoordinateSystem(),
        ColorService(),
        TakeoffDomainService(),
        output_path=str(path),
        auto_open=False,
        pages=[],
        include_elevation_callouts=False,
        **_OPTIONS,
    )
    text = path.read_text(encoding="utf-8")
    scene = json.loads(
        text.split('<script type="application/json" id="scene-data">', 1)[1].split(
            "</script>", 1
        )[0]
    )
    lights = [(intensity, _unit(direction)) for intensity, direction in _HTML_LIGHTS]
    winding, lighting = {}, {}
    for geometry in scene["geometries"]:
        flat = geometry["vertices"]
        vertices = [tuple(flat[i : i + 3]) for i in range(0, len(flat), 3)]
        indices = geometry["indices"]
        triangles = [tuple(indices[i : i + 3]) for i in range(0, len(indices), 3)]
        normals = geometry["normals"]

        def lit(index):
            return _HTML_AMBIENT + sum(
                intensity
                * max(sum(normals[3 * index + k] * direction[k] for k in range(3)), 0.0)
                for intensity, direction in lights
            )

        uid = geometry["takeoff_uid"]
        winding[uid] = _winding(vertices, triangles, 1)
        lighting[uid] = {
            tuple(
                round(sum(vertices[i][axis] for i in triangle) / 3, 6)
                for axis in range(3)
            ): round(sum(lit(i) for i in triangle) / 3, 6)
            for triangle in triangles
        }
    return winding, lighting


class UncutWindingWithNegativesTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = folder.name

    def test_uncut_meshes_keep_their_winding_in_the_3d_view_obj_and_html(self):
        results = {
            name: (_view(takeoffs), _obj(takeoffs, self.folder))
            + _html(takeoffs, self.folder)
            for name, takeoffs in _SCENES.items()
        }
        view, obj, html, lighting = results["no negative"]
        self.assertEqual(view, {"w": (-800.0, 0, 8), "r": (1150.0, 8, 8)})
        self.assertEqual(html, {"w": (-800.0, 0, 8), "r": (1150.0, 8, 8)})
        self.assertEqual(
            obj,
            {
                "Unknown_wall_wall": (800.0, 8, 8),
                "Unknown_rhombus_rhombus": (-1150.0, 0, 12),
            },
        )
        self.assertEqual(len(lighting["w"]), 12)
        for name in ("other-type negative", "same-type negative apart"):
            with self.subTest(scene=name):
                self.assertEqual(results[name], results["no negative"])


if __name__ == "__main__":
    unittest.main()
