import math
import unittest
from itertools import product
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.infrastructure.mdb.components.serialization import (
    parse_position_storage,
)
from ost_visualizer.presentation.components.plan_view.components import placement_mode
from ost_visualizer.presentation.components.plan_view.components.drag_handler import (
    DragHandlerMixin,
)
from ost_visualizer.presentation.components.plan_view.components.placement_mode import (
    PlacementModeMixin,
)
from ost_visualizer.presentation.components.plan_view.components.selection_manager import (
    SelectionManagerMixin,
)
from ost_visualizer.presentation.components.plan_view.components.zoom_handler import (
    ZoomHandlerMixin,
)
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication
from tests import test_plan_property_ownership as storage_fixtures
from tests import test_plan_view_action_handler as action_fixtures
from tests import test_plan_view_snap_helper as fixtures


class LinearPlacementHarness(fixtures.PreviewHarness):
    _placement_snap_from_scene = PlacementModeMixin._placement_snap_from_scene
    _snap_angle_for_placement = PlacementModeMixin._snap_angle_for_placement
    _scene_pos_to_ost = SelectionManagerMixin._scene_pos_to_ost
    _pt_to_scene = SelectionManagerMixin._pt_to_scene
    _ost_to_scene_pos = TakeoffPlanView._ost_to_scene_pos
    snap_ost = DragHandlerMixin.snap_ost

    def __init__(
        self,
        increment=1.0,
        ratio=48.0,
        resolution=1.0,
        zoom=1.0,
        rotation=0,
        flip_x=False,
        flip_y=False,
    ):
        super().__init__()
        self.cs = OSTCoordinateSystem(
            {"scale_factor1": 1.0, "scale_factor2": ratio, "view_scale": resolution}
        )
        self._scene_builder = SimpleNamespace(get_coordinate_system=lambda: self.cs)
        self._snap_increments = increment
        self._snap_to_grid_threshold_px = 100
        self._current_rotation = rotation
        self._current_flip_x = flip_x
        self._current_flip_y = flip_y
        self.zoom_transform = QTransform().scale(zoom, zoom)
        self._place_points = [(3.0 * increment, 4.0 * increment)]
        self._place_linear_dragging = True
        self._linear_geom = SimpleNamespace(
            calc_chord_length=lambda x1, y1, x2, y2: math.hypot(x2 - x1, y2 - y1)
        )
        self.created = []
        self.takeoff_created = SimpleNamespace(
            emit=lambda *args: self.created.append(args)
        )

    def _query_takeoff_snap(self, *args):
        return None

    def _query_pdf_line_snap(self, *args):
        return None

    def _current_page_transform(self):
        return ZoomHandlerMixin._get_page_transform(self, 600.0, 800.0)

    def mapFromScene(self, point):
        return self.zoom_transform.map(point).toPoint()

    def mapToScene(self, point):
        return self.zoom_transform.inverted()[0].map(QPointF(point))

    def preview_and_release(self, dx, dy):
        x, y = self._place_points[0]
        viewport = self.mapFromScene(self._ost_to_scene_pos(x + dx, y + dy))
        self.update_place_preview(self.mapToScene(viewport))
        preview = [
            coordinate for point in self.handle_points[:2] for coordinate in point[:2]
        ]
        event = SimpleNamespace(position=lambda: QPointF(viewport), accept=lambda: None)
        self.handle_place_release_linear(event)
        return preview, self.created[0][1]


class LinearPlacementIncrementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        action_fixtures.PlanViewActionHandlerTests.setUpClass()

    def test_preview_matches_commit_across_increments_scale_zoom_and_page_transform(
        self,
    ):
        for increment, ratio, resolution, zoom, direction, transform in product(
            (0.25, 1.0, 3.0),
            (24.0, 48.0, 96.0),
            (1.0, 2.0),
            (0.5, 1.0, 3.0),
            ((12.0, 0.0), (0.0, 12.0), (9.0, 7.0)),
            (
                (0, False, False),
                (90, True, False),
                (180, False, True),
                (270, True, True),
            ),
        ):
            with self.subTest(
                increment=increment,
                ratio=ratio,
                resolution=resolution,
                zoom=zoom,
                direction=direction,
                transform=transform,
            ):
                harness = LinearPlacementHarness(
                    increment, ratio, resolution, zoom, *transform
                )
                preview, committed = harness.preview_and_release(
                    *(coordinate * increment for coordinate in direction)
                )
                projected = harness.cs.transform_vertices_to_2d(committed)
                for actual, expected in zip(preview, projected):
                    self.assertAlmostEqual(actual, expected, places=10)
                length = math.hypot(
                    committed[2] - committed[0], committed[3] - committed[1]
                )
                self.assertAlmostEqual(
                    length / increment, round(length / increment), places=10
                )
                page_transform = harness._current_page_transform()
                self.assertEqual(
                    page_transform.map(QPointF(*preview[2:])),
                    page_transform.map(QPointF(*projected[2:])),
                )

    def test_snapped_geometry_survives_insert_update_curve_and_reload(self):
        fixture = storage_fixtures.PlanPropertyOwnershipTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.conn.executescript(
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER);"
            "INSERT INTO BidConditions VALUES (30,7);"
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER);"
            "INSERT INTO BidPages VALUES (20,7);"
            "ALTER TABLE BidTakeoffs ADD COLUMN Curve INTEGER;"
        )
        harness = LinearPlacementHarness()
        preview, position = harness.preview_and_release(9.0, 7.0)
        uids = fixture.ops.insert_takeoffs(
            "database.mdb",
            "7",
            [
                InsertTakeoffSpec(
                    condition_uid="30",
                    page_uid="20",
                    area_uid=None,
                    position=position,
                )
            ],
        )
        self.assertEqual(len(uids), 1)

        def assert_round_trip():
            stored = fixture.conn.execute(
                "SELECT Position FROM BidTakeoffs WHERE UID=?", (int(uids[0]),)
            ).fetchone()[0]
            self.assertEqual(parse_position_storage(stored), position)
            self.assertEqual(
                harness.cs.transform_vertices_to_2d(parse_position_storage(stored)),
                preview,
            )

        assert_round_trip()
        self.assertTrue(
            fixture.ops.save_takeoff_positions("database.mdb", [(uids[0], position)])
        )
        assert_round_trip()
        self.assertTrue(
            fixture.ops.set_takeoff_curve("database.mdb", uids[0], position, 0)
        )
        assert_round_trip()

    def test_shift_angle_override_keeps_measurement_increment_and_preview(self):
        for modifier in (
            Qt.KeyboardModifier.NoModifier,
            Qt.KeyboardModifier.ShiftModifier,
        ):
            with self.subTest(modifier=modifier), patch.object(
                placement_mode.QGuiApplication,
                "keyboardModifiers",
                return_value=modifier,
            ):
                harness = LinearPlacementHarness(ratio=96.0)
                preview, committed = harness.preview_and_release(19.0, 7.0)
                self.assertEqual(
                    preview, harness.cs.transform_vertices_to_2d(committed)
                )
                length = math.hypot(
                    committed[2] - committed[0], committed[3] - committed[1]
                )
                self.assertAlmostEqual(length, round(length), places=10)

    def test_placement_undo_redo_retains_exact_snapped_coordinates(self):
        harness = LinearPlacementHarness()
        preview, committed = harness.preview_and_release(19.0, 7.0)
        (
            handler,
            write,
            undo,
        ) = action_fixtures.PlanViewActionHandlerTests()._make_group_transform_handler(
            {}, False
        )
        handler._data_svc.conditions["linear"] = Condition(
            uid="linear", condition_type=Condition.TYPE_LINEAR, layer_visible=True
        )
        handler.on_takeoff_created("linear", committed, "p1")
        self.assertEqual(undo.count, 1)
        for _ in range(3):
            self.assertEqual(write.calls[-1][2][0].position, committed)
            self.assertTrue(undo.undo())
            self.assertTrue(undo.redo())
        self.assertEqual(write.calls[-1][2][0].position, committed)
        self.assertEqual(
            harness.cs.transform_vertices_to_2d(write.calls[-1][2][0].position), preview
        )


if __name__ == "__main__":
    unittest.main()
