import math
import unittest
from ost_visualizer.domain.entities import shape as shapes
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.visualization.meshing.mesh_factory import MeshFactory
from ost_visualizer.presentation.visualization.renderers.threejs.two_d_takeoff_processor import (
    process_takeoffs_2d_for_threejs,
)
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)
from tests.presentation.visualization.renderers.threejs.export_support import (
    _IdentityMeshCoordinateSystem as _export_support__IdentityMeshCoordinateSystem,
    _TakeoffService as _export_support__TakeoffService,
)


class ThreejsExportLayerTests(unittest.TestCase):
    def test_rotated_ellipse_uses_render_minimum_only_for_two_d_threejs(self):
        condition = Condition(
            uid="ellipse-count",
            condition_type=Condition.TYPE_COUNT,
            shape=shapes.ELLIPSE,
            width=20.0,
            depth=2.0,
            height=10.0,
            display_size=100.0,
        )
        takeoff = Takeoff(
            uid="count-1",
            condition_uid=condition.uid,
            page_uid="page-1",
            position=[10.0, 20.0],
            rotation=math.pi / 2.0,
        )
        entries, _callouts = process_takeoffs_2d_for_threejs(
            {condition.uid: condition},
            [takeoff],
            ColorService(),
            _export_support__TakeoffService(),
            {
                "scale_factor1": 1.0,
                "scale_factor2": 72.0,
                "width": 612.0,
                "height": 792.0,
            },
            include_elevation_callouts=False,
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
        )
        mesh = MeshFactory(
            _export_support__IdentityMeshCoordinateSystem()
        ).create_mesh_for_takeoff(
            takeoff,
            condition,
        )
        ring = entries[0]["rings"][0]
        self.assertAlmostEqual(
            max(point[0] for point in ring) - min(point[0] for point in ring), 8.0
        )
        self.assertAlmostEqual(
            max(point[1] for point in ring) - min(point[1] for point in ring), 80.0
        )
        self.assertIsNotNone(mesh)
        self.assertAlmostEqual(
            max(vertex[0] for vertex in mesh.vertices)
            - min(vertex[0] for vertex in mesh.vertices),
            2.0,
        )
        self.assertAlmostEqual(
            max(vertex[1] for vertex in mesh.vertices)
            - min(vertex[1] for vertex in mesh.vertices),
            20.0,
        )
