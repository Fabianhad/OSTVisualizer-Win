import unittest
from types import SimpleNamespace
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from PySide6.QtCore import QPointF, Qt
import tests.presentation.components.plan_view.components.test_input_handler as fixtures


class AttachmentMovementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = fixtures._app()

    def make_view(self):
        view = fixtures.CtrlDragTests()._make_view({"attachment"})
        view._scene_builder = fixtures.FakeSceneBuilder()
        view._scene_builder.cs = fixtures.IdentityCoordinateSystem()
        view._linear_geom = fixtures.FakeLinearGeom()
        view._rotation_before_edit = {}
        view._dirty_rotations = {}
        view._current_conditions = {
            "area": Condition(uid="area", condition_type=Condition.TYPE_AREA),
            "attachment": Condition(
                uid="attachment", condition_type=Condition.TYPE_ATTACHMENT
            ),
        }
        view._current_takeoffs = {
            "parent": Takeoff(
                uid="parent",
                condition_uid="area",
                page_uid="page",
                position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0],
            ),
            "attachment": Takeoff(
                uid="attachment",
                condition_uid="attachment",
                page_uid="page",
                parent_uid="parent",
                position=[5.0, 5.0],
                area_uid="bid-area",
            ),
        }
        view._uid_to_items = {"attachment": [fixtures.FakeItem()]}
        view._handle_infos = [SimpleNamespace(item=fixtures.FakeItem(5.0, 5.0))]
        view._pt_to_scene = lambda x, y: QPointF(x, y)
        return view

    def add_backout(self, view, position):
        view._current_takeoffs["backout"] = Takeoff(
            uid="backout",
            condition_uid="area",
            page_uid="page",
            parent_uid="parent",
            position=list(position),
        )

    def test_legacy_curved_linear_sibling_is_not_a_polygon_backout(self):
        view = self.make_view()
        del view._current_takeoffs["attachment"]
        self.add_backout(view, [5, 5, 6, 5, 6, 6, 5, 6])
        view._current_conditions["linear"] = Condition(
            uid="linear", condition_type=Condition.TYPE_LINEAR
        )
        view._current_takeoffs["linear"] = Takeoff(
            uid="linear",
            condition_uid="linear",
            parent_uid="parent",
            position=[3, 3, 9, 3, 6, 9],
            curve=0,
        )
        backout = view._current_takeoffs["backout"]
        self.assertTrue(view._validate_hole_position(backout, backout.position))
        from ost_visualizer.presentation.components.plan_view.components.placement_mode import (
            PlacementModeMixin,
        )

        self.assertFalse(
            PlacementModeMixin._check_hole_overlap(
                view, backout.position, "parent", "backout"
            )
        )
