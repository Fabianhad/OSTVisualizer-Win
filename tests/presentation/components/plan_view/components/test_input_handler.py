import math
import os
import unittest
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.components.plan_view.components.input_handler import (
    InputHandlerMixin,
)
from unittest.mock import patch
from ost_visualizer.presentation.components.plan_view.components import input_handler
from PySide6 import QtCore, QtWidgets
from shiboken6 import isValid
from types import SimpleNamespace
from ost_visualizer.presentation.modes.cursor import CURSOR_MODE_PLACE
from itertools import combinations
from ost_visualizer.application.dtos.color_dtos import ColorWithOpacity
from ost_visualizer.application.dtos.hotlink_dto import HotlinkDto
from ost_visualizer.domain.entities import shape as shapes
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_CALLOUT,
    ANNOTATION_TYPE_CLOUD,
    ANNOTATION_TYPE_DIMENSION,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_POLYGON,
    BidAnnotation,
)
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.presentation.config import RIGHT_CLICK_CONTEXT_MENU_MAX_MS
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.components.plan_view.components import (
    input_handler as input_handler_module,
)
from ost_visualizer.presentation.components.plan_view.components.drag_handler import (
    DragHandlerMixin,
)
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    DIMENSION_LABEL_ITEM_KIND,
    NAMED_VIEW_LABEL_ITEM_KIND,
)
from ost_visualizer.presentation.components.plan_view.components.placement_mode import (
    PlacementModeMixin,
)
from ost_visualizer.presentation.components.plan_view.components.selection_manager import (
    PolygonControlPointTarget,
    SelectionManagerMixin,
)
from ost_visualizer.presentation.visualization.core.geometry.linear_geometry import (
    LinearGeometry,
)
from ost_visualizer.presentation.visualization.core.geometry.takeoff_geometry import (
    MINIMUM_RENDERED_LINEAR_THICKNESS,
    MINIMUM_RENDERED_POINT_TAKEOFF_SIZE,
    compute_takeoff_footprint_vertices,
)
from ost_visualizer.presentation.visualization.pdf.renderers.takeoff_renderer import (
    TakeoffRenderer,
)
from PySide6 import QtCore
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QBrush, QColor, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QMenu,
)
from tests.presentation.components.plan_view.components.interaction_support import (
    AREA_CP_ADDED_POSITION,
    AREA_CP_HOLE_ADDED_POSITION,
    AREA_CP_HOLE_ORIGINAL_POSITION,
    AREA_CP_HOLE_SUBTRACTED_SECOND_VERTEX_POSITION,
    AREA_CP_ORIGINAL_POSITION,
    AREA_CP_SUBTRACTED_FIRST_VERTEX_POSITION,
    AREA_CP_SUBTRACTED_SECOND_VERTEX_POSITION,
    AnnotationPlacementHarness,
    BaseKeyHandler,
    CapturingMenu,
    FakeContextMenuEvent,
    FakeCoordinateSystem,
    FakeCursorViewport,
    FakeItem,
    FakeKeyEvent,
    FakeLinearGeom,
    FakeMouseEvent,
    FakeSceneBuilder,
    FakeSignal,
    FakeTakeoffRendererColorService,
    FakeWheelEvent,
    IdentityCoordinateSystem,
    InputHandlerHarness,
    _FakeSignal,
    _IdentityCoordinateSystem,
    _PlacementSceneBuilder,
    _app,
)
from PySide6.QtCore import QPointF, Qt
import tests.presentation.components.plan_view.components.test_input_handler as fixtures
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPainterPath, QTransform
from PySide6 import QtCore, QtGui, QtWidgets
from ost_visualizer.domain.entities.page import Page, build_pages_from_bid_data
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_DIMENSION,
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    DIMENSION_LABEL_ITEM_KIND,
    NAMED_VIEW_LABEL_BACKGROUND_ITEM_KIND,
    NAMED_VIEW_LABEL_ITEM_KIND,
    ClippedTextGraphicsItem,
    ImageBackgroundItem,
    TileGraphicsItem,
)
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.modes.cursor import (
    CURSOR_MODE_ANNOTATION_PLACE,
    CURSOR_MODE_PASTE_BACKOUT,
    CURSOR_MODE_PLACE,
    CURSOR_MODE_SELECT,
)
from PySide6 import QtCore, QtTest, QtWidgets
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QFont,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPixmap,
    QTextCursor,
    QTextOption,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
    QStyleOptionGraphicsItem,
)
from shiboken6 import delete
from tests.presentation.components.plan_view.overlay_support import (
    FakeAnnotationRenderer,
    FakeColorService,
    FakeDebouncer,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakePageItem,
    FakePageSizeProvider,
    FakeRenderingService,
    FakeScene,
    FakeScrollBar,
    FakeSizedViewport,
    FakeTakeoffRenderer,
    FakeTransform,
    FakeViewport,
    RecordingPathTakeoffRenderer,
)
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    NAMED_VIEW_LABEL_ITEM_KIND,
)
from shiboken6 import delete, isValid
from tests.presentation.components.plan_view.overlay_support import (
    FakeAnnotationRenderer,
    FakeColorService,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakeRenderingService,
    FakeTakeoffRenderer,
)
from PySide6.QtWidgets import QApplication
from ost_visualizer.presentation.modes.cursor import (
    CURSOR_MODE_ANNOTATION_PLACE,
    CURSOR_MODE_SELECT,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from tests.presentation.components.plan_view.overlay_support import (
    FakeAnnotationRenderer,
    FakeColorService,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakeRenderingService,
    RecordingPathTakeoffRenderer,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _PlanMenuHarness(QtWidgets.QWidget):
    _show_common_context_menu = (
        input_handler.InputHandlerMixin._show_common_context_menu
    )

    def _context_menu_owner(self):
        return self

    def _add_common_context_submenus(self, menu):
        return 0, None, None

    def _add_context_page_actions(self, menu, **options):
        pass

    def reset_ctrl_held(self):
        pass


class _OwnedPlanMenuHarness(_PlanMenuHarness):
    _context_menu_owner = input_handler.InputHandlerMixin._context_menu_owner
    _context_menu_owner_is_current = (
        input_handler.InputHandlerMixin._context_menu_owner_is_current
    )
    _trigger_owned_context_command = (
        input_handler.InputHandlerMixin._trigger_owned_context_command
    )
    _trigger_context_command = input_handler.InputHandlerMixin._trigger_context_command
    _add_context_command = input_handler.InputHandlerMixin._add_context_command
    _plan_item_edit_actions_enabled = (
        input_handler.InputHandlerMixin._plan_item_edit_actions_enabled
    )
    _context_annotations_are_current = (
        input_handler.InputHandlerMixin._context_annotations_are_current
    )
    _select_context_annotation_color = (
        input_handler.InputHandlerMixin._select_context_annotation_color
    )
    _apply_context_annotation_width = (
        input_handler.InputHandlerMixin._apply_context_annotation_width
    )

    def __init__(self, parent):
        super().__init__(parent)
        self._current_bid_ref = None
        self._current_page = None
        self._selected_uids = set()
        self._current_annotations = {}
        self._is_cleaning_up = False
        self.commands = []
        self._context_menu_command_trigger = self.commands.append
        self._context_menu_action_state = lambda _key: {"enabled": True}


class SlopeRotationHarness(InputHandlerMixin):
    def __init__(self):
        self._selection_enabled = True
        self._editing_enabled = True
        self._selected_uids = {"a1"}
        self._current_conditions = {
            "area": Condition(
                uid="area",
                condition_type=Condition.TYPE_AREA,
                layer_visible=True,
                rise=3,
                run=12,
            ),
            "linear": Condition(
                uid="linear",
                condition_type=Condition.TYPE_LINEAR,
                layer_visible=True,
                rise=3,
                run=12,
            ),
        }
        self._current_takeoffs = {
            "a1": Takeoff(
                uid="a1",
                condition_uid="area",
                position=[0, 0, 10, 0, 10, 10, 0, 10],
                rotation=0.0,
            ),
            "a2": Takeoff(
                uid="a2",
                condition_uid="area",
                position=[0, 0, 10, 0, 10, 10, 0, 10],
                rotation=0.0,
                parent_uid="a1",
            ),
            "l1": Takeoff(
                uid="l1",
                condition_uid="linear",
                position=[0, 0, 10, 0, 5, 5, 0],
                rotation=0.0,
            ),
            "a3": Takeoff(
                uid="a3",
                condition_uid="area",
                position=[0, 0, 10, 0, 10, 10, 0, 10],
                rotation=0.0,
            ),
            "orphan": Takeoff(
                uid="orphan",
                condition_uid="missing-condition",
                position=[0, 0, 10, 0, 10, 10, 0, 10],
                rotation=0.0,
            ),
        }
        self._rotation_drag_uid = ""
        self._rotation_drag_orig_rotations = {}
        self._rotation_before_edit = {}
        self._dirty_rotations = {}
        self.flushed_rotations = []
        self.rotate_handle_requests = []

    def _create_rotate_handle(self, uids, **handle_options) -> bool:
        self.rotate_handle_requests.append((set(uids), handle_options))
        return True

    def _flush_dirty_rotations(self) -> None:
        self.flushed_rotations.extend(
            (uid, self._rotation_before_edit.get(uid, 0.0), rotation)
            for uid, rotation in self._dirty_rotations.items()
        )
        self._rotation_before_edit.clear()
        self._dirty_rotations.clear()


class AreaSlopeRotationModeTests(unittest.TestCase):
    def test_slope_rotate_selection_requires_single_area_takeoff_with_slope(self):
        harness = SlopeRotationHarness()
        self.assertEqual(harness._selected_area_slope_uid(), "a1")
        harness._selected_uids = {"a1", "l1"}
        self.assertEqual(harness._selected_area_slope_uid(), "")
        harness._selected_uids = {"l1"}
        self.assertEqual(harness._selected_area_slope_uid(), "")
        harness._selected_uids = {"a2"}
        self.assertEqual(harness._selected_area_slope_uid(), "")
        harness._selected_uids = {"a1"}
        harness._current_conditions["area"].run = 0
        self.assertEqual(harness._selected_area_slope_uid(), "")

    def test_slope_rotate_selection_rejects_each_ineligible_state(self):
        cases = {
            "editing disabled": lambda h: setattr(h, "_editing_enabled", False),
            "empty selection": lambda h: setattr(h, "_selected_uids", set()),
            "two eligible areas": lambda h: setattr(h, "_selected_uids", {"a1", "a3"}),
            "unknown takeoff": lambda h: setattr(h, "_selected_uids", {"ghost"}),
            "linear with rise and run": lambda h: setattr(h, "_selected_uids", {"l1"}),
            "area hole": lambda h: setattr(h, "_selected_uids", {"a2"}),
            "missing condition": lambda h: setattr(h, "_selected_uids", {"orphan"}),
            "zero rise": lambda h: setattr(h._current_conditions["area"], "rise", 0),
            "zero run": lambda h: setattr(h._current_conditions["area"], "run", 0),
            "hidden layer": lambda h: setattr(
                h._current_conditions["area"], "layer_visible", False
            ),
            "too few vertices": lambda h: setattr(
                h._current_takeoffs["a1"], "position", [0, 0, 10, 0]
            ),
        }
        for name, break_selection in cases.items():
            with self.subTest(name):
                harness = SlopeRotationHarness()
                self.assertEqual(harness._selected_area_slope_uid(), "a1")
                break_selection(harness)
                self.assertEqual(harness._selected_area_slope_uid(), "")

    def test_slope_rotate_selection_accepts_negative_rise_and_run(self):
        harness = SlopeRotationHarness()
        condition = harness._current_conditions["area"]
        condition.rise = -3
        condition.run = -12
        self.assertEqual(harness._selected_area_slope_uid(), "a1")

    def test_slope_handle_starts_at_negated_area_rotation_in_slope_mode(self):
        harness = SlopeRotationHarness()
        harness._current_takeoffs["a1"].rotation = math.radians(30.0)
        self.assertTrue(harness._create_slope_rotate_handle())
        self.assertEqual(len(harness.rotate_handle_requests), 1)
        uids, options = harness.rotate_handle_requests[0]
        self.assertEqual(uids, {"a1"})
        self.assertEqual(set(options), {"start_angle_degrees", "slope_mode"})
        self.assertAlmostEqual(options["start_angle_degrees"], -30.0)
        self.assertIs(options["slope_mode"], True)

    def test_slope_handle_is_not_created_for_ineligible_selection(self):
        harness = SlopeRotationHarness()
        harness._selected_uids = {"l1"}
        self.assertFalse(harness._create_slope_rotate_handle())
        self.assertEqual(harness.rotate_handle_requests, [])

    def test_slope_rotation_ignores_missing_or_unknown_takeoff(self):
        harness = SlopeRotationHarness()
        for uid in (None, "", "ghost"):
            with self.subTest(uid=uid):
                harness._apply_slope_rotation(uid, 45.0)
        self.assertEqual(harness.flushed_rotations, [])
        self.assertEqual(harness._dirty_rotations, {})
        self.assertEqual(harness._current_takeoffs["a1"].rotation, 0.0)

    def test_slope_rotation_without_drag_origin_uses_current_rotation(self):
        harness = SlopeRotationHarness()
        harness._current_takeoffs["a1"].rotation = 0.5
        harness._apply_slope_rotation("a1", -30.0)
        self.assertAlmostEqual(
            harness._current_takeoffs["a1"].rotation, 0.5 + math.radians(30.0)
        )
        self.assertEqual(len(harness.flushed_rotations), 1)
        uid, before, after = harness.flushed_rotations[0]
        self.assertEqual((uid, before), ("a1", 0.5))
        self.assertAlmostEqual(after, 0.5 + math.radians(30.0))

    def test_apply_slope_rotation_changes_rotation_without_moving_area(self):
        harness = SlopeRotationHarness()
        original_position = list(harness._current_takeoffs["a1"].position)
        harness._rotation_drag_uid = "a1"
        harness._rotation_drag_orig_rotations = {"a1": 0.25}
        harness._apply_slope_rotation("a1", 90.0)
        self.assertEqual(harness._current_takeoffs["a1"].position, original_position)
        self.assertAlmostEqual(
            harness._current_takeoffs["a1"].rotation,
            0.25 - math.pi / 2.0,
        )
        self.assertEqual(
            harness.flushed_rotations,
            [("a1", 0.25, 0.25 - math.pi / 2.0)],
        )


class PlanNativeContextMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_top_level_menu_cannot_dispatch_after_plan_native_deletion(self):
        window = QtWidgets.QMainWindow()
        self.addCleanup(window.deleteLater)
        view = _OwnedPlanMenuHarness(window)
        menu = QtWidgets.QMenu(view.window())
        view._add_context_command(menu, "Paste", "paste")
        view.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(
            view, QtCore.QEvent.Type.DeferredDelete
        )
        self.assertFalse(isValid(view))
        self.assertTrue(isValid(menu))
        menu.actions()[0].trigger()
        self.assertEqual(view.commands, [])

    def test_empty_plan_menu_cannot_dispatch_after_cleanup_started(self):
        window = QtWidgets.QMainWindow()
        self.addCleanup(window.deleteLater)
        view = _OwnedPlanMenuHarness(window)
        menu = QtWidgets.QMenu(view.window())
        view._add_context_command(menu, "Paste", "paste")
        view._is_cleaning_up = True
        menu.actions()[0].trigger()
        self.assertEqual(view.commands, [])

    def test_annotation_menu_validates_native_owner_before_querying_action_state(self):
        window = QtWidgets.QMainWindow()
        self.addCleanup(window.deleteLater)
        view = _OwnedPlanMenuHarness(window)
        view._selected_uids = {"annotation"}
        view._current_annotations = {"annotation": object()}
        owner = view._context_menu_owner()
        view._context_menu_action_state = lambda _key: {"enabled": view.isEnabled()}
        view.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(
            view, QtCore.QEvent.Type.DeferredDelete
        )
        view._select_context_annotation_color(owner, view._current_annotations)
        view._apply_context_annotation_width(owner, view._current_annotations, 2.0)
        self.assertEqual(view.commands, [])

    def test_menu_cannot_dispatch_when_plan_is_deleted_during_exec(self):
        window = QtWidgets.QMainWindow()
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        view = _OwnedPlanMenuHarness(window)
        window.show()

        def create_menu(parent):
            menu = QtWidgets.QMenu(parent)

            def delete_plan_then_trigger():
                view.deleteLater()
                QtCore.QCoreApplication.sendPostedEvents(
                    view, QtCore.QEvent.Type.DeferredDelete
                )
                menu.actions()[1].trigger()
                menu.close()

            QtCore.QTimer.singleShot(0, delete_plan_then_trigger)
            return menu

        from types import SimpleNamespace

        event = SimpleNamespace(
            globalPos=lambda: window.mapToGlobal(QtCore.QPoint(20, 20))
        )
        with patch.object(input_handler, "QMenu", create_menu):
            view._show_common_context_menu(
                event, lambda menu: view._add_context_command(menu, "Paste", "paste")
            )
        self.assertFalse(isValid(view))
        self.assertEqual(view.commands, [])

    def test_main_and_detached_plan_menu_flows_keep_their_own_window(self):
        import tests.presentation.components.plan_view.components.test_input_handler as helpers

        builder = helpers.CtrlDragTests()
        for window_type in (QtWidgets.QMainWindow, QtWidgets.QWidget):
            window = window_type()
            self.addCleanup(window.deleteLater)
            for selection in ("empty", "takeoff", "annotation"):
                with self.subTest(
                    window_type=window_type.__name__, selection=selection
                ):
                    if selection == "annotation":
                        view, _annotation = builder._make_annotation_control_point_view(
                            "rect"
                        )
                    else:
                        view = builder._make_area_control_point_view(
                            {"area1", "linear1"} if selection == "takeoff" else set()
                        )
                    view.window = lambda: window
                    menus = []

                    def create_menu(parent):
                        menu = QtWidgets.QMenu(parent)
                        menus.append(menu)
                        QtCore.QTimer.singleShot(0, menu.close)
                        return menu

                    with patch.object(input_handler, "QMenu", create_menu):
                        view.contextMenuEvent(helpers.FakeContextMenuEvent(-100, -100))
                    self.assertIs(menus[0].parentWidget(), window)
                    QtCore.QCoreApplication.sendPostedEvents(
                        menus[0], QtCore.QEvent.Type.DeferredDelete
                    )
                    self.assertFalse(isValid(menus[0]))

    def test_page_or_selection_change_invalidates_menu_command(self):
        window = QtWidgets.QWidget()
        self.addCleanup(window.deleteLater)
        view = _OwnedPlanMenuHarness(window)
        for change in ("page", "selection"):
            menu = QtWidgets.QMenu(window)
            view._add_context_command(menu, "Paste", "paste")
            if change == "page":
                view._current_page = object()
            else:
                view._selected_uids = {"different"}
            menu.actions()[0].trigger()
        self.assertEqual(view.commands, [])

    def test_top_level_owner_deletion_unwinds_native_menu(self):
        from types import SimpleNamespace

        window = QtWidgets.QWidget()
        view = _OwnedPlanMenuHarness(window)
        window.show()
        menus = []

        def create_menu(parent):
            menu = QtWidgets.QMenu(parent)
            menus.append(menu)

            def delete_window():
                window.deleteLater()
                QtCore.QCoreApplication.sendPostedEvents(
                    window, QtCore.QEvent.Type.DeferredDelete
                )

            QtCore.QTimer.singleShot(0, delete_window)
            return menu

        event = SimpleNamespace(
            globalPos=lambda: window.mapToGlobal(QtCore.QPoint(20, 20))
        )
        with patch.object(input_handler, "QMenu", create_menu):
            view._show_common_context_menu(
                event, lambda menu: view._add_context_command(menu, "Paste", "paste")
            )
        self.assertFalse(isValid(window))
        self.assertFalse(isValid(view))
        self.assertFalse(isValid(menus[0]))
        self.assertEqual(view.commands, [])

    def test_plan_menu_uses_top_level_owner_under_native_stack(self):
        window = QtWidgets.QMainWindow()
        self.addCleanup(window.close)
        self.addCleanup(window.deleteLater)
        stack = QtWidgets.QStackedWidget(window)
        window.setCentralWidget(stack)
        stack.setAttribute(QtCore.Qt.WidgetAttribute.WA_NativeWindow)
        view = _PlanMenuHarness()
        stack.addWidget(view)
        window.show()
        messages = []
        menus = []
        previous = QtCore.qInstallMessageHandler(
            lambda _kind, _context, message: messages.append(message)
        )
        self.addCleanup(QtCore.qInstallMessageHandler, previous)

        def create_menu(parent):
            menu = QtWidgets.QMenu(parent)
            menus.append(menu)
            QtCore.QTimer.singleShot(0, menu.close)
            return menu

        class Event:
            def globalPos(self):
                return window.mapToGlobal(QtCore.QPoint(20, 20))

        with patch.object(input_handler, "QMenu", create_menu):
            view._show_common_context_menu(
                Event(), lambda menu: menu.addAction("Paste")
            )
        self.assertIs(menus[0].parentWidget(), window)
        self.assertFalse(
            [message for message in messages if "must be a top level window" in message]
        )


class UIAccessPlanEditingTests(unittest.TestCase):
    def test_stale_mouse_release_cannot_commit_after_access_revocation(self):
        event = SimpleNamespace(accepted=False)

        def accept():
            event.accepted = True

        event.accept = accept
        view = SimpleNamespace(
            _editing_enabled=False,
            _cursor_mode=CURSOR_MODE_PLACE,
            _editing_cursor_mode_allowed=lambda: False,
        )
        InputHandlerMixin.mouseReleaseEvent(view, event)
        self.assertTrue(event.accepted)


class _CtrlDragFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _rendered_box_side_lengths(self, position):
        points = [
            (position[0], position[1]),
            (position[6], position[7]),
            (position[2], position[3]),
            (position[4], position[5]),
        ]
        return sorted(
            round(
                math.hypot(
                    points[(index + 1) % 4][0] - points[index][0],
                    points[(index + 1) % 4][1] - points[index][1],
                ),
                6,
            )
            for index in range(4)
        )

    def _make_view(self, selected_uids=None):
        view = InputHandlerHarness()
        view._scene_builder = FakeSceneBuilder()
        view._current_bid_ref = None
        view._current_page = None
        view._cursor_mode = "select"
        view._selection_enabled = True
        view._ctrl_held = False
        view._use_full_window_crosshairs = False
        view._zoom_press_ctrl = False
        view._select_band_origin = None
        view._select_band_active = False
        view._select_band_dragged = False
        view._press_changed_selection = False
        view._rotation_drag_active = False
        view._rotate_cursor = Qt.CursorShape.CrossCursor
        view._rotate_handle_item = None
        view._panning = False
        view._right_pan_active = False
        view._point_annotation_release_pending = False
        view._last_pan_point = None
        view._drag_plan_item_uid = None
        view._drag_handle_index = -2
        view._drag_orig_position = []
        view._drag_handle_corner_count = 0
        view._drag_item_orig_positions = {}
        view._drag_item_orig_paths = {}
        view._drag_item_orig_text_states = {}
        view._drag_uid_orig_items = {}
        view._drag_multi_orig_positions = {}
        view._drag_last_valid_new_pos = []
        view._keyboard_move_dirty = False
        view._selected_uids = set({"t1"} if selected_uids is None else selected_uids)
        view.plan_item_selection_changed = _FakeSignal()
        view.takeoff_selection_changed = _FakeSignal()
        view._handle_infos = []
        view._selection_items = []
        view._current_takeoffs = {
            "t1": Takeoff(
                uid="t1",
                position=[0.0, 0.0, 10.0, 0.0],
                condition_uid="c",
            ),
            "t2": Takeoff(
                uid="t2",
                position=[20.0, 0.0, 30.0, 0.0],
                condition_uid="c",
            ),
        }
        view._current_annotations = {}
        view._hotlink_items = []
        view._current_conditions = {}
        view._scene = None
        view._uid_to_items = {"t1": [FakeItem(1.0, 2.0)], "t2": [FakeItem(3.0, 4.0)]}
        view._takeoff_items = []
        view.mapToScene = lambda _point: QtCore.QPointF(10.0, 10.0)
        view.mapFromScene = lambda point: QtCore.QPoint(int(point.x()), int(point.y()))
        view.find_takeoff_at = lambda _scene_pos: "t1"
        view.find_takeoffs_at = lambda _scene_pos: ["t1"]
        view._flush_dirty_positions = lambda: None
        view.update_selection_visuals = lambda *args, **_call_options: None
        view._rubber_band_origin = None
        view._rubber_band = None
        view._update_cursor = lambda *args, **_call_options: None
        view._snap_increments = 1.0
        view._position_before_edit = {}
        view._dirty_positions = {}
        view._dirty_ann_positions = {}
        view.ost_to_scene_delta = lambda dx, dy: (dx, dy)
        return view

    def _make_transform_view(self, selected_uids):
        view = self._make_view(selected_uids)
        view._scene_builder = FakeSceneBuilder()
        view._linear_geom = LinearGeometry()
        view._current_conditions = {
            "linear": Condition(
                uid="linear",
                condition_type=Condition.TYPE_LINEAR,
                thickness=4.0,
            ),
            "count": Condition(
                uid="count",
                condition_type=Condition.TYPE_COUNT,
                shape=shapes.TRIANGLE,
                width=20.0,
                depth=12.0,
                display_size=150.0,
            ),
            "area": Condition(uid="area", condition_type=Condition.TYPE_AREA),
            "attachment": Condition(
                uid="attachment",
                condition_type=Condition.TYPE_ATTACHMENT,
                shape=shapes.TRIANGLE,
                width=14.0,
                depth=8.0,
            ),
        }
        view._current_takeoffs = {
            "area": Takeoff(
                uid="area",
                condition_uid="area",
                position=[-2.0, 1.0, 11.0, 0.0, 9.0, 12.0, 1.0, 8.0],
            ),
            "linear": Takeoff(
                uid="linear",
                condition_uid="linear",
                position=[12.0, 2.0, 22.0, 2.0],
            ),
            "count": Takeoff(
                uid="count",
                condition_uid="count",
                position=[30.0, 5.0],
                rotation=math.radians(32.0),
            ),
            "attachment": Takeoff(
                uid="attachment",
                condition_uid="attachment",
                position=[45.0, 5.0],
                rotation=math.radians(25.0),
            ),
        }
        view._rotation_before_edit = {}
        view._dirty_rotations = {}
        view.flushed_transform_groups = []

        def flush_rotation_group():
            position_changes = [
                (
                    uid,
                    list(view._position_before_edit[uid]),
                    list(new_position),
                )
                for uid, new_position in view._dirty_positions.items()
            ]
            rotation_changes = [
                (uid, view._rotation_before_edit[uid], new_rotation)
                for uid, new_rotation in view._dirty_rotations.items()
            ]
            view.flushed_transform_groups.append((position_changes, rotation_changes))
            view._position_before_edit.clear()
            view._dirty_positions.clear()
            view._rotation_before_edit.clear()
            view._dirty_rotations.clear()

        view._flush_rotation_group = flush_rotation_group
        return view

    @staticmethod
    def _minimum_rendered_dimensions(view):
        coordinate_system = view._scene_builder.get_coordinate_system()
        screen_units_per_ost = coordinate_system.ost_to_screen_pixels(1.0)
        return (
            MINIMUM_RENDERED_POINT_TAKEOFF_SIZE / screen_units_per_ost,
            MINIMUM_RENDERED_LINEAR_THICKNESS / screen_units_per_ost,
        )

    @staticmethod
    def _takeoff_vertices(view, uid):
        takeoff = view._current_takeoffs[uid]
        minimum_point_dimension, minimum_linear_thickness = (
            CtrlDragTests._minimum_rendered_dimensions(view)
        )
        return compute_takeoff_footprint_vertices(
            takeoff,
            view._current_conditions[takeoff.condition_uid],
            view._linear_geom,
            minimum_point_dimension,
            minimum_linear_thickness,
        )

    def _assert_bounds_almost_equal(self, first, second):
        for first_value, second_value in zip(first, second):
            self.assertAlmostEqual(first_value, second_value, places=9)

    def _assert_vertices_almost_equal(self, first, second):
        normalized_first = sorted((round(x, 9), round(y, 9)) for x, y in first)
        normalized_second = sorted((round(x, 9), round(y, 9)) for x, y in second)
        self.assertEqual(normalized_first, normalized_second)

    def _assert_quarter_turn_bounds(self, before, after):
        before_center = (
            (before[0] + before[2]) / 2.0,
            (before[1] + before[3]) / 2.0,
        )
        after_center = (
            (after[0] + after[2]) / 2.0,
            (after[1] + after[3]) / 2.0,
        )
        self._assert_bounds_almost_equal(before_center, after_center)
        self.assertAlmostEqual(before[2] - before[0], after[3] - after[1], places=9)
        self.assertAlmostEqual(before[3] - before[1], after[2] - after[0], places=9)

    def _flip_and_assert_reflection(self, view, selected, horizontal):
        left, top, right, bottom = self._rendered_takeoff_selection_bounds(
            view, selected
        )
        pivot_x = (left + right) / 2.0
        pivot_y = (top + bottom) / 2.0
        before = {uid: self._takeoff_vertices(view, uid) for uid in selected}
        view.flip_selected_takeoffs(horizontal)
        for uid in selected:
            expected = [
                (
                    2.0 * pivot_x - x if horizontal else x,
                    y if horizontal else 2.0 * pivot_y - y,
                )
                for x, y in before[uid]
            ]
            self._assert_vertices_almost_equal(
                expected, self._takeoff_vertices(view, uid)
            )

    def _rotate_and_assert_rotation(self, view, selected, degrees):
        left, top, right, bottom = self._rendered_takeoff_selection_bounds(
            view, selected
        )
        pivot_x = (left + right) / 2.0
        pivot_y = (top + bottom) / 2.0
        cos_a = math.cos(math.radians(degrees))
        sin_a = math.sin(math.radians(degrees))
        before = {uid: self._takeoff_vertices(view, uid) for uid in selected}
        view.rotate_selected_takeoffs(degrees)
        for uid in selected:
            expected = [
                (
                    pivot_x + (x - pivot_x) * cos_a - (y - pivot_y) * sin_a,
                    pivot_y + (x - pivot_x) * sin_a + (y - pivot_y) * cos_a,
                )
                for x, y in before[uid]
            ]
            self._assert_vertices_almost_equal(
                expected, self._takeoff_vertices(view, uid)
            )

    @staticmethod
    def _rendered_takeoff_selection_bounds(view, uids):
        coordinate_system = view._scene_builder.get_coordinate_system()
        renderer = TakeoffRenderer(
            IdentityCoordinateSystem(coordinate_system.ost_to_screen_pixels(1.0)),
            FakeTakeoffRendererColorService(),
        )
        takeoffs = [view._current_takeoffs[uid] for uid in uids]
        color_map = {
            takeoff.condition_uid: ColorWithOpacity("#123456", 1.0)
            for takeoff in takeoffs
        }
        bounds = None
        rendered = renderer.create_all_path_items(
            takeoffs,
            view._current_conditions,
            color_map,
            inactive_object_color="#808080",
        )
        for _uid, takeoff_items in rendered:
            items = (
                takeoff_items if isinstance(takeoff_items, list) else [takeoff_items]
            )
            for item in items:
                if not isinstance(item, QGraphicsPathItem):
                    continue
                item_bounds = item.path().boundingRect()
                bounds = item_bounds if bounds is None else bounds.united(item_bounds)
        return (
            bounds.left(),
            bounds.top(),
            bounds.right(),
            bounds.bottom(),
        )

    def _make_linear_resize_gesture_view(
        self,
        *,
        scale_ratio=48.0,
        coordinate_view_scale=2.0,
        zoom=1.0,
        position=None,
        snap_increment=1.0,
    ):
        view = self._make_view({"t1"})
        view._advanced_mouse_controls_enabled = False
        view._drag_model_orig_position = None
        view._drag_position_before_edit_existed = False
        view._current_conditions = {
            "c": Condition(uid="c", condition_type=Condition.TYPE_LINEAR)
        }
        view._current_takeoffs["t1"].position = list(position or [0.0, 0.0, 10.0, 0.0])
        view._scene_builder = FakeSceneBuilder()
        coordinate_system = view._scene_builder.get_coordinate_system()
        coordinate_system.scale_ratio = float(scale_ratio)
        coordinate_system.view_scale = float(coordinate_view_scale)
        view._snap_increments = float(snap_increment)
        view.mapToScene = lambda point: QtCore.QPointF(
            point.x() / zoom,
            point.y() / zoom,
        )
        view.mapFromScene = lambda point: QtCore.QPoint(
            round(point.x() * zoom),
            round(point.y() * zoom),
        )
        view._current_page_transform = lambda: None
        view._snap_angle = lambda _ox, _oy, nx, ny: (nx, ny)
        view.find_text_annotation_at = lambda _scene_pos: None
        view.find_selected_movable_at = lambda _scene_pos: "t1"
        view.find_takeoff_at = lambda _scene_pos, cycle_from_uid=None: "t1"
        view.find_takeoffs_at = lambda _scene_pos: ["t1"]
        handles = [
            SimpleNamespace(item=FakeItem()),
            SimpleNamespace(item=FakeItem()),
        ]
        view._handle_infos = handles
        view._is_handle_info_at_viewport_pos = lambda info, _pos: info is handles[1]
        view.resize_previews = []
        view.update_drag_handle_positions = (
            lambda new_pos, uid, *_args: view.resize_previews.append(
                (uid, list(new_pos))
            )
        )
        view.positions_flushed = FakeSignal()

        def flush_dirty_positions():
            if not view._dirty_positions and not view._dirty_ann_positions:
                return
            previous = dict(view._position_before_edit)
            takeoff_changes = [
                (uid, previous.get(uid, []), list(new_pos))
                for uid, new_pos in view._dirty_positions.items()
            ]
            annotation_changes = [
                (uid, annotation_type, previous.get(uid, []), list(new_pos))
                for uid, (annotation_type, new_pos) in view._dirty_ann_positions.items()
            ]
            view._dirty_positions.clear()
            view._dirty_ann_positions.clear()
            view._position_before_edit.clear()
            view.positions_flushed.emit(takeoff_changes, annotation_changes)

        view._flush_dirty_positions = flush_dirty_positions
        return view

    @staticmethod
    def _perform_linear_resize_gesture(view, points):
        view.mousePressEvent(FakeMouseEvent(x=0, y=0))
        drag_latches = []
        for x, y in points:
            view.mouseMoveEvent(FakeMouseEvent(x=x, y=y))
            drag_latches.append(view._select_band_dragged)
        release_x, release_y = points[-1] if points else (0, 0)
        release = FakeMouseEvent(
            x=release_x,
            y=release_y,
            buttons=Qt.MouseButton.NoButton,
        )
        view.mouseReleaseEvent(release)
        return drag_latches, release

    def _make_area_control_point_view(self, selected_uids=None, include_hole=False):
        view = self._make_view(set() if selected_uids is None else selected_uids)
        view._scene = QGraphicsScene()
        view._scene_builder = FakeSceneBuilder()
        view._annotation_only_selection = False
        view._hidden_layer_uids = set()
        view._current_page = None
        view._current_conditions = {
            "area": Condition(
                uid="area",
                condition_type=Condition.TYPE_AREA,
                layer_visible=True,
            ),
            "linear": Condition(
                uid="linear",
                condition_type=Condition.TYPE_LINEAR,
                layer_visible=True,
            ),
        }
        view._current_takeoffs = {
            "area1": Takeoff(
                uid="area1",
                condition_uid="area",
                page_uid="page-1",
                position=list(AREA_CP_ORIGINAL_POSITION),
            ),
            "linear1": Takeoff(
                uid="linear1",
                condition_uid="linear",
                page_uid="page-1",
                position=[200.0, 0.0, 300.0, 0.0],
            ),
        }
        if include_hole:
            view._current_takeoffs["hole1"] = Takeoff(
                uid="hole1",
                condition_uid="area",
                page_uid="page-1",
                parent_uid="area1",
                position=list(AREA_CP_HOLE_ORIGINAL_POSITION),
            )
        area_path = QPainterPath()
        area_path.moveTo(0.0, 0.0)
        area_path.lineTo(100.0, 0.0)
        area_path.lineTo(100.0, 100.0)
        area_path.lineTo(0.0, 100.0)
        area_path.closeSubpath()
        area_item = QGraphicsPathItem(area_path)
        area_item.setData(0, "area1")
        area_item.setZValue(0.5)
        items_by_uid = {"area1": [area_item]}
        if include_hole:
            hole_path = QPainterPath()
            hole_path.moveTo(20.0, 20.0)
            hole_path.lineTo(40.0, 20.0)
            hole_path.lineTo(40.0, 40.0)
            hole_path.lineTo(20.0, 40.0)
            hole_path.closeSubpath()
            hole_item = QGraphicsPathItem(hole_path)
            hole_item.setData(0, "hole1")
            hole_item.setZValue(0.6)
            view._scene.addItem(hole_item)
            items_by_uid["hole1"] = [hole_item]
        linear_path = QPainterPath()
        linear_path.moveTo(200.0, 0.0)
        linear_path.lineTo(300.0, 0.0)
        linear_item = QGraphicsPathItem(linear_path)
        linear_item.setData(0, "linear1")
        linear_item.setZValue(0.5)
        view._scene.addItem(area_item)
        view._scene.addItem(linear_item)
        items_by_uid["linear1"] = [linear_item]
        view._uid_to_items = items_by_uid
        view._current_annotations = {}
        view._hotlink_items = []
        view._current_page_transform = lambda: None
        view._pt_to_scene = lambda x, y: QtCore.QPointF(float(x), float(y))
        view._scene_pos_to_ost = lambda point: QtCore.QPointF(point)
        view.transform = lambda: QTransform()
        view.mapToScene = lambda point: QtCore.QPointF(point)
        view.mapFromScene = lambda point: QtCore.QPoint(int(point.x()), int(point.y()))
        del view.find_takeoff_at
        del view.find_takeoffs_at
        view._position_before_edit = {}
        view._dirty_positions = {}
        view._dirty_ann_positions = {}
        view._ann_db_uid_map = {}
        view._refreshing_overlays = False
        view.positions_flushed = FakeSignal()
        view.rebuild_count = 0
        view.selection_update_count = 0
        view.snap_invalidations = 0

        def rebuild_current_overlays_from_model():
            view.rebuild_count += 1

        def update_selection_visuals(*_args, **_options):
            view.selection_update_count += 1

        def invalidate_snap_index():
            view.snap_invalidations += 1

        view._rebuild_current_overlays_from_model = rebuild_current_overlays_from_model
        view.update_selection_visuals = update_selection_visuals
        view._invalidate_snap_index = invalidate_snap_index

        def flush_dirty_positions():
            if view._refreshing_overlays:
                return
            if not view._dirty_positions and not view._dirty_ann_positions:
                return
            if view._dirty_positions:
                view._invalidate_snap_index()
            dirty = dict(view._dirty_positions)
            ann_dirty = dict(view._dirty_ann_positions)
            prev = dict(view._position_before_edit)
            view._dirty_positions.clear()
            view._dirty_ann_positions.clear()
            view._position_before_edit.clear()
            takeoff_changes = [
                (uid, prev.get(uid, []), pos) for uid, pos in dirty.items()
            ]
            ann_changes = [
                (view._ann_db_uid_map.get(uid, uid), ann_type, prev.get(uid, []), pos)
                for uid, (ann_type, pos) in ann_dirty.items()
            ]
            view.positions_flushed.emit(takeoff_changes, ann_changes)

        view._flush_dirty_positions = flush_dirty_positions
        view._add_common_context_submenus = lambda _menu: (0, None, None)
        view._add_context_clipboard_actions = lambda _menu: None
        view._add_context_page_actions = lambda _menu, **_options: None
        view._context_menu_command_trigger = None
        view._context_menu_action_state = lambda _key: {"enabled": True}
        view._suppress_next_context_menu = False
        view.reset_ctrl_held = lambda: None
        return view

    def _make_annotation_control_point_view(self, annotation_type, selected_uids=None):
        view = self._make_area_control_point_view(set())
        uid = f"{annotation_type}1"
        position = [
            400.0,
            0.0,
            500.0,
            0.0,
            500.0,
            100.0,
            400.0,
            100.0,
        ]
        annotation = BidAnnotation(
            uid=uid,
            annotation_type=annotation_type,
            page_uid="page-1",
            position=list(position),
        )
        path = QPainterPath()
        path.moveTo(400.0, 0.0)
        path.lineTo(500.0, 0.0)
        path.lineTo(500.0, 100.0)
        path.lineTo(400.0, 100.0)
        path.closeSubpath()
        item = QGraphicsPathItem(path)
        item.setData(0, uid)
        item.setZValue(1.0)
        view._scene.addItem(item)
        view._current_annotations = {uid: annotation}
        view._uid_to_items[uid] = [item]
        view._selected_uids = {uid} if selected_uids is None else set(selected_uids)
        return view, annotation

    def _capture_context_menu(self, view, x, y, action_text=None):
        CapturingMenu.instances = []
        CapturingMenu.action_text_to_return = action_text
        with (
            patch.object(input_handler_module, "QMenu", CapturingMenu),
            patch.object(
                input_handler_module,
                "add_reassign_condition_submenu",
                return_value=None,
            ),
            patch.object(
                input_handler_module,
                "add_selected_annotation_style_actions",
                return_value=SimpleNamespace(color_action=None, width_actions={}),
            ),
        ):
            InputHandlerMixin.contextMenuEvent(view, FakeContextMenuEvent(x, y))
        self.assertTrue(CapturingMenu.instances)
        return [
            action.text()
            for action in CapturingMenu.instances[0].actions
            if isinstance(action, QAction)
        ]

    def _make_overlapping_text_cycle_view(self, selected_uid="t1"):
        view = self._make_view({selected_uid})
        view._current_annotations = {
            "a1": BidAnnotation(
                uid="a1",
                annotation_type="text",
                position=[10.0, 10.0, 40.0, 20.0],
                properties={"Text": "Note"},
            )
        }
        view._current_takeoffs = {
            "t1": SimpleNamespace(position=[0.0, 0.0, 10.0, 0.0], condition_uid="c"),
            "t2": SimpleNamespace(position=[20.0, 0.0, 30.0, 0.0], condition_uid="c"),
        }
        view._uid_to_items = {
            "t1": [FakeItem(1.0, 2.0)],
            "t2": [FakeItem(3.0, 4.0)],
            "a1": [FakeItem(5.0, 6.0)],
        }
        hits = ["a1", "t1", "t2"]
        view.find_text_annotation_at = lambda _scene_pos: "a1"
        view.find_takeoffs_at = lambda _scene_pos: list(hits)
        view.find_selected_movable_at = lambda _scene_pos: (
            selected_uid if selected_uid in view._selected_uids else None
        )
        view.find_takeoff_at = lambda _scene_pos, cycle_from_uid=None: (
            hits[(hits.index(cycle_from_uid) + 1) % len(hits)]
            if cycle_from_uid in hits
            else hits[0]
        )
        view._on_selection_changed = lambda: None
        return view

    def _make_selected_text_annotation_view(self):
        view = self._make_view({"a1"})
        view._scene = QGraphicsScene()
        view._annotation_only_selection = False
        view._current_takeoffs = {}
        view._current_annotations = {
            "a1": BidAnnotation(
                uid="a1",
                annotation_type="text",
                position=[30.0, 20.0, 40.0, 20.0],
                properties={"Text": "Note"},
            )
        }
        item = QGraphicsTextItem("Note")
        item.setTextWidth(40.0)
        item.setPos(10.0, 10.0)
        item.setData(0, "a1")
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._scene_builder = FakeSceneBuilder()
        view._current_page_transform = lambda: None
        view.transform = lambda: QTransform()
        view.mapToScene = lambda point: QtCore.QPointF(point)
        view.mapFromScene = lambda point: QtCore.QPoint(int(point.x()), int(point.y()))
        del view.find_takeoff_at
        del view.find_takeoffs_at
        return view, item

    def _make_hotlink_view(self, *, selected: bool):
        view = self._make_view({"h1"} if selected else set())
        view.hotlink_clicked = FakeSignal()
        view._current_takeoffs = {}
        view._current_annotations = {
            "h1": BidAnnotation(
                uid="h1",
                annotation_type="hotlink",
                position=[10.0, 10.0],
                properties={"BidPageViewUID": "view-1"},
            )
        }
        path = QPainterPath()
        path.addEllipse(QtCore.QPointF(10.0, 10.0), 5.0, 5.0)
        item = QGraphicsPathItem(path)
        item.setData(0, "h1")
        view._uid_to_items = {"h1": [item]}
        view._hotlink_items = [
            (
                item,
                HotlinkDto(
                    uid="h1",
                    bid_page_uid="page-1",
                    target_view_uid="view-1",
                    center_x=10.0,
                    center_y=10.0,
                    radius=5.0,
                ),
            )
        ]
        view.find_takeoff_at = lambda _scene_pos, cycle_from_uid=None: None
        view.find_takeoffs_at = lambda _scene_pos: []
        view.mapToScene = lambda _point: QtCore.QPointF(10.0, 10.0)
        return view

    def _make_selected_path_takeoff_view(self):
        view = self._make_view({"t1"})
        view._scene = QGraphicsScene()
        view._annotation_only_selection = False
        view._current_conditions = {
            "c": Condition(
                uid="c",
                condition_type=Condition.TYPE_LINEAR,
                layer_visible=True,
            )
        }
        view._current_takeoffs = {
            "t1": Takeoff(
                uid="t1",
                condition_uid="c",
                position=[0.0, 0.0, 10.0, 0.0],
            )
        }
        path = QPainterPath()
        path.addRect(0.0, 0.0, 10.0, 10.0)
        item = QGraphicsPathItem(path)
        item.setData(0, "t1")
        view._scene.addItem(item)
        view._uid_to_items = {"t1": [item]}
        view.mapToScene = lambda point: QtCore.QPointF(point)
        view.mapFromScene = lambda point: QtCore.QPoint(int(point.x()), int(point.y()))
        view.transform = lambda: QTransform()
        del view.find_takeoff_at
        del view.find_takeoffs_at
        return view

    def _make_named_view_resize_view(self):
        view = InputHandlerHarness()
        view._snap_increments = 0
        ann = BidAnnotation(
            uid="nv1",
            annotation_type="namedview",
            position=[100.0, 80.0, 10.0, 20.0, 100.0, 20.0, 10.0, 80.0, 0.0],
            color="#008000",
        )
        return view, ann


class CtrlDragTests(_CtrlDragFixture):
    """InputHandlerMixin: lifecycle and combined contracts."""

    def test_three_pixel_snapped_linear_resize_commits_geometry_change(self):
        view = self._make_linear_resize_gesture_view(zoom=1.0)
        drag_latches, release = self._perform_linear_resize_gesture(view, [(3, 0)])
        expected = [0.0, 0.0, 11.0, 0.0]
        self.assertEqual(drag_latches, [False])
        self.assertTrue(release.accepted)
        self.assertEqual(view._current_takeoffs["t1"].position, expected)
        self.assertEqual(
            view.positions_flushed.emitted,
            [([("t1", [0.0, 0.0, 10.0, 0.0], expected)], [])],
        )

    def test_exactly_five_pixel_snapped_linear_resize_commits_geometry_change(self):
        view = self._make_linear_resize_gesture_view(zoom=5.0 / 3.0)
        drag_latches, _release = self._perform_linear_resize_gesture(view, [(5, 0)])
        self.assertEqual(drag_latches, [False])
        self.assertEqual(
            view._current_takeoffs["t1"].position,
            [0.0, 0.0, 11.0, 0.0],
        )
        self.assertEqual(len(view.positions_flushed.emitted), 1)

    def test_six_pixel_snapped_linear_resize_continues_to_commit(self):
        view = self._make_linear_resize_gesture_view(zoom=2.0)
        drag_latches, _release = self._perform_linear_resize_gesture(view, [(6, 0)])
        self.assertEqual(drag_latches, [True])
        self.assertEqual(
            view._current_takeoffs["t1"].position,
            [0.0, 0.0, 11.0, 0.0],
        )
        self.assertEqual(len(view.positions_flushed.emitted), 1)

    def test_linear_resize_overshoot_matches_direct_final_endpoint(self):
        direct = self._make_linear_resize_gesture_view(zoom=1.0)
        overshoot = self._make_linear_resize_gesture_view(zoom=1.0)
        direct_latches, _release = self._perform_linear_resize_gesture(direct, [(3, 0)])
        overshoot_latches, _release = self._perform_linear_resize_gesture(
            overshoot, [(6, 0), (3, 0)]
        )
        self.assertEqual(direct_latches, [False])
        self.assertEqual(overshoot_latches, [True, True])
        self.assertEqual(
            direct._current_takeoffs["t1"].position,
            overshoot._current_takeoffs["t1"].position,
        )
        self.assertEqual(
            direct.positions_flushed.emitted,
            overshoot.positions_flushed.emitted,
        )

    def test_resize_returning_to_original_geometry_reverts_without_persistence(self):
        view = self._make_linear_resize_gesture_view(zoom=1.0)
        drag_latches, release = self._perform_linear_resize_gesture(
            view, [(6, 0), (0, 0)]
        )
        self.assertEqual(drag_latches, [True, True])
        self.assertTrue(release.accepted)
        self.assertEqual(
            view._current_takeoffs["t1"].position,
            [0.0, 0.0, 10.0, 0.0],
        )
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_resize_handle_click_without_geometry_change_remains_a_click(self):
        view = self._make_linear_resize_gesture_view(zoom=1.0)
        drag_latches, release = self._perform_linear_resize_gesture(view, [])
        self.assertEqual(drag_latches, [])
        self.assertTrue(release.accepted)
        self.assertEqual(view._selected_uids, {"t1"})
        self.assertEqual(
            view._current_takeoffs["t1"].position,
            [0.0, 0.0, 10.0, 0.0],
        )
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_small_body_drag_commits_changed_snapped_geometry(self):
        view = self._make_linear_resize_gesture_view(zoom=1.0)
        view._is_handle_info_at_viewport_pos = lambda _info, _pos: False
        drag_latches, _release = self._perform_linear_resize_gesture(view, [(3, 0)])
        self.assertEqual(drag_latches, [True])
        self.assertEqual(
            view._current_takeoffs["t1"].position,
            [1.0, 0.0, 11.0, 0.0],
        )
        self.assertEqual(
            view.positions_flushed.emitted,
            [([("t1", [0.0, 0.0, 10.0, 0.0], [1.0, 0.0, 11.0, 0.0])], [])],
        )

    def test_angled_resize_is_consistent_across_page_scale_and_zoom(self):
        configurations = (
            {"scale_ratio": 48.0, "zoom": 5.0 / 3.0},
            {"scale_ratio": 96.0, "zoom": 10.0 / 3.0},
        )
        results = []
        for configuration in configurations:
            with self.subTest(**configuration):
                view = self._make_linear_resize_gesture_view(
                    **configuration,
                    position=[0.0, 0.0, 6.0, 8.0],
                    snap_increment=0.1,
                )
                drag_latches, _release = self._perform_linear_resize_gesture(
                    view, [(3, 4)]
                )
                self.assertEqual(drag_latches, [False])
                self.assertEqual(len(view.positions_flushed.emitted), 1)
                result = view._current_takeoffs["t1"].position
                self.assertAlmostEqual(result[2], 6.6)
                self.assertAlmostEqual(result[3], 8.8)
                results.append(result)
        self.assertEqual(results[0], results[1])

    def test_context_menu_shows_add_control_point_only_for_edge_target(self):
        view = self._make_area_control_point_view()
        texts = self._capture_context_menu(view, 50.0, 0.0)
        self.assertIn("Add Control Point", texts)
        self.assertNotIn("Subtract Control Point", texts)

    def test_context_menu_shows_subtract_control_point_only_for_vertex_target(self):
        view = self._make_area_control_point_view()
        texts = self._capture_context_menu(view, 0.0, 0.0)
        self.assertIn("Subtract Control Point", texts)
        self.assertNotIn("Add Control Point", texts)

    def test_context_menu_shows_add_control_point_for_hole_edge_target(self):
        view = self._make_area_control_point_view(include_hole=True)
        texts = self._capture_context_menu(view, 30.0, 20.0)
        self.assertIn("Add Control Point", texts)
        self.assertNotIn("Subtract Control Point", texts)

    def test_context_menu_shows_subtract_control_point_for_hole_vertex_target(self):
        view = self._make_area_control_point_view(include_hole=True)
        texts = self._capture_context_menu(view, 20.0, 20.0)
        self.assertIn("Subtract Control Point", texts)
        self.assertNotIn("Add Control Point", texts)

    def test_context_menu_uses_actual_hit_not_stale_selected_area(self):
        view = self._make_area_control_point_view({"area1"})
        texts = self._capture_context_menu(view, 50.0, 50.0)
        self.assertNotIn("Add Control Point", texts)
        self.assertNotIn("Subtract Control Point", texts)

    def test_context_menu_uses_actual_hole_hit_not_parent_selection(self):
        view = self._make_area_control_point_view({"area1"}, include_hole=True)
        self._capture_context_menu(view, 30.0, 20.0, action_text="Add Control Point")
        self.assertEqual(
            view._current_takeoffs["hole1"].position, AREA_CP_HOLE_ADDED_POSITION
        )
        self.assertEqual(
            view._current_takeoffs["area1"].position, AREA_CP_ORIGINAL_POSITION
        )

    def test_context_menu_add_control_point_uses_existing_flush_path(self):
        view = self._make_area_control_point_view()
        old_pos = list(view._current_takeoffs["area1"].position)
        self._capture_context_menu(view, 50.0, 0.0, action_text="Add Control Point")
        new_pos = list(AREA_CP_ADDED_POSITION)
        self.assertEqual(
            view.positions_flushed.emitted,
            [([("area1", old_pos, new_pos)], [])],
        )

    def test_context_menu_subtract_control_point_uses_existing_flush_path(self):
        view = self._make_area_control_point_view()
        old_pos = list(view._current_takeoffs["area1"].position)
        self._capture_context_menu(view, 0.0, 0.0, action_text="Subtract Control Point")
        new_pos = list(AREA_CP_SUBTRACTED_FIRST_VERTEX_POSITION)
        self.assertEqual(
            view.positions_flushed.emitted,
            [([("area1", old_pos, new_pos)], [])],
        )

    def test_context_menu_rejects_takeoff_action_after_same_uid_page_replacement(self):
        view = self._make_area_control_point_view({"area1"})
        view._current_bid_ref = BidRef("db.mdb", "bid-1")
        view._current_page = Page(uid="page-1", name="Original")
        view.assign_to_area_requested = FakeSignal()
        view._context_menu_action_state = lambda _key: {"enabled": True}

        class ReplacingMenu(CapturingMenu):
            def exec(self, _pos):
                view._current_page = Page(uid="page-1", name="Replacement")
                return next(
                    action
                    for action in self.actions
                    if isinstance(action, QAction)
                    and action.text() == "Assign to Current Area"
                )

        with (
            patch.object(input_handler_module, "QMenu", ReplacingMenu),
            patch.object(
                input_handler_module,
                "add_reassign_condition_submenu",
                return_value=None,
            ),
        ):
            InputHandlerMixin.contextMenuEvent(view, FakeContextMenuEvent(50, 50))
        self.assertEqual(view.assign_to_area_requested.emitted, [])

    def test_context_menu_rejects_takeoff_action_after_edit_access_loss(self):
        view = self._make_area_control_point_view({"area1"})
        view._current_bid_ref = BidRef("db.mdb", "bid-1")
        view._current_page = Page(uid="page-1", name="Page")
        view.assign_to_area_requested = FakeSignal()
        access = {"enabled": True}
        view._context_menu_action_state = lambda _key: dict(access)

        class RevokingMenu(CapturingMenu):
            def exec(self, _pos):
                access["enabled"] = False
                return next(
                    action
                    for action in self.actions
                    if isinstance(action, QAction)
                    and action.text() == "Assign to Current Area"
                )

        with (
            patch.object(input_handler_module, "QMenu", RevokingMenu),
            patch.object(
                input_handler_module,
                "add_reassign_condition_submenu",
                return_value=None,
            ),
        ):
            InputHandlerMixin.contextMenuEvent(view, FakeContextMenuEvent(50, 50))
        self.assertEqual(view.assign_to_area_requested.emitted, [])

    def test_queued_context_command_rejects_replaced_page_owner(self):
        view = self._make_area_control_point_view()
        view._current_bid_ref = BidRef("db.mdb", "bid-1")
        view._current_page = Page(uid="page-1", name="Original")
        triggered = []
        view._context_menu_command_trigger = triggered.append
        view._context_menu_action_state = lambda _key: {"enabled": True}
        menu = QMenu()
        InputHandlerMixin._add_context_command(view, menu, "Delete", "delete")
        action = menu.actions()[0]
        view._current_page = Page(uid="page-1", name="Replacement")
        action.trigger()
        self.assertEqual(triggered, [])

    def test_polygon_and_cloud_annotations_expose_existing_control_point_actions(self):
        for annotation_type in (ANNOTATION_TYPE_POLYGON, ANNOTATION_TYPE_CLOUD):
            with self.subTest(annotation_type=annotation_type):
                view, annotation = self._make_annotation_control_point_view(
                    annotation_type
                )
                add_texts = self._capture_context_menu(view, 450.0, 0.0)
                subtract_texts = self._capture_context_menu(view, 400.0, 0.0)
                self.assertIn("Add Control Point", add_texts)
                self.assertNotIn("Subtract Control Point", add_texts)
                self.assertIn("Subtract Control Point", subtract_texts)
                self.assertNotIn("Add Control Point", subtract_texts)
                self.assertEqual(view._selected_uids, {annotation.uid})

    def test_context_annotation_style_rejects_edit_access_loss(self):
        view, annotation = self._make_annotation_control_point_view(
            ANNOTATION_TYPE_POLYGON
        )
        owner = view._context_menu_owner()
        applied = []
        view.apply_annotation_style_to_selection = lambda **values: applied.append(
            values
        )
        view._context_menu_action_state = lambda _key: {"enabled": False}
        view._apply_context_annotation_width(owner, {annotation.uid: annotation}, 6.0)
        self.assertEqual(applied, [])

    def test_polygon_and_cloud_add_control_point_use_annotation_flush_path(self):
        for annotation_type in (ANNOTATION_TYPE_POLYGON, ANNOTATION_TYPE_CLOUD):
            with self.subTest(annotation_type=annotation_type):
                view, annotation = self._make_annotation_control_point_view(
                    annotation_type
                )
                old_pos = list(annotation.position)
                self._capture_context_menu(
                    view, 450.0, 0.0, action_text="Add Control Point"
                )
                new_pos = [
                    400.0,
                    0.0,
                    450.0,
                    0.0,
                    500.0,
                    0.0,
                    500.0,
                    100.0,
                    400.0,
                    100.0,
                ]
                self.assertEqual(annotation.position, new_pos)
                self.assertEqual(
                    view.positions_flushed.emitted,
                    [([], [(annotation.uid, annotation_type, old_pos, new_pos)])],
                )
                self.assertEqual(view.rebuild_count, 1)
                self.assertEqual(view.selection_update_count, 1)
                self.assertEqual(view._selected_uids, {annotation.uid})

    def test_non_polygon_annotations_do_not_expose_control_point_actions(self):
        for annotation_type in ("text", "dimension", "line", "rect", "oval"):
            with self.subTest(annotation_type=annotation_type):
                view, _annotation = self._make_annotation_control_point_view(
                    annotation_type
                )
                self.assertIsNone(
                    view.polygon_control_point_target_at(QtCore.QPointF(450.0, 0.0))
                )
                texts = self._capture_context_menu(view, 450.0, 0.0)
                self.assertNotIn("Add Control Point", texts)
                self.assertNotIn("Subtract Control Point", texts)

    def test_polygon_control_points_respect_visibility_and_editability(self):
        view, annotation = self._make_annotation_control_point_view(
            ANNOTATION_TYPE_POLYGON
        )
        annotation.visible = False
        self.assertIsNone(
            view.polygon_control_point_target_at(QtCore.QPointF(450.0, 0.0))
        )
        annotation.visible = True
        view._editing_enabled = False
        texts = self._capture_context_menu(view, 450.0, 0.0)
        self.assertNotIn("Add Control Point", texts)
        self.assertNotIn("Subtract Control Point", texts)

    def test_mixed_selection_does_not_expose_polygon_control_point_actions(self):
        view, annotation = self._make_annotation_control_point_view(
            ANNOTATION_TYPE_POLYGON, {"area1", "polygon1"}
        )
        texts = self._capture_context_menu(view, 450.0, 50.0)
        self.assertNotIn("Add Control Point", texts)
        self.assertNotIn("Subtract Control Point", texts)
        self.assertEqual(view._selected_uids, {"area1", annotation.uid})

    def test_selected_hotlink_hover_uses_move_cursor(self):
        view = self._make_hotlink_view(selected=True)
        cursor = view._resolve_select_cursor(QtCore.QPoint(10, 10))
        self.assertEqual(cursor, Qt.CursorShape.SizeAllCursor)

    def test_real_hotlink_click_after_placement_release_still_opens(self):
        view = self._make_hotlink_view(selected=False)
        view._cursor_mode = "annotation_place"
        view._annotation_place_type = "hotlink"
        view.annotation_place_release_consumed = True
        placement_release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(placement_release)
        self.assertFalse(view.annotation_place_release_consumed)
        view._cursor_mode = "select"
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        click_release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(click_release)
        self.assertTrue(click_release.accepted)
        self.assertEqual(len(view.hotlink_clicked.emitted), 1)

    def test_selected_takeoff_hover_far_away_does_not_use_move_cursor(self):
        view = self._make_selected_path_takeoff_view()
        cursor = view._resolve_select_cursor(QtCore.QPoint(100, 100))
        self.assertEqual(cursor, Qt.CursorShape.ArrowCursor)

    def test_selected_takeoff_hover_on_hit_area_uses_move_cursor(self):
        view = self._make_selected_path_takeoff_view()
        cursor = view._resolve_select_cursor(QtCore.QPoint(5, 5))
        self.assertEqual(cursor, Qt.CursorShape.SizeAllCursor)

    def test_rotate_mode_uses_normal_hover_cursors_except_rotate_handle(self):
        view = self._make_selected_path_takeoff_view()
        view._cursor_mode = "rotate"
        view._rotate_handle_item = FakeItem(0.0, 0.0)
        self.assertEqual(
            view._resolve_cursor(QtCore.QPoint(100, 100)),
            Qt.CursorShape.ArrowCursor,
        )
        view._rotate_handle_item = FakeItem(100.0, 100.0)
        self.assertEqual(
            view._resolve_cursor(QtCore.QPoint(5, 5)),
            Qt.CursorShape.SizeAllCursor,
        )
        view._rotate_handle_item = FakeItem(5.0, 5.0)
        self.assertEqual(
            view._resolve_cursor(QtCore.QPoint(5, 5)),
            Qt.CursorShape.CrossCursor,
        )

    def test_rotate_mode_update_cursor_uses_live_viewport_pos_not_stale_hover(self):
        view = self._make_selected_path_takeoff_view()
        view._cursor_mode = "rotate"
        view._last_mouse_vp_pos = QtCore.QPoint(5, 5)
        view._rotate_handle_item = FakeItem(0.0, 0.0)
        viewport = FakeCursorViewport()
        view.viewport = lambda: viewport
        with patch.object(
            input_handler_module,
            "QCursor",
            SimpleNamespace(pos=lambda: QtCore.QPoint(100, 100)),
        ):
            InputHandlerMixin._update_cursor(view)
        self.assertEqual(viewport.cursor, Qt.CursorShape.ArrowCursor)

    def test_stale_move_drag_index_does_not_force_move_cursor_without_active_press(
        self,
    ):
        view = self._make_selected_path_takeoff_view()
        view._drag_handle_index = -1
        cursor = view._resolve_cursor(QtCore.QPoint(100, 100))
        self.assertEqual(cursor, Qt.CursorShape.ArrowCursor)

    def test_pan_update_accepts_viewport_origin_as_previous_point(self):
        view = self._make_view()
        view._panning = True
        view._last_pan_point = QtCore.QPoint(0, 0)
        horizontal_values = []
        vertical_values = []
        horizontal = SimpleNamespace(
            value=lambda: 10,
            setValue=horizontal_values.append,
        )
        vertical = SimpleNamespace(
            value=lambda: 20,
            setValue=vertical_values.append,
        )
        view.horizontalScrollBar = lambda: horizontal
        view.verticalScrollBar = lambda: vertical
        user_changes = []
        view._mark_user_view_changed_during_load = lambda: user_changes.append(True)
        self.assertTrue(view._apply_pan_update(QtCore.QPoint(3, 4)))
        self.assertEqual(horizontal_values, [7])
        self.assertEqual(vertical_values, [16])
        self.assertEqual(view._last_pan_point, QtCore.QPoint(3, 4))
        self.assertEqual(user_changes, [True])

    def test_zero_vertical_wheel_delta_does_not_zoom(self):
        view = self._make_view()
        calls = []
        view._mark_user_view_changed_during_load = lambda: calls.append("changed")
        view._apply_zoom = lambda _factor: calls.append("zoom")
        view._publish_current_page_view_state = lambda: calls.append("publish")
        view._apply_wheel_zoom(FakeWheelEvent(), 0)
        self.assertEqual(calls, [])

    def test_selected_text_annotation_cursor_only_moves_over_text_bounds(self):
        view, _item = self._make_selected_text_annotation_view()
        self.assertEqual(
            view._resolve_select_cursor(QtCore.QPoint(20, 20)),
            Qt.CursorShape.SizeAllCursor,
        )
        self.assertEqual(
            view._resolve_select_cursor(QtCore.QPoint(200, 200)),
            Qt.CursorShape.ArrowCursor,
        )

    def test_stale_drag_state_clears_when_mouse_moves_without_left_button(self):
        view = self._make_view()
        overlay = view._uid_to_items["t1"][0]
        overlay_orig = overlay.pos()
        overlay.setPos(25.0, 30.0)
        view._drag_plan_item_uid = "t1"
        view._drag_handle_index = -1
        view._drag_orig_position = [0.0, 0.0, 10.0, 0.0]
        view._drag_item_orig_positions = {id(overlay): overlay_orig}
        view._select_band_origin = QtCore.QPointF(10.0, 10.0)
        move = FakeMouseEvent(x=200, y=200, buttons=Qt.MouseButton.NoButton)
        view.mouseMoveEvent(move)
        self.assertIsNone(view._drag_plan_item_uid)
        self.assertEqual(view._drag_handle_index, -2)
        self.assertIsNone(view._select_band_origin)
        self.assertEqual(overlay.pos(), overlay_orig)

    def test_double_click_text_annotation_enters_inline_edit_without_dragging(self):
        view, _item = self._make_selected_text_annotation_view()
        press = FakeMouseEvent(x=20, y=20)
        view.mouseDoubleClickEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(view.selected_text_annotation_uids, ["a1"])
        self.assertEqual(view.editing_text_annotation_uids, ["a1"])
        self.assertIsNone(view._drag_plan_item_uid)

    def test_double_click_named_view_label_enters_rename_without_text_toolbar(self):
        view = self._make_view({"nv1"})
        label = QGraphicsTextItem("Named View")
        label.setData(0, "nv1")
        label.setData(2, NAMED_VIEW_LABEL_ITEM_KIND)
        view._named_view_label_at = lambda _pos: label
        view._current_annotations = {
            "nv1": BidAnnotation(uid="nv1", annotation_type="namedview")
        }
        press = FakeMouseEvent(x=20, y=20)
        view.mouseDoubleClickEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(view.editing_named_view_uids, ["nv1"])
        self.assertEqual(view.editing_text_annotation_uids, [])
        self.assertEqual(view.selected_text_annotation_uids, [])
        self.assertIsNone(view._drag_plan_item_uid)

    def test_ctrl_zoom_release_restores_temporary_overlay_and_handle_positions(self):
        view = self._make_view()
        overlay = view._uid_to_items["t1"][0]
        handle = FakeItem(5.0, 6.0)
        view._selection_items = [handle]
        overlay_orig = overlay.pos()
        handle_orig = handle.pos()
        overlay.setPos(21.0, 22.0)
        handle.setPos(25.0, 26.0)
        view._drag_plan_item_uid = "t1"
        view._drag_item_orig_positions = {
            id(overlay): overlay_orig,
            id(handle): handle_orig,
        }
        view._ctrl_held = True
        view._zoom_press_ctrl = True
        InputHandlerMixin.keyReleaseEvent(view, FakeKeyEvent())
        self.assertEqual(overlay.pos(), overlay_orig)
        self.assertEqual(handle.pos(), handle_orig)
        self.assertIsNone(view._drag_plan_item_uid)
        self.assertEqual(view._drag_item_orig_positions, {})

    def test_sql_selection_refreshes_move_cursor_before_async_lease(self):
        view = self._make_view(set())
        viewport = FakeCursorViewport()
        view.viewport = lambda: viewport
        view.find_selected_movable_at = lambda _scene_pos: (
            "t1" if "t1" in view._selected_uids else None
        )
        view._update_cursor = lambda vp_pos=None: InputHandlerMixin._update_cursor(
            view, vp_pos
        )
        view.request_geometry_edit_lease = lambda _uids: False
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(view._selected_uids, {"t1"})
        self.assertEqual(viewport.cursor, Qt.CursorShape.SizeAllCursor)

    def test_multi_rotation_commits_compact_rect_as_rotated_corners(self):
        view = self._make_view({"rect1"})
        annotation = BidAnnotation(
            uid="rect1",
            annotation_type="rect",
            position=[0.0, 0.0, 10.0, 4.0],
        )
        view._current_takeoffs = {}
        view._current_annotations = {"rect1": annotation}
        view._rotation_drag_orig_positions = {"rect1": list(annotation.position)}
        view._position_before_edit = {}
        view._dirty_positions = {}
        view._dirty_ann_positions = {}
        view._dirty_rotations = {}
        view._rotation_before_edit = {}
        view._rotate_ost_center = (20.0, 20.0)
        view._flush_rotation_group = lambda: None
        view._apply_multi_rotation(90.0)
        new_position = annotation.position
        self.assertEqual(len(new_position), 9)
        self.assertAlmostEqual(new_position[-1], math.pi / 2.0)
        self.assertEqual(
            self._rendered_box_side_lengths(new_position),
            [4.0, 4.0, 10.0, 10.0],
        )
        self.assertEqual(
            view._dirty_ann_positions["rect1"],
            ("rect", new_position),
        )

    def test_multi_rotation_commits_compact_highlight_as_rotated_corners(self):
        view = self._make_view({"highlight1"})
        annotation = BidAnnotation(
            uid="highlight1",
            annotation_type="highlight",
            position=[0.0, 0.0, 12.0, 3.0],
        )
        view._current_takeoffs = {}
        view._current_annotations = {"highlight1": annotation}
        view._rotation_drag_orig_positions = {"highlight1": list(annotation.position)}
        view._position_before_edit = {}
        view._dirty_positions = {}
        view._dirty_ann_positions = {}
        view._dirty_rotations = {}
        view._rotation_before_edit = {}
        view._rotate_ost_center = (20.0, 20.0)
        view._flush_rotation_group = lambda: None
        view._apply_multi_rotation(90.0)
        new_position = annotation.position
        self.assertEqual(len(new_position), 9)
        self.assertAlmostEqual(new_position[-1], math.pi / 2.0)
        self.assertEqual(
            self._rendered_box_side_lengths(new_position),
            [3.0, 3.0, 12.0, 12.0],
        )
        self.assertEqual(
            view._dirty_ann_positions["highlight1"],
            ("highlight", new_position),
        )

    def test_rotated_annotation_resize_press_defers_write_and_cancel_restores(self):
        view = self._make_view({"a1"})
        original = [
            0.0,
            0.0,
            10.0,
            0.0,
            10.0,
            4.0,
            0.0,
            4.0,
            math.radians(30.0),
        ]
        ann = BidAnnotation(
            uid="a1",
            annotation_type="rect",
            position=list(original),
        )
        view._current_takeoffs = {}
        view._current_annotations = {"a1": ann}
        view._drag_plan_item_uid = "a1"
        view._drag_orig_position = list(original)
        view._flush_dirty_positions = lambda: self.fail(
            "resize press must not persist before movement"
        )
        view._unrotate_annotation_for_resize(ann, "a1")
        self.assertNotEqual(ann.position, original)
        self.assertEqual(view._position_before_edit["a1"], original)
        self.assertEqual(view._dirty_ann_positions, {})
        view._clear_drag_tracking(restore_preview=True)
        self.assertEqual(ann.position, original)
        self.assertNotIn("a1", view._position_before_edit)

    def test_ink_annotation_drag_translates_even_path_points_once(self):
        view = InputHandlerHarness()
        view._snap_increments = 0
        original = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
        moved = view._compute_ink_drag_position(original, 3.0, -4.0)
        self.assertEqual(moved, [13.0, 16.0, 33.0, 36.0, 53.0, 56.0])
        self.assertEqual(original, [10.0, 20.0, 30.0, 40.0, 50.0, 60.0])

    def test_ink_annotation_drag_preserves_rotation_prefix(self):
        view = InputHandlerHarness()
        view._snap_increments = 0
        original = [0.25, 10.0, 20.0, 30.0, 40.0]
        moved = view._compute_ink_drag_position(original, 3.0, -4.0)
        self.assertEqual(moved, [0.25, 13.0, 16.0, 33.0, 36.0])

    def test_multi_drag_ink_preview_delta_uses_first_path_point(self):
        view = InputHandlerHarness()
        view._snap_increments = 0
        view._scene_builder = FakeSceneBuilder()
        view._current_page_transform = lambda: None
        annotation = BidAnnotation(
            uid="ink1",
            annotation_type="ink",
            position=[0.25, 10.0, 20.0, 30.0, 40.0],
        )
        view._current_annotations = {"ink1": annotation}
        moved = view._translate_group_plan_item_position(
            "ink1", annotation.position, 3.0, -4.0
        )
        self.assertEqual(moved, [0.25, 13.0, 16.0, 33.0, 36.0])
        delta = view._snapped_multi_drag_scene_delta(
            "ink1", annotation.position, moved, 100.0, 200.0
        )
        expected_dx, expected_dy = view.ost_to_scene_delta(3.0, -4.0)
        self.assertEqual(delta, QtCore.QPointF(expected_dx, expected_dy))

    def test_ink_drag_snaps_the_first_point_and_ignores_empty_paths(self):
        view = InputHandlerHarness()
        view._snap_increments = 5.0
        self.assertEqual(
            view._compute_ink_drag_position([0.25, 10.0, 20.0, 30.0, 40.0], 3.0, -4.0),
            [0.25, 15.0, 15.0, 35.0, 35.0],
        )
        self.assertEqual(view._compute_ink_drag_position([0.25], 3.0, 3.0), [0.25])
        self.assertEqual(view._compute_ink_drag_position([], 3.0, 3.0), [])
        self.assertEqual(view._compute_ink_drag_position([7.0], 3.0, 3.0), [7.0])

    def test_group_translation_moves_each_annotation_kind_by_its_own_anchor_rule(self):
        view = InputHandlerHarness()
        view._current_annotations = {
            "text": BidAnnotation(uid="text", annotation_type="text"),
            "ink": BidAnnotation(uid="ink", annotation_type="ink"),
            "rect": BidAnnotation(uid="rect", annotation_type="rect"),
        }
        translate = view._translate_group_plan_item_position
        self.assertEqual(
            translate("text", [10.0, 10.0, 40.0, 20.0, 0.5], 3.0, -4.0),
            [13.0, 6.0, 40.0, 20.0, 0.5],
        )
        self.assertEqual(translate("text", [10.0], 3.0, -4.0), [10.0])
        self.assertEqual(
            translate("ink", [0.25, 10.0, 20.0, 30.0, 40.0], 3.0, -4.0),
            [0.25, 13.0, 16.0, 33.0, 36.0],
        )
        self.assertEqual(
            translate("ink", [10.0, 20.0, 30.0, 40.0], 3.0, -4.0),
            [13.0, 16.0, 33.0, 36.0],
        )
        self.assertEqual(
            translate("rect", [0.0, 0.0, 10.0, 4.0], 3.0, -4.0),
            [3.0, -4.0, 13.0, 0.0],
        )
        self.assertEqual(translate("missing", [1.0, 2.0], 3.0, -4.0), [4.0, -2.0])

    def test_scene_delta_uses_fallback_when_positions_are_too_short(self):
        view = InputHandlerHarness()
        view._scene_builder = FakeSceneBuilder()
        view._current_page_transform = lambda: None
        view._current_annotations = {
            "ink": BidAnnotation(uid="ink", annotation_type="ink")
        }
        scene_delta = view._snapped_multi_drag_scene_delta
        self.assertEqual(
            scene_delta("ink", [0.25], [0.25], 7.0, 9.0), QtCore.QPointF(7.0, 9.0)
        )
        self.assertEqual(
            scene_delta("t1", [1.0], [2.0], 7.0, 9.0), QtCore.QPointF(7.0, 9.0)
        )
        self.assertEqual(
            scene_delta("t1", [1.0, 1.0], [2.0, 4.0], 7.0, 9.0),
            QtCore.QPointF(*view.ost_to_scene_delta(1.0, 3.0)),
        )

    def test_selection_borders_without_a_computed_delta_follow_the_group_fallback(self):
        view = InputHandlerHarness()
        view._snap_increments = 1.0
        view._scene_builder = FakeSceneBuilder()
        view._current_page_transform = lambda: None
        view._current_annotations = {}
        view._current_takeoffs = {
            "t1": Takeoff(uid="t1", condition_uid="c", position=[0.0, 0.0, 10.0, 0.0])
        }
        view._current_conditions = {}
        item = FakeItem(100.0, 100.0)
        orphan_border = FakeItem(300.0, 300.0, uid="ghost")
        view._uid_to_items = {"t1": [item]}
        view._selection_items = [orphan_border]
        view._drag_multi_orig_positions = {"t1": [0.0, 0.0, 10.0, 0.0]}
        view._drag_item_orig_positions = {
            id(item): QtCore.QPointF(100.0, 100.0),
            id(orphan_border): QtCore.QPointF(300.0, 300.0),
        }
        expected = QtCore.QPointF(*view.ost_to_scene_delta(3.0, 2.0))
        changed = view._update_snapped_multi_drag_preview(1.0, 1.0, 3.0, 2.0)
        self.assertTrue(changed)
        self.assertEqual(item.pos(), QtCore.QPointF(100.0, 100.0) + expected)
        self.assertEqual(orphan_border.pos(), QtCore.QPointF(300.0, 300.0) + expected)
        view._selection_items = [FakeItem(1.0, 1.0, uid="ghost2")]
        view._drag_item_orig_positions[id(view._selection_items[0])] = QtCore.QPointF(
            1.0, 1.0
        )
        border = view._selection_items[0]
        view._move_selection_items_by_uid_delta({}, QtCore.QPointF(4.0, 5.0))
        self.assertEqual(border.pos(), QtCore.QPointF(5.0, 6.0))
        view._move_selection_items_by_uid_delta(
            {"ghost2": QtCore.QPointF(1.0, 1.0)}, QtCore.QPointF(4.0, 5.0)
        )
        self.assertEqual(border.pos(), QtCore.QPointF(6.0, 7.0))

    def test_unchanged_group_preview_reports_no_change(self):
        view = InputHandlerHarness()
        view._snap_increments = 10.0
        view._scene_builder = FakeSceneBuilder()
        view._current_page_transform = lambda: None
        view._current_annotations = {}
        view._current_takeoffs = {
            "t1": Takeoff(uid="t1", condition_uid="c", position=[0.0, 0.0, 10.0, 0.0])
        }
        view._current_conditions = {}
        view._uid_to_items = {"t1": [FakeItem(0.0, 0.0)]}
        view._selection_items = []
        view._drag_multi_orig_positions = {"t1": [0.0, 0.0, 10.0, 0.0]}
        view._drag_item_orig_positions = {}
        self.assertFalse(view._update_snapped_multi_drag_preview(1.0, 1.0, 3.0, 2.0))
        self.assertTrue(view._update_snapped_multi_drag_preview(6.0, 6.0, 6.0, 6.0))

    def test_area_child_parent_map_follows_nested_area_ancestry_only(self):
        view = InputHandlerHarness()
        view._current_conditions = {
            "area": Condition(uid="area", condition_type=Condition.TYPE_AREA),
            "linear": Condition(uid="linear", condition_type=Condition.TYPE_LINEAR),
        }

        def takeoff(uid, condition, parent=None):
            options = {"parent_uid": parent} if parent is not None else {}
            return Takeoff(
                uid=uid,
                condition_uid=condition,
                position=[0.0, 0.0, 1.0, 0.0, 1.0, 1.0],
                **options,
            )

        view._current_takeoffs = {
            "A": takeoff("A", "area"),
            "B": takeoff("B", "area", "A"),
            "C": takeoff("C", "area", "B"),
            "L": takeoff("L", "linear", "A"),
        }
        self.assertEqual(
            view._area_child_parent_map({"A"}), {"B": "A", "C": "A", "L": "A"}
        )
        self.assertEqual(view._area_child_parent_map({"B"}), {"C": "B"})
        self.assertEqual(
            view._area_child_parent_map({"A", "B"}), {"B": "A", "C": "A", "L": "A"}
        )
        self.assertEqual(
            view._area_child_parent_map({"A"}, child_uids={"C"}), {"C": "A"}
        )
        self.assertEqual(view._area_child_parent_map({"A"}, child_uids={"ghost"}), {})
        self.assertEqual(view._area_child_parent_map(set()), {})

    def test_area_child_parent_map_stops_at_non_area_ancestors_and_cycles(self):
        view = InputHandlerHarness()
        view._current_conditions = {
            "area": Condition(uid="area", condition_type=Condition.TYPE_AREA),
            "linear": Condition(uid="linear", condition_type=Condition.TYPE_LINEAR),
        }
        view._current_takeoffs = {
            "L": Takeoff(uid="L", condition_uid="linear", position=[0.0] * 4),
            "X": Takeoff(
                uid="X", condition_uid="area", parent_uid="L", position=[0.0] * 6
            ),
            "P": Takeoff(
                uid="P", condition_uid="area", parent_uid="Q", position=[0.0] * 6
            ),
            "Q": Takeoff(
                uid="Q", condition_uid="area", parent_uid="P", position=[0.0] * 6
            ),
        }
        self.assertEqual(view._area_child_parent_map({"L"}, child_uids={"X"}), {})
        self.assertEqual(view._area_child_parent_map({"P"}), {"Q": "P"})


class InputHandlerMixinFlipSelectedTakeoffsTests(_CtrlDragFixture):
    """InputHandlerMixin.flip_selected_takeoffs."""

    def test_each_takeoff_type_flips_about_its_complete_footprint(self):
        for uid in ("linear", "count", "area", "attachment"):
            for horizontal in (True, False):
                with self.subTest(uid=uid, horizontal=horizontal):
                    view = self._make_transform_view({uid})
                    before = self._rendered_takeoff_selection_bounds(view, {uid})
                    self._flip_and_assert_reflection(view, {uid}, horizontal)
                    after = self._rendered_takeoff_selection_bounds(view, {uid})
                    self._assert_bounds_almost_equal(before, after)

    def test_every_pairwise_type_flip_preserves_group_bounds(self):
        takeoff_types = ("linear", "count", "area", "attachment")
        for selected in combinations(takeoff_types, 2):
            for horizontal in (True, False):
                with self.subTest(selected=selected, horizontal=horizontal):
                    view = self._make_transform_view(set(selected))
                    before = self._rendered_takeoff_selection_bounds(view, selected)
                    self._flip_and_assert_reflection(view, set(selected), horizontal)
                    after = self._rendered_takeoff_selection_bounds(view, selected)
                    self._assert_bounds_almost_equal(before, after)

    def test_full_mixed_flip_reflects_every_authoritative_footprint_once(self):
        selected = {"linear", "count", "area", "attachment"}
        for horizontal in (True, False):
            with self.subTest(horizontal=horizontal):
                view = self._make_transform_view(selected)
                left, top, right, bottom = self._rendered_takeoff_selection_bounds(
                    view, selected
                )
                pivot_x = (left + right) / 2.0
                pivot_y = (top + bottom) / 2.0
                before = {uid: self._takeoff_vertices(view, uid) for uid in selected}
                view.flip_selected_takeoffs(horizontal)
                for uid in selected:
                    expected = [
                        (
                            2.0 * pivot_x - x if horizontal else x,
                            y if horizontal else 2.0 * pivot_y - y,
                        )
                        for x, y in before[uid]
                    ]
                    self._assert_vertices_almost_equal(
                        expected,
                        self._takeoff_vertices(view, uid),
                    )

    def test_full_mixed_flip_keeps_rendered_selection_in_place(self):
        selected = {"linear", "count", "area", "attachment"}
        for horizontal in (True, False):
            with self.subTest(horizontal=horizontal):
                view = self._make_transform_view(selected)
                before = self._rendered_takeoff_selection_bounds(view, selected)
                view.flip_selected_takeoffs(horizontal)
                after = self._rendered_takeoff_selection_bounds(view, selected)
                self._assert_bounds_almost_equal(before, after)

    def test_rotated_count_size_matrix_cannot_shift_flip_pivot(self):
        for rotation_degrees in (0.0, 27.0, 90.0, 143.0):
            for display_size in (10.0, 25.0, 50.0, 100.0, 175.0):
                for horizontal in (True, False):
                    with self.subTest(
                        rotation=rotation_degrees,
                        display_size=display_size,
                        horizontal=horizontal,
                    ):
                        view = self._make_transform_view({"area", "count"})
                        view._current_takeoffs["count"].rotation = math.radians(
                            rotation_degrees
                        )
                        view._current_conditions["count"].display_size = display_size
                        rendered_before = self._rendered_takeoff_selection_bounds(
                            view, {"area", "count"}
                        )
                        view.flip_selected_takeoffs(horizontal)
                        rendered_after = self._rendered_takeoff_selection_bounds(
                            view, {"area", "count"}
                        )
                        self._assert_bounds_almost_equal(
                            rendered_before,
                            rendered_after,
                        )

    def test_curved_linear_and_count_flip_preserves_group_bounds(self):
        for horizontal in (True, False):
            with self.subTest(horizontal=horizontal):
                selected = {"linear", "count"}
                view = self._make_transform_view(selected)
                view._current_takeoffs["linear"].position = [
                    0.0,
                    0.0,
                    20.0,
                    0.0,
                    10.0,
                    8.0,
                    0.0,
                ]
                view._current_takeoffs["linear"].curve = Takeoff.CURVE_ENABLED
                view._current_conditions["linear"].thickness = 0.25
                before = self._rendered_takeoff_selection_bounds(view, selected)
                view.flip_selected_takeoffs(horizontal)
                after = self._rendered_takeoff_selection_bounds(view, selected)
                self._assert_bounds_almost_equal(before, after)

    def test_curved_linear_flip_reflects_signed_offset_footprint(self):
        selected = {"linear", "count"}
        for horizontal in (True, False):
            with self.subTest(horizontal=horizontal):
                view = self._make_transform_view(selected)
                linear = view._current_takeoffs["linear"]
                linear.position = [0.0, 0.0, 20.0, 0.0, 10.0, 8.0, -8.0]
                linear.curve = Takeoff.CURVE_ENABLED
                left, top, right, bottom = self._rendered_takeoff_selection_bounds(
                    view, selected
                )
                pivot_x = (left + right) / 2.0
                pivot_y = (top + bottom) / 2.0
                before = self._takeoff_vertices(view, "linear")
                view.flip_selected_takeoffs(horizontal)
                expected = [
                    (
                        2.0 * pivot_x - x if horizontal else x,
                        y if horizontal else 2.0 * pivot_y - y,
                    )
                    for x, y in before
                ]
                self._assert_vertices_almost_equal(
                    expected,
                    self._takeoff_vertices(view, "linear"),
                )
                self.assertEqual(linear.position[6], 8.0)

    def test_page_scale_and_calibration_preserve_small_count_rendered_bounds(self):
        selected = {"area", "count"}
        for screen_units_per_ost in (0.25, 1.0, 4.0):
            for horizontal in (True, False):
                with self.subTest(
                    screen_units_per_ost=screen_units_per_ost,
                    horizontal=horizontal,
                ):
                    view = self._make_transform_view(selected)
                    view._scene_builder.cs.ost_to_screen_pixels = (
                        lambda value: float(value) * screen_units_per_ost
                    )
                    view._current_conditions["count"].display_size = 10.0
                    before = self._rendered_takeoff_selection_bounds(view, selected)
                    view.flip_selected_takeoffs(horizontal)
                    after = self._rendered_takeoff_selection_bounds(view, selected)
                    self._assert_bounds_almost_equal(before, after)

    def test_page_scale_preserves_thin_linear_rendered_bounds(self):
        selected = {"area", "linear"}
        for screen_units_per_ost in (0.25, 1.0, 4.0):
            for horizontal in (True, False):
                with self.subTest(
                    screen_units_per_ost=screen_units_per_ost,
                    horizontal=horizontal,
                ):
                    view = self._make_transform_view(selected)
                    view._scene_builder.cs.ost_to_screen_pixels = (
                        lambda value: float(value) * screen_units_per_ost
                    )
                    view._current_conditions["linear"].thickness = 0.1
                    before = self._rendered_takeoff_selection_bounds(view, selected)
                    view.flip_selected_takeoffs(horizontal)
                    after = self._rendered_takeoff_selection_bounds(view, selected)
                    self._assert_bounds_almost_equal(before, after)

    def test_mixed_flip_with_multiple_objects_per_type_preserves_bounds(self):
        base_selection = {"linear", "count", "area", "attachment"}
        for horizontal in (True, False):
            with self.subTest(horizontal=horizontal):
                selected = set(base_selection)
                view = self._make_transform_view(selected)
                for source_uid in base_selection:
                    duplicate_uid = f"{source_uid}-2"
                    source = view._current_takeoffs[source_uid]
                    duplicate_position = list(source.position)
                    for index in range(0, len(duplicate_position), 2):
                        duplicate_position[index] += 70.0
                        duplicate_position[index + 1] += 30.0
                    view._current_takeoffs[duplicate_uid] = Takeoff(
                        uid=duplicate_uid,
                        condition_uid=source.condition_uid,
                        position=duplicate_position,
                        rotation=source.rotation,
                    )
                    selected.add(duplicate_uid)
                view._selected_uids = set(selected)
                before = self._rendered_takeoff_selection_bounds(view, selected)
                view.flip_selected_takeoffs(horizontal)
                after = self._rendered_takeoff_selection_bounds(view, selected)
                self._assert_bounds_almost_equal(before, after)

    def test_double_mixed_flip_restores_authoritative_geometry_and_rotation(self):
        selected = {"linear", "count", "area", "attachment"}
        for horizontal in (True, False):
            with self.subTest(horizontal=horizontal):
                view = self._make_transform_view(selected)
                original_positions = {
                    uid: list(takeoff.position)
                    for uid, takeoff in view._current_takeoffs.items()
                }
                original_rotations = {
                    uid: takeoff.rotation
                    for uid, takeoff in view._current_takeoffs.items()
                }
                view.flip_selected_takeoffs(horizontal)
                view.flip_selected_takeoffs(horizontal)
                for uid, takeoff in view._current_takeoffs.items():
                    for original, restored in zip(
                        original_positions[uid], takeoff.position
                    ):
                        self.assertAlmostEqual(original, restored, places=9)
                    self.assertAlmostEqual(
                        original_rotations[uid], takeoff.rotation, places=9
                    )
                self.assertEqual(len(view.flushed_transform_groups), 2)

    def test_flip_then_rotate_uses_one_stable_canonical_group_pivot(self):
        selected = {"linear", "count", "area", "attachment"}
        for horizontal in (True, False):
            for screen_units_per_ost in (0.25, 1.0, 4.0):
                with self.subTest(
                    horizontal=horizontal,
                    screen_units_per_ost=screen_units_per_ost,
                ):
                    view = self._make_transform_view(selected)
                    view._scene_builder.cs.ost_to_screen_pixels = (
                        lambda value: float(value) * screen_units_per_ost
                    )
                    view._current_conditions["linear"].thickness = 0.1
                    linear = view._current_takeoffs["linear"]
                    linear.position = [0.0, 0.0, 20.0, 0.0, 7.0, 9.0, -8.0]
                    linear.curve = Takeoff.CURVE_ENABLED
                    view._current_conditions["count"].shape = shapes.SQUARE
                    view._current_conditions["count"].display_size = 10.0
                    view._current_conditions["attachment"].shape = shapes.TRIANGLE
                    original_positions = {
                        uid: list(view._current_takeoffs[uid].position)
                        for uid in selected
                    }
                    original_rotations = {
                        uid: view._current_takeoffs[uid].rotation for uid in selected
                    }
                    original_bounds = self._rendered_takeoff_selection_bounds(
                        view, selected
                    )
                    original_center = (
                        (original_bounds[0] + original_bounds[2]) / 2.0,
                        (original_bounds[1] + original_bounds[3]) / 2.0,
                    )
                    view.flip_selected_takeoffs(horizontal)
                    flipped_bounds = self._rendered_takeoff_selection_bounds(
                        view, selected
                    )
                    self._assert_bounds_almost_equal(original_bounds, flipped_bounds)
                    view.rotate_selected_takeoffs(90.0)
                    rotated_bounds = self._rendered_takeoff_selection_bounds(
                        view, selected
                    )
                    rotated_center = (
                        (rotated_bounds[0] + rotated_bounds[2]) / 2.0,
                        (rotated_bounds[1] + rotated_bounds[3]) / 2.0,
                    )
                    self._assert_bounds_almost_equal(original_center, rotated_center)
                    view.rotate_selected_takeoffs(-90.0)
                    view.flip_selected_takeoffs(horizontal)
                    for uid in selected:
                        self._assert_bounds_almost_equal(
                            original_positions[uid],
                            view._current_takeoffs[uid].position,
                        )
                        self.assertAlmostEqual(
                            original_rotations[uid],
                            view._current_takeoffs[uid].rotation,
                            places=9,
                        )


class InputHandlerMixinRotateSelectedTakeoffsTests(_CtrlDragFixture):
    """InputHandlerMixin.rotate_selected_takeoffs."""

    def test_each_takeoff_type_rotates_about_its_complete_visible_footprint(self):
        for uid in ("linear", "count", "area", "attachment"):
            for degrees in (-90.0, 90.0):
                with self.subTest(uid=uid, degrees=degrees):
                    view = self._make_transform_view({uid})
                    original_rotation = view._current_takeoffs[uid].rotation
                    before = self._rendered_takeoff_selection_bounds(view, {uid})
                    self._rotate_and_assert_rotation(view, {uid}, degrees)
                    after = self._rendered_takeoff_selection_bounds(view, {uid})
                    self._assert_quarter_turn_bounds(before, after)
                    condition = view._current_conditions[uid]
                    if condition.is_count or condition.is_attachment:
                        self.assertAlmostEqual(
                            view._current_takeoffs[uid].rotation,
                            original_rotation + math.radians(degrees),
                        )

    def test_every_pairwise_type_rotation_keeps_one_visible_group_center(self):
        takeoff_types = ("linear", "count", "area", "attachment")
        for selected in combinations(takeoff_types, 2):
            for degrees in (-90.0, 90.0):
                with self.subTest(selected=selected, degrees=degrees):
                    view = self._make_transform_view(set(selected))
                    before = self._rendered_takeoff_selection_bounds(view, selected)
                    self._rotate_and_assert_rotation(view, set(selected), degrees)
                    after = self._rendered_takeoff_selection_bounds(view, selected)
                    self._assert_quarter_turn_bounds(before, after)

    def test_full_mixed_rotation_uses_complete_visible_group_pivot(self):
        selected = {"linear", "count", "area", "attachment"}
        for degrees in (-90.0, 90.0):
            with self.subTest(degrees=degrees):
                view = self._make_transform_view(selected)
                before = self._rendered_takeoff_selection_bounds(view, selected)
                view.rotate_selected_takeoffs(degrees)
                after = self._rendered_takeoff_selection_bounds(view, selected)
                self._assert_quarter_turn_bounds(before, after)
                rotation_delta = math.radians(degrees)
                self.assertAlmostEqual(
                    view._current_takeoffs["count"].rotation,
                    math.radians(32.0) + rotation_delta,
                )
                self.assertAlmostEqual(
                    view._current_takeoffs["attachment"].rotation,
                    math.radians(25.0) + rotation_delta,
                )

    def test_point_shape_rotation_matrix_keeps_visible_group_center(self):
        shape_dimensions = (
            (shapes.SQUARE, 20.0, 8.0),
            (shapes.RECTANGLE, 20.0, 8.0),
            (shapes.TRIANGLE, 20.0, 8.0),
            (shapes.ELLIPSE, 20.0, 8.0),
        )
        for point_uid in ("count", "attachment"):
            display_sizes = (10.0, 75.0, 175.0) if point_uid == "count" else (100.0,)
            for shape_id, width, depth in shape_dimensions:
                for display_size in display_sizes:
                    for screen_units_per_ost in (0.25, 1.0, 4.0):
                        for initial_degrees in (0.0, 27.0, 143.0):
                            for degrees in (-90.0, 90.0):
                                with self.subTest(
                                    point_uid=point_uid,
                                    shape_id=shape_id,
                                    display_size=display_size,
                                    screen_units_per_ost=screen_units_per_ost,
                                    initial_degrees=initial_degrees,
                                    degrees=degrees,
                                ):
                                    selected = {"area", point_uid}
                                    view = self._make_transform_view(selected)
                                    view._scene_builder.cs.ost_to_screen_pixels = (
                                        lambda value: float(value)
                                        * screen_units_per_ost
                                    )
                                    condition = view._current_conditions[point_uid]
                                    condition.shape = shape_id
                                    condition.width = width
                                    condition.depth = depth
                                    condition.display_size = display_size
                                    point = view._current_takeoffs[point_uid]
                                    point.rotation = math.radians(initial_degrees)
                                    before = self._rendered_takeoff_selection_bounds(
                                        view, selected
                                    )
                                    view.rotate_selected_takeoffs(degrees)
                                    after = self._rendered_takeoff_selection_bounds(
                                        view, selected
                                    )
                                    self._assert_quarter_turn_bounds(before, after)
                                    self.assertAlmostEqual(
                                        point.rotation,
                                        math.radians(initial_degrees + degrees),
                                    )

    def test_thin_straight_and_curved_linear_rotation_respects_page_scale(self):
        selected = {"area", "linear"}
        for curved in (False, True):
            for screen_units_per_ost in (0.25, 1.0, 4.0):
                for degrees in (-90.0, 90.0):
                    with self.subTest(
                        curved=curved,
                        screen_units_per_ost=screen_units_per_ost,
                        degrees=degrees,
                    ):
                        view = self._make_transform_view(selected)
                        view._scene_builder.cs.ost_to_screen_pixels = (
                            lambda value: float(value) * screen_units_per_ost
                        )
                        view._current_conditions["linear"].thickness = 0.1
                        if curved:
                            linear = view._current_takeoffs["linear"]
                            linear.position = [0.0, 0.0, 20.0, 0.0, 10.0, 8.0, 0.0]
                            linear.curve = Takeoff.CURVE_ENABLED
                        before = self._rendered_takeoff_selection_bounds(view, selected)
                        view.rotate_selected_takeoffs(degrees)
                        after = self._rendered_takeoff_selection_bounds(view, selected)
                        self._assert_quarter_turn_bounds(before, after)

    def test_left_then_right_restores_mixed_authoritative_geometry(self):
        selected = {"linear", "count", "area", "attachment"}
        view = self._make_transform_view(selected)
        original_positions = {
            uid: list(takeoff.position)
            for uid, takeoff in view._current_takeoffs.items()
        }
        original_rotations = {
            uid: takeoff.rotation for uid, takeoff in view._current_takeoffs.items()
        }
        view.rotate_selected_takeoffs(-90.0)
        view.rotate_selected_takeoffs(90.0)
        for uid, takeoff in view._current_takeoffs.items():
            self._assert_bounds_almost_equal(original_positions[uid], takeoff.position)
            self.assertAlmostEqual(original_rotations[uid], takeoff.rotation)

    def test_four_quarter_turns_restore_mixed_visible_geometry(self):
        selected = {"linear", "count", "area", "attachment"}
        for degrees in (-90.0, 90.0):
            with self.subTest(degrees=degrees):
                view = self._make_transform_view(selected)
                original_positions = {
                    uid: list(takeoff.position)
                    for uid, takeoff in view._current_takeoffs.items()
                }
                original_vertices = {
                    uid: self._takeoff_vertices(view, uid) for uid in selected
                }
                original_rotations = {
                    uid: takeoff.rotation
                    for uid, takeoff in view._current_takeoffs.items()
                }
                for _turn in range(4):
                    view.rotate_selected_takeoffs(degrees)
                for uid, takeoff in view._current_takeoffs.items():
                    self._assert_bounds_almost_equal(
                        original_positions[uid], takeoff.position
                    )
                    self._assert_vertices_almost_equal(
                        original_vertices[uid], self._takeoff_vertices(view, uid)
                    )
                    rotation_delta = math.remainder(
                        takeoff.rotation - original_rotations[uid],
                        math.tau,
                    )
                    self.assertAlmostEqual(rotation_delta, 0.0)
                self.assertEqual(len(view.flushed_transform_groups), 4)


class InputHandlerMixinToolbarTransformTests(_CtrlDragFixture):
    """InputHandlerMixin toolbar rotate/flip gating, children and edit state."""

    def test_toolbar_transform_requires_edit_access_and_positioned_takeoffs(self):
        for name, prepare in (
            ("editing disabled", lambda v: setattr(v, "_editing_enabled", False)),
            ("nothing selected", lambda v: setattr(v, "_selected_uids", set())),
            (
                "selected takeoff without geometry",
                lambda v: setattr(v._current_takeoffs["count"], "position", []),
            ),
        ):
            with self.subTest(name):
                view = self._make_transform_view({"count"})
                before = {
                    uid: (list(item.position), item.rotation)
                    for uid, item in view._current_takeoffs.items()
                }
                prepare(view)
                view.rotate_selected_takeoffs(90.0)
                view.flip_selected_takeoffs(True)
                after = {
                    uid: (list(item.position), item.rotation)
                    for uid, item in view._current_takeoffs.items()
                }
                if name == "selected takeoff without geometry":
                    before["count"] = ([], before["count"][1])
                self.assertEqual(after, before)
                self.assertEqual(view.flushed_transform_groups, [])
                self.assertEqual(view._dirty_positions, {})

    def test_unknown_transform_kind_is_rejected(self):
        view = self._make_transform_view({"count"})
        with self.assertRaises(ValueError):
            view._transform_selected_takeoffs("shear")
        self.assertEqual(view.flushed_transform_groups, [])

    def test_rotation_and_flip_record_before_edit_dirty_state_in_one_group(self):
        for kind in ("rotate", "flip"):
            with self.subTest(kind=kind):
                view = self._make_transform_view({"linear", "count"})
                before_positions = {
                    uid: list(view._current_takeoffs[uid].position)
                    for uid in ("linear", "count")
                }
                count_rotation = view._current_takeoffs["count"].rotation
                if kind == "rotate":
                    view.rotate_selected_takeoffs(90.0)
                    expected_rotation = count_rotation + math.pi / 2.0
                else:
                    view.flip_selected_takeoffs(True)
                    expected_rotation = (
                        input_handler_module.mirror_point_takeoff_rotation(
                            count_rotation, True
                        )
                    )
                self.assertEqual(len(view.flushed_transform_groups), 1)
                position_changes, rotation_changes = view.flushed_transform_groups[0]
                self.assertEqual(
                    {uid: old for uid, old, _new in position_changes}, before_positions
                )
                for uid, _old, new in position_changes:
                    self.assertEqual(new, view._current_takeoffs[uid].position)
                    self.assertNotEqual(new, before_positions[uid])
                self.assertEqual(len(rotation_changes), 1)
                uid, old, new = rotation_changes[0]
                self.assertEqual(uid, "count")
                self.assertEqual(old, count_rotation)
                self.assertAlmostEqual(new, expected_rotation)
                self.assertEqual(view._current_takeoffs["linear"].rotation, 0.0)

    def test_transform_carries_unselected_area_children_around_the_selection_pivot(
        self,
    ):
        hole_position = [2.0, 2.0, 4.0, 2.0, 4.0, 4.0, 2.0, 4.0]
        for kind in ("rotate", "flip"):
            with self.subTest(kind=kind):
                view = self._make_transform_view({"area"})
                view._current_takeoffs["hole"] = Takeoff(
                    uid="hole",
                    condition_uid="area",
                    parent_uid="area",
                    position=list(hole_position),
                )
                pivot = view._takeoff_transform_center({"area"})
                if kind == "rotate":
                    view.rotate_selected_takeoffs(90.0)
                    expected = input_handler_module.rotate_points_around(
                        hole_position, 90.0, *pivot
                    )
                else:
                    view.flip_selected_takeoffs(False)
                    expected = input_handler_module.mirror_position_coords(
                        hole_position, pivot[0], pivot[1], False
                    )
                for actual, wanted in zip(
                    view._current_takeoffs["hole"].position, expected
                ):
                    self.assertAlmostEqual(actual, wanted)
                self.assertNotEqual(
                    view._current_takeoffs["hole"].position, hole_position
                )
                changed = {uid for uid, _o, _n in view.flushed_transform_groups[0][0]}
                self.assertEqual(changed, {"area", "hole"})

    def test_flip_direction_and_curved_offset_follow_the_requested_axis(self):
        view = self._make_transform_view({"linear"})
        linear = view._current_takeoffs["linear"]
        linear.position = [12.0, 2.0, 22.0, 6.0, 17.0, 4.0, 3.0]
        linear.curve = Takeoff.CURVE_ENABLED
        pivot = view._takeoff_transform_center({"linear"})
        original = list(linear.position)
        view.flip_selected_takeoffs(True)
        self.assertAlmostEqual(linear.position[0], 2.0 * pivot[0] - original[0])
        self.assertAlmostEqual(linear.position[1], original[1])
        self.assertAlmostEqual(linear.position[6], -original[6])
        view.flip_selected_takeoffs(False)
        self.assertAlmostEqual(linear.position[1], 2.0 * pivot[1] - original[1])
        self.assertAlmostEqual(linear.position[0], 2.0 * pivot[0] - original[0])
        self.assertAlmostEqual(linear.position[6], original[6])

    def test_transform_center_requires_complete_footprints(self):
        view = self._make_transform_view({"linear"})
        self.assertIsNone(view._takeoff_transform_center(set()))
        left_center = view._takeoff_transform_center({"linear"})
        right_center = view._takeoff_transform_center({"count"})
        both = view._takeoff_transform_center({"linear", "count"})
        self.assertLess(left_center[0], right_center[0])
        self.assertLess(left_center[0], both[0])
        self.assertLess(both[0], right_center[0])
        with patch.object(
            input_handler_module, "compute_takeoff_footprint_bounds", return_value=None
        ):
            self.assertIsNone(view._takeoff_transform_center({"linear"}))
            view.rotate_selected_takeoffs(90.0)
        self.assertEqual(view.flushed_transform_groups, [])
        self.assertEqual(view._dirty_positions, {})


class InputHandlerMixinApplyPolygonControlPointTargetTests(_CtrlDragFixture):
    """InputHandlerMixin._apply_polygon_control_point_target."""

    def test_area_control_point_target_respects_selection_edit_gate(self):
        view = self._make_area_control_point_view()
        view._selection_enabled = False
        view._editing_enabled = False
        self.assertIsNone(
            view.polygon_control_point_target_at(QtCore.QPointF(50.0, 0.0))
        )
        target = PolygonControlPointTarget(
            plan_item_uid="area1",
            kind="edge",
            edge_index=0,
            insert_point=(50.0, 0.0),
        )
        self.assertFalse(view._apply_polygon_control_point_target(target))
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_hole_control_point_target_rejects_non_area_parent(self):
        view = self._make_area_control_point_view(include_hole=True)
        view._current_takeoffs["parent-linear"] = Takeoff(
            uid="parent-linear",
            condition_uid="linear",
            page_uid="page-1",
            position=[200.0, 0.0, 300.0, 0.0],
        )
        view._current_takeoffs["hole1"].parent_uid = "parent-linear"
        self.assertIsNone(
            view.polygon_control_point_target_at(QtCore.QPointF(30.0, 20.0))
        )
        target = PolygonControlPointTarget(
            plan_item_uid="hole1",
            kind="edge",
            edge_index=0,
            insert_point=(30.0, 20.0),
        )
        self.assertFalse(view._apply_polygon_control_point_target(target))
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_add_area_control_point_flushes_old_and_new_position(self):
        view = self._make_area_control_point_view()
        old_pos = list(view._current_takeoffs["area1"].position)
        target = PolygonControlPointTarget(
            plan_item_uid="area1",
            kind="edge",
            edge_index=0,
            insert_point=(50.0, 0.0),
        )
        self.assertTrue(view._apply_polygon_control_point_target(target))
        new_pos = list(AREA_CP_ADDED_POSITION)
        self.assertEqual(view._current_takeoffs["area1"].position, new_pos)
        self.assertEqual(
            view.positions_flushed.emitted,
            [([("area1", old_pos, new_pos)], [])],
        )
        self.assertEqual(view.snap_invalidations, 1)
        self.assertEqual(view.rebuild_count, 1)

    def test_subtract_area_control_point_flushes_old_and_new_position(self):
        view = self._make_area_control_point_view()
        old_pos = list(view._current_takeoffs["area1"].position)
        target = PolygonControlPointTarget(
            plan_item_uid="area1",
            kind="vertex",
            vertex_index=1,
        )
        self.assertTrue(view._apply_polygon_control_point_target(target))
        new_pos = list(AREA_CP_SUBTRACTED_SECOND_VERTEX_POSITION)
        self.assertEqual(view._current_takeoffs["area1"].position, new_pos)
        self.assertEqual(
            view.positions_flushed.emitted,
            [([("area1", old_pos, new_pos)], [])],
        )

    def test_subtract_area_control_point_rejects_triangle(self):
        view = self._make_area_control_point_view()
        view._current_takeoffs["area1"].position = [0.0, 0.0, 10.0, 0.0, 0.0, 10.0]
        target = PolygonControlPointTarget(
            plan_item_uid="area1",
            kind="vertex",
            vertex_index=1,
        )
        self.assertFalse(view._apply_polygon_control_point_target(target))
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_area_control_point_rejects_invalid_polygon_result(self):
        view = self._make_area_control_point_view()
        target = PolygonControlPointTarget(
            plan_item_uid="area1",
            kind="edge",
            edge_index=0,
            insert_point=(50.0, 0.0),
        )
        with patch.object(input_handler_module, "polygon_is_valid", return_value=False):
            self.assertFalse(view._apply_polygon_control_point_target(target))
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_add_hole_control_point_flushes_old_and_new_position(self):
        view = self._make_area_control_point_view(include_hole=True)
        old_pos = list(view._current_takeoffs["hole1"].position)
        target = PolygonControlPointTarget(
            plan_item_uid="hole1",
            kind="edge",
            edge_index=0,
            insert_point=(30.0, 20.0),
        )
        self.assertTrue(view._apply_polygon_control_point_target(target))
        new_pos = list(AREA_CP_HOLE_ADDED_POSITION)
        self.assertEqual(view._current_takeoffs["hole1"].position, new_pos)
        self.assertEqual(
            view.positions_flushed.emitted,
            [([("hole1", old_pos, new_pos)], [])],
        )

    def test_subtract_hole_control_point_flushes_old_and_new_position(self):
        view = self._make_area_control_point_view(include_hole=True)
        old_pos = list(view._current_takeoffs["hole1"].position)
        target = PolygonControlPointTarget(
            plan_item_uid="hole1",
            kind="vertex",
            vertex_index=1,
        )
        self.assertTrue(view._apply_polygon_control_point_target(target))
        new_pos = list(AREA_CP_HOLE_SUBTRACTED_SECOND_VERTEX_POSITION)
        self.assertEqual(view._current_takeoffs["hole1"].position, new_pos)
        self.assertEqual(
            view.positions_flushed.emitted,
            [([("hole1", old_pos, new_pos)], [])],
        )

    def test_subtract_hole_control_point_rejects_triangle(self):
        view = self._make_area_control_point_view(include_hole=True)
        view._current_takeoffs["hole1"].position = [20.0, 20.0, 40.0, 20.0, 20.0, 40.0]
        target = PolygonControlPointTarget(
            plan_item_uid="hole1",
            kind="vertex",
            vertex_index=1,
        )
        self.assertFalse(view._apply_polygon_control_point_target(target))
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_hole_control_point_rejects_invalid_polygon_result(self):
        view = self._make_area_control_point_view(include_hole=True)
        target = PolygonControlPointTarget(
            plan_item_uid="hole1",
            kind="edge",
            edge_index=0,
            insert_point=(30.0, 20.0),
        )
        with patch.object(input_handler_module, "polygon_is_valid", return_value=False):
            self.assertFalse(view._apply_polygon_control_point_target(target))
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_hole_control_point_rejects_position_outside_parent(self):
        view = self._make_area_control_point_view(include_hole=True)
        target = PolygonControlPointTarget(
            plan_item_uid="hole1",
            kind="edge",
            edge_index=1,
            insert_point=(150.0, 30.0),
        )
        self.assertFalse(view._apply_polygon_control_point_target(target))
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_hole_control_point_rejects_sibling_overlap(self):
        view = self._make_area_control_point_view(include_hole=True)
        view._current_takeoffs["hole2"] = Takeoff(
            uid="hole2",
            condition_uid="area",
            page_uid="page-1",
            parent_uid="area1",
            position=[45.0, 20.0, 65.0, 20.0, 65.0, 40.0, 45.0, 40.0],
        )
        target = PolygonControlPointTarget(
            plan_item_uid="hole1",
            kind="edge",
            edge_index=1,
            insert_point=(55.0, 30.0),
        )
        self.assertFalse(view._apply_polygon_control_point_target(target))
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_polygon_and_cloud_subtract_control_point_enforce_minimum(self):
        for annotation_type in (ANNOTATION_TYPE_POLYGON, ANNOTATION_TYPE_CLOUD):
            with self.subTest(annotation_type=annotation_type):
                view, annotation = self._make_annotation_control_point_view(
                    annotation_type
                )
                old_pos = list(annotation.position)
                target = PolygonControlPointTarget(
                    plan_item_uid=annotation.uid,
                    kind="vertex",
                    vertex_index=0,
                )
                self.assertTrue(view._apply_polygon_control_point_target(target))
                triangle = [500.0, 0.0, 500.0, 100.0, 400.0, 100.0]
                self.assertEqual(annotation.position, triangle)
                self.assertEqual(
                    view.positions_flushed.emitted,
                    [([], [(annotation.uid, annotation_type, old_pos, triangle)])],
                )
                self.assertFalse(view._apply_polygon_control_point_target(target))
                self.assertEqual(len(view.positions_flushed.emitted), 1)

    def test_edge_insertion_accepts_the_closing_edge_and_rejects_bad_indices(self):
        square = list(AREA_CP_ORIGINAL_POSITION)
        for index, insert_point, expected in (
            (3, (0.0, 50.0), square + [0.0, 50.0]),
            (4, (0.0, 50.0), None),
            (-1, (50.0, 0.0), None),
        ):
            with self.subTest(index=index):
                view = self._make_area_control_point_view()
                target = PolygonControlPointTarget(
                    plan_item_uid="area1",
                    kind="edge",
                    edge_index=index,
                    insert_point=insert_point,
                )
                applied = view._apply_polygon_control_point_target(target)
                self.assertEqual(applied, expected is not None)
                self.assertEqual(
                    view._current_takeoffs["area1"].position,
                    expected if expected is not None else square,
                )

    def test_vertex_removal_rejects_out_of_range_indices(self):
        for index, removed in ((0, True), (3, True), (4, False), (-1, False)):
            with self.subTest(index=index):
                view = self._make_area_control_point_view()
                target = PolygonControlPointTarget(
                    plan_item_uid="area1", kind="vertex", vertex_index=index
                )
                self.assertEqual(
                    view._apply_polygon_control_point_target(target), removed
                )
                self.assertEqual(
                    len(view._current_takeoffs["area1"].position), 6 if removed else 8
                )

    def test_incomplete_or_foreign_control_point_targets_are_rejected(self):
        view = self._make_area_control_point_view()
        for target in (
            PolygonControlPointTarget(plan_item_uid="area1", kind="edge", edge_index=0),
            PolygonControlPointTarget(
                plan_item_uid="area1", kind="bogus", edge_index=0
            ),
            PolygonControlPointTarget(
                plan_item_uid="missing",
                kind="edge",
                edge_index=0,
                insert_point=(50.0, 0.0),
            ),
        ):
            with self.subTest(kind=target.kind, uid=target.plan_item_uid):
                self.assertFalse(view._apply_polygon_control_point_target(target))
        self.assertEqual(view.positions_flushed.emitted, [])
        self.assertEqual(
            view._current_takeoffs["area1"].position, AREA_CP_ORIGINAL_POSITION
        )

    def test_area_vertex_removal_must_keep_child_holes_inside(self):
        for hole_position, removed in (
            (list(AREA_CP_HOLE_ORIGINAL_POSITION), True),
            ([60.0, 60.0, 80.0, 60.0, 80.0, 80.0, 60.0, 80.0], False),
        ):
            with self.subTest(hole=hole_position):
                view = self._make_area_control_point_view(include_hole=True)
                view._current_takeoffs["hole1"].position = list(hole_position)
                target = PolygonControlPointTarget(
                    plan_item_uid="area1", kind="vertex", vertex_index=2
                )
                self.assertEqual(
                    view._apply_polygon_control_point_target(target), removed
                )
                self.assertEqual(
                    len(view._current_takeoffs["area1"].position), 6 if removed else 8
                )
                self.assertEqual(
                    len(view.positions_flushed.emitted), 1 if removed else 0
                )


class InputHandlerMixinMousepresseventTests(_CtrlDragFixture):
    """InputHandlerMixin.mousePressEvent."""

    def test_text_takeoff_cycle_press_does_not_activate_text_toolbar(self):
        view = self._make_overlapping_text_cycle_view("t1")
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(view.selected_text_annotation_uids, [])
        self.assertEqual(view._selected_uids, {"t1"})
        release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(release)
        self.assertTrue(release.accepted)
        self.assertEqual(view._selected_uids, {"t2"})
        self.assertEqual(view.selected_text_annotation_uids, [])

    def test_text_takeoff_cycle_back_to_text_shows_toolbar_after_commit(self):
        view = self._make_overlapping_text_cycle_view("t2")
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(view.selected_text_annotation_uids, [])
        self.assertEqual(view._selected_uids, {"t2"})
        release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(release)
        self.assertTrue(release.accepted)
        self.assertEqual(view._selected_uids, {"a1"})
        self.assertEqual(view.selected_text_annotation_uids, ["a1"])

    def test_plain_text_annotation_press_still_shows_toolbar(self):
        view = self._make_overlapping_text_cycle_view("t1")
        view._selected_uids = set()
        view.find_takeoffs_at = lambda _scene_pos: ["a1"]
        view.find_takeoff_at = lambda _scene_pos, cycle_from_uid=None: "a1"
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(view.selected_text_annotation_uids, ["a1"])

    def test_ctrl_left_press_uses_zoom_even_if_cached_ctrl_state_is_false(self):
        view = self._make_view()
        event = FakeMouseEvent(Qt.KeyboardModifier.ControlModifier)
        view.mousePressEvent(event)
        self.assertTrue(event.accepted)
        self.assertTrue(view._zoom_press_ctrl)
        self.assertIsNone(view._drag_plan_item_uid)
        self.assertEqual(view._drag_handle_index, -2)
        self.assertEqual(view._drag_item_orig_positions, {})

    def test_named_view_click_away_commit_does_not_start_annotation_placement(self):
        view = self._make_view(set())
        view._cursor_mode = "annotation_place"
        view._editing_named_view_uid = "draft"
        view.find_takeoff_at = lambda _scene_pos, cycle_from_uid=None: None
        view.find_takeoffs_at = lambda _scene_pos: []
        event = FakeMouseEvent(x=40, y=50)
        view.mousePressEvent(event)
        self.assertTrue(event.accepted)
        self.assertEqual(view.finished_inline_edits, [True])
        self.assertEqual(view.annotation_place_presses, [])

    def test_single_click_hotlink_does_not_select_it(self):
        view = self._make_hotlink_view(selected=False)
        view.find_takeoff_at = lambda _scene_pos: "h1"
        event = FakeMouseEvent()
        view.mousePressEvent(event)
        self.assertTrue(event.accepted)
        self.assertEqual(view._selected_uids, set())
        self.assertIsNone(view._drag_plan_item_uid)

    def test_selected_hotlink_center_press_starts_drag(self):
        view = self._make_hotlink_view(selected=True)
        event = FakeMouseEvent()
        view.mousePressEvent(event)
        self.assertTrue(event.accepted)
        self.assertEqual(view._drag_plan_item_uid, "h1")
        self.assertEqual(view._drag_orig_position, [10.0, 10.0])
        self.assertEqual(view._drag_handle_index, -1)

    def test_selected_item_click_clears_all_drag_tracking(self):
        view = self._make_hotlink_view(selected=True)
        view._scene = QGraphicsScene()
        view._scene.addItem(view._uid_to_items["h1"][0])
        view.mousePressEvent(FakeMouseEvent())
        view._drag_item_orig_paths = {1: QPainterPath()}
        view._drag_item_orig_text_states = {
            2: ("", -1.0, 0.0, QtCore.QPointF(), None, None)
        }
        view._drag_last_valid_new_pos = [10.0, 10.0]
        release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(release)
        self.assertTrue(release.accepted)
        self.assertIsNone(view._drag_plan_item_uid)
        self.assertEqual(view._drag_item_orig_positions, {})
        self.assertEqual(view._drag_item_orig_paths, {})
        self.assertEqual(view._drag_item_orig_text_states, {})
        self.assertEqual(view._drag_uid_orig_items, {})
        self.assertEqual(view._drag_last_valid_new_pos, [])

    def test_selected_hotlink_drag_does_not_start_rubber_band(self):
        view = self._make_hotlink_view(selected=True)
        view.mapToScene = lambda point: QtCore.QPointF(point)
        view._scene_builder = FakeSceneBuilder()
        view._snap_increments = 1.0
        view.scene_to_ost_delta = lambda dx, dy: (dx, dy)
        view.ost_to_scene_delta = lambda dx, dy: (dx, dy)
        press = FakeMouseEvent(x=10, y=10)
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        move = FakeMouseEvent(x=18, y=18)
        view.mouseMoveEvent(move)
        self.assertTrue(move.accepted)
        self.assertEqual(view._drag_plan_item_uid, "h1")
        self.assertFalse(view._select_band_active)
        self.assertIsNone(view._rubber_band_origin)
        self.assertEqual(view._uid_to_items["h1"][0].pos(), QtCore.QPointF(8.0, 8.0))

    def test_unselected_hotlink_release_still_activates_hotlink(self):
        view = self._make_hotlink_view(selected=False)
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(release)
        self.assertTrue(release.accepted)
        self.assertEqual(len(view.hotlink_clicked.emitted), 1)
        self.assertEqual(view._selected_uids, set())

    def test_cancelled_hotlink_placement_release_allows_next_click(self):
        view = self._make_hotlink_view(selected=False)
        hotlink_items = list(view._hotlink_items)
        view.annotation_place_release_consumed = True
        view._hotlink_items = []
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(release)
        self.assertFalse(view.annotation_place_release_consumed)
        self.assertEqual(view.hotlink_clicked.emitted, [])
        view._hotlink_items = hotlink_items
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        second_release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(second_release)
        self.assertEqual(len(view.hotlink_clicked.emitted), 1)

    def test_ctrl_left_press_blocks_multi_select_drag_setup(self):
        view = self._make_view({"t1", "t2"})
        view.find_takeoff_at = lambda _scene_pos: self.fail(
            "Ctrl zoom press should not hit-test takeoff dragging"
        )
        event = FakeMouseEvent(Qt.KeyboardModifier.ControlModifier)
        view.mousePressEvent(event)
        self.assertTrue(event.accepted)
        self.assertTrue(view._zoom_press_ctrl)
        self.assertEqual(view._drag_multi_orig_positions, {})
        self.assertEqual(view._drag_item_orig_positions, {})

    def test_left_press_without_ctrl_still_starts_selected_takeoff_drag(self):
        view = self._make_view()
        event = FakeMouseEvent()
        view.mousePressEvent(event)
        self.assertTrue(event.accepted)
        self.assertFalse(view._zoom_press_ctrl)
        self.assertEqual(view._drag_plan_item_uid, "t1")
        item = view._uid_to_items["t1"][0]
        self.assertEqual(view._drag_item_orig_positions[id(item)], item.pos())

    def test_selected_text_annotation_drag_starts_only_inside_hitbox(self):
        view, item = self._make_selected_text_annotation_view()
        outside_press = FakeMouseEvent(x=200, y=200)
        view.mousePressEvent(outside_press)
        self.assertTrue(outside_press.accepted)
        self.assertIsNone(view._drag_plan_item_uid)
        self.assertEqual(view._drag_orig_position, [])
        inside_press = FakeMouseEvent(x=20, y=20)
        view.mousePressEvent(inside_press)
        self.assertTrue(inside_press.accepted)
        self.assertEqual(view._drag_plan_item_uid, "a1")
        self.assertEqual(
            view._drag_orig_position,
            view._current_annotations["a1"].position,
        )
        self.assertEqual(view._drag_item_orig_positions[id(item)], item.pos())

    def test_single_click_text_annotation_selects_toolbar_target_without_editing(self):
        view, _item = self._make_selected_text_annotation_view()
        press = FakeMouseEvent(x=20, y=20)
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(view.selected_text_annotation_uids, ["a1"])
        self.assertEqual(view.editing_text_annotation_uids, [])

    def test_multi_takeoff_drag_preview_and_commit_preserve_group_offsets(self):
        view = self._make_view({"t1", "t2"})
        view._current_takeoffs["t1"].position = [3.0, 3.0, 13.0, 3.0]
        view._current_takeoffs["t2"].position = [22.0, 22.0, 32.0, 22.0]
        view._uid_to_items = {
            "t1": [FakeItem(100.0, 100.0)],
            "t2": [FakeItem(200.0, 200.0)],
        }
        border1 = FakeItem(300.0, 300.0, uid="t1")
        border2 = FakeItem(400.0, 400.0, uid="t2")
        view._selection_items = [border1, border2]
        view._snap_increments = 10.0
        view.mapToScene = lambda point: QtCore.QPointF(point)
        view.scene_to_ost_delta = lambda dx, dy: (dx, dy)
        view.ost_to_scene_delta = lambda dx, dy: (dx, dy)
        press = FakeMouseEvent(x=0, y=0)
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(set(view._drag_multi_orig_positions), {"t1", "t2"})
        move = FakeMouseEvent(x=6, y=6)
        view.mouseMoveEvent(move)
        self.assertTrue(move.accepted)
        self.assertEqual(
            view._uid_to_items["t1"][0].pos(), QtCore.QPointF(110.0, 110.0)
        )
        self.assertEqual(
            view._uid_to_items["t2"][0].pos(), QtCore.QPointF(210.0, 210.0)
        )
        self.assertEqual(border1.pos(), QtCore.QPointF(310.0, 310.0))
        self.assertEqual(border2.pos(), QtCore.QPointF(410.0, 410.0))
        view.mouseReleaseEvent(
            FakeMouseEvent(x=6, y=6, buttons=Qt.MouseButton.NoButton)
        )
        self.assertEqual(
            view._current_takeoffs["t1"].position,
            [13.0, 13.0, 23.0, 13.0],
        )
        self.assertEqual(
            view._current_takeoffs["t2"].position,
            [32.0, 32.0, 42.0, 32.0],
        )

    def test_multi_drag_moves_unselected_hole_with_selected_area_parent(self):
        view = self._make_view({"parent", "t2"})
        view._current_conditions = {
            "area": Condition(uid="area", condition_type=Condition.TYPE_AREA),
            "linear": Condition(uid="linear", condition_type=Condition.TYPE_LINEAR),
        }
        view._current_takeoffs = {
            "parent": Takeoff(
                uid="parent",
                condition_uid="area",
                position=[3.0, 3.0, 13.0, 3.0, 13.0, 13.0, 3.0, 13.0],
            ),
            "hole": Takeoff(
                uid="hole",
                condition_uid="area",
                parent_uid="parent",
                position=[6.0, 6.0, 9.0, 6.0, 9.0, 9.0, 6.0, 9.0],
            ),
            "t2": Takeoff(
                uid="t2",
                condition_uid="linear",
                position=[22.0, 22.0, 32.0, 22.0],
            ),
        }
        view._uid_to_items = {
            "parent": [FakeItem(100.0, 100.0)],
            "hole": [FakeItem(150.0, 150.0)],
            "t2": [FakeItem(200.0, 200.0)],
        }
        view._snap_increments = 10.0
        view.mapToScene = lambda point: QtCore.QPointF(point)
        view.scene_to_ost_delta = lambda dx, dy: (dx, dy)
        view.ost_to_scene_delta = lambda dx, dy: (dx, dy)
        view.find_takeoff_at = lambda _scene_pos: "parent"
        view.find_takeoffs_at = lambda _scene_pos: ["parent"]
        view.mousePressEvent(FakeMouseEvent(x=0, y=0))
        self.assertEqual(set(view._drag_multi_orig_positions), {"parent", "hole", "t2"})
        view.mouseMoveEvent(FakeMouseEvent(x=6, y=6))
        self.assertEqual(
            view._uid_to_items["parent"][0].pos(), QtCore.QPointF(110.0, 110.0)
        )
        self.assertEqual(
            view._uid_to_items["hole"][0].pos(), QtCore.QPointF(160.0, 160.0)
        )
        view.mouseReleaseEvent(
            FakeMouseEvent(x=6, y=6, buttons=Qt.MouseButton.NoButton)
        )
        self.assertEqual(
            view._current_takeoffs["parent"].position,
            [13.0, 13.0, 23.0, 13.0, 23.0, 23.0, 13.0, 23.0],
        )
        self.assertEqual(
            view._current_takeoffs["hole"].position,
            [16.0, 16.0, 19.0, 16.0, 19.0, 19.0, 16.0, 19.0],
        )

    def test_rotation_preview_does_not_rotate_condition_label_items(self):
        view = self._make_view({"t1"})
        view._cursor_mode = "rotate"
        view._rotate_handle_item = QGraphicsPathItem()
        view._rotate_handle_item.setPos(10.0, 0.0)
        view._rotate_center_scene = QtCore.QPointF(0.0, 0.0)
        view._rotate_handle_uid = "t1"
        view._rotate_handle_radius = 10.0
        view._rotate_handle_start_angle_deg = 0.0
        view._is_rotatable_uid = lambda uid: uid == "t1"
        view._current_takeoffs["t1"].rotation = 0.0
        path = QGraphicsPathItem()
        path.setData(0, "t1")
        label = QGraphicsTextItem("Display Name")
        label.setData(0, "t1")
        label.setData(2, "condition_label")
        label.setData(3, "display_name")
        view._uid_to_items = {"t1": [path, label]}
        press = FakeMouseEvent(x=10, y=0)
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertTrue(view._rotation_drag_active)
        self.assertIn(path, view._rotation_drag_preview_items)
        self.assertNotIn(label, view._rotation_drag_preview_items)

    def test_rotate_handle_press_takes_priority_over_condition_label(self):
        view = self._make_view({"t1"})
        view._cursor_mode = "rotate"
        view._rotate_handle_item = QGraphicsPathItem()
        view._rotate_handle_item.setPos(10.0, 0.0)
        view._rotate_center_scene = QtCore.QPointF(0.0, 0.0)
        view._rotate_handle_uid = "t1"
        view._rotate_handle_radius = 10.0
        view._rotate_handle_start_angle_deg = 0.0
        view._is_rotatable_uid = lambda uid: uid == "t1"
        view._current_takeoffs["t1"].rotation = 0.0
        path = QGraphicsPathItem()
        path.setData(0, "t1")
        label = QGraphicsTextItem("Display Dimension")
        label.setData(0, "t1")
        label.setData(2, "condition_label")
        label.setData(3, "display_dimension")
        view._uid_to_items = {"t1": [path, label]}
        view._dimension_text_label_at = lambda _pos: label
        view._select_dimension_text_label = lambda _item: self.fail(
            "rotation handle press should not select display text labels"
        )
        press = FakeMouseEvent(x=10, y=0)
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertTrue(view._rotation_drag_active)
        self.assertIn(path, view._rotation_drag_preview_items)
        self.assertNotIn(label, view._rotation_drag_preview_items)


class InputHandlerMixinKeypresseventTests(_CtrlDragFixture):
    """InputHandlerMixin.keyPressEvent."""

    def test_ctrl_r_does_not_enter_rotate_mode_when_selection_disabled(self):
        view = self._make_view({"t1"})
        view._selection_enabled = False
        view._rotate_handle_uid = None
        view._advanced_mouse_controls_enabled = False
        view.cursor_mode_change_requested = FakeSignal()
        calls = []
        view._create_rotate_handle = lambda _uids: calls.append("create") or True
        view._create_slope_rotate_handle = lambda: calls.append("slope") or True
        view._remove_rotate_handle = lambda: calls.append("remove")
        view._apply_cursor_mode = lambda mode: calls.append(("mode", mode))
        view.copy_selected_pdf_text = lambda: False
        event = FakeKeyEvent(
            Qt.Key.Key_R,
            Qt.KeyboardModifier.ControlModifier,
        )
        InputHandlerMixin.keyPressEvent(view, event)
        self.assertFalse(event.accepted)
        self.assertEqual(calls, [])
        self.assertEqual(view.cursor_mode_change_requested.emitted, [])

    def test_ctrl_v_uses_content_specific_paste_state_when_editing_is_disabled(self):
        view = self._make_view(set())
        view._editing_enabled = False
        paste_allowed = [True]
        view._paste_allowed = lambda: paste_allowed[0]
        view.paste_requested = FakeSignal()
        event = FakeKeyEvent(
            Qt.Key.Key_V,
            Qt.KeyboardModifier.ControlModifier,
        )
        InputHandlerMixin.keyPressEvent(view, event)
        self.assertTrue(event.accepted)
        self.assertEqual(view.paste_requested.emitted, [()])
        paste_allowed[0] = False
        blocked_event = FakeKeyEvent(
            Qt.Key.Key_V,
            Qt.KeyboardModifier.ControlModifier,
        )
        InputHandlerMixin.keyPressEvent(view, blocked_event)
        self.assertFalse(blocked_event.accepted)
        self.assertEqual(view.paste_requested.emitted, [()])

    def test_ctrl_r_clears_snap_preview_without_removing_selection_items(self):
        view = self._make_view({"t1"})
        scene = QGraphicsScene()
        snap_preview = QGraphicsRectItem(0.0, 0.0, 4.0, 4.0)
        selection_item = QGraphicsPathItem()
        scene.addItem(snap_preview)
        scene.addItem(selection_item)
        view._scene = scene
        view._place_preview_items = [snap_preview]
        view._place_flashing = False
        view._backout_orig_parent_path = None
        view.clear_place_preview = lambda: PlacementModeMixin.clear_place_preview(view)
        view._rotate_handle_uid = None
        view.cursor_mode_change_requested = FakeSignal()
        view._create_rotate_handle = lambda uids: set(uids) == {"t1"}

        def apply_cursor_mode(mode):
            view._cursor_mode = mode

        view._apply_cursor_mode = apply_cursor_mode
        view.copy_selected_pdf_text = lambda: False
        event = FakeKeyEvent(
            Qt.Key.Key_R,
            Qt.KeyboardModifier.ControlModifier,
        )
        InputHandlerMixin.keyPressEvent(view, event)
        self.assertTrue(event.accepted)
        self.assertEqual(view._cursor_mode, "rotate")
        self.assertEqual(view._place_preview_items, [])
        self.assertIsNone(snap_preview.scene())
        self.assertIs(selection_item.scene(), scene)
        self.assertEqual(view.cursor_mode_change_requested.emitted, [("rotate",)])

    def test_ctrl_r_from_place_mode_exits_placement_before_rotate(self):
        view = self._make_view({"t1"})
        view._cursor_mode = "place"
        view._rotate_handle_uid = None
        view.cursor_mode_change_requested = FakeSignal()
        calls = []

        def exit_place_mode():
            calls.append("exit_place")
            view._cursor_mode = "select"
            view.place_exited.emit()

        def apply_cursor_mode(mode):
            calls.append(("mode", mode))
            view._cursor_mode = mode

        view.place_exited = FakeSignal()
        view._exit_place_mode = exit_place_mode
        view._create_rotate_handle = (
            lambda uids: calls.append(("create", set(uids))) or True
        )
        view.clear_place_preview = lambda: None
        view._apply_cursor_mode = apply_cursor_mode
        view.copy_selected_pdf_text = lambda: False
        event = FakeKeyEvent(
            Qt.Key.Key_R,
            Qt.KeyboardModifier.ControlModifier,
        )
        InputHandlerMixin.keyPressEvent(view, event)
        self.assertTrue(event.accepted)
        self.assertEqual(
            calls,
            [
                "exit_place",
                ("create", {"t1"}),
                ("mode", "rotate"),
            ],
        )
        self.assertEqual(view._cursor_mode, "rotate")
        self.assertEqual(view.place_exited.emitted, [()])
        self.assertEqual(
            view.cursor_mode_change_requested.emitted,
            [("rotate",)],
        )

    def test_ctrl_shift_r_clears_snap_preview_before_slope_rotate(self):
        view = self._make_view({"t1"})
        scene = QGraphicsScene()
        snap_preview = QGraphicsRectItem(0.0, 0.0, 4.0, 4.0)
        selection_item = QGraphicsPathItem()
        scene.addItem(snap_preview)
        scene.addItem(selection_item)
        view._scene = scene
        view._place_preview_items = [snap_preview]
        view._place_flashing = False
        view._backout_orig_parent_path = None
        view.clear_place_preview = lambda: PlacementModeMixin.clear_place_preview(view)
        view._cursor_mode = "select"
        view.cursor_mode_change_requested = FakeSignal()
        view._create_slope_rotate_handle = lambda: True

        def apply_cursor_mode(mode):
            view._cursor_mode = mode

        view._apply_cursor_mode = apply_cursor_mode
        view.copy_selected_pdf_text = lambda: False
        event = FakeKeyEvent(
            Qt.Key.Key_R,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        InputHandlerMixin.keyPressEvent(view, event)
        self.assertTrue(event.accepted)
        self.assertEqual(view._cursor_mode, "slope_rotate")
        self.assertEqual(view._place_preview_items, [])
        self.assertIsNone(snap_preview.scene())
        self.assertIs(selection_item.scene(), scene)
        self.assertEqual(view.cursor_mode_change_requested.emitted, [("slope_rotate",)])

    def test_multi_hotlink_arrow_move_updates_graphics_and_dirty_positions(self):
        view = self._make_view({"hot1", "hot2"})
        hot1 = BidAnnotation(
            uid="hot1",
            annotation_type="hotlink",
            position=[10.0, 20.0],
        )
        hot2 = BidAnnotation(
            uid="hot2",
            annotation_type="hotlink",
            position=[30.0, 40.0],
        )
        view._current_takeoffs = {}
        view._current_annotations = {"hot1": hot1, "hot2": hot2}
        hot1_item = FakeItem(100.0, 200.0, uid="hot1")
        hot2_item = FakeItem(300.0, 400.0, uid="hot2")
        border1 = FakeItem(500.0, 600.0, uid="hot1")
        border2 = FakeItem(700.0, 800.0, uid="hot2")
        view._uid_to_items = {"hot1": [hot1_item], "hot2": [hot2_item]}
        view._selection_items = [border1, border2]
        event = FakeKeyEvent(Qt.Key.Key_Right)
        InputHandlerMixin.keyPressEvent(view, event)
        self.assertTrue(event.accepted)
        self.assertEqual(hot1.position, [11.0, 20.0])
        self.assertEqual(hot2.position, [31.0, 40.0])
        self.assertEqual(hot1_item.pos(), QtCore.QPointF(101.0, 200.0))
        self.assertEqual(hot2_item.pos(), QtCore.QPointF(301.0, 400.0))
        self.assertEqual(border1.pos(), QtCore.QPointF(501.0, 600.0))
        self.assertEqual(border2.pos(), QtCore.QPointF(701.0, 800.0))
        self.assertEqual(
            view._dirty_ann_positions,
            {
                "hot1": ("hotlink", [11.0, 20.0]),
                "hot2": ("hotlink", [31.0, 40.0]),
            },
        )

    def test_single_hotlink_arrow_move_flushes_on_key_release(self):
        view = self._make_view({"hot1"})
        hotlink = BidAnnotation(
            uid="hot1",
            annotation_type="hotlink",
            position=[10.0, 20.0],
        )
        view._current_takeoffs = {}
        view._current_annotations = {"hot1": hotlink}
        view._uid_to_items = {"hot1": [FakeItem(100.0, 200.0, uid="hot1")]}
        flushed = []

        def flush_dirty_positions():
            flushed.append(dict(view._dirty_ann_positions))
            view._dirty_ann_positions.clear()
            view._position_before_edit.clear()

        view._flush_dirty_positions = flush_dirty_positions
        InputHandlerMixin.keyPressEvent(view, FakeKeyEvent(Qt.Key.Key_Down))
        release = FakeKeyEvent(Qt.Key.Key_Down)
        InputHandlerMixin.keyReleaseEvent(view, release)
        self.assertTrue(release.accepted)
        self.assertEqual(hotlink.position, [10.0, 21.0])
        self.assertEqual(flushed, [{"hot1": ("hotlink", [10.0, 21.0])}])
        self.assertFalse(view._keyboard_move_dirty)

    def test_takeoff_arrow_move_uses_same_key_release_flush_boundary(self):
        view = self._make_view({"t1"})
        flushed = []

        def flush_dirty_positions():
            flushed.append(dict(view._dirty_positions))
            view._dirty_positions.clear()
            view._position_before_edit.clear()

        view._flush_dirty_positions = flush_dirty_positions
        InputHandlerMixin.keyPressEvent(view, FakeKeyEvent(Qt.Key.Key_Right))
        release = FakeKeyEvent(Qt.Key.Key_Right)
        InputHandlerMixin.keyReleaseEvent(view, release)
        self.assertTrue(release.accepted)
        self.assertEqual(
            view._current_takeoffs["t1"].position,
            [1.0, 0.0, 11.0, 0.0],
        )
        self.assertEqual(flushed, [{"t1": [1.0, 0.0, 11.0, 0.0]}])

    def test_takeoff_arrow_move_waits_for_geometry_edit_lease(self):
        view = self._make_view({"t1"})
        requested = []
        view.request_geometry_edit_lease = (
            lambda uids: requested.append(set(uids)) or False
        )
        event = FakeKeyEvent(Qt.Key.Key_Right)
        InputHandlerMixin.keyPressEvent(view, event)
        self.assertTrue(event.accepted)
        self.assertEqual(requested, [{"t1"}])
        self.assertEqual(
            view._current_takeoffs["t1"].position,
            [0.0, 0.0, 10.0, 0.0],
        )
        self.assertEqual(view._dirty_positions, {})

    def test_area_parent_arrow_move_preserves_hole_relative_position(self):
        view = self._make_view({"parent"})
        view._current_conditions = {
            "area": Condition(uid="area", condition_type=Condition.TYPE_AREA)
        }
        view._current_takeoffs = {
            "parent": Takeoff(
                uid="parent",
                condition_uid="area",
                position=[3.0, 3.0, 13.0, 3.0, 13.0, 13.0, 3.0, 13.0],
            ),
            "hole": Takeoff(
                uid="hole",
                condition_uid="area",
                parent_uid="parent",
                position=[6.0, 6.0, 9.0, 6.0, 9.0, 9.0, 6.0, 9.0],
            ),
        }
        view._uid_to_items = {
            "parent": [FakeItem(100.0, 100.0)],
            "hole": [FakeItem(150.0, 150.0)],
        }
        view._snap_increments = 10.0
        InputHandlerMixin.keyPressEvent(view, FakeKeyEvent(Qt.Key.Key_Right))
        self.assertEqual(
            view._current_takeoffs["parent"].position,
            [13.0, 3.0, 23.0, 3.0, 23.0, 13.0, 13.0, 13.0],
        )
        self.assertEqual(
            view._current_takeoffs["hole"].position,
            [16.0, 6.0, 19.0, 6.0, 19.0, 9.0, 16.0, 9.0],
        )
        self.assertEqual(
            view._uid_to_items["hole"][0].pos(), QtCore.QPointF(160.0, 150.0)
        )
        self.assertEqual(
            set(view._dirty_positions),
            {"parent", "hole"},
        )
        self.assertEqual(
            view._position_before_edit["hole"],
            [6.0, 6.0, 9.0, 6.0, 9.0, 9.0, 6.0, 9.0],
        )

    def test_arrow_auto_repeat_release_does_not_split_move_flush(self):
        view = self._make_view({"t1"})
        flushed = []
        view._flush_dirty_positions = lambda: flushed.append(
            dict(view._dirty_positions)
        )
        InputHandlerMixin.keyPressEvent(view, FakeKeyEvent(Qt.Key.Key_Right))
        repeat_release = FakeKeyEvent(Qt.Key.Key_Right, auto_repeat=True)
        InputHandlerMixin.keyReleaseEvent(view, repeat_release)
        self.assertTrue(repeat_release.accepted)
        self.assertEqual(flushed, [])
        self.assertTrue(view._keyboard_move_dirty)
        final_release = FakeKeyEvent(Qt.Key.Key_Right)
        InputHandlerMixin.keyReleaseEvent(view, final_release)
        self.assertTrue(final_release.accepted)
        self.assertEqual(flushed, [{"t1": [1.0, 0.0, 11.0, 0.0]}])
        self.assertFalse(view._keyboard_move_dirty)

    def test_focus_loss_flushes_pending_keyboard_move(self):
        view = self._make_view({"t1"})
        flushed = []
        reset_calls = []
        view._flush_dirty_positions = lambda: flushed.append(
            dict(view._dirty_positions)
        )
        view.reset_ctrl_held = lambda: reset_calls.append(True)
        InputHandlerMixin.keyPressEvent(view, FakeKeyEvent(Qt.Key.Key_Right))
        InputHandlerMixin.focusOutEvent(view, object())
        self.assertEqual(flushed, [{"t1": [1.0, 0.0, 11.0, 0.0]}])
        self.assertFalse(view._keyboard_move_dirty)
        self.assertEqual(reset_calls, [True])


class InputHandlerMixinFocusouteventTests(_CtrlDragFixture):
    """InputHandlerMixin.focusOutEvent."""

    def test_focus_loss_cancels_zoom_rubber_band_started_without_selection(self):
        view = self._make_view()
        hidden = []
        view._rubber_band_origin = QtCore.QPointF(1.0, 2.0)
        view._rubber_band = SimpleNamespace(hide=lambda: hidden.append(True))
        view.reset_ctrl_held = lambda: None
        InputHandlerMixin.focusOutEvent(view, object())
        self.assertEqual(hidden, [True])
        self.assertIsNone(view._rubber_band_origin)

    def test_focus_loss_finishes_pan_and_publishes_changed_view(self):
        view = self._make_view()
        published = []
        view._panning = True
        view._pan_view_changed = True
        view._last_pan_point = QtCore.QPoint(5, 6)
        view._right_pan_press_pos = None
        view._right_pan_dragged = False
        view._publish_current_page_view_state = lambda: published.append(True)
        view.reset_ctrl_held = lambda: None
        InputHandlerMixin.focusOutEvent(view, object())
        self.assertFalse(view._panning)
        self.assertFalse(view._pan_view_changed)
        self.assertIsNone(view._last_pan_point)
        self.assertEqual(published, [True])

    def test_focus_loss_restores_rotation_preview_without_committing(self):
        view = self._make_view()
        preview_item = QGraphicsPathItem()
        preview_item.setRotation(15.0)
        handle_item = FakeItem(15.0, 20.0)
        view._rotation_drag_active = True
        view._rotation_drag_uid = "t1"
        view._rotation_drag_last_angle = 15.0
        view._rotation_drag_accumulated_deg = 15.0
        view._rotation_drag_snapped_deg = 15.0
        view._rotation_drag_preview_items = [preview_item]
        view._rotation_drag_handle_origins = [(handle_item, QtCore.QPointF(10.0, 20.0))]
        view._rotation_drag_orig_positions = {"t1": [0.0, 0.0, 10.0, 0.0]}
        view._rotation_drag_orig_rotations = {"t1": 0.0}
        view._rotate_line_item = None
        view._rotate_line_outline_item = None
        view.reset_ctrl_held = lambda: None
        InputHandlerMixin.focusOutEvent(view, object())
        self.assertEqual(preview_item.rotation(), 0.0)
        self.assertEqual(handle_item.pos(), QtCore.QPointF(10.0, 20.0))
        self.assertFalse(view._rotation_drag_active)
        self.assertEqual(view._rotation_drag_preview_items, [])
        self.assertEqual(view._rotation_drag_orig_positions, {})

    def test_focus_loss_finishes_pdf_text_selection_drag(self):
        view = self._make_view()
        finished = []
        view._pdf_text_drag_anchor = (0, 1)

        def finish_pdf_text_selection_drag():
            finished.append(True)
            view._pdf_text_drag_anchor = None
            return True

        view._finish_pdf_text_selection_drag = finish_pdf_text_selection_drag
        view.reset_ctrl_held = lambda: None
        InputHandlerMixin.focusOutEvent(view, object())
        self.assertEqual(finished, [True])
        self.assertIsNone(view._pdf_text_drag_anchor)

    def test_focus_loss_during_right_pan_suppresses_the_next_context_menu(self):
        for right_pan, suppressed in ((True, True), (False, False)):
            with self.subTest(right_pan=right_pan):
                view = self._make_view()
                view._panning = True
                view._right_pan_active = right_pan
                view._suppress_next_context_menu = False
                finished = []
                view._finish_pan_interaction = lambda: finished.append(1)
                view.reset_ctrl_held = lambda: None
                InputHandlerMixin.focusOutEvent(view, object())
                self.assertEqual(finished, [1])
                self.assertEqual(view._suppress_next_context_menu, suppressed)

    def test_focus_loss_without_pan_or_keyboard_move_leaves_state_untouched(self):
        view = self._make_view()
        view._keyboard_move_dirty = False
        flushed = []
        view._flush_dirty_positions = lambda: flushed.append(1)
        view._finish_pan_interaction = lambda: self.fail("no pan to finish")
        view.reset_ctrl_held = lambda: None
        InputHandlerMixin.focusOutEvent(view, object())
        self.assertEqual(flushed, [])


class InputHandlerMixinComputeAnnResizeTests(_CtrlDragFixture):
    """InputHandlerMixin._compute_ann_resize."""

    def test_named_view_resize_top_middle_changes_top_edge_only(self):
        view, ann = self._make_named_view_resize_view()
        new_pos = view._compute_ann_resize(
            ann,
            ann.position,
            0.0,
            -5.0,
            4,
            4,
        )
        self.assertEqual(
            new_pos,
            [100.0, 80.0, 10.0, 15.0, 100.0, 15.0, 10.0, 80.0, 0.0],
        )

    def test_named_view_resize_bottom_middle_changes_bottom_edge_only(self):
        view, ann = self._make_named_view_resize_view()
        new_pos = view._compute_ann_resize(
            ann,
            ann.position,
            0.0,
            9.0,
            6,
            4,
        )
        self.assertEqual(
            new_pos,
            [100.0, 89.0, 10.0, 20.0, 100.0, 20.0, 10.0, 89.0, 0.0],
        )

    def test_named_view_resize_top_left_corner_changes_expected_corner(self):
        view, ann = self._make_named_view_resize_view()
        new_pos = view._compute_ann_resize(
            ann,
            ann.position,
            -5.0,
            -7.0,
            0,
            4,
        )
        self.assertEqual(
            new_pos,
            [100.0, 80.0, 5.0, 13.0, 100.0, 13.0, 5.0, 80.0, 0.0],
        )

    def _resize_view(self, increments=0):
        view = InputHandlerHarness()
        view._snap_increments = increments
        view._snap_angle = lambda _ox, _oy, nx, ny: (nx, ny)
        return view

    def test_bbox_handle_indices_move_the_expected_box_sides(self):
        apply_handle = InputHandlerMixin._apply_bbox_handle
        cases = {
            0: (1.0, 2.0, 10.0, 20.0),
            1: (0.0, 2.0, 11.0, 20.0),
            2: (0.0, 0.0, 11.0, 22.0),
            3: (1.0, 0.0, 10.0, 22.0),
            4: (0.0, 2.0, 10.0, 20.0),
            5: (0.0, 0.0, 11.0, 20.0),
            6: (0.0, 0.0, 10.0, 22.0),
            7: (1.0, 0.0, 10.0, 20.0),
        }
        for handle, expected in cases.items():
            with self.subTest(handle=handle):
                self.assertEqual(
                    apply_handle(0.0, 0.0, 10.0, 20.0, handle, 4, 1.0, 2.0), expected
                )

    def test_box_annotation_resize_scales_every_point_and_snaps_the_delta(self):
        view = self._resize_view(increments=2.0)
        ann = BidAnnotation(
            uid="r", annotation_type="rect", position=[0.0, 0.0, 10.0, 4.0]
        )
        self.assertEqual(
            view._compute_ann_resize(ann, ann.position, 3.0, 2.0, 2, 4),
            [0.0, 0.0, 14.0, 6.0],
        )
        poly_like = BidAnnotation(
            uid="o",
            annotation_type="oval",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 4.0, 0.0, 4.0],
        )
        self.assertEqual(
            view._compute_ann_resize(poly_like, poly_like.position, 4.0, 0.0, 1, 4),
            [0.0, 0.0, 14.0, 0.0, 14.0, 4.0, 0.0, 4.0],
        )

    def test_box_annotation_resize_without_snapping_uses_the_raw_delta(self):
        view = self._resize_view(increments=0)
        ann = BidAnnotation(
            uid="r", annotation_type="rect", position=[0.0, 0.0, 10.0, 4.0]
        )
        self.assertEqual(
            view._compute_ann_resize(ann, ann.position, 3.5, 2.25, 2, 4),
            [0.0, 0.0, 13.5, 6.25],
        )

    def test_text_annotation_resize_rewrites_center_and_absolute_size(self):
        view = self._resize_view(increments=0)
        ann = BidAnnotation(
            uid="t", annotation_type="text", position=[10.0, 10.0, 40.0, 20.0, 0.5]
        )
        self.assertEqual(
            view._compute_ann_resize(ann, ann.position, 3.0, 2.0, 2, 4),
            [11.5, 11.0, 43.0, 22.0, 0.5],
        )
        self.assertEqual(
            view._compute_ann_resize(ann, ann.position, -60.0, -40.0, 2, 4),
            [-20.0, -10.0, 20.0, 20.0, 0.5],
        )

    def test_degenerate_box_resize_collapses_to_the_moved_edge(self):
        view = self._resize_view(increments=0)
        flat = BidAnnotation(
            uid="f", annotation_type="rect", position=[5.0, 0.0, 5.0, 4.0]
        )
        self.assertEqual(
            view._compute_ann_resize(flat, flat.position, 3.0, 0.0, 0, 4),
            [8.0, 0.0, 8.0, 4.0],
        )
        thin = BidAnnotation(
            uid="n", annotation_type="rect", position=[0.0, 5.0, 10.0, 5.0]
        )
        self.assertEqual(
            view._compute_ann_resize(thin, thin.position, 0.0, 3.0, 0, 4),
            [0.0, 8.0, 10.0, 8.0],
        )

    def test_unmeasurable_box_annotation_resize_returns_a_copy_of_the_original(self):
        view = self._resize_view(increments=0)
        ann = BidAnnotation(uid="o", annotation_type="oval", position=[1.0, 2.0])
        original = ann.position
        result = view._compute_ann_resize(ann, original, 3.0, 2.0, 0, 4)
        self.assertEqual(result, [1.0, 2.0])
        self.assertIsNot(result, original)

    def test_vertex_and_line_annotations_resize_through_point_handles(self):
        view = self._resize_view(increments=0)
        square = [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
        for annotation_type in ("polygon", "cloud"):
            with self.subTest(annotation_type=annotation_type):
                ann = BidAnnotation(
                    uid="p", annotation_type=annotation_type, position=square
                )
                self.assertEqual(
                    view._compute_ann_resize(ann, square, 3.0, 2.0, 2, 4),
                    [0.0, 0.0, 10.0, 0.0, 13.0, 12.0, 0.0, 10.0],
                )
        for annotation_type in ("line", "arrow", "dimension"):
            with self.subTest(annotation_type=annotation_type):
                ann = BidAnnotation(
                    uid="l",
                    annotation_type=annotation_type,
                    position=[0.0, 0.0, 10.0, 4.0],
                )
                self.assertEqual(
                    view._compute_ann_resize(ann, ann.position, 3.0, 2.0, 1, 4),
                    [0.0, 0.0, 13.0, 6.0],
                )

    def test_handle_hit_test_is_inclusive_within_half_size_plus_two_pixels(self):
        view = InputHandlerHarness()
        view.mapFromScene = lambda point: QtCore.QPoint(int(point.x()), int(point.y()))
        handle = QGraphicsRectItem(-4.0, -4.0, 8.0, 8.0)
        handle.setPos(50.0, 60.0)
        info = SimpleNamespace(item=handle)
        for point, hit in (
            (QtCore.QPoint(56, 66), True),
            (QtCore.QPoint(44, 54), True),
            (QtCore.QPoint(57, 60), False),
            (QtCore.QPoint(50, 67), False),
            (QtCore.QPoint(43, 60), False),
            (QtCore.QPoint(50, 53), False),
        ):
            with self.subTest(point=point):
                self.assertEqual(view._is_handle_info_at_viewport_pos(info, point), hit)

    def test_rotation_handle_preview_requires_handle_and_both_guide_lines(self):
        view = InputHandlerHarness()
        handle = QGraphicsRectItem(-3.0, -3.0, 6.0, 6.0)
        handle.setPos(5.0, 5.0)
        line = QtWidgets.QGraphicsLineItem()
        outline = QtWidgets.QGraphicsLineItem()
        view._rotate_center_scene = QtCore.QPointF(0.0, 0.0)
        view._rotate_handle_radius = 10.0
        view._rotate_handle_start_angle_deg = 0.0
        for items in (
            (None, line, outline),
            (handle, None, outline),
            (handle, line, None),
        ):
            (
                view._rotate_handle_item,
                view._rotate_line_item,
                view._rotate_line_outline_item,
            ) = items
            view._update_rotation_handle_preview(90.0)
            self.assertEqual(handle.pos(), QtCore.QPointF(5.0, 5.0))
        view._rotate_handle_item = handle
        view._rotate_line_item = line
        view._rotate_line_outline_item = outline
        view._update_rotation_handle_preview(90.0)
        self.assertAlmostEqual(handle.pos().x(), 0.0, places=9)
        self.assertAlmostEqual(handle.pos().y(), 10.0, places=9)
        self.assertAlmostEqual(line.line().y2(), 10.0, places=9)
        self.assertEqual(outline.line(), line.line())
        view._rotate_handle_start_angle_deg = 90.0
        view._update_rotation_handle_preview(-90.0)
        self.assertAlmostEqual(handle.pos().x(), 10.0, places=9)
        self.assertAlmostEqual(handle.pos().y(), 0.0, places=9)


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

    def set_attachment_dimensions(self, view, width, depth):
        condition = view._current_conditions["attachment"]
        condition.width = width
        condition.depth = depth

    def test_keyboard_collides_at_every_edge(self):
        for dx, dy in ((-6, 0), (6, 0), (0, -6), (0, 6)):
            with self.subTest(delta=(dx, dy)):
                view = self.make_view()
                self.assertFalse(view._apply_position_keyboard_move(dx, dy))
                self.assertEqual(
                    view._current_takeoffs["attachment"].position, [5.0, 5.0]
                )
                self.assertEqual(view._dirty_positions, {})

    def test_backout_group_moves_reject_parent_escape_and_sibling_collision_atomically(
        self,
    ):
        for delta in ((-6, 0), (6, 0), (0, -6), (0, 6), (2, 0)):
            with self.subTest(delta=delta):
                view = self.make_view()
                del view._current_takeoffs["attachment"]
                self.add_backout(view, [2, 2, 5, 2, 5, 5, 2, 5])
                view._current_takeoffs["sibling"] = Takeoff(
                    uid="sibling",
                    condition_uid="area",
                    page_uid="page",
                    parent_uid="parent",
                    position=[6, 1, 9, 1, 9, 9, 6, 9],
                )
                view._current_conditions["count"] = Condition(
                    uid="count", condition_type=Condition.TYPE_COUNT
                )
                view._current_takeoffs["count"] = Takeoff(
                    uid="count",
                    condition_uid="count",
                    page_uid="page",
                    position=[20, 20],
                )
                view._selected_uids = {"backout", "count"}
                before = {
                    uid: list(item.position)
                    for uid, item in view._current_takeoffs.items()
                }
                self.assertFalse(view._apply_position_keyboard_move(*delta))
                self.assertEqual(
                    {
                        uid: item.position
                        for uid, item in view._current_takeoffs.items()
                    },
                    before,
                )
                self.assertEqual(view._dirty_positions, {})

    def test_toolbar_backout_rotation_cannot_escape_parent_without_attachments(self):
        view = self.make_view()
        view._scene_builder.cs.ost_to_screen_pixels = lambda value: float(value)
        del view._current_takeoffs["attachment"]
        self.add_backout(view, [1, 1, 9, 1, 9, 2, 1, 2])
        view._selected_uids = {"backout"}
        flushed = []
        view._flush_rotation_group = lambda: flushed.append(True)
        original = list(view._current_takeoffs["backout"].position)
        view._transform_selected_takeoffs("rotate", degrees=90)
        self.assertEqual(view._current_takeoffs["backout"].position, original)
        self.assertEqual(flushed, [])

    def test_multi_rotation_moves_unselected_children_around_group_pivot(self):
        view = self.make_view()
        self.add_backout(view, [1, 1, 2, 1, 2, 2, 1, 2])
        view._current_conditions["count"] = Condition(
            uid="count", condition_type=Condition.TYPE_COUNT
        )
        view._current_takeoffs["count"] = Takeoff(
            uid="count", condition_uid="count", page_uid="page", position=[20, 20]
        )
        view._selected_uids = {"parent", "count"}
        view._rotation_drag_orig_positions = {
            uid: list(view._current_takeoffs[uid].position)
            for uid in view._selected_uids
        }
        view._rotation_drag_orig_rotations = {uid: 0 for uid in view._selected_uids}
        view._rotate_ost_center = (0, 0)
        view._flush_rotation_group = lambda: None
        view._apply_multi_rotation(90)
        self.assertAlmostEqual(view._current_takeoffs["parent"].position[2], 0)
        self.assertEqual(view._current_takeoffs["attachment"].position, [-5, 5])
        self.assertAlmostEqual(
            view._current_takeoffs["attachment"].rotation, math.pi / 2
        )
        self.assertAlmostEqual(view._current_takeoffs["count"].rotation, math.pi / 2)
        for actual, expected in zip(
            view._current_takeoffs["backout"].position, [-1, 1, -1, 2, -2, 2, -2, 1]
        ):
            self.assertAlmostEqual(actual, expected)

    def test_nested_children_follow_ancestor_move_and_rotation_once(self):
        for operation in ("nudge", "multi_rotation", "toolbar_rotation"):
            with self.subTest(operation=operation):
                view = self.make_view()
                view._scene_builder.cs.ost_to_screen_pixels = float
                self.add_backout(view, [1, 1, 4, 1, 4, 4, 1, 4])
                attachment = view._current_takeoffs["attachment"]
                attachment.condition_uid = "area"
                attachment.parent_uid = "backout"
                attachment.position = [2, 2, 3, 2, 3, 3, 2, 3]
                # Reverse insertion order exercises graph traversal, not list order.
                view._current_takeoffs = dict(
                    reversed(list(view._current_takeoffs.items()))
                )
                view._selected_uids = {"parent"}
                view._rotation_drag_orig_positions = {
                    "parent": list(view._current_takeoffs["parent"].position)
                }
                view._rotation_drag_orig_rotations = {"parent": 0}
                view._rotate_ost_center = (5, 5)
                view._flush_rotation_group = lambda: None
                if operation == "nudge":
                    self.assertTrue(view._apply_position_keyboard_move(1, 0))
                    expected = [3, 2, 4, 2, 4, 3, 3, 3]
                else:
                    if operation == "multi_rotation":
                        view._apply_multi_rotation(90)
                    else:
                        view._transform_selected_takeoffs("rotate", degrees=90)
                    expected = [8, 2, 8, 3, 7, 3, 7, 2]
                for actual, wanted in zip(attachment.position, expected):
                    self.assertAlmostEqual(actual, wanted)

    def test_single_area_rotation_rotates_legacy_count_child_orientation(self):
        view = self.make_view()
        condition = view._current_conditions["attachment"]
        condition.condition_type = Condition.TYPE_COUNT
        condition.shape = 3
        condition.width, condition.depth = 4, 2
        child = view._current_takeoffs["attachment"]
        child.rotation = 0.25
        child.position = [6, 5]
        view._rotation_drag_orig_positions = {
            "parent": list(view._current_takeoffs["parent"].position)
        }
        view._rotation_drag_orig_rotations = {"parent": 0}
        view._flush_rotation_group = lambda: None
        view._flush_dirty_positions = lambda: None
        view._apply_single_rotation("parent", 90)
        self.assertEqual(child.position, [5, 6])
        self.assertAlmostEqual(child.rotation, 0.25 + math.pi / 2)

    def test_interactive_attachment_rotation_preview_accepts_valid_footprint(self):
        view = self.make_view()
        view._cursor_mode = "rotate"
        view._rotation_drag_active = True
        view._rotation_drag_uid = "attachment"
        view._rotation_drag_orig_positions = {"attachment": [5, 5]}
        view._rotation_drag_orig_rotations = {"attachment": 0}
        view._rotation_drag_preview_items = []
        view._rotation_drag_handle_origins = []
        view._rotation_drag_last_angle = 0
        view._rotation_drag_accumulated_deg = 0
        view._rotation_drag_snapped_deg = 0
        view._rotate_center_scene = QPointF(5, 5)
        view._update_rotation_handle_preview = lambda _angle: None
        view.mapToScene = lambda point: QPointF(point)
        view.mouseMoveEvent(fixtures.FakeMouseEvent(x=5, y=10))
        self.assertEqual(view._rotation_drag_snapped_deg, 90)

    def test_legacy_parented_count_rotation_does_not_use_polygon_validation(self):
        view = self.make_view()
        view._current_conditions["attachment"].condition_type = Condition.TYPE_COUNT
        view._cursor_mode = "rotate"
        view._rotation_drag_active = True
        view._rotation_drag_uid = "attachment"
        view._rotation_drag_orig_positions = {"attachment": [5, 5]}
        view._rotation_drag_orig_rotations = {"attachment": 0}
        view._rotation_drag_preview_items = []
        view._rotation_drag_handle_origins = []
        view._rotation_drag_last_angle = 0
        view._rotation_drag_accumulated_deg = 0
        view._rotation_drag_snapped_deg = 0
        view._rotate_center_scene = QPointF(5, 5)
        view._update_rotation_handle_preview = lambda _angle: None
        view.mapToScene = lambda point: QPointF(point)
        view.mouseMoveEvent(fixtures.FakeMouseEvent(x=5, y=10))
        self.assertEqual(view._rotation_drag_snapped_deg, 90)

    def test_legacy_parented_linear_rotation_commits_without_area_cutout_validation(
        self,
    ):
        view = self.make_view()
        view._current_conditions["attachment"].condition_type = Condition.TYPE_LINEAR
        item = view._current_takeoffs["attachment"]
        item.position = [2, 5, 8, 5]
        view._rotation_drag_orig_positions = {item.uid: list(item.position)}
        view._rotation_drag_orig_rotations = {item.uid: 0}
        view._flush_dirty_positions = lambda: None
        view._create_rotate_handle = lambda _uid: None
        view._apply_single_rotation(item.uid, 90)
        for actual, expected in zip(item.position, [5, 2, 5, 8]):
            self.assertAlmostEqual(actual, expected)

    def test_attachment_full_footprint_must_remain_inside_area(self):
        view = self.make_view()
        self.set_attachment_dimensions(view, 4.0, 2.0)
        self.assertFalse(view._apply_position_keyboard_move(4.0, 0.0))
        self.assertEqual(view._current_takeoffs["attachment"].position, [5.0, 5.0])

    def test_concave_area_rejects_notch_not_just_bounding_box(self):
        view = self.make_view()
        view._current_takeoffs["parent"].position = [
            0.0,
            0.0,
            10.0,
            0.0,
            10.0,
            3.0,
            3.0,
            3.0,
            3.0,
            10.0,
            0.0,
            10.0,
        ]
        view._current_takeoffs["attachment"].position = [2.0, 2.0]
        self.assertFalse(view._apply_position_keyboard_move(3, 3))
        self.assertTrue(view._apply_position_keyboard_move(5, 0))
        self.assertEqual(view._current_takeoffs["attachment"].position, [7.0, 2.0])

    def test_mouse_release_outside_preserves_last_valid_position(self):
        for handle in (-1, 0):
            with self.subTest(handle=handle):
                view = self.make_view()
                view._select_band_origin = QPointF(5.0, 5.0)
                view._select_band_dragged = True
                view._drag_plan_item_uid = "attachment"
                view._drag_handle_index = handle
                view._drag_orig_position = [5.0, 5.0]
                view._drag_last_valid_new_pos = [5.0, 5.0]
                view.mapToScene = lambda point: QPointF(point)
                view.scene_to_ost_delta = lambda dx, dy: (dx, dy)
                view.update_drag_handle_positions([8.0, 5.0], "attachment")
                view.update_drag_handle_positions([20.0, 5.0], "attachment")
                view.mouseReleaseEvent(
                    fixtures.FakeMouseEvent(x=20, y=5, buttons=Qt.MouseButton.NoButton)
                )
                self.assertEqual(
                    view._current_takeoffs["attachment"].position, [8.0, 5.0]
                )
                self.assertEqual(view._dirty_positions, {"attachment": [8.0, 5.0]})

    def test_boundary_nudge_is_consumed_without_scroll_or_dirty_state(self):
        view = self.make_view()
        view._current_takeoffs["attachment"].position = [9.0, 5.0]
        for _ in range(3):
            event = fixtures.FakeKeyEvent(Qt.Key.Key_Right)
            view.keyPressEvent(event)
            self.assertTrue(event.accepted)
        self.assertEqual(view._current_takeoffs["attachment"].position, [9.0, 5.0])
        self.assertEqual(view._dirty_positions, {})
        self.assertFalse(view._keyboard_move_dirty)

    def test_missing_wrong_page_and_non_area_parent_reject(self):
        for mutation in ("missing", "page", "condition", "backout"):
            with self.subTest(mutation=mutation):
                view = self.make_view()
                parent = view._current_takeoffs["parent"]
                if mutation == "missing":
                    del view._current_takeoffs["parent"]
                elif mutation == "page":
                    parent.page_uid = "other-page"
                elif mutation == "condition":
                    parent.condition_uid = "attachment"
                else:
                    parent.parent_uid = "another-area"
                self.assertFalse(view._apply_position_keyboard_move(1, 0))
                self.assertEqual(view._dirty_positions, {})

    def test_parent_and_attachment_move_together_without_double_translation(self):
        view = self.make_view()
        view._selected_uids = {"parent", "attachment"}
        self.assertTrue(view._apply_position_keyboard_move(100, 100))
        self.assertEqual(view._current_takeoffs["attachment"].position, [105.0, 105.0])
        self.assertEqual(view._current_takeoffs["parent"].position[:2], [100.0, 100.0])
        self.assertEqual(view._current_takeoffs["attachment"].parent_uid, "parent")
        self.assertEqual(view._current_takeoffs["attachment"].area_uid, "bid-area")

    def test_invalid_group_move_does_not_partially_move_other_items(self):
        view = self.make_view()
        view._current_conditions["count"] = Condition(
            uid="count", condition_type=Condition.TYPE_COUNT
        )
        view._current_takeoffs["count"] = Takeoff(
            uid="count", condition_uid="count", position=[50.0, 50.0]
        )
        view._selected_uids.add("count")
        self.assertFalse(view._apply_position_keyboard_move(6, 0))
        self.assertEqual(view._current_takeoffs["count"].position, [50.0, 50.0])
        self.assertEqual(view._dirty_positions, {})

    def test_group_backout_move_cannot_enter_unselected_attachment(self):
        view = self.make_view()
        self.set_attachment_dimensions(view, 2.0, 2.0)
        self.add_backout(view, [1.0, 4.0, 3.0, 4.0, 3.0, 6.0, 1.0, 6.0])
        view._selected_uids = {"backout"}
        self.assertFalse(view._apply_position_keyboard_move(3.0, 0.0))
        self.assertEqual(
            view._current_takeoffs["backout"].position,
            [1.0, 4.0, 3.0, 4.0, 3.0, 6.0, 1.0, 6.0],
        )
        self.assertEqual(view._dirty_positions, {})

    def test_single_attachment_rotation_updates_rotation(self):
        view = self.make_view()
        self.set_attachment_dimensions(view, 4.0, 2.0)
        view._rotation_drag_orig_positions = {"attachment": [5.0, 5.0]}
        view._rotation_drag_orig_rotations = {"attachment": 0.0}
        flushed = []
        view._flush_dirty_rotations = lambda: flushed.append(True)
        view._create_rotate_handle = lambda _uids: True
        view._apply_single_rotation("attachment", 90.0)
        self.assertAlmostEqual(
            view._current_takeoffs["attachment"].rotation, math.pi / 2.0
        )
        self.assertEqual(flushed, [True])

    def test_single_attachment_rotation_rejects_footprint_outside_area(self):
        view = self.make_view()
        self.set_attachment_dimensions(view, 4.0, 2.0)
        attachment = view._current_takeoffs["attachment"]
        attachment.position = [5.0, 1.0]
        view._rotation_drag_orig_positions = {"attachment": [5.0, 1.0]}
        view._rotation_drag_orig_rotations = {"attachment": 0.0}
        flushed = []
        view._flush_dirty_rotations = lambda: flushed.append(True)
        view._create_rotate_handle = lambda _uids: True
        view._apply_single_rotation("attachment", 90.0)
        self.assertEqual(attachment.rotation, 0.0)
        self.assertEqual(view._dirty_rotations, {})
        self.assertEqual(flushed, [])

    def test_single_attachment_rotation_rejects_backout_collision(self):
        view = self.make_view()
        self.set_attachment_dimensions(view, 4.0, 2.0)
        attachment = view._current_takeoffs["attachment"]
        attachment.position = [3.0, 5.0]
        self.add_backout(view, [2.0, 1.0, 4.0, 1.0, 4.0, 3.9, 2.0, 3.9])
        view._rotation_drag_orig_positions = {"attachment": [3.0, 5.0]}
        view._rotation_drag_orig_rotations = {"attachment": 0.0}
        view._create_rotate_handle = lambda _uids: True
        flushed = []
        view._flush_dirty_rotations = lambda: flushed.append(True)
        view._apply_single_rotation("attachment", 90.0)
        self.assertEqual(attachment.rotation, 0.0)
        self.assertEqual(view._dirty_rotations, {})
        self.assertEqual(flushed, [])

    def test_toolbar_attachment_rotation_rejects_footprint_outside_area(self):
        view = self.make_view()
        self.set_attachment_dimensions(view, 4.0, 2.0)
        attachment = view._current_takeoffs["attachment"]
        attachment.position = [5.0, 1.0]
        view._scene_builder.cs.ost_to_screen_pixels = lambda value: float(value)
        flushed = []
        view._flush_rotation_group = lambda: flushed.append(True)
        view.rotate_selected_takeoffs(90.0)
        self.assertEqual(attachment.position, [5.0, 1.0])
        self.assertEqual(attachment.rotation, 0.0)
        self.assertEqual(view._dirty_positions, {})
        self.assertEqual(view._dirty_rotations, {})
        self.assertEqual(flushed, [])

    def test_area_rotation_rotates_attachment_footprint_with_parent(self):
        view = self.make_view()
        self.set_attachment_dimensions(view, 4.0, 2.0)
        view._selected_uids = {"parent"}
        view._rotation_drag_orig_positions = {
            "parent": list(view._current_takeoffs["parent"].position)
        }
        view._rotation_drag_orig_rotations = {"parent": 0.0}
        view._flush_dirty_positions = lambda: None
        view._flush_rotation_group = lambda: None
        view._apply_single_rotation("parent", 90.0)
        self.assertAlmostEqual(
            view._current_takeoffs["attachment"].rotation, math.pi / 2.0
        )
        self.assertIn("attachment", view._dirty_rotations)

    def test_group_backout_rotation_cannot_enter_unselected_attachment(self):
        view = self.make_view()
        self.set_attachment_dimensions(view, 2.0, 2.0)
        original = [1.0, 4.0, 3.0, 4.0, 3.0, 6.0, 1.0, 6.0]
        self.add_backout(view, original)
        view._selected_uids = {"backout"}
        view._rotation_drag_orig_positions = {"backout": list(original)}
        view._rotation_drag_orig_rotations = {"backout": 0.0}
        view._rotate_ost_center = (3.5, 5.0)
        flushed = []
        view._flush_rotation_group = lambda: flushed.append(True)
        view._apply_multi_rotation(180.0)
        self.assertEqual(view._current_takeoffs["backout"].position, original)
        self.assertEqual(view._dirty_positions, {})
        self.assertEqual(flushed, [])

    def test_toolbar_backout_rotation_cannot_enter_unselected_attachment(self):
        view = self.make_view()
        self.set_attachment_dimensions(view, 2.0, 2.0)
        original = [2.5, 2.0, 3.5, 2.0, 3.5, 8.0, 2.5, 8.0]
        self.add_backout(view, original)
        view._selected_uids = {"backout"}
        view._scene_builder.cs.ost_to_screen_pixels = lambda value: float(value)
        flushed = []
        view._flush_rotation_group = lambda: flushed.append(True)
        view.rotate_selected_takeoffs(90.0)
        self.assertEqual(view._current_takeoffs["backout"].position, original)
        self.assertEqual(view._dirty_positions, {})
        self.assertEqual(flushed, [])

    def test_mouse_release_outside_without_last_valid_position_changes_nothing(self):
        for handle in (-1, 0):
            with self.subTest(handle=handle):
                view = self.make_view()
                view._select_band_origin = QPointF(5.0, 5.0)
                view._select_band_dragged = True
                view._drag_plan_item_uid = "attachment"
                view._drag_handle_index = handle
                view._drag_orig_position = [5.0, 5.0]
                view._drag_last_valid_new_pos = []
                view.mapToScene = lambda point: QPointF(point)
                view.scene_to_ost_delta = lambda dx, dy: (dx, dy)
                view.mouseReleaseEvent(
                    fixtures.FakeMouseEvent(x=20, y=5, buttons=Qt.MouseButton.NoButton)
                )
                self.assertEqual(
                    view._current_takeoffs["attachment"].position, [5.0, 5.0]
                )
                self.assertEqual(view._dirty_positions, {})
                self.assertIsNone(view._drag_plan_item_uid)

    def test_selected_attachment_rotates_once_with_its_selected_area(self):
        view = self.make_view()
        view._selected_uids = {"parent", "attachment"}
        view._rotation_drag_orig_positions = {
            uid: list(view._current_takeoffs[uid].position)
            for uid in view._selected_uids
        }
        view._rotation_drag_orig_rotations = {"parent": 0.0, "attachment": 0.25}
        view._rotate_ost_center = (5, 5)
        view._flush_rotation_group = lambda: None
        view._apply_multi_rotation(90)
        attachment = view._current_takeoffs["attachment"]
        self.assertAlmostEqual(attachment.rotation, 0.25 + math.pi / 2)
        self.assertEqual(view._dirty_rotations, {"attachment": attachment.rotation})
        self.assertEqual(view._rotation_before_edit, {"attachment": 0.25})


class SmallSnappedDragTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = fixtures._app()

    def make_view(self, **options):
        view = fixtures.CtrlDragTests()._make_linear_resize_gesture_view(**options)
        view._current_conditions["c"].condition_type = Condition.TYPE_AREA
        view._current_takeoffs["t1"].position = [
            0.0,
            0.0,
            12.0,
            0.0,
            12.0,
            12.0,
            0.0,
            12.0,
        ]
        view._is_handle_info_at_viewport_pos = lambda _info, _pos: False
        view._pt_to_scene = lambda x, y: QPointF(x, y)
        view.ost_to_scene_delta = lambda dx, dy: DragHandlerMixin.ost_to_scene_delta(
            view, dx, dy
        )
        view.update_drag_handle_positions = (
            lambda *args: DragHandlerMixin.update_drag_handle_positions(view, *args)
        )
        return view

    @staticmethod
    def gesture(view, points):
        view.mousePressEvent(fixtures.FakeMouseEvent(x=0, y=0))
        for x, y in points:
            view.mouseMoveEvent(fixtures.FakeMouseEvent(x=x, y=y))
        candidate = list(view._drag_last_valid_new_pos)
        x, y = points[-1] if points else (0, 0)
        view.mouseReleaseEvent(
            fixtures.FakeMouseEvent(x=x, y=y, buttons=Qt.MouseButton.NoButton)
        )
        return candidate

    def test_minimal_increments_in_each_direction_across_scale_and_zoom(self):
        # Cover Sheet accepts positive floating increments; there is no fixed
        # smallest increment. Include 1/64 inch and the metric 1 mm conversion.
        for increment in (1.0, 1.0 / 64.0, 0.1, 1.0 / 25.4, 2.0):
            for scale in (48.0, 96.0):
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1)):
                    with self.subTest(
                        increment=increment, scale=scale, direction=(dx, dy)
                    ):
                        zoom = scale / (144.0 * increment)
                        view = self.make_view(
                            scale_ratio=scale, zoom=zoom, snap_increment=increment
                        )
                        original = list(view._current_takeoffs["t1"].position)
                        candidate = self.gesture(view, [(dx, dy)])
                        self.assertEqual(
                            view._current_takeoffs["t1"].position, candidate
                        )
                        self.assertAlmostEqual(
                            candidate[0] - original[0], dx * increment
                        )
                        self.assertAlmostEqual(
                            candidate[1] - original[1], dy * increment
                        )
                        self.assertEqual(
                            view.positions_flushed.emitted,
                            [([("t1", original, candidate)], [])],
                        )

    def test_raw_two_pixels_snap_to_one_inch_and_large_movement_still_commits(self):
        for pixels, inches in ((2, 1.0), (30, 10.0)):
            with self.subTest(pixels=pixels):
                view = self.make_view()
                candidate = self.gesture(view, [(pixels, 0)])
                self.assertEqual(candidate[0], inches)
                self.assertEqual(view._current_takeoffs["t1"].position, candidate)
                self.assertEqual(len(view.positions_flushed.emitted), 1)

    def test_snap_back_and_click_are_no_ops_without_selection_cycling(self):
        for points in ([], [(1, 0)], [(3, 0), (0, 0)], [(30, 0), (0, 0)]):
            with self.subTest(points=points):
                view = self.make_view()
                original = list(view._current_takeoffs["t1"].position)
                self.gesture(view, points)
                self.assertEqual(view._current_takeoffs["t1"].position, original)
                self.assertEqual(view.positions_flushed.emitted, [])
                self.assertEqual(view._selected_uids, {"t1"})

    def test_click_on_off_grid_area_does_not_quantize_its_geometry(self):
        view = self.make_view()
        view._current_takeoffs["t1"].position = [
            v + 0.2 for v in view._current_takeoffs["t1"].position
        ]
        original = list(view._current_takeoffs["t1"].position)
        self.gesture(view, [])
        self.assertEqual(view._current_takeoffs["t1"].position, original)
        self.assertEqual(view.positions_flushed.emitted, [])

    def test_small_drag_uses_page_rotation_and_flip_transform_once(self):
        for angle, expected in (
            (0, (1, 0)),
            (90, (0, -1)),
            (180, (-1, 0)),
            (270, (0, 1)),
        ):
            for flip in (False, True):
                with self.subTest(angle=angle, flip=flip):
                    view = self.make_view()
                    transform = QTransform().rotate(angle).scale(-1 if flip else 1, 1)
                    view._current_page_transform = lambda: transform
                    candidate = self.gesture(view, [(3, 0)])
                    self.assertEqual(
                        candidate[:2],
                        [-expected[0] if flip else expected[0], expected[1]],
                    )
                    self.assertEqual(view._current_takeoffs["t1"].position, candidate)

    def add_children(self, view):
        view._current_conditions["attachment"] = Condition(
            "attachment", condition_type=Condition.TYPE_ATTACHMENT
        )
        for uid, condition, position in (
            ("backout", "c", [2.0, 2.0, 4.0, 2.0, 4.0, 4.0, 2.0, 4.0]),
            ("attachment", "attachment", [8.0, 8.0]),
        ):
            view._current_takeoffs[uid] = Takeoff(
                uid, condition, parent_uid="t1", position=position, area_uid="area-id"
            )

    def test_minimal_parent_movement_translates_backout_and_attachment_once(self):
        for selected in ({"t1"}, {"t1", "backout", "attachment"}):
            with self.subTest(selected=selected):
                view = self.make_view()
                self.add_children(view)
                view._selected_uids = selected
                original = {
                    uid: list(t.position)
                    for uid, t in view._current_takeoffs.items()
                    if uid != "t2"
                }
                self.gesture(view, [(3, 0)])
                for uid, before in original.items():
                    expected = [
                        v + (1.0 if i % 2 == 0 else 0.0) for i, v in enumerate(before)
                    ]
                    self.assertEqual(view._current_takeoffs[uid].position, expected)
                for uid in ("backout", "attachment"):
                    self.assertEqual(view._current_takeoffs[uid].parent_uid, "t1")
                    self.assertEqual(view._current_takeoffs[uid].area_uid, "area-id")
                self.assertEqual(len(view.positions_flushed.emitted), 1)
                self.assertEqual(len(view.positions_flushed.emitted[0][0]), 3)

    def test_adjacent_body_drag_paths_commit_the_same_small_translation(self):
        for kind in ("linear", "count", "backout", "attachment"):
            with self.subTest(kind=kind):
                view = self.make_view()
                condition = view._current_conditions["c"]
                condition.condition_type = {
                    "linear": Condition.TYPE_LINEAR,
                    "count": Condition.TYPE_COUNT,
                    "backout": Condition.TYPE_AREA,
                    "attachment": Condition.TYPE_ATTACHMENT,
                }[kind]
                takeoff = view._current_takeoffs["t1"]
                if kind == "linear":
                    takeoff.position = [0.0, 0.0, 12.0, 0.0]
                elif kind in ("count", "attachment"):
                    takeoff.position = [0.0, 0.0]
                if kind in ("backout", "attachment"):
                    takeoff.parent_uid = "t2"
                    view._current_conditions["parent"] = Condition(
                        "parent", condition_type=Condition.TYPE_AREA
                    )
                    parent = view._current_takeoffs["t2"]
                    parent.condition_uid = "parent"
                    parent.position = [
                        -100.0,
                        -100.0,
                        100.0,
                        -100.0,
                        100.0,
                        100.0,
                        -100.0,
                        100.0,
                    ]
                original = list(takeoff.position)
                self.gesture(view, [(3, 0)])
                expected = [
                    v + (1.0 if i % 2 == 0 else 0.0) for i, v in enumerate(original)
                ]
                self.assertEqual(takeoff.position, expected)
                self.assertEqual(
                    view.positions_flushed.emitted, [([("t1", original, expected)], [])]
                )

    def test_one_inch_area_preview_is_committed_below_pixel_threshold(self):
        view = self.make_view()
        original = list(view._current_takeoffs["t1"].position)
        item = view._uid_to_items["t1"][0]
        original_item_position = item.pos()
        view.mousePressEvent(fixtures.FakeMouseEvent(x=0, y=0))
        view.mouseMoveEvent(fixtures.FakeMouseEvent(x=3, y=0))
        candidate = list(view._drag_last_valid_new_pos)
        self.assertEqual(candidate[0] - original[0], 1.0)
        self.assertEqual(item.pos() - original_item_position, QPointF(3, 0))
        self.assertEqual(view._current_takeoffs["t1"].position, original)
        view.mouseReleaseEvent(
            fixtures.FakeMouseEvent(x=3, y=0, buttons=Qt.MouseButton.NoButton)
        )
        self.assertEqual(view._current_takeoffs["t1"].position, candidate)
        self.assertEqual(
            view.positions_flushed.emitted, [([("t1", original, candidate)], [])]
        )

    def test_small_multi_area_preview_is_committed(self):
        view = self.make_view()
        view._selected_uids = {"t1", "t2"}
        original = {uid: list(t.position) for uid, t in view._current_takeoffs.items()}
        view.mousePressEvent(fixtures.FakeMouseEvent(x=0, y=0))
        view.mouseMoveEvent(fixtures.FakeMouseEvent(x=3, y=0))
        self.assertEqual(view._uid_to_items["t1"][0].pos(), QPointF(4, 2))
        view.mouseReleaseEvent(
            fixtures.FakeMouseEvent(x=3, y=0, buttons=Qt.MouseButton.NoButton)
        )
        for uid, before in original.items():
            self.assertEqual(
                view._current_takeoffs[uid].position,
                [v + (1.0 if i % 2 == 0 else 0.0) for i, v in enumerate(before)],
            )
        self.assertEqual(len(view.positions_flushed.emitted), 1)


class PlanViewInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def test_takeoff_context_menu_without_reassign_targets_exits_cleanly(self):
        class FakeContextMenuEvent:
            def __init__(self):
                self.accepted = False

            def pos(self):
                return QtCore.QPoint(0, 0)

            def globalPos(self):
                return QtCore.QPoint(0, 0)

            def accept(self):
                self.accepted = True

        class FakeMenu:
            def __init__(self, _parent=None):
                self._actions = []

            def addAction(self, text):
                action = QAction(text)
                self._actions.append(action)
                return action

            def addSeparator(self):
                pass

            def exec(self, _pos):
                return None

            def deleteLater(self):
                pass

        def add_no_common_submenus(_menu):
            return 0, None, None

        def add_no_context_actions(_menu):
            pass

        view = self._make_plan_view()
        self._install_page_canvas(
            view, Page(uid="page-1", name="Page 1", width_pts=612.0, height_pts=792.0)
        )
        view._add_common_context_submenus = add_no_common_submenus
        view._add_context_clipboard_actions = add_no_context_actions
        view._add_context_page_actions = add_no_context_actions
        view._current_conditions = {
            "linear": Condition(uid="linear", condition_type=Condition.TYPE_LINEAR),
            "area": Condition(uid="area", condition_type=Condition.TYPE_AREA),
        }
        view._current_takeoffs = {
            "linear-takeoff": Takeoff(uid="linear-takeoff", condition_uid="linear"),
            "area-takeoff": Takeoff(uid="area-takeoff", condition_uid="area"),
        }
        view._selected_uids = {"linear-takeoff", "area-takeoff"}
        event = FakeContextMenuEvent()
        with patch(
            "ost_visualizer.presentation.components.plan_view.components.input_handler.QMenu",
            FakeMenu,
        ):
            view.contextMenuEvent(event)
        self.assertTrue(event.accepted)
        view.cleanup()

    def test_plan_labels_remain_selectable_outside_annotation_placement(self):
        for label_kind in ("condition", "dimension"):
            with self.subTest(label_kind=label_kind):
                view = self._make_plan_view()
                selected = []
                label = QGraphicsTextItem(label_kind)
                if label_kind == "condition":
                    label.setData(2, "condition_label")
                    lookup_patch = patch.object(
                        view, "_condition_text_label_at", return_value=label
                    )
                    selection_patch = patch.object(
                        view,
                        "_select_condition_text_label",
                        side_effect=lambda item: selected.append(item),
                    )
                else:
                    label.setData(2, DIMENSION_LABEL_ITEM_KIND)
                    lookup_patch = patch.object(
                        view, "_dimension_text_label_at", return_value=label
                    )
                    selection_patch = patch.object(
                        view,
                        "_select_dimension_text_label",
                        side_effect=lambda item: selected.append(item) or True,
                    )
                with lookup_patch, selection_patch:
                    press = self._left_press_event(80.0, 80.0)
                    view.mousePressEvent(press)
                self.assertTrue(press.isAccepted())
                self.assertEqual(selected, [label])
                self.assertEqual(view.cursor_mode, CURSOR_MODE_SELECT)
                self.assertIsNone(view.annotation_place_type)
                view.cleanup()

    def test_context_color_picker_drops_result_after_selection_changes(self):
        view = self._make_plan_view()
        original = BidAnnotation(
            uid="a1",
            annotation_type="rect",
            position=[1.0, 2.0, 13.0, 14.0],
            color="#ff0000",
            width=4.0,
        )
        replacement_selection = BidAnnotation(
            uid="a2",
            annotation_type="rect",
            position=[20.0, 22.0, 33.0, 34.0],
            color="#0000ff",
            width=5.0,
        )
        view._current_annotations = {
            "a1": original,
            "a2": replacement_selection,
        }
        view._selected_uids = {"a1"}
        emitted = []
        view.annotation_styles_flushed.connect(lambda changes: emitted.extend(changes))

        def change_selection(*_args, **_kwargs):
            view._selected_uids = {"a2"}
            return QColor("#445566")

        with patch.object(QColorDialog, "getColor", side_effect=change_selection):
            view._select_context_annotation_color(
                view._context_menu_owner(), {"a1": original}
            )
        self.assertEqual(original.color, "#ff0000")
        self.assertEqual(replacement_selection.color, "#0000ff")
        self.assertEqual(emitted, [])
        view.cleanup()

    def test_escape_cancel_inline_text_annotation_clears_text_cursor_selection(self):
        view = self._make_plan_view()
        annotation, item = self._add_text_annotation(view, text="Before")
        view._selected_uids = {"a1"}
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        item.setPlainText("After")
        self._select_document_text(item)
        view.keyPressEvent(
            QKeyEvent(
                QtCore.QEvent.Type.KeyPress,
                QtCore.Qt.Key.Key_Escape,
                QtCore.Qt.KeyboardModifier.NoModifier,
            )
        )
        self.assertFalse(item.textCursor().hasSelection())
        self.assertEqual(item.textCursor().selectedText(), "")
        self.assertEqual(item.toPlainText(), "Before")
        self.assertEqual(annotation.properties["Text"], "Before")
        self.assertEqual(view._selected_uids, {"a1"})
        view.cleanup()

    def test_named_view_inline_edit_uses_ibeam_cursor_over_label(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="nv1",
            annotation_type="namedview",
            properties={"Text": "Before"},
        )
        background = QGraphicsRectItem(0.0, 0.0, 40.0, 18.0)
        background.setData(0, "nv1")
        background.setData(2, NAMED_VIEW_LABEL_BACKGROUND_ITEM_KIND)
        label = QGraphicsTextItem("Before")
        label.setData(0, "nv1")
        label.setData(2, NAMED_VIEW_LABEL_ITEM_KIND)
        view._scene.addItem(background)
        view._scene.addItem(label)
        view._uid_to_items = {"nv1": [background, label]}
        view._current_annotations = {"nv1": annotation}
        view._selection_enabled = True
        view._selected_uids = {"nv1"}
        view._cursor_mode = "select"
        self.assertTrue(view._begin_named_view_rename("nv1"))
        label_center = view.mapFromScene(
            label.mapToScene(label.boundingRect().center())
        )
        self.assertEqual(
            view._resolve_cursor(label_center),
            QtCore.Qt.CursorShape.IBeamCursor,
        )
        self.assertEqual(
            view._resolve_cursor(QtCore.QPoint(200, 200)),
            QtCore.Qt.CursorShape.ArrowCursor,
        )
        view.cleanup()

    def test_click_outside_inline_text_edit_commits_and_clears_access_lock(self):
        view = self._make_plan_view()
        annotation, item = self._add_text_annotation(
            view,
            text="Before",
            position=[0.0, 0.0, 80.0, 24.0],
        )
        item.setPos(0, 0)
        view._selected_uids = {"a1"}
        view._cursor_mode = "select"
        edit_active_states = []
        access_state = []
        view.text_annotation_edit_mode_changed.connect(edit_active_states.append)
        view.text_annotation_edit_mode_changed.connect(
            lambda active: access_state.append(bool(active))
        )
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        item.setPlainText("After")
        event = self._left_press_event(300, 300)
        view.mousePressEvent(event)
        self.assertFalse(view.is_text_annotation_inline_edit_active())
        self.assertEqual(edit_active_states, [True, False])
        self.assertEqual(access_state, [True, False])
        self.assertEqual(annotation.properties["Text"], "After")
        self.assertEqual(
            item.textInteractionFlags(),
            QtCore.Qt.TextInteractionFlag.NoTextInteraction,
        )
        self.assertFalse(item.hasFocus())
        self.assertIsNone(view._selected_text_item)
        self.assertIsNone(view._selected_text_annotation_uid)
        self.assertTrue(view._condition_text_toolbar.isHidden())
        view.cleanup()

    def test_click_outside_inline_text_edit_clears_text_cursor_selection(self):
        view = self._make_plan_view()
        annotation, item = self._add_text_annotation(view, text="Before")
        item.setPos(0, 0)
        view._selected_uids = {"a1"}
        view._cursor_mode = "select"
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        item.setPlainText("After")
        self._select_document_text(item)
        event = self._left_press_event(300, 300)
        view.mousePressEvent(event)
        self.assertFalse(view.is_text_annotation_inline_edit_active())
        self.assertFalse(item.textCursor().hasSelection())
        self.assertEqual(item.textCursor().selectedText(), "")
        self.assertEqual(annotation.properties["Text"], "After")
        self.assertEqual(view._selected_uids, {"a1"})
        view.cleanup()

    def test_delete_key_clears_text_annotation_toolbar_before_delete_signal(self):
        view = self._make_plan_view()
        _annotation, _item = self._add_text_annotation(view, text="Before")
        view._editing_enabled = True
        view._selected_uids = {"a1"}
        view._cursor_mode = "select"
        self.assertTrue(view._select_text_annotation_label("a1"))
        delete_states = []
        view.elements_deleted.connect(
            lambda uids: delete_states.append(
                (
                    list(uids),
                    view.get_selected_uids(),
                    view._selected_text_annotation_uid,
                    view._condition_text_toolbar.isHidden(),
                )
            )
        )
        view.keyPressEvent(
            QKeyEvent(
                QtCore.QEvent.Type.KeyPress,
                QtCore.Qt.Key.Key_Delete,
                QtCore.Qt.KeyboardModifier.NoModifier,
            )
        )
        self.assertEqual(delete_states, [(["a1"], [], None, True)])
        self.assertIsNone(view._selected_text_item)
        view.cleanup()

    def test_click_inside_inline_text_edit_stays_in_editor(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        item.setPos(0, 0)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        view._selected_uids = {"a1"}
        view._cursor_mode = "select"
        edit_active_states = []
        view.text_annotation_edit_mode_changed.connect(edit_active_states.append)
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        text_center = view.mapFromScene(item.mapToScene(item.boundingRect().center()))
        event = QMouseEvent(
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.QPointF(text_center),
            QtCore.QPointF(text_center),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        view.mousePressEvent(event)
        self.assertTrue(view.is_text_annotation_inline_edit_active())
        self.assertEqual(edit_active_states, [True])
        self.assertEqual(
            item.textInteractionFlags(),
            QtCore.Qt.TextInteractionFlag.TextEditorInteraction,
        )
        view.cleanup()

    def test_select_mode_leave_clears_cursor_from_viewport_owner(self):
        host = QtWidgets.QWidget()
        host.setCursor(QtCore.Qt.CursorShape.CrossCursor)
        view = self._make_plan_view()
        view.setParent(host)
        view._selection_enabled = True
        view._cursor_mode = "select"
        view.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        view.viewport().setCursor(QtCore.Qt.CursorShape.IBeamCursor)
        view.leaveEvent(QtCore.QEvent(QtCore.QEvent.Type.Leave))
        self.assertEqual(
            view.cursor().shape(),
            QtCore.Qt.CursorShape.CrossCursor,
        )
        self.assertEqual(
            view.viewport().cursor().shape(),
            QtCore.Qt.CursorShape.CrossCursor,
        )
        view.cleanup()

    def test_leave_cancels_active_drag_only_when_left_button_is_released(self):
        for buttons, cancelled in (
            (QtCore.Qt.MouseButton.NoButton, True),
            (QtCore.Qt.MouseButton.LeftButton, False),
        ):
            with self.subTest(buttons=buttons):
                view = self._make_plan_view()
                view._drag_plan_item_uid = "t1"
                view._drag_handle_index = -1
                view._last_mouse_vp_pos = QtCore.QPoint(3, 4)
                with patch.object(
                    input_handler,
                    "QApplication",
                    SimpleNamespace(mouseButtons=lambda buttons=buttons: buttons),
                ):
                    view.leaveEvent(QtCore.QEvent(QtCore.QEvent.Type.Leave))
                self.assertEqual(view._drag_plan_item_uid, None if cancelled else "t1")
                self.assertIsNone(view._last_mouse_vp_pos)
                view._drag_plan_item_uid = None
                view.cleanup()

    def test_leave_keeps_viewport_cursor_outside_selection_mode(self):
        for mode, selection_enabled in (("pan", True), ("select", False)):
            with self.subTest(mode=mode, selection_enabled=selection_enabled):
                view = self._make_plan_view()
                view._selection_enabled = selection_enabled
                view._cursor_mode = mode
                view.viewport().setCursor(QtCore.Qt.CursorShape.IBeamCursor)
                view.leaveEvent(QtCore.QEvent(QtCore.QEvent.Type.Leave))
                self.assertEqual(
                    view.viewport().cursor().shape(),
                    QtCore.Qt.CursorShape.IBeamCursor,
                )
                self.assertIsNone(view._last_mouse_vp_pos)
                view.cleanup()

    def test_inline_text_annotation_edit_ibeam_cursor_is_limited_to_textbox(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 80.0, 40.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = ClippedTextGraphicsItem("Before", QtCore.QRectF(0.0, 0.0, 80.0, 40.0))
        item.setData(0, "a1")
        item.setPos(60.0, 80.0)
        item.setTextWidth(80.0)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        view._selected_uids = {"a1"}
        view._last_mouse_vp_pos = view.mapFromScene(QtCore.QPointF(70.0, 90.0))
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        self.assertEqual(
            view._resolve_cursor(view.mapFromScene(QtCore.QPointF(70.0, 90.0))),
            QtCore.Qt.CursorShape.IBeamCursor,
        )
        self.assertEqual(
            view._resolve_cursor(view.mapFromScene(QtCore.QPointF(20.0, 20.0))),
            QtCore.Qt.CursorShape.ArrowCursor,
        )
        view._finish_text_annotation_edit(commit=True)
        self.assertEqual(
            view._resolve_cursor(view.mapFromScene(QtCore.QPointF(70.0, 90.0))),
            QtCore.Qt.CursorShape.SizeAllCursor,
        )
        view.cleanup()

    def test_inline_text_annotation_edit_routes_keys_to_text_item(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        view._selected_uids = {"a1"}
        view._cursor_mode = "select"
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        view.keyPressEvent(
            QKeyEvent(
                QtCore.QEvent.Type.KeyPress,
                QtCore.Qt.Key.Key_A,
                QtCore.Qt.KeyboardModifier.ControlModifier,
            )
        )
        self.assertEqual(item.textCursor().selectedText(), "Before")
        item_pos = item.pos()
        cursor = item.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        item.setTextCursor(cursor)
        view.keyPressEvent(
            QKeyEvent(
                QtCore.QEvent.Type.KeyPress,
                QtCore.Qt.Key.Key_Right,
                QtCore.Qt.KeyboardModifier.NoModifier,
            )
        )
        self.assertEqual(item.pos(), item_pos)
        self.assertEqual(item.textCursor().position(), 1)
        cursor = item.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        item.setTextCursor(cursor)
        view.keyPressEvent(
            QKeyEvent(
                QtCore.QEvent.Type.KeyPress,
                QtCore.Qt.Key.Key_Delete,
                QtCore.Qt.KeyboardModifier.NoModifier,
            )
        )
        self.assertEqual(item.toPlainText(), "")
        self.assertEqual(view._selected_uids, {"a1"})
        view.cleanup()

    def _add_text_annotation(
        self,
        view,
        *,
        uid="a1",
        text="Text",
        page_uid="",
        position=None,
        font_size=12,
    ):
        if position is None:
            position = [0.0, 0.0, 80.0, 24.0]
        annotation = BidAnnotation(
            uid=uid,
            annotation_type="text",
            page_uid=page_uid,
            position=list(position),
            properties={
                "Text": text,
                "FontName": "Arial",
                "FontColor": 0,
                "FontSize": font_size,
                "FontBold": False,
                "FontItalic": False,
                "FontUnderline": False,
                "TextAlign": 0,
            },
        )
        item = QGraphicsTextItem(text)
        item.setData(0, uid)
        item.setFont(QFont("Arial", font_size))
        item.setTextWidth(position[2])
        view._scene.addItem(item)
        view._uid_to_items = {uid: [item]}
        view._current_annotations = {uid: annotation}
        view._selection_enabled = True
        return annotation, item

    def _select_document_text(self, item):
        cursor = item.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        item.setTextCursor(cursor)

    def _left_press_event(self, x, y):
        return QMouseEvent(
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.QPointF(x, y),
            QtCore.QPointF(x, y),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )

    def _make_plan_view(self, *, load_coordinator=None, annotation_renderer=None):
        view = TakeoffPlanView(
            color_service=FakeColorService(),
            rendering_service=FakeRenderingService(),
            load_coordinator=load_coordinator or FakeLoadCoordinator(),
            takeoff_renderer=FakeTakeoffRenderer(),
            annotation_renderer=annotation_renderer or FakeAnnotationRenderer(),
            linear_geometry=FakeLinearGeometry(),
        )
        # Release test-owned windows before another test enters a native popup
        # loop. cleanup() releases services, but does not destroy the Qt widget.
        owned = [view]
        view.destroyed.connect(lambda: owned.clear())

        def release_view():
            if owned:
                delete(owned[0])

        self.addCleanup(release_view)
        # Production window composition projects access immediately after
        # constructing the view. Tests exercising edit workflows must model
        # that contract explicitly.
        view.set_editing_enabled(True)
        return view

    def _install_page_canvas(self, view, page, scene_scale=2.0):
        view._current_page = page
        view._current_bid_page_uid = page.uid
        view._scene_scale = scene_scale
        item = QGraphicsRectItem(
            0.0,
            0.0,
            page.effective_width_pts * scene_scale,
            page.effective_height_pts * scene_scale,
        )
        item.setZValue(-1.0)
        view._white_canvas_item = item
        view._scene.addItem(item)
        view._scene.setSceneRect(item.rect())
        view.resize(300, 300)
        QApplication.processEvents()
        return item


class InputHandlerMixinDragTrackingTests(_CtrlDragFixture):
    """Drag tracking, restore, pan, wheel and rotation-cancel state machines."""

    def _scene_items_view(self):
        view = self._make_view({"t1"})
        view._scene = QGraphicsScene()
        view._takeoff_items = []
        return view

    def test_restore_returns_path_and_text_items_to_their_pre_drag_state(self):
        view = self._scene_items_view()
        original_path = QPainterPath()
        original_path.addRect(0.0, 0.0, 10.0, 5.0)
        path_item = QGraphicsPathItem(original_path)
        path_item.setPos(1.0, 2.0)
        text_item = QGraphicsTextItem("Original")
        original_font = QFont("Arial", 9)
        text_item.setFont(original_font)
        text_item.setTextWidth(40.0)
        text_item.setRotation(5.0)
        text_item.setTransformOriginPoint(QtCore.QPointF(1.0, 2.0))
        text_item.setDefaultTextColor(QColor("#112233"))
        for item in (path_item, text_item):
            view._scene.addItem(item)
        view._uid_to_items = {"t1": [path_item, text_item]}
        view._drag_plan_item_uid = "t1"
        view._drag_item_orig_positions = {
            id(path_item): QtCore.QPointF(1.0, 2.0),
            id(text_item): QtCore.QPointF(0.0, 0.0),
        }
        view._drag_item_orig_paths = {id(path_item): QPainterPath(original_path)}
        view._drag_item_orig_text_states = {
            id(text_item): (
                "Original",
                40.0,
                5.0,
                QtCore.QPointF(1.0, 2.0),
                original_font,
                QColor("#112233"),
            )
        }
        view._drag_uid_orig_items = {"t1": [path_item, text_item]}
        changed_path = QPainterPath()
        changed_path.addRect(0.0, 0.0, 99.0, 99.0)
        path_item.setPath(changed_path)
        path_item.setPos(50.0, 60.0)
        text_item.setPlainText("Preview")
        text_item.setTextWidth(77.0)
        text_item.setRotation(40.0)
        text_item.setTransformOriginPoint(QtCore.QPointF(9.0, 9.0))
        text_item.setFont(QFont("Courier", 20))
        text_item.setDefaultTextColor(QColor("#ff0000"))
        view._restore_drag_preview_positions()
        self.assertEqual(path_item.path(), original_path)
        self.assertEqual(path_item.pos(), QtCore.QPointF(1.0, 2.0))
        self.assertEqual(text_item.toPlainText(), "Original")
        self.assertEqual(text_item.textWidth(), 40.0)
        self.assertEqual(text_item.rotation(), 5.0)
        self.assertEqual(text_item.transformOriginPoint(), QtCore.QPointF(1.0, 2.0))
        self.assertEqual(text_item.font(), original_font)
        self.assertEqual(text_item.defaultTextColor(), QColor("#112233"))

    def test_restore_replaces_rebuilt_preview_items_with_original_items(self):
        view = self._scene_items_view()
        original = QGraphicsRectItem(0.0, 0.0, 4.0, 4.0)
        rebuilt = QGraphicsRectItem(0.0, 0.0, 9.0, 9.0)
        view._scene.addItem(rebuilt)
        view._takeoff_items = [rebuilt]
        view._uid_to_items = {"t1": [rebuilt]}
        view._drag_plan_item_uid = "t1"
        view._drag_uid_orig_items = {"t1": [original]}
        view._restore_drag_preview_positions()
        self.assertIsNone(rebuilt.scene())
        self.assertIs(original.scene(), view._scene)
        self.assertEqual(view._takeoff_items, [original])
        self.assertEqual(view._uid_to_items["t1"], [original])

    def test_restore_does_nothing_without_captured_drag_state(self):
        view = self._scene_items_view()
        item = QGraphicsRectItem(0.0, 0.0, 4.0, 4.0)
        item.setPos(30.0, 40.0)
        view._scene.addItem(item)
        view._uid_to_items = {"t1": [item]}
        view._drag_plan_item_uid = "t1"
        view._restore_drag_preview_positions()
        self.assertEqual(item.pos(), QtCore.QPointF(30.0, 40.0))

    def test_restore_covers_every_multi_drag_uid_and_selection_borders(self):
        view = self._make_view({"t1", "t2"})
        first, second = view._uid_to_items["t1"][0], view._uid_to_items["t2"][0]
        border = FakeItem(7.0, 8.0, uid="t1")
        view._selection_items = [border]
        view._drag_multi_orig_positions = {
            "t1": [0.0, 0.0, 10.0, 0.0],
            "t2": [20.0, 0.0, 30.0, 0.0],
        }
        view._drag_item_orig_positions = {
            id(first): QtCore.QPointF(1.0, 2.0),
            id(second): QtCore.QPointF(3.0, 4.0),
            id(border): QtCore.QPointF(7.0, 8.0),
        }
        first.setPos(100.0, 100.0)
        second.setPos(200.0, 200.0)
        border.setPos(300.0, 300.0)
        view._restore_drag_preview_positions()
        self.assertEqual(first.pos(), QtCore.QPointF(1.0, 2.0))
        self.assertEqual(second.pos(), QtCore.QPointF(3.0, 4.0))
        self.assertEqual(border.pos(), QtCore.QPointF(7.0, 8.0))

    def test_clear_drag_tracking_resets_every_gesture_field(self):
        view = self._make_view({"t1"})
        view._drag_plan_item_uid = "t1"
        view._drag_handle_index = 3
        view._drag_orig_position = [1.0, 2.0]
        view._drag_handle_corner_count = 4
        view._drag_item_orig_positions = {1: QtCore.QPointF()}
        view._drag_item_orig_paths = {1: QPainterPath()}
        view._drag_item_orig_text_states = {1: ()}
        view._drag_uid_orig_items = {"t1": []}
        view._drag_multi_orig_positions = {"t1": [1.0, 2.0]}
        view._drag_last_valid_new_pos = [3.0, 4.0]
        view._drag_model_orig_position = [5.0, 6.0]
        view._drag_position_before_edit_existed = True
        view._clear_drag_tracking()
        self.assertIsNone(view._drag_plan_item_uid)
        self.assertEqual(view._drag_handle_index, -2)
        self.assertEqual(view._drag_orig_position, [])
        self.assertEqual(view._drag_handle_corner_count, 0)
        self.assertEqual(view._drag_item_orig_positions, {})
        self.assertEqual(view._drag_item_orig_paths, {})
        self.assertEqual(view._drag_item_orig_text_states, {})
        self.assertEqual(view._drag_uid_orig_items, {})
        self.assertEqual(view._drag_multi_orig_positions, {})
        self.assertEqual(view._drag_last_valid_new_pos, [])
        self.assertIsNone(view._drag_model_orig_position)
        self.assertFalse(view._drag_position_before_edit_existed)

    def test_clear_with_restore_keeps_pre_existing_before_edit_snapshot(self):
        view = self._make_view({"a1"})
        ann = BidAnnotation(
            uid="a1", annotation_type="rect", position=[9.0, 9.0, 19.0, 19.0]
        )
        view._current_annotations = {"a1": ann}
        view._drag_plan_item_uid = "a1"
        view._drag_model_orig_position = [0.0, 0.0, 10.0, 10.0]
        view._drag_position_before_edit_existed = True
        view._position_before_edit = {"a1": [0.0, 0.0, 10.0, 10.0]}
        view._clear_drag_tracking(restore_preview=True)
        self.assertEqual(ann.position, [0.0, 0.0, 10.0, 10.0])
        self.assertEqual(view._position_before_edit, {"a1": [0.0, 0.0, 10.0, 10.0]})

    def test_clear_without_restore_leaves_model_and_preview_untouched(self):
        view = self._make_view({"a1"})
        ann = BidAnnotation(
            uid="a1", annotation_type="rect", position=[9.0, 9.0, 19.0, 19.0]
        )
        view._current_annotations = {"a1": ann}
        overlay = view._uid_to_items["t1"][0]
        overlay.setPos(40.0, 50.0)
        view._drag_plan_item_uid = "a1"
        view._drag_model_orig_position = [0.0, 0.0, 10.0, 10.0]
        view._drag_item_orig_positions = {id(overlay): QtCore.QPointF(1.0, 2.0)}
        view._clear_drag_tracking()
        self.assertEqual(ann.position, [9.0, 9.0, 19.0, 19.0])
        self.assertEqual(overlay.pos(), QtCore.QPointF(40.0, 50.0))

    def test_each_active_gesture_state_is_detected_and_cancelled(self):
        states = {
            "zoom rubber band": lambda v: setattr(
                v, "_rubber_band_origin", QtCore.QPointF(1.0, 1.0)
            ),
            "select band origin": lambda v: setattr(
                v, "_select_band_origin", QtCore.QPointF(1.0, 1.0)
            ),
            "select band active": lambda v: setattr(v, "_select_band_active", True),
            "select band dragged": lambda v: setattr(v, "_select_band_dragged", True),
            "ctrl zoom press": lambda v: setattr(v, "_zoom_press_ctrl", True),
            "move handle": lambda v: setattr(v, "_drag_handle_index", -1),
            "resize handle": lambda v: setattr(v, "_drag_handle_index", 0),
            "plan item": lambda v: setattr(v, "_drag_plan_item_uid", "t1"),
            "multi drag": lambda v: setattr(
                v, "_drag_multi_orig_positions", {"t1": [0.0, 0.0]}
            ),
        }
        clean = self._make_view({"t1"})
        clean_hidden = []
        clean._rubber_band = SimpleNamespace(hide=lambda: clean_hidden.append(True))
        self.assertFalse(clean._has_active_drag_interaction())
        self.assertFalse(clean._cancel_active_drag_interaction())
        self.assertEqual(clean_hidden, [])
        for name, activate in states.items():
            with self.subTest(name):
                view = self._make_view({"t1"})
                hidden = []
                view._rubber_band = SimpleNamespace(
                    hide=lambda hidden=hidden: hidden.append(True)
                )
                activate(view)
                self.assertTrue(view._has_active_drag_interaction())
                self.assertTrue(view._cancel_active_drag_interaction())
                self.assertEqual(hidden, [True])
                self.assertFalse(view._has_active_drag_interaction())
                self.assertIsNone(view._rubber_band_origin)
                self.assertIsNone(view._select_band_origin)
                self.assertFalse(view._select_band_active)
                self.assertFalse(view._select_band_dragged)
                self.assertFalse(view._zoom_press_ctrl)

    def test_cancel_active_drag_restores_preview_only_when_requested(self):
        for restore in (True, False):
            with self.subTest(restore=restore):
                view = self._make_view({"t1"})
                overlay = view._uid_to_items["t1"][0]
                original = overlay.pos()
                overlay.setPos(60.0, 70.0)
                view._drag_plan_item_uid = "t1"
                view._drag_item_orig_positions = {id(overlay): original}
                self.assertTrue(
                    view._cancel_active_drag_interaction(restore_preview=restore)
                )
                self.assertEqual(
                    overlay.pos(), original if restore else QtCore.QPointF(60.0, 70.0)
                )

    def test_mouse_move_with_left_button_held_keeps_active_drag_state(self):
        view = self._make_view({"t1"})
        view._drag_plan_item_uid = "t1"
        view._drag_handle_index = -1
        view._select_band_origin = QtCore.QPointF(10.0, 10.0)
        view._select_band_dragged = True
        view._clear_stale_drag_tracking_if_mouse_released(
            FakeMouseEvent(buttons=Qt.MouseButton.LeftButton)
        )
        self.assertEqual(view._drag_plan_item_uid, "t1")
        self.assertIsNotNone(view._select_band_origin)
        self.assertTrue(view._select_band_dragged)

    def _scroll_recorders(self, view, horizontal=10, vertical=20):
        values = {"h": [], "v": []}
        view.horizontalScrollBar = lambda: SimpleNamespace(
            value=lambda: horizontal, setValue=values["h"].append
        )
        view.verticalScrollBar = lambda: SimpleNamespace(
            value=lambda: vertical, setValue=values["v"].append
        )
        view.view_changes = []
        view._mark_user_view_changed_during_load = lambda: view.view_changes.append(
            "user"
        )
        return values

    def test_pan_update_rejects_inactive_missing_origin_and_zero_movement(self):
        cases = {
            "not panning": (False, QtCore.QPoint(1, 1), QtCore.QPoint(5, 5)),
            "no previous point": (True, None, QtCore.QPoint(5, 5)),
            "zero movement": (True, QtCore.QPoint(5, 5), QtCore.QPoint(5, 5)),
        }
        for name, (panning, last, current) in cases.items():
            with self.subTest(name):
                view = self._make_view()
                scrolls = self._scroll_recorders(view)
                view._panning = panning
                view._last_pan_point = last
                view._pan_view_changed = False
                self.assertFalse(view._apply_pan_update(current))
                self.assertEqual(scrolls, {"h": [], "v": []})
                self.assertEqual(view.view_changes, [])
                self.assertFalse(view._pan_view_changed)
                self.assertEqual(view._last_pan_point, last)

    def test_pan_update_scrolls_against_drag_direction_and_marks_view_changed(self):
        view = self._make_view()
        scrolls = self._scroll_recorders(view)
        view._panning = True
        view._last_pan_point = QtCore.QPoint(10, 10)
        view._pan_view_changed = False
        self.assertTrue(view._apply_pan_update(QtCore.QPoint(4, 13)))
        self.assertEqual(scrolls, {"h": [16], "v": [17]})
        self.assertTrue(view._pan_view_changed)
        self.assertEqual(view._last_pan_point, QtCore.QPoint(4, 13))

    def _pan_finish_view(self, *, right_pan, changed):
        view = self._make_view()
        view._panning = True
        view._pan_view_changed = changed
        view._right_pan_active = right_pan
        view._last_pan_point = QtCore.QPoint(3, 3)
        view._right_pan_press_pos = QtCore.QPoint(1, 1)
        view._right_pan_dragged = True
        view._persistent_cursor_mode = "pan"
        view._pre_pan_persistent_mode = "select"
        view.cursor_mode_change_requested = FakeSignal()
        view.cursor_updates = []
        view._update_cursor = lambda *args: view.cursor_updates.append(args)
        view.published = []
        view._publish_current_page_view_state = lambda: view.published.append(True)
        return view

    def test_left_pan_finish_resets_state_and_publishes_only_changed_views(self):
        for changed in (True, False):
            with self.subTest(changed=changed):
                view = self._pan_finish_view(right_pan=False, changed=changed)
                view._finish_pan_interaction()
                self.assertFalse(view._panning)
                self.assertFalse(view._pan_view_changed)
                self.assertIsNone(view._last_pan_point)
                self.assertIsNone(view._right_pan_press_pos)
                self.assertFalse(view._right_pan_dragged)
                self.assertEqual(view.published, [True] if changed else [])
                self.assertEqual(len(view.cursor_updates), 1)
                self.assertEqual(view.cursor_mode_change_requested.emitted, [])
                self.assertEqual(view._persistent_cursor_mode, "pan")

    def test_right_pan_finish_restores_the_pre_pan_persistent_mode(self):
        view = self._pan_finish_view(right_pan=True, changed=True)
        view._finish_pan_interaction()
        self.assertFalse(view._right_pan_active)
        self.assertEqual(view._persistent_cursor_mode, "select")
        self.assertIsNone(view._pre_pan_persistent_mode)
        self.assertEqual(view.cursor_mode_change_requested.emitted, [("select",)])
        self.assertEqual(view.published, [True])

    def _wheel_view(self):
        view = self._make_view()
        view.ZOOM_FACTOR = 1.25
        view.zoom_calls = []
        view._apply_zoom = view.zoom_calls.append
        view.publications = []
        view._publish_current_page_view_state = lambda: view.publications.append(True)
        view.mapToScene = lambda point: QtCore.QPointF(point)
        view.mapFromScene = lambda point: QtCore.QPoint(
            int(point.x()) + 7, int(point.y()) + 3
        )
        return view

    def test_wheel_zoom_direction_scroll_correction_and_notifications(self):
        for delta, factor in ((120.0, 1.25), (-120.0, 0.8)):
            with self.subTest(delta=delta):
                view = self._wheel_view()
                scrolls = self._scroll_recorders(view)
                view._apply_wheel_zoom(FakeWheelEvent(x=10, y=10), delta)
                self.assertEqual(view.zoom_calls, [factor])
                self.assertEqual(scrolls, {"h": [17], "v": [23]})
                self.assertEqual(view.view_changes, ["user"])
                self.assertEqual(view.publications, [True])

    @staticmethod
    def _wheel_event(*, angle=0, pixel=0, modifiers=Qt.KeyboardModifier.NoModifier):
        class Wheel:
            accepted = False

            def modifiers(self):
                return modifiers

            def pixelDelta(self):
                return QtCore.QPoint(0, pixel)

            def angleDelta(self):
                return QtCore.QPoint(0, angle)

            def position(self):
                return QtCore.QPointF(10.0, 10.0)

            def accept(self):
                self.accepted = True

        return Wheel()

    def _wheel_routing_view(self, cursor_mode="select", advanced=True):
        view = self._wheel_view()
        view._cursor_mode = cursor_mode
        view._advanced_mouse_controls_enabled = advanced
        view.band_syncs = []
        view._sync_rubber_band_to_viewport = lambda: view.band_syncs.append(True)
        view.scrolls = self._scroll_recorders(view)
        return view

    def test_wheel_scrolls_vertically_and_shift_wheel_scrolls_horizontally(self):
        view = self._wheel_routing_view()
        event = self._wheel_event(angle=120)
        view.wheelEvent(event)
        self.assertEqual(view.scrolls, {"h": [], "v": [-60]})
        self.assertEqual(view.view_changes, ["user"])
        self.assertEqual(view.zoom_calls, [])
        self.assertTrue(event.accepted)
        self.assertEqual(view.band_syncs, [True])
        view = self._wheel_routing_view()
        event = self._wheel_event(
            angle=-120, modifiers=Qt.KeyboardModifier.ShiftModifier
        )
        view.wheelEvent(event)
        self.assertEqual(view.scrolls, {"h": [90], "v": []})
        self.assertTrue(event.accepted)

    def test_wheel_prefers_pixel_delta_over_angle_delta(self):
        view = self._wheel_routing_view()
        view.wheelEvent(self._wheel_event(angle=120, pixel=15))
        self.assertEqual(view.scrolls, {"h": [], "v": [5]})

    def test_ctrl_wheel_zooms_only_with_advanced_mouse_controls(self):
        view = self._wheel_routing_view()
        view.wheelEvent(
            self._wheel_event(angle=120, modifiers=Qt.KeyboardModifier.ControlModifier)
        )
        self.assertEqual(view.zoom_calls, [1.25])
        view = self._wheel_routing_view(advanced=False)
        view.wheelEvent(
            self._wheel_event(angle=120, modifiers=Qt.KeyboardModifier.ControlModifier)
        )
        self.assertEqual(view.zoom_calls, [])
        self.assertEqual(view.scrolls["v"], [-60])
        view = self._wheel_routing_view(advanced=False)
        view.wheelEvent(
            self._wheel_event(angle=120, modifiers=Qt.KeyboardModifier.ShiftModifier)
        )
        self.assertEqual(view.scrolls, {"h": [], "v": [-60]})

    def test_zoom_mode_wheel_zooms_unless_ctrl_is_held(self):
        view = self._wheel_routing_view(cursor_mode="zoom")
        event = self._wheel_event(angle=120)
        view.wheelEvent(event)
        self.assertEqual(view.zoom_calls, [1.25])
        self.assertEqual(view.scrolls, {"h": [17], "v": [23]})
        self.assertTrue(event.accepted)
        self.assertEqual(view.band_syncs, [True])
        view = self._wheel_routing_view(cursor_mode="zoom")
        event = self._wheel_event(
            angle=120, modifiers=Qt.KeyboardModifier.ControlModifier
        )
        view.wheelEvent(event)
        self.assertEqual(view.zoom_calls, [])
        self.assertEqual(view.scrolls, {"h": [], "v": []})
        self.assertTrue(event.accepted)
        self.assertEqual(view.band_syncs, [True])

    def test_cancelling_inactive_rotation_drag_is_a_no_op(self):
        view = self._make_view()
        view.cursor_updates = []
        view._update_cursor = lambda *args: view.cursor_updates.append(args)
        preview = QGraphicsPathItem()
        preview.setRotation(12.0)
        view._rotation_drag_preview_items = [preview]
        self.assertFalse(view._cancel_rotation_drag_interaction())
        self.assertEqual(preview.rotation(), 12.0)
        self.assertEqual(view.cursor_updates, [])

    def test_cancelling_rotation_drag_restores_handles_and_resets_every_field(self):
        view = self._make_view()
        view.cursor_updates = []
        view._update_cursor = lambda *args: view.cursor_updates.append(args)
        handle = QGraphicsRectItem(-3.0, -3.0, 6.0, 6.0)
        line = QtWidgets.QGraphicsLineItem()
        outline = QtWidgets.QGraphicsLineItem()
        view._rotate_handle_item = handle
        view._rotate_line_item = line
        view._rotate_line_outline_item = outline
        view._rotate_center_scene = QtCore.QPointF(0.0, 0.0)
        view._rotate_handle_radius = 10.0
        view._rotate_handle_start_angle_deg = 90.0
        handle.setPos(-10.0, 0.0)
        preview = QGraphicsPathItem()
        preview.setRotation(30.0)
        other = FakeItem(1.0, 1.0)
        view._rotation_drag_active = True
        view._rotation_drag_uid = "t1"
        view._rotation_drag_last_angle = 4.0
        view._rotation_drag_accumulated_deg = 30.0
        view._rotation_drag_snapped_deg = 30.0
        view._rotation_drag_preview_items = [preview]
        view._rotation_drag_handle_origins = [(other, QtCore.QPointF(5.0, 6.0))]
        view._rotation_drag_orig_positions = {"t1": [0.0, 0.0]}
        view._rotation_drag_orig_rotations = {"t1": 0.25}
        self.assertTrue(view._cancel_rotation_drag_interaction())
        self.assertEqual(preview.rotation(), 0.0)
        self.assertEqual(other.pos(), QtCore.QPointF(5.0, 6.0))
        self.assertAlmostEqual(handle.pos().x(), 0.0, places=9)
        self.assertAlmostEqual(handle.pos().y(), 10.0, places=9)
        self.assertAlmostEqual(line.line().x2(), 0.0, places=9)
        self.assertAlmostEqual(line.line().y2(), 10.0, places=9)
        self.assertEqual(outline.line(), line.line())
        self.assertFalse(view._rotation_drag_active)
        self.assertIsNone(view._rotation_drag_uid)
        self.assertEqual(view._rotation_drag_last_angle, 0.0)
        self.assertEqual(view._rotation_drag_accumulated_deg, 0.0)
        self.assertEqual(view._rotation_drag_snapped_deg, 0.0)
        self.assertEqual(view._rotation_drag_preview_items, [])
        self.assertEqual(view._rotation_drag_handle_origins, [])
        self.assertEqual(view._rotation_drag_orig_positions, {})
        self.assertEqual(view._rotation_drag_orig_rotations, {})
        self.assertEqual(len(view.cursor_updates), 1)


class InputHandlerMixinPressGestureTests(_CtrlDragFixture):
    """InputHandlerMixin.mousePressEvent/mouseDoubleClickEvent drag setup."""

    def _recording_view(self, selected=("t1",)):
        view = self._make_view(set(selected))
        view.events = []
        view._flush_dirty_positions = lambda: view.events.append("flush")
        view._on_selection_changed = lambda: view.events.append("selection_changed")
        view.update_selection_visuals = lambda *a, **k: view.events.append("visuals")
        view._update_cursor = lambda *a, **k: view.events.append(("cursor", a))
        view.find_selected_movable_at = lambda _p: None
        view.find_takeoff_at = lambda _p, cycle_from_uid=None: "t1"
        view.find_takeoffs_at = lambda _p: ["t1"]
        view.finish_calls = []
        view.finish_intelligent_paste_placement = lambda: view.finish_calls.append(1)
        view.pdf_begin_calls = []
        view.pdf_begin_result = False

        def begin_pdf_text_selection(scene_pos):
            view.pdf_begin_calls.append(scene_pos)
            return view.pdf_begin_result

        view._begin_pdf_text_selection = begin_pdf_text_selection
        return view

    def test_press_move_and_release_are_swallowed_when_editing_mode_is_not_allowed(
        self,
    ):
        for handler in ("mousePressEvent", "mouseMoveEvent", "mouseReleaseEvent"):
            with self.subTest(handler=handler):
                view = self._make_view({"t1"})
                view._cursor_mode = CURSOR_MODE_PLACE
                view._editing_enabled = False
                view._last_mouse_vp_pos = None
                view._select_band_origin = QtCore.QPointF(1.0, 1.0)
                event = FakeMouseEvent(x=30, y=40, buttons=Qt.MouseButton.NoButton)
                getattr(view, handler)(event)
                self.assertTrue(event.accepted)
                self.assertIsNone(view._last_mouse_vp_pos)
                self.assertEqual(view._select_band_origin, QtCore.QPointF(1.0, 1.0))

    def test_read_only_press_on_selected_takeoff_does_not_begin_drag_or_lease(self):
        view = self._make_selected_path_takeoff_view()
        view._editing_enabled = False
        leases = []
        view.request_geometry_edit_lease = lambda uids: leases.append(set(uids)) or True
        view._flush_dirty_positions = lambda: self.fail(
            "read-only press must not flush"
        )
        press = FakeMouseEvent(x=5, y=5)
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(leases, [])
        self.assertIsNone(view._drag_plan_item_uid)
        self.assertEqual(view._drag_item_orig_positions, {})
        self.assertEqual(view._drag_handle_index, -2)
        release = FakeMouseEvent(x=5, y=5, buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(release)
        self.assertTrue(release.accepted)
        self.assertEqual(view._current_takeoffs["t1"].position, [0.0, 0.0, 10.0, 0.0])
        self.assertEqual(view._dirty_positions, {})

    def _baseline_view(self, condition_type=Condition.TYPE_LINEAR):
        view = self._make_selected_path_takeoff_view()
        view._current_conditions["c"].condition_type = condition_type
        path_item = view._uid_to_items["t1"][0]
        path_item.setPos(2.0, 3.0)
        text_item = QGraphicsTextItem("Label")
        text_item.setData(0, "t1")
        text_item.setTextWidth(33.0)
        text_item.setRotation(3.0)
        text_item.setTransformOriginPoint(QtCore.QPointF(1.0, 1.0))
        text_item.setDefaultTextColor(QColor("#336699"))
        view._scene.addItem(text_item)
        view._uid_to_items["t1"].append(text_item)
        far_handle = QGraphicsRectItem(-4.0, -4.0, 8.0, 8.0)
        far_handle.setPos(100.0, 100.0)
        edge_handle = QGraphicsRectItem(-4.0, -4.0, 8.0, 8.0)
        edge_handle.setPos(50.0, 60.0)
        view._handle_infos = [
            SimpleNamespace(item=far_handle, cursor=Qt.CursorShape.SizeFDiagCursor),
            SimpleNamespace(item=edge_handle, cursor=Qt.CursorShape.SizeVerCursor),
        ]
        border = QGraphicsPathItem()
        border.setData(0, "t1")
        border.setPos(7.0, 8.0)
        view._selection_items = [border]
        view.lease_requests = []
        view.request_geometry_edit_lease = lambda uids: (
            view.lease_requests.append(set(uids)) or True
        )
        return view, path_item, text_item, far_handle, edge_handle, border

    def test_body_press_on_selected_takeoff_captures_complete_drag_baseline(self):
        view, path_item, text_item, far_handle, edge_handle, border = (
            self._baseline_view()
        )
        press = FakeMouseEvent(x=5, y=5)
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(view.lease_requests, [{"t1"}])
        self.assertEqual(view._drag_plan_item_uid, "t1")
        self.assertEqual(view._drag_orig_position, [0.0, 0.0, 10.0, 0.0])
        self.assertEqual(view._drag_handle_index, -1)
        self.assertEqual(
            view._drag_item_orig_positions,
            {
                id(path_item): QtCore.QPointF(2.0, 3.0),
                id(text_item): text_item.pos(),
                id(far_handle): QtCore.QPointF(100.0, 100.0),
                id(edge_handle): QtCore.QPointF(50.0, 60.0),
                id(border): QtCore.QPointF(7.0, 8.0),
            },
        )
        self.assertEqual(view._drag_item_orig_paths, {id(path_item): path_item.path()})
        self.assertEqual(set(view._drag_item_orig_text_states), {id(text_item)})
        (text, width, rotation, origin, font, color) = view._drag_item_orig_text_states[
            id(text_item)
        ]
        self.assertEqual(
            (text, width, rotation, origin, color),
            ("Label", 33.0, 3.0, QtCore.QPointF(1.0, 1.0), QColor("#336699")),
        )
        self.assertEqual(font, text_item.font())
        self.assertEqual(view._drag_uid_orig_items, {"t1": [path_item, text_item]})
        self.assertEqual(view._drag_handle_corner_count, 0)
        self.assertEqual(view._drag_last_valid_new_pos, [])

    def test_handle_press_records_handle_index_and_area_polygon_state(self):
        for condition_type, corners, last_valid in (
            (Condition.TYPE_AREA, 4, [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]),
            (Condition.TYPE_LINEAR, 0, []),
        ):
            with self.subTest(condition_type=condition_type):
                view, *_items = self._baseline_view(condition_type)
                if condition_type == Condition.TYPE_AREA:
                    view._current_takeoffs["t1"].position = list(last_valid)
                press = FakeMouseEvent(x=50, y=60)
                view.mousePressEvent(press)
                self.assertTrue(press.accepted)
                self.assertEqual(view._drag_plan_item_uid, "t1")
                self.assertEqual(view._drag_handle_index, 1)
                self.assertEqual(view._drag_handle_corner_count, corners)
                self.assertEqual(view._drag_last_valid_new_pos, last_valid)

    def test_handle_press_requires_edit_access_and_a_single_selection(self):
        view, *_items = self._baseline_view()
        view._editing_enabled = False
        view.find_takeoff_at = lambda _p, cycle_from_uid=None: None
        view.mousePressEvent(FakeMouseEvent(x=50, y=60))
        self.assertIsNone(view._drag_plan_item_uid)
        self.assertEqual(view.lease_requests, [])
        view, *_items = self._baseline_view()
        view._selected_uids = {"t1", "t2"}
        view.find_takeoff_at = lambda _p, cycle_from_uid=None: None
        view.find_selected_movable_at = lambda _p: None
        view.mousePressEvent(FakeMouseEvent(x=50, y=60))
        self.assertIsNone(view._drag_plan_item_uid)
        self.assertEqual(view._drag_handle_index, -2)
        self.assertEqual(view._drag_multi_orig_positions, {})
        self.assertEqual(view.lease_requests, [])

    def _annotation_press_view(self, annotation_type, position, handle_hit):
        view = self._make_view({"a1"})
        view._current_takeoffs = {}
        annotation = BidAnnotation(
            uid="a1", annotation_type=annotation_type, position=list(position)
        )
        view._current_annotations = {"a1": annotation}
        view._uid_to_items = {"a1": [FakeItem(1.0, 2.0)]}
        handle = SimpleNamespace(item=FakeItem(), cursor=Qt.CursorShape.SizeAllCursor)
        view._handle_infos = [handle]
        view._is_handle_info_at_viewport_pos = lambda info, _pos: (
            handle_hit and info is handle
        )
        view.find_selected_movable_at = lambda _p: "a1"
        view.find_text_annotation_at = lambda _p: None
        return view, annotation

    def test_annotation_press_records_resize_state_by_annotation_type(self):
        square = [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
        cases = (
            ("polygon", square, False, 4, square),
            ("cloud", square[:6], False, 3, square[:6]),
            ("rect", [0.0, 0.0, 10.0, 4.0], True, 4, []),
            ("oval", [0.0, 0.0, 10.0, 4.0], True, 4, []),
            ("highlight", [0.0, 0.0, 10.0, 4.0], True, 4, []),
            ("namedview", [0.0, 0.0, 10.0, 4.0], True, 4, []),
            ("text", [10.0, 10.0, 40.0, 20.0], True, 4, []),
            ("text", [10.0, 10.0], True, 0, []),
            ("line", [0.0, 0.0, 10.0, 4.0], True, 0, []),
        )
        for annotation_type, position, handle_hit, corners, last_valid in cases:
            with self.subTest(annotation_type=annotation_type, length=len(position)):
                view, _annotation = self._annotation_press_view(
                    annotation_type, position, handle_hit
                )
                press = FakeMouseEvent(x=5, y=5)
                view.mousePressEvent(press)
                self.assertTrue(press.accepted)
                self.assertEqual(view._drag_plan_item_uid, "a1")
                self.assertEqual(view._drag_orig_position, position)
                self.assertEqual(view._drag_handle_index, 0 if handle_hit else -1)
                self.assertEqual(view._drag_handle_corner_count, corners)
                self.assertEqual(view._drag_last_valid_new_pos, last_valid)

    def test_rotated_annotation_is_unrotated_only_for_a_resize_handle_press(self):
        rotated = [0.0, 0.0, 10.0, 0.0, 10.0, 4.0, 0.0, 4.0, math.radians(30.0)]
        for handle_hit in (True, False):
            with self.subTest(handle_hit=handle_hit):
                view, annotation = self._annotation_press_view(
                    "rect", rotated, handle_hit
                )
                view.mousePressEvent(FakeMouseEvent(x=5, y=5))
                if handle_hit:
                    self.assertEqual(view._drag_model_orig_position, rotated)
                    self.assertEqual(view._position_before_edit["a1"], rotated)
                    self.assertNotEqual(annotation.position, rotated)
                    self.assertEqual(view._drag_orig_position, annotation.position)
                else:
                    self.assertIsNone(view._drag_model_orig_position)
                    self.assertEqual(annotation.position, rotated)
                    self.assertEqual(view._position_before_edit, {})

    def test_press_on_unselected_takeoff_selects_it_then_starts_drag(self):
        view = self._recording_view(selected=())
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(view._selected_uids, {"t1"})
        self.assertTrue(view._press_changed_selection)
        self.assertEqual(
            view.events[:4],
            [
                "flush",
                "selection_changed",
                "visuals",
                ("cursor", (QtCore.QPoint(10, 10),)),
            ],
        )
        self.assertEqual(view._drag_plan_item_uid, "t1")
        self.assertEqual(view.events[-1], ("cursor", (QtCore.QPoint(10, 10),)))
        self.assertEqual(view.pdf_begin_calls, [])
        self.assertEqual(view.finish_calls, [])

    def test_press_on_item_overlapping_the_selection_keeps_selection_and_drags(self):
        view = self._recording_view(selected=("t1",))
        view.find_takeoff_at = lambda _p, cycle_from_uid=None: "t2"
        view.find_takeoffs_at = lambda _p: ["t2", "t1"]
        view.mousePressEvent(FakeMouseEvent())
        self.assertEqual(view._selected_uids, {"t1"})
        self.assertFalse(view._press_changed_selection)
        self.assertNotIn("selection_changed", view.events)
        self.assertNotIn("flush", view.events)
        self.assertEqual(view._drag_plan_item_uid, "t1")
        view = self._recording_view(selected=("t1",))
        view.find_takeoff_at = lambda _p, cycle_from_uid=None: "t2"
        view.find_takeoffs_at = lambda _p: ["t2"]
        view.mousePressEvent(FakeMouseEvent())
        self.assertEqual(view._selected_uids, {"t2"})
        self.assertTrue(view._press_changed_selection)
        self.assertEqual(view._drag_plan_item_uid, "t2")

    def test_shift_press_drags_a_selected_item_but_defers_unselected_toggle(self):
        shift = Qt.KeyboardModifier.ShiftModifier
        view = self._recording_view(selected=("t1",))
        view.mousePressEvent(FakeMouseEvent(shift))
        self.assertEqual(view._drag_plan_item_uid, "t1")
        view = self._recording_view(selected=("t1",))
        view.find_takeoff_at = lambda _p, cycle_from_uid=None: "t2"
        view.find_takeoffs_at = lambda _p: ["t2"]
        press = FakeMouseEvent(shift)
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertIsNone(view._drag_plan_item_uid)
        self.assertEqual(view._selected_uids, {"t1"})
        self.assertEqual(view.events, [])
        self.assertEqual(view.pdf_begin_calls, [])
        self.assertEqual(view.finish_calls, [1])
        self.assertEqual(view._select_band_origin, QtCore.QPointF(10.0, 10.0))
        view.mouseReleaseEvent(FakeMouseEvent(shift, buttons=Qt.MouseButton.NoButton))
        self.assertEqual(view._selected_uids, {"t1", "t2"})
        view.find_takeoff_at = lambda _p, cycle_from_uid=None: "t1"
        view._select_band_origin = QtCore.QPointF(10.0, 10.0)
        view.mouseReleaseEvent(FakeMouseEvent(shift, buttons=Qt.MouseButton.NoButton))
        self.assertEqual(view._selected_uids, {"t2"})

    def test_denied_geometry_lease_clears_tracking_and_band_origin(self):
        view = self._recording_view(selected=("t1",))
        leases = []
        view.request_geometry_edit_lease = (
            lambda uids: leases.append(set(uids)) or False
        )
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(leases, [{"t1"}])
        self.assertIsNone(view._drag_plan_item_uid)
        self.assertEqual(view._drag_item_orig_positions, {})
        self.assertIsNone(view._select_band_origin)
        self.assertEqual(view.finish_calls, [])

    def test_press_that_starts_no_drag_begins_pdf_text_selection(self):
        view = self._recording_view(selected=())
        view.find_takeoff_at = lambda _p, cycle_from_uid=None: None
        view.find_takeoffs_at = lambda _p: []
        view.pdf_begin_result = True
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(view.pdf_begin_calls, [QtCore.QPointF(10.0, 10.0)])
        self.assertEqual(view.finish_calls, [1])
        self.assertIsNone(view._select_band_origin)
        self.assertFalse(view._select_band_active)
        self.assertFalse(view._select_band_dragged)
        view = self._recording_view(selected=())
        view.find_takeoff_at = lambda _p, cycle_from_uid=None: None
        view.find_takeoffs_at = lambda _p: []
        view.mousePressEvent(FakeMouseEvent())
        self.assertEqual(len(view.pdf_begin_calls), 1)
        self.assertEqual(view._select_band_origin, QtCore.QPointF(10.0, 10.0))
        for name, event, prepare in (
            ("multi", FakeMouseEvent(Qt.KeyboardModifier.ShiftModifier), None),
            ("hotlink", FakeMouseEvent(), "hotlink"),
        ):
            with self.subTest(name):
                view = (
                    self._make_hotlink_view(selected=False)
                    if prepare == "hotlink"
                    else self._recording_view(selected=())
                )
                view.pdf_begin_calls = []
                view._begin_pdf_text_selection = lambda pos: (
                    view.pdf_begin_calls.append(pos) or True
                )
                if prepare is None:
                    view.find_takeoff_at = lambda _p, cycle_from_uid=None: None
                    view.find_takeoffs_at = lambda _p: []
                view.mousePressEvent(event)
                self.assertEqual(view.pdf_begin_calls, [])

    def test_dimension_label_press_selects_label_only_when_selection_succeeds(self):
        for succeeds in (True, False):
            with self.subTest(succeeds=succeeds):
                view = self._recording_view(selected=())
                label = QGraphicsTextItem("dim")
                selected, cleared = [], []
                view._dimension_text_label_at = lambda _p, label=label: label
                view._select_dimension_text_label = lambda item, ok=succeeds: (
                    selected.append(item) or ok
                )
                view._clear_pdf_text_selection = lambda: cleared.append(True)
                view.find_takeoff_at = lambda _p, cycle_from_uid=None: None
                view.find_takeoffs_at = lambda _p: []
                press = FakeMouseEvent()
                view.mousePressEvent(press)
                self.assertTrue(press.accepted)
                self.assertEqual(selected, [label])
                if succeeds:
                    self.assertEqual(cleared, [True])
                    self.assertIsNone(view._select_band_origin)
                else:
                    self.assertEqual(view._select_band_origin, QtCore.QPointF(10, 10))

    def test_condition_label_press_selects_label_and_clears_pdf_text(self):
        view = self._recording_view(selected=())
        label = QGraphicsTextItem("name")
        selected, cleared = [], []
        view._condition_text_label_at = lambda _p: label
        view._select_condition_text_label = selected.append
        view._clear_pdf_text_selection = lambda: cleared.append(True)
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(selected, [label])
        self.assertEqual(cleared, [True])
        self.assertIsNone(view._select_band_origin)

    def test_labels_are_not_hit_tested_while_placing_annotations(self):
        view = self._recording_view(selected=())
        view._cursor_mode = CURSOR_MODE_ANNOTATION_PLACE
        view._annotation_place_type = "text"
        view._dimension_text_label_at = lambda _p: self.fail("label hit-tested")
        view._condition_text_label_at = lambda _p: self.fail("label hit-tested")
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(len(view.annotation_place_presses), 1)

    def test_text_annotation_press_toolbar_rules(self):
        shift = Qt.KeyboardModifier.ShiftModifier

        def build(selected, hits):
            view = self._make_overlapping_text_cycle_view("t1")
            view._selected_uids = set(selected)
            view.find_takeoffs_at = lambda _p: list(hits)
            view.find_takeoff_at = lambda _p, cycle_from_uid=None: hits[0]
            view.clear_text_calls = []
            view._clear_text_selection = lambda: view.clear_text_calls.append(1)
            view.find_selected_movable_at = lambda _p: None
            return view

        none = Qt.KeyboardModifier.NoModifier
        cases = {
            "single hit that is selected": (["a1"], ["a1"], none, ["a1"]),
            "overlap containing no selected item": (
                ["t9"],
                ["a1", "t1"],
                none,
                ["a1"],
            ),
            "overlap containing a selected item defers": (
                ["t1"],
                ["a1", "t1"],
                none,
                [],
            ),
            "shift press never defers": (["t1"], ["a1", "t1"], shift, ["a1"]),
        }
        for name, (selected, hits, modifier, expected) in cases.items():
            with self.subTest(name):
                view = build(selected, hits)
                view.mousePressEvent(FakeMouseEvent(modifier))
                self.assertEqual(view.selected_text_annotation_uids, expected)
                self.assertEqual(view.clear_text_calls, [1] if expected else [])

    def test_ctrl_zoom_press_uses_cached_ctrl_state_and_requires_advanced_select(self):
        view = self._make_view()
        view._ctrl_held = True
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertTrue(view._zoom_press_ctrl)
        self.assertIsNone(view._drag_plan_item_uid)
        view = self._recording_view(selected=("t1",))
        view._advanced_mouse_controls_enabled = False
        view.mousePressEvent(FakeMouseEvent(Qt.KeyboardModifier.ControlModifier))
        self.assertFalse(view._zoom_press_ctrl)
        self.assertEqual(view._drag_plan_item_uid, "t1")
        view = self._recording_view(selected=("t1",))
        view._cursor_mode = "rotate"
        view._rotate_handle_item = None
        view.removed_handles = []
        view._remove_rotate_handle = lambda: view.removed_handles.append(1)
        view.cursor_mode_change_requested = FakeSignal()
        view._apply_cursor_mode = lambda mode: self.fail("mode must be kept")
        view.mousePressEvent(FakeMouseEvent(Qt.KeyboardModifier.ControlModifier))
        self.assertFalse(view._zoom_press_ctrl)
        self.assertEqual(view.removed_handles, [1])
        self.assertEqual(view.cursor_mode_change_requested.emitted, [])

    def test_double_click_selects_text_and_named_view_targets_before_editing(self):
        view, _item = self._make_selected_text_annotation_view()
        view._selected_uids = {"other"}
        view.events = []
        view._flush_dirty_positions = lambda: view.events.append("flush")
        view._on_selection_changed = lambda: view.events.append("selection_changed")
        view.update_selection_visuals = lambda *a, **k: view.events.append("visuals")
        press = FakeMouseEvent(x=20, y=20)
        view.mouseDoubleClickEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(view._selected_uids, {"a1"})
        self.assertEqual(view.events, ["flush", "selection_changed", "visuals"])
        self.assertEqual(view.selected_text_annotation_uids, ["a1"])
        self.assertEqual(view.editing_text_annotation_uids, ["a1"])
        view = self._make_view({"other"})
        label = QGraphicsTextItem("Named View")
        label.setData(0, "nv1")
        view._named_view_label_at = lambda _pos: label
        view.events = []
        view._flush_dirty_positions = lambda: view.events.append("flush")
        view._on_selection_changed = lambda: view.events.append("selection_changed")
        view.update_selection_visuals = lambda *a, **k: view.events.append("visuals")
        view.mouseDoubleClickEvent(FakeMouseEvent(x=20, y=20))
        self.assertEqual(view._selected_uids, {"nv1"})
        self.assertEqual(view.events, ["flush", "selection_changed", "visuals"])
        self.assertEqual(view.editing_named_view_uids, ["nv1"])

    def test_double_click_without_selection_access_or_in_zoom_does_not_edit(self):
        for name, prepare in (
            ("selection disabled", lambda v: setattr(v, "_selection_enabled", False)),
            ("zoom mode", lambda v: setattr(v, "_cursor_mode", "zoom")),
        ):
            with self.subTest(name):
                view, _item = self._make_selected_text_annotation_view()
                prepare(view)
                view.mousePressEvent = lambda event, view=view: (
                    view.fallback_presses.append(event) or event.accept()
                )
                view.fallback_presses = []
                press = FakeMouseEvent(x=20, y=20)
                view.mouseDoubleClickEvent(press)
                self.assertEqual(view.editing_text_annotation_uids, [])
                self.assertEqual(view.editing_named_view_uids, [])
                self.assertEqual(view.fallback_presses, [press])

    def test_double_click_while_placing_is_swallowed(self):
        view = self._make_view({"t1"})
        view._cursor_mode = CURSOR_MODE_PLACE
        view._last_mouse_vp_pos = None
        view.mousePressEvent = lambda event: self.fail("must not forward to press")
        press = FakeMouseEvent(x=20, y=20)
        view.mouseDoubleClickEvent(press)
        self.assertTrue(press.accepted)
        self.assertIsNone(view._last_mouse_vp_pos)

    def test_press_discards_stale_press_state_before_starting_new_gesture(self):
        view = self._recording_view(selected=("t1",))
        overlay = view._uid_to_items["t1"][0]
        original = overlay.pos()
        overlay.setPos(50.0, 60.0)
        view._press_changed_selection = True
        view._drag_plan_item_uid = "t1"
        view._drag_item_orig_positions = {id(overlay): original}
        view.mousePressEvent(FakeMouseEvent())
        self.assertFalse(view._press_changed_selection)
        self.assertEqual(overlay.pos(), original)
        self.assertEqual(view._drag_plan_item_uid, "t1")
        self.assertEqual(view._drag_item_orig_positions[id(overlay)], original)

    def test_ctrl_zoom_press_discards_stale_drag_tracking(self):
        view = self._recording_view(selected=("t1",))
        overlay = view._uid_to_items["t1"][0]
        original = overlay.pos()
        overlay.setPos(50.0, 60.0)
        view._drag_plan_item_uid = "t1"
        view._drag_item_orig_positions = {id(overlay): original}
        view.mousePressEvent(FakeMouseEvent(Qt.KeyboardModifier.ControlModifier))
        self.assertTrue(view._zoom_press_ctrl)
        self.assertIsNone(view._drag_plan_item_uid)
        self.assertEqual(overlay.pos(), original)

    def test_intelligent_paste_drag_hook_receives_captured_original_positions(self):
        view = self._recording_view(selected=("t1",))
        hook_calls = []
        view.begin_intelligent_paste_drag_if_pending = lambda positions: (
            hook_calls.append(positions) or False
        )
        view.mousePressEvent(FakeMouseEvent())
        self.assertEqual(hook_calls, [{"t1": [0.0, 0.0, 10.0, 0.0]}])
        view = self._recording_view(selected=("t1", "t2"))
        hook_calls = []
        view.begin_intelligent_paste_drag_if_pending = lambda positions: (
            hook_calls.append(positions) or False
        )
        view.mousePressEvent(FakeMouseEvent())
        self.assertEqual(
            hook_calls,
            [{"t1": [0.0, 0.0, 10.0, 0.0], "t2": [20.0, 0.0, 30.0, 0.0]}],
        )
        view = self._recording_view(selected=())
        view.find_takeoff_at = lambda _p, cycle_from_uid=None: None
        view.find_takeoffs_at = lambda _p: []
        hook_calls = []
        view.begin_intelligent_paste_drag_if_pending = lambda positions: (
            hook_calls.append(positions) or False
        )
        view.mousePressEvent(FakeMouseEvent())
        self.assertEqual(hook_calls, [])
        self.assertEqual(view.finish_calls, [1])

    def test_press_refreshes_cursor_once_per_selection_change_and_drag_start(self):
        view = self._recording_view(selected=("t1",))
        view.mousePressEvent(FakeMouseEvent())
        self.assertEqual(
            [event for event in view.events if isinstance(event, tuple)],
            [("cursor", (QtCore.QPoint(10, 10),))],
        )
        view = self._recording_view(selected=())
        view.mousePressEvent(FakeMouseEvent())
        self.assertEqual(
            [event for event in view.events if isinstance(event, tuple)],
            [("cursor", (QtCore.QPoint(10, 10),))] * 2,
        )

    def test_hotlink_press_opens_link_when_selection_is_disabled(self):
        view = self._make_hotlink_view(selected=False)
        view._selection_enabled = False
        press = FakeMouseEvent()
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(len(view.hotlink_clicked.emitted), 1)
        self.assertEqual(view._selected_uids, set())
        self.assertIsNone(view._drag_plan_item_uid)

    def test_double_click_with_a_non_left_button_is_handled_as_a_plain_press(self):
        view, _item = self._make_selected_text_annotation_view()
        view.fallback_presses = []
        view.mousePressEvent = lambda event: (
            view.fallback_presses.append(event) or event.accept()
        )
        press = _RightButtonMouseEvent(x=20, y=20)
        view.mouseDoubleClickEvent(press)
        self.assertEqual(view.fallback_presses, [press])
        self.assertEqual(view.editing_text_annotation_uids, [])
        self.assertEqual(view.editing_named_view_uids, [])


class _RightButtonMouseEvent(FakeMouseEvent):
    def button(self):
        return Qt.MouseButton.RightButton


class InputHandlerMixinRotationDragTests(_CtrlDragFixture):
    """InputHandlerMixin interactive rotation drag, release and handle restore."""

    def _rotating_view(self, selected=("t1",), cursor_mode="rotate"):
        view = self._make_view(set(selected))
        view._cursor_mode = cursor_mode
        view._rotation_drag_active = True
        view._rotation_drag_uid = "t1"
        view._rotation_drag_last_angle = 0.0
        view._rotation_drag_accumulated_deg = 0.0
        view._rotation_drag_snapped_deg = 0.0
        view._rotation_drag_orig_positions = {}
        view._rotation_drag_orig_rotations = {}
        view._rotate_center_scene = QtCore.QPointF(0.0, 0.0)
        view.mapToScene = lambda point: QtCore.QPointF(point)
        view.preview_updates = []
        view._update_rotation_handle_preview = view.preview_updates.append
        view.preview_item = QGraphicsPathItem()
        view._rotation_drag_preview_items = [view.preview_item]
        view.handle_item = FakeItem(10.0, 0.0)
        view._rotation_drag_handle_origins = [
            (view.handle_item, QtCore.QPointF(10.0, 0.0))
        ]
        return view

    def _move_to_angle(self, view, degrees, modifiers=Qt.KeyboardModifier.NoModifier):
        radians = math.radians(degrees)
        event = FakeMouseEvent(
            modifiers,
            x=round(1000 * math.cos(radians)),
            y=round(1000 * math.sin(radians)),
        )
        view.mouseMoveEvent(event)
        self.assertTrue(event.accepted)

    def test_rotation_drag_snaps_to_fifteen_forty_five_or_free_degrees(self):
        cases = (
            (Qt.KeyboardModifier.NoModifier, 30.0),
            (Qt.KeyboardModifier.ControlModifier, 45.0),
            (Qt.KeyboardModifier.ShiftModifier, math.degrees(math.atan2(500, 1000))),
        )
        for modifiers, expected in cases:
            with self.subTest(modifiers=modifiers):
                view = self._rotating_view()
                view.mouseMoveEvent(FakeMouseEvent(modifiers, x=1000, y=500))
                self.assertAlmostEqual(view._rotation_drag_snapped_deg, expected)
                self.assertAlmostEqual(view.preview_item.rotation(), expected)
                self.assertEqual(len(view.preview_updates), 1)
                self.assertAlmostEqual(view.preview_updates[0], expected)

    def test_rotation_drag_rotates_handle_around_center_by_snapped_angle(self):
        view = self._rotating_view()
        self._move_to_angle(view, 90.0)
        self.assertAlmostEqual(view.handle_item.pos().x(), 0.0, places=9)
        self.assertAlmostEqual(view.handle_item.pos().y(), 10.0, places=9)
        view = self._rotating_view()
        view._rotation_drag_handle_origins = [
            (view.handle_item, QtCore.QPointF(0.0, 10.0))
        ]
        self._move_to_angle(view, 90.0)
        self.assertAlmostEqual(view.handle_item.pos().x(), -10.0, places=9)
        self.assertAlmostEqual(view.handle_item.pos().y(), 0.0, places=9)
        view = self._rotating_view()
        view._rotate_center_scene = QtCore.QPointF(5.0, 5.0)
        view._rotation_drag_handle_origins = [
            (view.handle_item, QtCore.QPointF(15.0, 5.0))
        ]
        view._rotation_drag_last_angle = 0.0
        view.mapToScene = lambda point: QtCore.QPointF(5.0, 5.0 + point.y())
        view.mouseMoveEvent(FakeMouseEvent(x=0, y=100))
        self.assertAlmostEqual(view.handle_item.pos().x(), 5.0, places=9)
        self.assertAlmostEqual(view.handle_item.pos().y(), 15.0, places=9)

    def test_rotation_drag_accumulates_across_the_half_turn_wrap(self):
        view = self._rotating_view()
        view._rotation_drag_last_angle = 170.0
        self._move_to_angle(view, -170.0)
        self.assertAlmostEqual(view._rotation_drag_accumulated_deg, 20.0, delta=0.1)
        self.assertEqual(view._rotation_drag_snapped_deg, 15.0)
        self.assertAlmostEqual(view._rotation_drag_last_angle, -170.0, delta=0.1)
        self._move_to_angle(view, -160.0)
        self.assertAlmostEqual(view._rotation_drag_accumulated_deg, 30.0, delta=0.1)
        self.assertEqual(view._rotation_drag_snapped_deg, 30.0)

    def test_rotation_drag_only_updates_preview_when_snapped_angle_changes(self):
        view = self._rotating_view()
        self._move_to_angle(view, 16.0)
        self._move_to_angle(view, 17.0)
        self._move_to_angle(view, 14.0)
        self.assertEqual(view.preview_updates, [15.0])
        self.assertEqual(view.preview_item.rotation(), 15.0)

    def test_slope_rotation_drag_previews_the_handle_without_rotating_items(self):
        view = self._rotating_view(cursor_mode="slope_rotate")
        self._move_to_angle(view, 31.0)
        self.assertEqual(view._rotation_drag_snapped_deg, 30.0)
        self.assertEqual(view.preview_updates, [30.0])
        self.assertEqual(view.preview_item.rotation(), 0.0)
        self.assertEqual(view.handle_item.pos(), QtCore.QPointF(10.0, 0.0))

    def test_group_rotation_drag_rejects_invalid_candidate_geometry(self):
        for valid in (False, True):
            with self.subTest(valid=valid):
                view = self._rotating_view(selected=("t1", "t2"))
                view._rotate_ost_center = (0.0, 0.0)
                view._rotation_drag_orig_positions = {
                    "t1": [0.0, 0.0, 10.0, 0.0],
                    "t2": [20.0, 0.0, 30.0, 0.0],
                }
                view._rotation_drag_orig_rotations = {"t1": 0.0, "t2": 0.0}
                checked = []
                view._takeoff_children_valid_for_geometry_changes = (
                    lambda positions, rotations=None, valid=valid: (
                        checked.append((positions, rotations)) or valid
                    )
                )
                self._move_to_angle(view, 90.0)
                self.assertEqual(len(checked), 1)
                positions, _rotations = checked[0]
                self.assertAlmostEqual(positions["t2"][0], 0.0, places=9)
                self.assertAlmostEqual(positions["t2"][1], 20.0, places=9)
                self.assertEqual(
                    view._rotation_drag_snapped_deg, 90.0 if valid else 0.0
                )
                self.assertEqual(view.preview_item.rotation(), 90.0 if valid else 0.0)
                self.assertEqual(len(view.preview_updates), 1 if valid else 0)

    def test_single_hole_rotation_drag_rejects_invalid_hole_position(self):
        for valid in (False, True):
            with self.subTest(valid=valid):
                view = self._rotating_view()
                view._current_conditions = {
                    "area": Condition(uid="area", condition_type=Condition.TYPE_AREA)
                }
                hole = Takeoff(
                    uid="t1",
                    condition_uid="area",
                    parent_uid="parent",
                    position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0],
                )
                view._current_takeoffs = {"t1": hole}
                view._rotation_drag_orig_positions = {"t1": list(hole.position)}
                validated = []
                view._validate_hole_position = lambda takeoff, position, valid=valid: (
                    validated.append((takeoff.uid, position)) or valid
                )
                view.hole_paths = []
                view._update_parent_hole_path = lambda parent, uid, path: (
                    view.hole_paths.append((parent, uid, path.boundingRect()))
                )
                self._move_to_angle(view, 90.0)
                self.assertEqual(len(validated), 1)
                self.assertEqual(validated[0][0], "t1")
                self.assertEqual(
                    view._rotation_drag_snapped_deg, 90.0 if valid else 0.0
                )
                if valid:
                    self.assertEqual(len(view.hole_paths), 1)
                    self.assertEqual(view.hole_paths[0][:2], ("parent", "t1"))
                else:
                    self.assertEqual(view.hole_paths, [])

    def test_attachment_rotation_drag_is_rejected_when_footprint_invalid(self):
        for valid in (False, True):
            with self.subTest(valid=valid):
                view = self._rotating_view()
                view._current_conditions = {
                    "att": Condition(
                        uid="att", condition_type=Condition.TYPE_ATTACHMENT
                    )
                }
                view._current_takeoffs = {
                    "t1": Takeoff(uid="t1", condition_uid="att", position=[5.0, 5.0])
                }
                view._rotation_drag_orig_positions = {"t1": [5.0, 5.0]}
                view._rotation_drag_orig_rotations = {"t1": 0.5}
                checked = []
                view._attachment_position_valid = (
                    lambda takeoff, position, rotation=None, valid=valid: (
                        checked.append((takeoff.uid, list(position), rotation)) or valid
                    )
                )
                self._move_to_angle(view, 90.0)
                self.assertEqual(len(checked), 1)
                uid, position, rotation = checked[0]
                self.assertEqual((uid, position), ("t1", [5.0, 5.0]))
                self.assertAlmostEqual(rotation, 0.5 + math.pi / 2.0)
                self.assertEqual(
                    view._rotation_drag_snapped_deg, 90.0 if valid else 0.0
                )

    def _release_recorder(self, view):
        calls = []
        view._apply_slope_rotation = lambda uid, deg: calls.append(("slope", uid, deg))
        view._apply_single_rotation = lambda uid, deg: calls.append(
            ("single", uid, deg)
        )
        view._apply_multi_rotation = lambda deg: calls.append(("multi", deg))
        view._restore_rotation_handles_if_needed = lambda: calls.append("restore")
        view._update_cursor = lambda *a: calls.append("cursor")
        return calls

    def test_rotation_release_dispatches_by_selection_and_mode(self):
        cases = {
            "single": (("t1",), "rotate", [("single", "t1", 45.0)]),
            "multi": (("t1", "t2"), "rotate", [("multi", 45.0)]),
            "slope": (("t1",), "slope_rotate", [("slope", "t1", 45.0)]),
        }
        for name, (selected, mode, expected) in cases.items():
            with self.subTest(name):
                view = self._rotating_view(selected=selected, cursor_mode=mode)
                view._rotation_drag_snapped_deg = 45.0
                view._rotation_drag_accumulated_deg = 47.0
                view._rotation_drag_last_angle = 3.0
                calls = self._release_recorder(view)
                release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
                view.mouseReleaseEvent(release)
                self.assertTrue(release.accepted)
                self.assertEqual(calls, expected + ["restore", "cursor"])
                self.assertFalse(view._rotation_drag_active)
                self.assertIsNone(view._rotation_drag_uid)
                self.assertEqual(view._rotation_drag_last_angle, 0.0)
                self.assertEqual(view._rotation_drag_accumulated_deg, 0.0)
                self.assertEqual(view._rotation_drag_snapped_deg, 0.0)
                self.assertEqual(view._rotation_drag_preview_items, [])
                self.assertEqual(view._rotation_drag_handle_origins, [])

    def test_rotation_release_without_angle_change_commits_nothing(self):
        view = self._rotating_view()
        view._rotation_drag_snapped_deg = 0.0
        calls = self._release_recorder(view)
        view.mouseReleaseEvent(FakeMouseEvent(buttons=Qt.MouseButton.NoButton))
        self.assertEqual(calls, ["restore", "cursor"])
        self.assertFalse(view._rotation_drag_active)

    def test_rotation_handles_are_restored_for_the_active_rotate_mode(self):
        view = self._make_view({"t1"})
        view._cursor_mode = "rotate"
        view.calls = []
        view.cursor_mode_change_requested = FakeSignal()
        view._remove_rotate_handle = lambda: view.calls.append("remove")
        view._apply_cursor_mode = lambda mode: view.calls.append(("mode", mode))
        view.update_selection_visuals = lambda *a, **k: view.calls.append(
            ("visuals", k)
        )
        view._create_rotate_handle = lambda uids: (
            view.calls.append(("create", set(uids))) or view.create_result
        )
        view.create_result = True
        view._restore_rotation_handles_if_needed()
        self.assertEqual(view.calls, [("visuals", {"emit": False}), ("create", {"t1"})])
        self.assertEqual(view.cursor_mode_change_requested.emitted, [])
        view.calls.clear()
        view.create_result = False
        view._restore_rotation_handles_if_needed()
        self.assertEqual(
            view.calls,
            [("visuals", {"emit": False}), ("create", {"t1"}), ("mode", "select")],
        )
        self.assertEqual(view.cursor_mode_change_requested.emitted, [("select",)])
        view.calls.clear()
        view.cursor_mode_change_requested.emitted.clear()
        view._selected_uids = set()
        view._restore_rotation_handles_if_needed()
        self.assertEqual(view.calls, ["remove"])
        view.calls.clear()
        view._cursor_mode = "select"
        view._restore_rotation_handles_if_needed()
        self.assertEqual(view.calls, [])
        self.assertEqual(view.cursor_mode_change_requested.emitted, [])

    def test_slope_handle_restore_falls_back_to_select_when_unavailable(self):
        for available in (True, False):
            with self.subTest(available=available):
                view = self._make_view({"t1"})
                view._cursor_mode = "slope_rotate"
                view.modes = []
                view.cursor_mode_change_requested = FakeSignal()
                view._create_slope_rotate_handle = lambda available=available: available
                view._apply_cursor_mode = view.modes.append
                view._restore_rotation_handles_if_needed()
                self.assertEqual(view.modes, [] if available else ["select"])
                self.assertEqual(
                    view.cursor_mode_change_requested.emitted,
                    [] if available else [("select",)],
                )

    def test_rotation_preview_uids_include_area_descendants_of_rotatable_items(self):
        view = self._make_view({"parent", "line"})
        view._current_conditions = {
            "area": Condition(uid="area", condition_type=Condition.TYPE_AREA),
            "linear": Condition(uid="linear", condition_type=Condition.TYPE_LINEAR),
        }
        view._current_takeoffs = {
            "parent": Takeoff(uid="parent", condition_uid="area", position=[0.0] * 8),
            "hole": Takeoff(
                uid="hole",
                condition_uid="area",
                parent_uid="parent",
                position=[1.0] * 8,
            ),
            "line": Takeoff(uid="line", condition_uid="linear", position=[0.0] * 4),
        }
        view._is_rotatable_uid = lambda uid: uid != "line"
        self.assertEqual(view._selected_rotation_preview_uids(), {"parent", "hole"})


class InputHandlerMixinMoveReleaseGestureTests(_CtrlDragFixture):
    """InputHandlerMixin.mouseMoveEvent/mouseReleaseEvent gesture contracts."""

    def _gesture_view(self, selected=("t1",)):
        view = self._make_view(set(selected))
        view.scene_to_ost_delta = lambda dx, dy: (dx, dy)
        view.mapToScene = lambda arg: (
            QtGui.QPolygonF(QtCore.QRectF(arg))
            if isinstance(arg, QtCore.QRect)
            else QtCore.QPointF(arg)
        )
        view.flushes = []

        def flush():
            view.flushes.append(
                (
                    dict(view._dirty_positions),
                    dict(view._dirty_ann_positions),
                    dict(view._position_before_edit),
                )
            )
            view._dirty_positions.clear()
            view._dirty_ann_positions.clear()
            view._position_before_edit.clear()

        view._flush_dirty_positions = flush
        view.preview_calls = []

        def update_drag_handle_positions(new_pos, uid, sdx, sdy):
            view.preview_calls.append((list(new_pos), uid, sdx, sdy))
            view._drag_last_valid_new_pos = (
                list(new_pos) if view._drag_handle_corner_count else []
            )

        view.update_drag_handle_positions = update_drag_handle_positions
        view.finish_calls = []
        view.finish_intelligent_paste_placement = lambda: view.finish_calls.append(1)
        view.cursor_updates = []
        view._update_cursor = lambda *a, **k: view.cursor_updates.append(a)
        view.find_text_annotation_at = lambda _p: None
        view._snap_angle = lambda _ox, _oy, nx, ny: (nx, ny)
        view.find_selected_movable_at = lambda uid_hit=None: next(
            iter(view._selected_uids), None
        )
        view.find_takeoff_at = lambda _p, cycle_from_uid=None: next(
            iter(view._selected_uids), None
        )
        view.find_takeoffs_at = lambda _p: list(view._selected_uids)
        return view

    def _annotation_gesture(self, annotation_type, position):
        view = self._gesture_view(("a1",))
        view._current_takeoffs = {}
        annotation = BidAnnotation(
            uid="a1", annotation_type=annotation_type, position=list(position)
        )
        view._current_annotations = {"a1": annotation}
        view._uid_to_items = {"a1": [FakeItem(1.0, 2.0)]}
        view._handle_infos = []
        return view, annotation

    def test_annotation_body_drag_previews_and_commits_the_snapped_translation(self):
        cases = (
            ("rect", [0.0, 0.0, 10.0, 4.0], [3.0, 2.0, 13.0, 6.0]),
            ("highlight", [0.0, 0.0, 10.0, 4.0], [3.0, 2.0, 13.0, 6.0]),
            ("line", [0.0, 0.0, 10.0, 4.0], [3.0, 2.0, 13.0, 6.0]),
            ("text", [10.0, 10.0, 40.0, 20.0], [13.0, 12.0, 40.0, 20.0]),
            ("ink", [0.25, 10.0, 20.0, 30.0, 40.0], [0.25, 13.0, 22.0, 33.0, 42.0]),
            ("dimension", [0.0, 0.0, 10.0, 4.0], [3.0, 2.0, 13.0, 6.0]),
        )
        for annotation_type, original, expected in cases:
            with self.subTest(annotation_type=annotation_type):
                view, annotation = self._annotation_gesture(annotation_type, original)
                view.mousePressEvent(FakeMouseEvent(x=0, y=0))
                move = FakeMouseEvent(x=3, y=2)
                view.mouseMoveEvent(move)
                self.assertTrue(move.accepted)
                self.assertEqual(view.preview_calls, [(expected, "a1", 3.0, 2.0)])
                self.assertEqual(annotation.position, original)
                self.assertTrue(view._select_band_dragged)
                release = FakeMouseEvent(x=3, y=2, buttons=Qt.MouseButton.NoButton)
                view.mouseReleaseEvent(release)
                self.assertTrue(release.accepted)
                self.assertEqual(annotation.position, expected)
                self.assertEqual(
                    view.flushes,
                    [({}, {"a1": (annotation_type, expected)}, {"a1": original})],
                )
                self.assertIsNone(view._drag_plan_item_uid)
                self.assertEqual(view._drag_item_orig_positions, {})
                self.assertEqual(view.finish_calls, [1])
                self.assertEqual(
                    len(view.preview_calls), 2 if annotation_type == "dimension" else 1
                )
                if annotation_type == "dimension":
                    self.assertEqual(view.preview_calls[1], (expected, "a1", 3.0, 2.0))

    def test_single_drag_uses_axis_snapped_delta_for_preview_and_release(self):
        view, annotation = self._annotation_gesture("rect", [0.0, 0.0, 10.0, 4.0])
        view.apply_intelligent_paste_axis_snap = lambda dx, dy: (0.0, dy)
        view.mousePressEvent(FakeMouseEvent(x=0, y=0))
        view.mouseMoveEvent(FakeMouseEvent(x=3, y=2))
        self.assertEqual(view.preview_calls, [([0.0, 2.0, 10.0, 6.0], "a1", 3.0, 2.0)])
        view.mouseReleaseEvent(
            FakeMouseEvent(x=3, y=2, buttons=Qt.MouseButton.NoButton)
        )
        self.assertEqual(annotation.position, [0.0, 2.0, 10.0, 6.0])

    def test_group_drag_uses_axis_snapped_delta_for_preview_and_release(self):
        view = self._gesture_view(("t1", "t2"))
        view._snap_increments = 10.0
        view.apply_intelligent_paste_axis_snap = lambda dx, dy: (0.0, dy)
        view._uid_to_items = {
            "t1": [FakeItem(100.0, 100.0)],
            "t2": [FakeItem(0.0, 0.0)],
        }
        view.mousePressEvent(FakeMouseEvent(x=0, y=0))
        view.mouseMoveEvent(FakeMouseEvent(x=6, y=6))
        self.assertEqual(
            view._uid_to_items["t1"][0].pos(), QtCore.QPointF(100.0, 110.0)
        )
        self.assertEqual(view._uid_to_items["t2"][0].pos(), QtCore.QPointF(0.0, 10.0))
        view.mouseReleaseEvent(
            FakeMouseEvent(x=6, y=6, buttons=Qt.MouseButton.NoButton)
        )
        self.assertEqual(view._current_takeoffs["t1"].position, [0.0, 10.0, 10.0, 10.0])
        self.assertEqual(
            view._current_takeoffs["t2"].position, [20.0, 10.0, 30.0, 10.0]
        )

    def test_group_drag_is_flagged_only_when_snapped_positions_change(self):
        view = self._gesture_view(("t1", "t2"))
        view._snap_increments = 10.0
        view.mousePressEvent(FakeMouseEvent(x=0, y=0))
        view.mouseMoveEvent(FakeMouseEvent(x=3, y=3))
        self.assertFalse(view._select_band_dragged)
        view.mouseMoveEvent(FakeMouseEvent(x=6, y=6))
        self.assertTrue(view._select_band_dragged)

    def test_group_release_skips_unchanged_items_and_records_annotations(self):
        view = self._gesture_view(("t1", "a1"))
        view._snap_increments = 1.0
        annotation = BidAnnotation(
            uid="a1", annotation_type="rect", position=[0.0, 0.0, 10.0, 4.0]
        )
        view._current_annotations = {"a1": annotation}
        view._uid_to_items["a1"] = [FakeItem(0.0, 0.0)]
        view._compute_group_translation_positions = lambda orig, dx, dy: {
            "t1": list(orig["t1"]),
            "a1": [3.0, 2.0, 13.0, 6.0],
        }
        view.mousePressEvent(FakeMouseEvent(x=0, y=0))
        view._select_band_dragged = True
        view.mouseReleaseEvent(
            FakeMouseEvent(x=3, y=2, buttons=Qt.MouseButton.NoButton)
        )
        self.assertEqual(annotation.position, [3.0, 2.0, 13.0, 6.0])
        self.assertEqual(
            view.flushes,
            [
                (
                    {},
                    {"a1": ("rect", [3.0, 2.0, 13.0, 6.0])},
                    {"a1": [0.0, 0.0, 10.0, 4.0]},
                )
            ],
        )

    def _area_parent_view(self):
        view = self._gesture_view(("parent",))
        view._current_conditions = {
            "area": Condition(uid="area", condition_type=Condition.TYPE_AREA)
        }
        view._current_takeoffs = {
            "parent": Takeoff(
                uid="parent",
                condition_uid="area",
                position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0],
            ),
            "hole": Takeoff(
                uid="hole",
                condition_uid="area",
                parent_uid="parent",
                position=[2.0, 2.0, 4.0, 2.0, 4.0, 4.0, 2.0, 4.0],
            ),
            "other": Takeoff(
                uid="other",
                condition_uid="area",
                position=[50.0, 50.0, 60.0, 50.0, 60.0, 60.0, 50.0, 60.0],
            ),
        }
        view._uid_to_items = {"parent": [FakeItem(100.0, 100.0)]}
        view._handle_infos = []
        return view

    def test_area_parent_drag_translates_descendant_holes_with_before_edit(self):
        view = self._area_parent_view()
        parent_before = list(view._current_takeoffs["parent"].position)
        hole_before = list(view._current_takeoffs["hole"].position)
        view.mousePressEvent(FakeMouseEvent(x=0, y=0))
        self.assertEqual(view._drag_handle_corner_count, 4)
        view.mouseMoveEvent(FakeMouseEvent(x=3, y=2))
        view.mouseReleaseEvent(
            FakeMouseEvent(x=3, y=2, buttons=Qt.MouseButton.NoButton)
        )
        parent_after = [3.0, 2.0, 13.0, 2.0, 13.0, 12.0, 3.0, 12.0]
        hole_after = [5.0, 4.0, 7.0, 4.0, 7.0, 6.0, 5.0, 6.0]
        self.assertEqual(view._current_takeoffs["parent"].position, parent_after)
        self.assertEqual(view._current_takeoffs["hole"].position, hole_after)
        self.assertEqual(
            view._current_takeoffs["other"].position,
            [50.0, 50.0, 60.0, 50.0, 60.0, 60.0, 50.0, 60.0],
        )
        self.assertEqual(
            view.flushes,
            [
                (
                    {"parent": parent_after, "hole": hole_after},
                    {},
                    {"parent": parent_before, "hole": hole_before},
                )
            ],
        )

    def test_resizing_an_area_vertex_does_not_translate_descendants(self):
        view = self._area_parent_view()
        handle = SimpleNamespace(item=FakeItem(), cursor=Qt.CursorShape.SizeAllCursor)
        view._handle_infos = [handle]
        view._is_handle_info_at_viewport_pos = lambda info, _pos: info is handle
        hole_before = list(view._current_takeoffs["hole"].position)
        view.mousePressEvent(FakeMouseEvent(x=0, y=0))
        self.assertEqual(view._drag_handle_index, 0)
        view.compute_new_position = lambda *a, **k: [3.0, 2.0] + a[0][2:]
        view.mouseMoveEvent(FakeMouseEvent(x=3, y=2))
        view.mouseReleaseEvent(
            FakeMouseEvent(x=3, y=2, buttons=Qt.MouseButton.NoButton)
        )
        self.assertEqual(view._current_takeoffs["parent"].position[:2], [3.0, 2.0])
        self.assertEqual(view._current_takeoffs["hole"].position, hole_before)
        self.assertEqual(set(view.flushes[0][0]), {"parent"})

    def test_drag_returning_to_origin_restores_preview_and_does_not_persist(self):
        view = self._area_parent_view()
        item = view._uid_to_items["parent"][0]
        view.mousePressEvent(FakeMouseEvent(x=0, y=0))
        view.mouseMoveEvent(FakeMouseEvent(x=3, y=2))
        item.setPos(103.0, 102.0)
        view.mouseMoveEvent(FakeMouseEvent(x=0, y=0))
        self.assertTrue(view._select_band_dragged)
        release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton, x=0, y=0)
        view.mouseReleaseEvent(release)
        self.assertTrue(release.accepted)
        self.assertEqual(item.pos(), QtCore.QPointF(100.0, 100.0))
        self.assertEqual(view.flushes, [])
        self.assertEqual(view._dirty_positions, {})
        self.assertIsNone(view._drag_plan_item_uid)
        self.assertFalse(view._select_band_dragged)
        self.assertEqual(view.finish_calls, [1])
        self.assertEqual(view._selected_uids, {"parent"})

    def test_move_flags_drag_only_beyond_five_pixels_on_either_axis(self):
        for point, flagged in (
            ((5, 0), False),
            ((0, 5), False),
            ((-5, -5), False),
            ((6, 0), True),
            ((0, 6), True),
            ((-6, 0), True),
            ((0, -6), True),
        ):
            with self.subTest(point=point):
                view = self._gesture_view(())
                view._rubber_band = SimpleNamespace(
                    setGeometry=lambda *_a: None, show=lambda: None, hide=lambda: None
                )
                view._select_band_origin = QtCore.QPointF(0.0, 0.0)
                view.mouseMoveEvent(FakeMouseEvent(x=point[0], y=point[1]))
                self.assertEqual(view._select_band_dragged, flagged)
                self.assertEqual(view._select_band_active, flagged)

    def test_marquee_rectangle_follows_mouse_and_is_normalized(self):
        view = self._gesture_view(())
        geometry = []
        shown = []
        view._rubber_band = SimpleNamespace(
            setGeometry=geometry.append,
            show=lambda: shown.append(True),
            hide=lambda: None,
        )
        view._select_band_origin = QtCore.QPointF(20.0, 20.0)
        move = FakeMouseEvent(x=5, y=8)
        view.mouseMoveEvent(move)
        self.assertTrue(move.accepted)
        self.assertEqual(shown, [True])
        origin = QtCore.QPoint(20, 20)
        self.assertEqual(
            geometry,
            [
                QtCore.QRect(origin, origin),
                QtCore.QRect(origin, QtCore.QPoint(5, 8)).normalized(),
            ],
        )
        self.assertEqual(geometry[1].topLeft(), QtCore.QPoint(6, 9))
        view.mouseMoveEvent(FakeMouseEvent(x=40, y=50))
        self.assertEqual(
            geometry[-1], QtCore.QRect(origin, QtCore.QPoint(40, 50)).normalized()
        )
        self.assertEqual(geometry[-1].bottomRight(), QtCore.QPoint(40, 50))
        self.assertEqual(shown, [True])

    def test_tracked_drag_prevents_marquee_from_starting(self):
        for name, prepare in (
            (
                "plan item without handle state",
                lambda v: setattr(v, "_drag_plan_item_uid", "t1"),
            ),
            (
                "group drag",
                lambda v: setattr(v, "_drag_multi_orig_positions", {"t1": [0.0, 0.0]}),
            ),
        ):
            with self.subTest(name):
                view = self._gesture_view(())
                view._rubber_band = SimpleNamespace(
                    setGeometry=lambda *_a: self.fail("marquee started"),
                    show=lambda: self.fail("marquee started"),
                    hide=lambda: None,
                )
                view._select_band_origin = QtCore.QPointF(0.0, 0.0)
                prepare(view)
                view.mouseMoveEvent(FakeMouseEvent(x=20, y=20))
                self.assertFalse(view._select_band_active)

    def test_ctrl_zoom_drag_converts_selection_band_into_zoom_rubber_band(self):
        view = self._gesture_view(("t1",))
        overlay = view._uid_to_items["t1"][0]
        original = overlay.pos()
        overlay.setPos(60.0, 70.0)
        view._drag_plan_item_uid = "t1"
        view._drag_item_orig_positions = {id(overlay): original}
        geometry = []
        shown = []
        view._rubber_band = SimpleNamespace(
            setGeometry=geometry.append,
            show=lambda: shown.append(True),
            hide=lambda: None,
        )
        view._select_band_origin = QtCore.QPointF(10.0, 10.0)
        view._zoom_press_ctrl = True
        view.mouseMoveEvent(FakeMouseEvent(x=12, y=12))
        self.assertEqual(geometry, [])
        self.assertEqual(view._select_band_origin, QtCore.QPointF(10.0, 10.0))
        move = FakeMouseEvent(x=30, y=40)
        view.mouseMoveEvent(move)
        self.assertTrue(move.accepted)
        self.assertEqual(view._rubber_band_origin, QtCore.QPointF(10.0, 10.0))
        self.assertIsNone(view._select_band_origin)
        self.assertEqual(overlay.pos(), original)
        self.assertIsNone(view._drag_plan_item_uid)
        self.assertEqual(shown, [True])
        self.assertEqual(
            geometry, [QtCore.QRect(QtCore.QPoint(10, 10), QtCore.QPoint(30, 40))]
        )
        view.mouseMoveEvent(FakeMouseEvent(x=5, y=6))
        self.assertEqual(
            geometry[-1],
            QtCore.QRect(QtCore.QPoint(10, 10), QtCore.QPoint(5, 6)).normalized(),
        )

    def test_pdf_text_drag_move_updates_the_text_selection_only(self):
        view = self._gesture_view(())
        updates = []
        view._pdf_text_drag_anchor = (0, 1)
        view._update_pdf_text_selection_drag = lambda pos: updates.append(pos) or True
        view._select_band_origin = QtCore.QPointF(0.0, 0.0)
        move = FakeMouseEvent(x=40, y=50)
        view.mouseMoveEvent(move)
        self.assertTrue(move.accepted)
        self.assertEqual(updates, [QtCore.QPointF(40.0, 50.0)])
        self.assertFalse(view._select_band_dragged)

    def test_right_pan_move_suppresses_context_menu_after_drag_threshold(self):
        threshold = QApplication.startDragDistance()
        for distance, suppressed in ((threshold - 1, False), (threshold, True)):
            with self.subTest(distance=distance):
                view = self._gesture_view(())
                view._panning = True
                view._right_pan_active = True
                view._last_pan_point = QtCore.QPoint(0, 0)
                view._right_pan_press_pos = QtCore.QPoint(0, 0)
                view._right_pan_dragged = False
                view._suppress_next_context_menu = False
                pans = []
                view._apply_pan_update = lambda point: pans.append(point) or True
                view._uses_dynamic_tile_coverage = lambda: False
                move = FakeMouseEvent(x=distance, y=0)
                view.mouseMoveEvent(move)
                self.assertTrue(move.accepted)
                self.assertEqual(pans, [QtCore.QPoint(distance, 0)])
                self.assertEqual(view._right_pan_dragged, suppressed)
                self.assertEqual(view._suppress_next_context_menu, suppressed)

    def test_pan_move_updates_dynamic_tile_coverage_scale(self):
        view = self._gesture_view(())
        view._panning = True
        view._right_pan_active = False
        view._last_pan_point = QtCore.QPoint(0, 0)
        view._apply_pan_update = lambda point: True
        view._uses_dynamic_tile_coverage = lambda: True
        view.transform = lambda: QTransform().scale(2.5, 2.5)
        scales = []
        view._zoom_debouncer = SimpleNamespace(handle_scale_changed=scales.append)
        move = FakeMouseEvent(x=5, y=5)
        view.mouseMoveEvent(move)
        self.assertTrue(move.accepted)
        self.assertEqual(scales, [2.5])

    def test_idle_move_refreshes_cursor_at_the_pointer(self):
        view = self._gesture_view(())
        view.mouseMoveEvent(FakeMouseEvent(x=7, y=9, buttons=Qt.MouseButton.NoButton))
        self.assertEqual(view.cursor_updates, [(QtCore.QPoint(7, 9),)])

    def test_zoom_rubber_band_move_resizes_the_band(self):
        view = self._gesture_view(())
        geometry = []
        view._rubber_band = SimpleNamespace(
            setGeometry=geometry.append, hide=lambda: None
        )
        view._rubber_band_origin = QtCore.QPointF(30.0, 30.0)
        move = FakeMouseEvent(x=10, y=50)
        view.mouseMoveEvent(move)
        self.assertTrue(move.accepted)
        self.assertEqual(
            geometry,
            [QtCore.QRect(QtCore.QPoint(30, 30), QtCore.QPoint(10, 50)).normalized()],
        )

    def _band_view(self, selected=()):
        view = self._gesture_view(selected)
        view._scene = QGraphicsScene()
        view._scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)
        for uid, x in (("t1", 5.0), ("t2", 25.0), ("locked", 45.0), ("", 65.0)):
            item = QGraphicsRectItem(x, 5.0, 10.0, 10.0)
            item.setData(0, uid)
            view._scene.addItem(item)
        view._is_selectable = lambda uid: uid != "locked"
        view._roping_selection_method = Config.ROPING_SELECTION_INCLUSIVE
        view.hidden = []
        view._rubber_band = SimpleNamespace(hide=lambda: view.hidden.append(True))
        view.events = []
        view._on_selection_changed = lambda: view.events.append("selection_changed")
        view.update_selection_visuals = lambda *a, **k: view.events.append("visuals")
        view._select_band_origin = QtCore.QPointF(0.0, 0.0)
        view._select_band_active = True
        view._select_band_dragged = True
        return view

    def test_marquee_release_selects_only_selectable_uids_inside_the_rectangle(self):
        view = self._band_view(selected=("old",))
        release = FakeMouseEvent(x=100, y=100, buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(release)
        self.assertTrue(release.accepted)
        self.assertEqual(view._selected_uids, {"t1", "t2"})
        self.assertEqual(view.hidden, [True])
        self.assertEqual(view.events, ["selection_changed", "visuals"])
        self.assertEqual(len(view.flushes), 1)
        self.assertIsNone(view._select_band_origin)
        self.assertFalse(view._select_band_active)
        self.assertFalse(view._select_band_dragged)
        self.assertEqual(view.cursor_updates, [()])

    def test_marquee_release_flushes_pending_positions_before_selection_change(self):
        view = self._band_view()
        view._dirty_positions = {"t1": [1.0, 1.0, 2.0, 2.0]}
        view._position_before_edit = {"t1": [0.0, 0.0, 1.0, 1.0]}
        view.mouseReleaseEvent(
            FakeMouseEvent(x=100, y=100, buttons=Qt.MouseButton.NoButton)
        )
        self.assertEqual(
            view.flushes,
            [({"t1": [1.0, 1.0, 2.0, 2.0]}, {}, {"t1": [0.0, 0.0, 1.0, 1.0]})],
        )

    def test_modifier_marquee_toggles_selection_symmetrically(self):
        for modifier in (
            Qt.KeyboardModifier.ShiftModifier,
            Qt.KeyboardModifier.ControlModifier,
        ):
            with self.subTest(modifier=modifier):
                view = self._band_view(selected=("t1", "keep"))
                view.mouseReleaseEvent(
                    FakeMouseEvent(
                        modifier, x=100, y=100, buttons=Qt.MouseButton.NoButton
                    )
                )
                self.assertEqual(view._selected_uids, {"t2", "keep"})

    def test_marquee_release_below_minimum_size_changes_nothing(self):
        for size in ((1, 100), (100, 1)):
            with self.subTest(size=size):
                view = self._band_view(selected=("old",))
                view.mouseReleaseEvent(
                    FakeMouseEvent(
                        x=size[0], y=size[1], buttons=Qt.MouseButton.NoButton
                    )
                )
                self.assertEqual(view._selected_uids, {"old"})
                self.assertEqual(view.events, [])
                self.assertEqual(view.hidden, [True])

    def test_touching_roping_selects_items_the_rectangle_only_crosses(self):
        view = self._band_view()
        view._roping_selection_method = Config.ROPING_SELECTION_TOUCHING
        view.mouseReleaseEvent(
            FakeMouseEvent(x=30, y=30, buttons=Qt.MouseButton.NoButton)
        )
        self.assertEqual(view._selected_uids, {"t1", "t2"})
        view = self._band_view()
        view.mouseReleaseEvent(
            FakeMouseEvent(x=30, y=30, buttons=Qt.MouseButton.NoButton)
        )
        self.assertEqual(view._selected_uids, {"t1"})

    def test_ctrl_zoom_click_zooms_in_only_for_an_undragged_press(self):
        for dragged, plan_uid, zooms in (
            (False, None, True),
            (True, None, False),
            (False, "t1", False),
        ):
            with self.subTest(dragged=dragged, plan_uid=plan_uid):
                view = self._gesture_view(("t1",))
                view.ZOOM_FACTOR = 1.25
                view.zoom_calls = []
                view._apply_zoom = view.zoom_calls.append
                view.view_changes = []
                view._mark_user_view_changed_during_load = (
                    lambda: view.view_changes.append(1)
                )
                view._select_band_origin = QtCore.QPointF(1.0, 1.0)
                view._zoom_press_ctrl = True
                view._select_band_dragged = dragged
                view._drag_plan_item_uid = plan_uid
                release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
                view.mouseReleaseEvent(release)
                self.assertTrue(release.accepted)
                self.assertEqual(view.zoom_calls, [1.25] if zooms else [])
                self.assertEqual(view.view_changes, [1] if zooms else [])
                self.assertIsNone(view._select_band_origin)
                self.assertFalse(view._zoom_press_ctrl)

    def _zoom_rectangle_view(self, cursor_mode="select"):
        view = self._gesture_view(())
        view._cursor_mode = cursor_mode
        view.hidden = []
        view._rubber_band = SimpleNamespace(hide=lambda: view.hidden.append(True))
        view._rubber_band_origin = QtCore.QPointF(10.0, 10.0)
        view.fits = []
        view.fitInView = lambda rect, mode: view.fits.append((rect, mode))
        view.transform = lambda: QTransform().scale(3.0, 3.0)
        view.scales = []
        view._zoom_debouncer = SimpleNamespace(handle_scale_changed=view.scales.append)
        view.zoom_changed = FakeSignal()
        view._scene_scale = 2.0
        view.published = []
        view._publish_current_page_view_state = lambda: view.published.append(1)
        view.view_changes = []
        view._mark_user_view_changed_during_load = lambda: view.view_changes.append(1)
        view.ZOOM_FACTOR = 1.25
        view.zoom_calls = []
        view._apply_zoom = view.zoom_calls.append
        return view

    def test_zoom_rectangle_release_fits_view_and_publishes_scale(self):
        view = self._zoom_rectangle_view()
        release = FakeMouseEvent(x=60, y=40, buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(release)
        self.assertTrue(release.accepted)
        self.assertEqual(view.hidden, [True])
        self.assertIsNone(view._rubber_band_origin)
        self.assertEqual(
            view.fits,
            [
                (
                    QtCore.QRectF(10.0, 10.0, 51.0, 31.0),
                    Qt.AspectRatioMode.KeepAspectRatio,
                )
            ],
        )
        self.assertEqual(view.scales, [3.0])
        self.assertEqual(len(view.zoom_changed.emitted), 1)
        self.assertAlmostEqual(view.zoom_changed.emitted[0][0], 3.0 * 2.0 * 0.333)
        self.assertEqual(view.published, [1])
        self.assertEqual(view.view_changes, [1])
        self.assertEqual(view.zoom_calls, [])

    def test_small_zoom_rectangle_zooms_in_only_in_zoom_mode(self):
        for mode, zooms in (("zoom", True), ("select", False)):
            with self.subTest(mode=mode):
                view = self._zoom_rectangle_view(cursor_mode=mode)
                view.mouseReleaseEvent(
                    FakeMouseEvent(x=14, y=14, buttons=Qt.MouseButton.NoButton)
                )
                self.assertEqual(view.fits, [])
                self.assertEqual(view.zoom_calls, [1.25] if zooms else [])
                self.assertEqual(view.published, [1] if zooms else [])
                self.assertEqual(view.hidden, [True])

    def test_zoom_rectangle_at_minimum_size_boundary_does_not_fit(self):
        for point in ((14, 40), (40, 14)):
            with self.subTest(point=point):
                view = self._zoom_rectangle_view()
                view.mouseReleaseEvent(
                    FakeMouseEvent(
                        x=point[0], y=point[1], buttons=Qt.MouseButton.NoButton
                    )
                )
                self.assertEqual(view.fits, [])

    def test_right_button_release_suppresses_context_menu_after_drag_or_long_hold(self):
        for dragged, held_ms, suppressed in (
            (False, 0, False),
            (True, 0, True),
            (False, RIGHT_CLICK_CONTEXT_MENU_MAX_MS + 1, True),
            (False, RIGHT_CLICK_CONTEXT_MENU_MAX_MS, False),
        ):
            with self.subTest(dragged=dragged, held_ms=held_ms):
                view = self._gesture_view(())
                view._right_pan_active = True
                view._right_pan_dragged = dragged
                view._suppress_next_context_menu = False
                view._right_pan_press_timer = SimpleNamespace(
                    elapsed=lambda ms=held_ms: ms
                )
                view.finished_pans = []
                view._finish_pan_interaction = lambda: view.finished_pans.append(1)
                release = _RightButtonMouseEvent(buttons=Qt.MouseButton.NoButton)
                view.mouseReleaseEvent(release)
                self.assertTrue(release.accepted)
                self.assertEqual(view.finished_pans, [1])
                self.assertEqual(view._suppress_next_context_menu, suppressed)

    def test_left_release_finishes_an_active_pan(self):
        view = self._gesture_view(())
        view._panning = True
        view.finished_pans = []
        view._finish_pan_interaction = lambda: view.finished_pans.append(1)
        release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(release)
        self.assertTrue(release.accepted)
        self.assertEqual(view.finished_pans, [1])

    def test_pdf_text_drag_release_finishes_selection_and_clears_plan_selection(self):
        view = self._gesture_view(("t1",))
        calls = []
        view._pdf_text_drag_anchor = (0, 1)
        view._update_pdf_text_selection_drag = lambda pos: calls.append(("update", pos))
        view._finish_pdf_text_selection_drag = lambda: calls.append("finish")
        view._on_selection_changed = lambda: calls.append("selection_changed")
        view.update_selection_visuals = lambda *a, **k: calls.append("visuals")
        release = FakeMouseEvent(x=30, y=40, buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(release)
        self.assertTrue(release.accepted)
        self.assertEqual(
            calls,
            [
                ("update", QtCore.QPointF(30.0, 40.0)),
                "finish",
                "selection_changed",
                "visuals",
            ],
        )
        self.assertEqual(view._selected_uids, set())
        self.assertEqual(view.cursor_updates, [()])

    def _click_view(self, selected, hit, hits=None, press_changed=False):
        view = self._gesture_view(selected)
        view.cycle_requests = []

        def find_takeoff_at(_pos, cycle_from_uid=None):
            view.cycle_requests.append(cycle_from_uid)
            return hit

        view.find_takeoff_at = find_takeoff_at
        view.find_takeoffs_at = lambda _p: list(hits if hits is not None else [hit])
        view._select_band_origin = QtCore.QPointF(10.0, 10.0)
        view._press_changed_selection = press_changed
        view.events = []
        view._on_selection_changed = lambda: view.events.append("selection_changed")
        view.update_selection_visuals = lambda *a, **k: view.events.append("visuals")
        view.pdf_cleared = []
        view._clear_pdf_text_selection = lambda: view.pdf_cleared.append(1)
        view.pdf_selects = []
        view.pdf_select_result = False
        view.select_pdf_text_at = lambda pos: (
            view.pdf_selects.append(pos) or view.pdf_select_result
        )
        return view

    def test_click_cycles_overlapping_selection_only_for_a_plain_single_selection(self):
        shift = Qt.KeyboardModifier.ShiftModifier
        cases = {
            "plain overlap": (
                ("t1",),
                ["t1", "t2"],
                False,
                Qt.KeyboardModifier.NoModifier,
                "t1",
            ),
            "single hit": (
                ("t1",),
                ["t1"],
                False,
                Qt.KeyboardModifier.NoModifier,
                None,
            ),
            "selection changed by press": (
                ("t1",),
                ["t1", "t2"],
                True,
                Qt.KeyboardModifier.NoModifier,
                None,
            ),
            "modifier click": (("t1",), ["t1", "t2"], False, shift, None),
            "multiple selected": (
                ("t1", "t2"),
                ["t1", "t2"],
                False,
                Qt.KeyboardModifier.NoModifier,
                None,
            ),
            "selected not under cursor": (
                ("t1",),
                ["t2", "t3"],
                False,
                Qt.KeyboardModifier.NoModifier,
                None,
            ),
        }
        for name, (selected, hits, changed, modifier, expected) in cases.items():
            with self.subTest(name):
                view = self._click_view(selected, hits[-1], hits, changed)
                view.mouseReleaseEvent(
                    FakeMouseEvent(modifier, buttons=Qt.MouseButton.NoButton)
                )
                self.assertEqual(view.cycle_requests, [expected])

    def test_click_on_hotlink_opens_it_and_clears_pdf_text_selection(self):
        view = self._make_hotlink_view(selected=False)
        view.pdf_cleared = []
        view._clear_pdf_text_selection = lambda: view.pdf_cleared.append(1)
        view._select_band_origin = QtCore.QPointF(10.0, 10.0)
        release = FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(release)
        self.assertTrue(release.accepted)
        self.assertEqual(len(view.hotlink_clicked.emitted), 1)
        self.assertEqual(view.pdf_cleared, [1])
        self.assertEqual(view._selected_uids, set())

    def test_click_selects_hit_with_flush_only_when_selection_changes(self):
        view = self._click_view(("t1",), "t2", ["t2"])
        view.mouseReleaseEvent(FakeMouseEvent(buttons=Qt.MouseButton.NoButton))
        self.assertEqual(view._selected_uids, {"t2"})
        self.assertEqual(len(view.flushes), 1)
        self.assertEqual(view.events, ["selection_changed", "visuals"])
        self.assertEqual(view.pdf_cleared, [1])
        view = self._click_view(("t1",), "t1", ["t1"])
        view.mouseReleaseEvent(FakeMouseEvent(buttons=Qt.MouseButton.NoButton))
        self.assertEqual(view._selected_uids, {"t1"})
        self.assertEqual(view.flushes, [])
        self.assertEqual(view.events, ["selection_changed", "visuals"])

    def test_modifier_click_toggles_hit_and_flushes_only_when_deselecting(self):
        shift = Qt.KeyboardModifier.ShiftModifier
        view = self._click_view(("t1",), "t2", ["t2"])
        view.mouseReleaseEvent(FakeMouseEvent(shift, buttons=Qt.MouseButton.NoButton))
        self.assertEqual(view._selected_uids, {"t1", "t2"})
        self.assertEqual(view.flushes, [])
        view = self._click_view(("t1", "t2"), "t2", ["t2"])
        view.mouseReleaseEvent(FakeMouseEvent(shift, buttons=Qt.MouseButton.NoButton))
        self.assertEqual(view._selected_uids, {"t1"})
        self.assertEqual(len(view.flushes), 1)

    def test_plain_click_on_text_annotation_selects_its_toolbar_label(self):
        view = self._click_view((), "a1", ["a1"])
        view._current_annotations = {
            "a1": BidAnnotation(
                uid="a1", annotation_type="text", position=[1.0, 1.0, 5.0, 5.0]
            )
        }
        view.selected_text_annotation_uids = []
        view.mouseReleaseEvent(FakeMouseEvent(buttons=Qt.MouseButton.NoButton))
        self.assertEqual(view.selected_text_annotation_uids, ["a1"])
        view = self._click_view((), "a1", ["a1"])
        view._current_annotations = {
            "a1": BidAnnotation(
                uid="a1", annotation_type="text", position=[1.0, 1.0, 5.0, 5.0]
            )
        }
        view.mouseReleaseEvent(
            FakeMouseEvent(
                Qt.KeyboardModifier.ShiftModifier, buttons=Qt.MouseButton.NoButton
            )
        )
        self.assertEqual(view.selected_text_annotation_uids, [])

    def test_click_on_empty_space_clears_selection_and_pdf_text_rules(self):
        view = self._click_view(("t1",), None, [])
        view.mouseReleaseEvent(FakeMouseEvent(buttons=Qt.MouseButton.NoButton))
        self.assertEqual(view._selected_uids, set())
        self.assertEqual(len(view.flushes), 1)
        self.assertEqual(view.pdf_selects, [QtCore.QPointF(10.0, 10.0)])
        self.assertEqual(view.pdf_cleared, [1])
        self.assertEqual(view.events, ["selection_changed", "visuals"])
        view = self._click_view(("t1",), None, [])
        view.pdf_select_result = True
        view.mouseReleaseEvent(FakeMouseEvent(buttons=Qt.MouseButton.NoButton))
        self.assertEqual(view.pdf_cleared, [])
        view = self._click_view(("t1",), None, [])
        view.mouseReleaseEvent(
            FakeMouseEvent(
                Qt.KeyboardModifier.ShiftModifier, buttons=Qt.MouseButton.NoButton
            )
        )
        self.assertEqual(view._selected_uids, {"t1"})
        self.assertEqual(view.flushes, [])

    def test_rotate_mode_click_creates_handle_or_falls_back_to_select(self):
        for created in (True, False):
            with self.subTest(created=created):
                view = self._click_view(("t1",), "t1", ["t1"])
                view._cursor_mode = "rotate"
                view.handle_requests = []
                view._create_rotate_handle = lambda uid, created=created: (
                    view.handle_requests.append(uid) or created
                )
                view.modes = []
                view._apply_cursor_mode = view.modes.append
                view.cursor_mode_change_requested = FakeSignal()
                view.mouseReleaseEvent(FakeMouseEvent(buttons=Qt.MouseButton.NoButton))
                self.assertEqual(view.handle_requests, ["t1"])
                self.assertEqual(view.modes, [] if created else ["select"])
                self.assertEqual(
                    view.cursor_mode_change_requested.emitted,
                    [] if created else [("select",)],
                )
        view = self._click_view(("t1", "t2"), "t3", ["t3"])
        view._cursor_mode = "rotate"
        view._create_rotate_handle = lambda uid: self.fail("handle needs one selection")
        view.mouseReleaseEvent(
            FakeMouseEvent(
                Qt.KeyboardModifier.ShiftModifier, buttons=Qt.MouseButton.NoButton
            )
        )

    def _handle_resize_view(self, annotation_type="rect", position=None):
        position = position or [0.0, 0.0, 10.0, 4.0]
        view, annotation = self._annotation_gesture(annotation_type, position)
        handle = SimpleNamespace(item=FakeItem(), cursor=Qt.CursorShape.SizeAllCursor)
        view._handle_infos = [handle]
        view._is_handle_info_at_viewport_pos = lambda info, _pos: info is handle
        return view, annotation

    def test_corner_handle_drag_resizes_annotation_box_on_preview_and_release(self):
        view, annotation = self._handle_resize_view()
        view.mousePressEvent(FakeMouseEvent(x=0, y=0))
        self.assertEqual(view._drag_handle_index, 0)
        view.mouseMoveEvent(FakeMouseEvent(x=3, y=2))
        self.assertEqual(view.preview_calls, [([3.0, 2.0, 10.0, 4.0], "a1", 3.0, 2.0)])
        view.mouseReleaseEvent(
            FakeMouseEvent(x=3, y=2, buttons=Qt.MouseButton.NoButton)
        )
        self.assertEqual(annotation.position, [3.0, 2.0, 10.0, 4.0])
        self.assertEqual(
            view.flushes,
            [
                (
                    {},
                    {"a1": ("rect", [3.0, 2.0, 10.0, 4.0])},
                    {"a1": [0.0, 0.0, 10.0, 4.0]},
                )
            ],
        )

    def test_resize_gesture_passes_shift_as_free_mode_on_preview_and_release(self):
        shift = Qt.KeyboardModifier.ShiftModifier
        for modifiers, free in ((Qt.KeyboardModifier.NoModifier, False), (shift, True)):
            with self.subTest(free=free):
                view = self._area_parent_view()
                handle = SimpleNamespace(
                    item=FakeItem(), cursor=Qt.CursorShape.SizeAllCursor
                )
                view._handle_infos = [handle]
                view._is_handle_info_at_viewport_pos = lambda info, _pos: info is handle
                requests = []

                def compute_new_position(
                    orig_pos, dx, dy, handle_idx, corners, **options
                ):
                    requests.append((handle_idx, corners, options))
                    return list(orig_pos)

                view.compute_new_position = compute_new_position
                view.mousePressEvent(FakeMouseEvent(x=0, y=0))
                view.mouseMoveEvent(FakeMouseEvent(modifiers, x=3, y=2))
                view.mouseReleaseEvent(
                    FakeMouseEvent(modifiers, x=3, y=2, buttons=Qt.MouseButton.NoButton)
                )
                self.assertEqual(
                    requests,
                    [
                        (0, 4, {"move_only_first_pair": False, "free_mode": free}),
                        (0, 4, {"move_only_first_pair": False, "free_mode": free}),
                    ],
                )

    def test_invalid_area_candidate_is_neither_flagged_nor_committed(self):
        view = self._area_parent_view()
        view.update_drag_handle_positions = lambda *args: None
        original = list(view._current_takeoffs["parent"].position)
        view.mousePressEvent(FakeMouseEvent(x=0, y=0))
        view.mouseMoveEvent(FakeMouseEvent(x=3, y=2))
        self.assertFalse(view._select_band_dragged)
        view._select_band_dragged = True
        view.mouseReleaseEvent(
            FakeMouseEvent(x=3, y=2, buttons=Qt.MouseButton.NoButton)
        )
        self.assertEqual(view._current_takeoffs["parent"].position, original)
        self.assertEqual(view.flushes, [])

    def test_area_vertex_release_commits_the_last_valid_candidate_not_the_pointer(self):
        view = self._area_parent_view()
        handle = SimpleNamespace(item=FakeItem(), cursor=Qt.CursorShape.SizeAllCursor)
        view._handle_infos = [handle]
        view._is_handle_info_at_viewport_pos = lambda info, _pos: info is handle
        original = list(view._current_takeoffs["parent"].position)
        view.update_drag_handle_positions = lambda *args: None
        view.mousePressEvent(FakeMouseEvent(x=0, y=0))
        view.mouseMoveEvent(FakeMouseEvent(x=30, y=20))
        view.mouseReleaseEvent(
            FakeMouseEvent(x=30, y=20, buttons=Qt.MouseButton.NoButton)
        )
        self.assertEqual(view._current_takeoffs["parent"].position, original)
        self.assertEqual(view.flushes, [])
        view = self._area_parent_view()
        view._handle_infos = [handle]
        view._is_handle_info_at_viewport_pos = lambda info, _pos: info is handle
        valid = [1.0, 1.0] + original[2:]
        view.update_drag_handle_positions = lambda *args: setattr(
            view, "_drag_last_valid_new_pos", list(valid)
        )
        view.mousePressEvent(FakeMouseEvent(x=0, y=0))
        view.mouseMoveEvent(FakeMouseEvent(x=30, y=20))
        view.mouseReleaseEvent(
            FakeMouseEvent(x=30, y=20, buttons=Qt.MouseButton.NoButton)
        )
        self.assertEqual(view._current_takeoffs["parent"].position, valid)

    def test_polygon_annotation_release_commits_the_last_valid_candidate(self):
        square = [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
        view, annotation = self._handle_resize_view("polygon", square)
        view.update_drag_handle_positions = lambda *args: None
        view.mousePressEvent(FakeMouseEvent(x=0, y=0))
        view.mouseMoveEvent(FakeMouseEvent(x=3, y=2))
        view.mouseReleaseEvent(
            FakeMouseEvent(x=3, y=2, buttons=Qt.MouseButton.NoButton)
        )
        self.assertEqual(annotation.position, square)
        self.assertEqual(view.flushes, [])

    def test_commit_keeps_the_earliest_pending_before_edit_snapshot(self):
        view, annotation = self._annotation_gesture("rect", [0.0, 0.0, 10.0, 4.0])
        view._position_before_edit = {"a1": [-9.0, -9.0, 1.0, 1.0]}
        view.mousePressEvent(FakeMouseEvent(x=0, y=0))
        view.mouseMoveEvent(FakeMouseEvent(x=3, y=2))
        view.mouseReleaseEvent(
            FakeMouseEvent(x=3, y=2, buttons=Qt.MouseButton.NoButton)
        )
        self.assertEqual(view.flushes[0][2], {"a1": [-9.0, -9.0, 1.0, 1.0]})
        view = self._area_parent_view()
        view._position_before_edit = {
            "parent": [-9.0, -9.0],
            "hole": [-8.0, -8.0],
        }
        view.mousePressEvent(FakeMouseEvent(x=0, y=0))
        view.mouseMoveEvent(FakeMouseEvent(x=3, y=2))
        view.mouseReleaseEvent(
            FakeMouseEvent(x=3, y=2, buttons=Qt.MouseButton.NoButton)
        )
        self.assertEqual(
            view.flushes[0][2], {"parent": [-9.0, -9.0], "hole": [-8.0, -8.0]}
        )

    def test_group_drag_before_edit_snapshot_is_kept_for_pending_items(self):
        view = self._gesture_view(("t1", "t2"))
        view._snap_increments = 10.0
        view._position_before_edit = {"t1": [-7.0, -7.0, 3.0, -7.0]}
        view.mousePressEvent(FakeMouseEvent(x=0, y=0))
        view.mouseMoveEvent(FakeMouseEvent(x=6, y=6))
        view.mouseReleaseEvent(
            FakeMouseEvent(x=6, y=6, buttons=Qt.MouseButton.NoButton)
        )
        self.assertEqual(
            view.flushes[0][2],
            {"t1": [-7.0, -7.0, 3.0, -7.0], "t2": [20.0, 0.0, 30.0, 0.0]},
        )


class InputHandlerMixinKeyboardShortcutTests(_CtrlDragFixture):
    """InputHandlerMixin.keyPressEvent/keyReleaseEvent shortcut routing."""

    def _key_view(self, selected=("t1",)):
        view = self._make_view(set(selected))
        for name in (
            "undo_requested",
            "redo_requested",
            "copy_requested",
            "paste_requested",
            "cursor_mode_change_requested",
        ):
            setattr(view, name, FakeSignal())
        view.copy_selected_pdf_text = lambda: False
        view._rotate_handle_uid = None
        view.calls = []
        view.cursor_updates = []
        view._update_cursor = lambda *a, **k: view.cursor_updates.append(a)

        def apply_cursor_mode(mode):
            view._cursor_mode = mode
            view.calls.append(("mode", mode))

        view._apply_cursor_mode = apply_cursor_mode
        view._remove_rotate_handle = lambda: view.calls.append("remove_handle")
        return view

    def _press(self, view, key, modifiers=Qt.KeyboardModifier.NoModifier, repeat=False):
        event = FakeKeyEvent(key, modifiers, auto_repeat=repeat)
        view.keyPressEvent(event)
        return event

    def test_ctrl_key_press_caches_ctrl_state_for_advanced_non_repeat_presses(self):
        for advanced, repeat, held in (
            (True, False, True),
            (True, True, False),
            (False, False, False),
        ):
            with self.subTest(advanced=advanced, repeat=repeat):
                view = self._key_view()
                view._advanced_mouse_controls_enabled = advanced
                view._ctrl_held = False
                event = self._press(view, Qt.Key.Key_Control, repeat=repeat)
                self.assertEqual(view._ctrl_held, held)
                self.assertEqual(len(view.cursor_updates), 1 if held else 0)
                self.assertFalse(event.accepted)

    def test_ctrl_z_and_ctrl_y_emit_history_requests_only_with_edit_access(self):
        ctrl = Qt.KeyboardModifier.ControlModifier
        for key, signal in (
            (Qt.Key.Key_Z, "undo_requested"),
            (Qt.Key.Key_Y, "redo_requested"),
        ):
            for editing in (True, False):
                with self.subTest(key=key, editing=editing):
                    view = self._key_view()
                    view._editing_enabled = editing
                    event = self._press(view, key, ctrl)
                    self.assertEqual(event.accepted, editing)
                    self.assertEqual(
                        getattr(view, signal).emitted, [()] if editing else []
                    )

    def test_ctrl_c_copies_pdf_text_before_plan_selection(self):
        ctrl = Qt.KeyboardModifier.ControlModifier
        view = self._key_view(("t1", "t2"))
        event = self._press(view, Qt.Key.Key_C, ctrl)
        self.assertTrue(event.accepted)
        self.assertEqual(len(view.copy_requested.emitted), 1)
        self.assertCountEqual(view.copy_requested.emitted[0][0], ["t1", "t2"])
        view = self._key_view(("t1",))
        view.copy_selected_pdf_text = lambda: True
        event = self._press(view, Qt.Key.Key_C, ctrl)
        self.assertTrue(event.accepted)
        self.assertEqual(view.copy_requested.emitted, [])
        view = self._key_view(())
        event = self._press(view, Qt.Key.Key_C, ctrl)
        self.assertFalse(event.accepted)
        self.assertEqual(view.copy_requested.emitted, [])

    def test_ctrl_r_requires_selection_edit_access_and_selected_items(self):
        ctrl = Qt.KeyboardModifier.ControlModifier
        cases = {
            "selection disabled": lambda v: setattr(v, "_selection_enabled", False),
            "editing disabled": lambda v: setattr(v, "_editing_enabled", False),
            "nothing selected": lambda v: setattr(v, "_selected_uids", set()),
        }
        for name, disable in cases.items():
            with self.subTest(name):
                view = self._key_view()
                view.clear_place_preview = lambda: view.calls.append("clear_preview")
                view._create_rotate_handle = lambda uids: view.calls.append("create")
                disable(view)
                event = self._press(view, Qt.Key.Key_R, ctrl)
                self.assertFalse(event.accepted)
                self.assertEqual(view.calls, [])
                self.assertEqual(view.cursor_mode_change_requested.emitted, [])

    def test_ctrl_r_toggles_an_existing_rotate_handle_off(self):
        view = self._key_view()
        view._rotate_handle_uid = "t1"
        view._cursor_mode = "rotate"
        event = self._press(view, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier)
        self.assertTrue(event.accepted)
        self.assertEqual(view.calls, ["remove_handle", ("mode", "select")])
        self.assertEqual(view.cursor_mode_change_requested.emitted, [("select",)])

    def test_ctrl_r_keeps_mode_when_handle_creation_fails(self):
        view = self._key_view()
        view.clear_place_preview = lambda: view.calls.append("clear_preview")
        view._create_rotate_handle = lambda uids: False
        event = self._press(view, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier)
        self.assertTrue(event.accepted)
        self.assertEqual(view.calls, ["clear_preview"])
        self.assertEqual(view.cursor_mode_change_requested.emitted, [])

    def test_ctrl_shift_r_toggles_slope_rotation_mode(self):
        both = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        view = self._key_view()
        view._cursor_mode = "slope_rotate"
        event = self._press(view, Qt.Key.Key_R, both)
        self.assertTrue(event.accepted)
        self.assertEqual(view.calls, ["remove_handle", ("mode", "select")])
        self.assertEqual(view.cursor_mode_change_requested.emitted, [("select",)])
        view = self._key_view()
        view.clear_place_preview = lambda: view.calls.append("clear_preview")
        view._create_slope_rotate_handle = lambda: False
        event = self._press(view, Qt.Key.Key_R, both)
        self.assertTrue(event.accepted)
        self.assertEqual(view.calls, ["clear_preview"])
        self.assertEqual(view.cursor_mode_change_requested.emitted, [])

    def test_ctrl_shift_r_from_place_mode_exits_placement_first(self):
        both = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        view = self._key_view()
        view._cursor_mode = "place"
        view.clear_place_preview = lambda: view.calls.append("clear_preview")
        view._exit_place_mode = lambda: (
            view.calls.append("exit_place"),
            setattr(view, "_cursor_mode", "select"),
        )
        view._create_slope_rotate_handle = lambda: True
        self._press(view, Qt.Key.Key_R, both)
        self.assertEqual(
            view.calls, ["exit_place", "clear_preview", ("mode", "slope_rotate")]
        )

    def test_escape_leaves_rotate_and_slope_rotate_modes(self):
        for mode in ("rotate", "slope_rotate"):
            with self.subTest(mode=mode):
                view = self._key_view()
                view._cursor_mode = mode
                event = self._press(view, Qt.Key.Key_Escape)
                self.assertTrue(event.accepted)
                self.assertEqual(view.calls, ["remove_handle", ("mode", "select")])
                self.assertEqual(
                    view.cursor_mode_change_requested.emitted, [("select",)]
                )

    def test_escape_cancels_intelligent_paste_drag_and_restores_preview(self):
        view = self._key_view()
        view._intelligent_paste_active = True
        overlay = view._uid_to_items["t1"][0]
        original = overlay.pos()
        overlay.setPos(40.0, 50.0)
        view._drag_plan_item_uid = "t1"
        view._drag_item_orig_positions = {id(overlay): original}
        view.finish_intelligent_paste_placement = lambda: view.calls.append("finish")
        event = self._press(view, Qt.Key.Key_Escape)
        self.assertTrue(event.accepted)
        self.assertEqual(overlay.pos(), original)
        self.assertIsNone(view._drag_plan_item_uid)
        self.assertEqual(view.calls, ["finish"])
        self.assertEqual(len(view.cursor_updates), 1)

    def test_escape_cancels_paste_backout_and_overlay_move_modes(self):
        view = self._key_view()
        view._cursor_mode = "paste_backout"
        view.cancel_paste_backout = lambda: view.calls.append("cancel_backout")
        event = self._press(view, Qt.Key.Key_Escape)
        self.assertTrue(event.accepted)
        self.assertEqual(view.calls, ["cancel_backout"])
        for mode in ("move_overlay", "move_overlay_handle"):
            with self.subTest(mode=mode):
                view = self._key_view()
                view._cursor_mode = mode
                view.cancel_overlay_move_mode = (
                    lambda restore_preview: view.calls.append(
                        ("cancel_overlay", restore_preview)
                    )
                )
                event = self._press(view, Qt.Key.Key_Escape)
                self.assertTrue(event.accepted)
                self.assertEqual(view.calls, [("cancel_overlay", True)])

    def _place_escape_view(self, points):
        view = self._key_view()
        view._cursor_mode = "place"
        view._place_points = list(points)
        view._place_linear_dragging = True
        view._place_area_rect_dragging = True
        view._last_mouse_vp_pos = QtCore.QPoint(3, 4)
        view.mapToScene = lambda point: QtCore.QPointF(point)
        view.finish_intelligent_paste_placement = lambda: view.calls.append("finish")
        view.clear_place_preview = lambda: view.calls.append("clear_preview")
        view.update_place_preview = lambda pos: view.calls.append(("preview", pos))
        view.viewport = lambda: SimpleNamespace(
            update=lambda: view.calls.append("viewport_update")
        )
        view._set_area_placement_in_progress = lambda flag: view.calls.append(
            ("progress", flag)
        )
        return view

    def test_escape_in_place_mode_removes_last_point_and_refreshes_preview(self):
        view = self._place_escape_view([(0, 0), (5, 5)])
        event = self._press(view, Qt.Key.Key_Escape)
        self.assertTrue(event.accepted)
        self.assertEqual(view._place_points, [(0, 0)])
        self.assertEqual(
            view.calls,
            [
                "finish",
                "clear_preview",
                ("preview", QtCore.QPointF(3.0, 4.0)),
                "viewport_update",
            ],
        )
        self.assertTrue(view._place_linear_dragging)

    def test_escape_in_place_mode_with_last_point_ends_area_placement(self):
        view = self._place_escape_view([(0, 0)])
        self._press(view, Qt.Key.Key_Escape)
        self.assertEqual(view._place_points, [])
        self.assertEqual(view.calls, ["finish", "clear_preview", ("progress", False)])
        self.assertFalse(view._place_linear_dragging)
        self.assertFalse(view._place_area_rect_dragging)

    def test_escape_in_place_mode_without_points_clears_preview_and_progress(self):
        view = self._place_escape_view([])
        event = self._press(view, Qt.Key.Key_Escape)
        self.assertTrue(event.accepted)
        self.assertEqual(view.calls, ["finish", "clear_preview", ("progress", False)])
        self.assertFalse(view._place_linear_dragging)
        self.assertFalse(view._place_area_rect_dragging)

    def test_escape_in_annotation_place_mode_returns_to_select_mode(self):
        view = self._key_view()
        view._cursor_mode = "annotation_place"
        view.finish_intelligent_paste_placement = lambda: view.calls.append("finish")
        view._exit_annotation_place_mode = lambda: view.calls.append("exit_annotation")
        event = self._press(view, Qt.Key.Key_Escape)
        self.assertTrue(event.accepted)
        self.assertEqual(view.calls, ["finish", "exit_annotation", ("mode", "select")])
        self.assertEqual(view.cursor_mode_change_requested.emitted, [("select",)])

    def test_delete_key_deletes_selection_only_with_edit_access(self):
        for editing, selected, deleted in (
            (True, ("t1",), True),
            (False, ("t1",), False),
            (True, (), False),
        ):
            with self.subTest(editing=editing, selected=selected):
                view = self._key_view(selected)
                view._editing_enabled = editing
                view.delete_selected = lambda: view.calls.append("delete")
                event = self._press(view, Qt.Key.Key_Delete)
                self.assertEqual(event.accepted, deleted)
                self.assertEqual(view.calls, ["delete"] if deleted else [])

    def test_ctrl_a_selects_all_only_in_select_mode_with_selection_access(self):
        ctrl = Qt.KeyboardModifier.ControlModifier
        for mode, selection_enabled, expected in (
            ("select", True, True),
            ("select", False, False),
            ("pan", True, False),
        ):
            with self.subTest(mode=mode, selection_enabled=selection_enabled):
                view = self._key_view()
                view._cursor_mode = mode
                view._selection_enabled = selection_enabled
                view.select_all = lambda: view.calls.append("select_all")
                event = self._press(view, Qt.Key.Key_A, ctrl)
                self.assertEqual(event.accepted, expected)
                self.assertEqual(view.calls, ["select_all"] if expected else [])

    def test_plain_a_does_not_select_all(self):
        view = self._key_view()
        view.select_all = lambda: view.calls.append("select_all")
        event = self._press(view, Qt.Key.Key_A)
        self.assertFalse(event.accepted)
        self.assertEqual(view.calls, [])

    def test_arrow_keys_move_selection_by_snap_step_in_each_direction(self):
        for key, delta in (
            (Qt.Key.Key_Left, (-5.0, 0.0)),
            (Qt.Key.Key_Right, (5.0, 0.0)),
            (Qt.Key.Key_Up, (0.0, -5.0)),
            (Qt.Key.Key_Down, (0.0, 5.0)),
        ):
            with self.subTest(key=key):
                view = self._key_view()
                view._snap_increments = 5.0
                event = self._press(view, key)
                self.assertTrue(event.accepted)
                self.assertEqual(
                    view._current_takeoffs["t1"].position,
                    [delta[0], delta[1], 10.0 + delta[0], delta[1]],
                )
                self.assertTrue(view._keyboard_move_dirty)

    def test_arrow_step_falls_back_to_one_inch_without_snapping(self):
        view = self._key_view()
        view._snap_increments = 0
        self._press(view, Qt.Key.Key_Down)
        self.assertEqual(view._current_takeoffs["t1"].position, [0.0, 1.0, 10.0, 1.0])

    def test_arrow_keys_move_in_placement_and_rotate_modes_only_when_allowed(self):
        for mode, moves in (
            ("select", True),
            ("place", True),
            ("annotation_place", True),
            ("rotate", True),
            ("pan", False),
            ("zoom", False),
        ):
            with self.subTest(mode=mode):
                view = self._key_view()
                view._cursor_mode = mode
                event = self._press(view, Qt.Key.Key_Right)
                self.assertEqual(event.accepted, moves)
                self.assertEqual(
                    view._current_takeoffs["t1"].position,
                    [1.0, 0.0, 11.0, 0.0] if moves else [0.0, 0.0, 10.0, 0.0],
                )

    def test_arrow_keys_do_not_move_without_selection_edit_access_or_items(self):
        cases = {
            "selection disabled": lambda v: setattr(v, "_selection_enabled", False),
            "editing disabled": lambda v: setattr(v, "_editing_enabled", False),
            "nothing selected": lambda v: setattr(v, "_selected_uids", set()),
        }
        for name, disable in cases.items():
            with self.subTest(name):
                view = self._key_view()
                leases = []
                view.request_geometry_edit_lease = (
                    lambda uids: leases.append(uids) or True
                )
                disable(view)
                event = self._press(view, Qt.Key.Key_Right)
                self.assertEqual(leases, [])
                self.assertFalse(event.accepted)
                self.assertEqual(
                    view._current_takeoffs["t1"].position, [0.0, 0.0, 10.0, 0.0]
                )
                self.assertFalse(view._keyboard_move_dirty)

    def test_key_release_of_non_arrow_keys_and_idle_arrows_is_not_consumed(self):
        view = self._key_view()
        view._keyboard_move_dirty = False
        for key in (Qt.Key.Key_Right, Qt.Key.Key_A):
            event = FakeKeyEvent(key)
            view.keyReleaseEvent(event)
            self.assertFalse(event.accepted)

    def test_each_arrow_release_flushes_pending_keyboard_move(self):
        for key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            with self.subTest(key=key):
                view = self._key_view()
                view._keyboard_move_dirty = True
                flushed = []
                view._flush_dirty_positions = lambda: flushed.append(1)
                event = FakeKeyEvent(key)
                view.keyReleaseEvent(event)
                self.assertTrue(event.accepted)
                self.assertEqual(flushed, [1])
                self.assertFalse(view._keyboard_move_dirty)

    def test_ctrl_release_clears_ctrl_state_and_refreshes_cursor(self):
        view = self._key_view()
        view._ctrl_held = True
        view.keyReleaseEvent(FakeKeyEvent(Qt.Key.Key_Control))
        self.assertFalse(view._ctrl_held)
        self.assertEqual(len(view.cursor_updates), 1)
        view = self._key_view()
        view._ctrl_held = True
        view.keyReleaseEvent(FakeKeyEvent(Qt.Key.Key_Control, auto_repeat=True))
        self.assertTrue(view._ctrl_held)
        self.assertEqual(view.cursor_updates, [])

    def test_arrow_move_skips_annotations_that_are_not_interactive_or_incomplete(self):
        view = self._make_view({"ok", "bogus", "short"})
        view._current_takeoffs = {}
        view._current_annotations = {
            "ok": BidAnnotation(
                uid="ok", annotation_type="rect", position=[0.0, 0.0, 10.0, 4.0]
            ),
            "bogus": BidAnnotation(
                uid="bogus", annotation_type="unknown", position=[0.0, 0.0, 5.0, 5.0]
            ),
            "short": BidAnnotation(
                uid="short", annotation_type="line", position=[1.0, 1.0]
            ),
        }
        view._uid_to_items = {
            "ok": [FakeItem()],
            "bogus": [FakeItem()],
            "short": [FakeItem()],
        }
        self.assertTrue(view._apply_position_keyboard_move(2.0, 0.0))
        self.assertEqual(
            view._current_annotations["ok"].position, [2.0, 0.0, 12.0, 4.0]
        )
        self.assertEqual(
            view._current_annotations["bogus"].position, [0.0, 0.0, 5.0, 5.0]
        )
        self.assertEqual(view._current_annotations["short"].position, [1.0, 1.0])
        self.assertEqual(set(view._dirty_ann_positions), {"ok"})
        self.assertEqual(view._position_before_edit, {"ok": [0.0, 0.0, 10.0, 4.0]})
        self.assertEqual(view._uid_to_items["bogus"][0].pos(), QtCore.QPointF(0.0, 0.0))

    def test_arrow_move_with_nothing_movable_reports_no_move(self):
        view = self._make_view({"ghost"})
        view._current_takeoffs = {}
        view._current_annotations = {}
        self.assertFalse(view._apply_position_keyboard_move(1.0, 0.0))
        self.assertFalse(view._keyboard_move_dirty)


class InputHandlerMixinCursorResolutionTests(_CtrlDragFixture):
    """InputHandlerMixin cursor precedence and viewport synchronization."""

    ZOOM = Qt.CursorShape.WhatsThisCursor
    OVERLAY = Qt.CursorShape.ForbiddenCursor
    ON_ITEM = QtCore.QPoint(5, 5)
    OFF_ITEM = QtCore.QPoint(100, 100)

    def _cursor_view(self, mode="select"):
        view = self._make_selected_path_takeoff_view()
        view._cursor_mode = mode
        view._zoom_cursor = self.ZOOM
        view._move_overlay_cursor = self.OVERLAY
        view._is_over_overlay_move_handle = lambda pos: pos == QtCore.QPoint(1, 1)
        view._ctrl_held = False
        view._advanced_mouse_controls_enabled = True
        return view

    @staticmethod
    def _buttons(buttons):
        return patch.object(
            input_handler_module,
            "QApplication",
            SimpleNamespace(mouseButtons=lambda: buttons),
        )

    def test_panning_shows_closed_hand_unless_right_pan_with_ctrl_zoom(self):
        view = self._cursor_view()
        view._panning = True
        self.assertEqual(
            view._resolve_cursor(self.OFF_ITEM), Qt.CursorShape.ClosedHandCursor
        )
        view._right_pan_active = True
        self.assertEqual(
            view._resolve_cursor(self.OFF_ITEM), Qt.CursorShape.ClosedHandCursor
        )
        view._ctrl_held = True
        self.assertEqual(view._resolve_cursor(self.OFF_ITEM), self.ZOOM)

    def test_active_rotation_drag_cursor_overrides_mode_cursors(self):
        for mode in ("select", "rotate", "zoom", "pan"):
            with self.subTest(mode=mode):
                view = self._cursor_view(mode)
                view._rotation_drag_active = True
                self.assertEqual(
                    view._resolve_cursor(self.ON_ITEM), view._rotate_cursor
                )

    def test_overlay_move_modes_use_overlay_cursor_only_over_the_handle(self):
        view = self._cursor_view("move_overlay")
        self.assertEqual(view._resolve_cursor(self.OFF_ITEM), self.OVERLAY)
        view = self._cursor_view("move_overlay_handle")
        self.assertEqual(view._resolve_cursor(QtCore.QPoint(1, 1)), self.OVERLAY)
        self.assertEqual(
            view._resolve_cursor(self.OFF_ITEM), Qt.CursorShape.ArrowCursor
        )

    def test_placement_modes_use_crosshair_even_over_selected_items(self):
        for mode in ("place", "annotation_place", "paste_backout"):
            with self.subTest(mode=mode):
                view = self._cursor_view(mode)
                self.assertEqual(
                    view._resolve_cursor(self.ON_ITEM), Qt.CursorShape.CrossCursor
                )

    def test_ctrl_zoom_press_uses_zoom_cursor(self):
        view = self._cursor_view()
        view._zoom_press_ctrl = True
        self.assertEqual(view._resolve_cursor(self.ON_ITEM), self.ZOOM)

    def test_active_left_press_uses_move_or_handle_cursor(self):
        view = self._cursor_view()
        far_handles = [QGraphicsRectItem(-4.0, -4.0, 8.0, 8.0) for _ in range(2)]
        for far_handle in far_handles:
            far_handle.setPos(300.0, 300.0)
        view._handle_infos = [
            SimpleNamespace(item=far_handles[0], cursor=Qt.CursorShape.SizeFDiagCursor),
            SimpleNamespace(item=far_handles[1], cursor=Qt.CursorShape.SizeVerCursor),
        ]
        view._select_band_origin = QtCore.QPointF(0.0, 0.0)
        with self._buttons(Qt.MouseButton.LeftButton):
            view._drag_handle_index = -1
            self.assertEqual(
                view._resolve_cursor(self.OFF_ITEM), Qt.CursorShape.SizeAllCursor
            )
            view._drag_handle_index = 1
            self.assertEqual(
                view._resolve_cursor(self.OFF_ITEM), Qt.CursorShape.SizeVerCursor
            )
            view._drag_handle_index = 5
            self.assertEqual(
                view._resolve_cursor(self.OFF_ITEM), Qt.CursorShape.ArrowCursor
            )
        with self._buttons(Qt.MouseButton.NoButton):
            view._drag_handle_index = -1
            self.assertEqual(
                view._resolve_cursor(self.OFF_ITEM), Qt.CursorShape.ArrowCursor
            )
        view._select_band_origin = None
        with self._buttons(Qt.MouseButton.LeftButton):
            self.assertFalse(view._has_active_cursor_press())
            self.assertEqual(
                view._resolve_cursor(self.OFF_ITEM), Qt.CursorShape.ArrowCursor
            )

    def test_held_ctrl_shows_zoom_cursor_only_for_advanced_non_rotate_modes(self):
        cases = (
            ("select", True, True, self.ZOOM),
            ("select", False, True, Qt.CursorShape.ArrowCursor),
            ("rotate", True, True, Qt.CursorShape.ArrowCursor),
            ("slope_rotate", True, True, Qt.CursorShape.ArrowCursor),
            ("select", True, False, Qt.CursorShape.ArrowCursor),
        )
        for mode, advanced, ctrl_held, expected in cases:
            with self.subTest(mode=mode, advanced=advanced, ctrl_held=ctrl_held):
                view = self._cursor_view(mode)
                view._advanced_mouse_controls_enabled = advanced
                view._ctrl_held = ctrl_held
                self.assertEqual(view._resolve_cursor(self.OFF_ITEM), expected)
        view = self._cursor_view()
        view._ctrl_held = True
        view._select_band_origin = QtCore.QPointF(0.0, 0.0)
        view._drag_handle_index = -1
        with self._buttons(Qt.MouseButton.LeftButton):
            self.assertEqual(
                view._resolve_cursor(self.OFF_ITEM), Qt.CursorShape.SizeAllCursor
            )

    def test_zoom_and_pan_modes_use_their_tool_cursors(self):
        self.assertEqual(
            self._cursor_view("zoom")._resolve_cursor(self.ON_ITEM), self.ZOOM
        )
        self.assertEqual(
            self._cursor_view("pan")._resolve_cursor(self.ON_ITEM),
            Qt.CursorShape.OpenHandCursor,
        )

    def test_rotate_modes_resolve_handle_select_and_missing_pointer_cursors(self):
        for mode in ("rotate", "slope_rotate"):
            with self.subTest(mode=mode):
                view = self._cursor_view(mode)
                view._rotate_handle_item = FakeItem(100.0, 100.0)
                self.assertEqual(view._resolve_cursor(None), Qt.CursorShape.ArrowCursor)
                self.assertEqual(
                    view._resolve_cursor(self.OFF_ITEM), view._rotate_cursor
                )
                self.assertEqual(
                    view._resolve_cursor(self.ON_ITEM), Qt.CursorShape.SizeAllCursor
                )

    def test_select_mode_without_pointer_uses_arrow(self):
        view = self._cursor_view()
        self.assertEqual(view._resolve_cursor(None), Qt.CursorShape.ArrowCursor)
        self.assertEqual(
            view._resolve_cursor(self.ON_ITEM), Qt.CursorShape.SizeAllCursor
        )

    def test_rotate_handle_hit_radius_is_sixteen_viewport_pixels_inclusive(self):
        view = self._cursor_view("rotate")
        view._rotate_handle_item = FakeItem(0.0, 0.0)
        for point, hit in (
            (QtCore.QPoint(16, 0), True),
            (QtCore.QPoint(0, -16), True),
            (QtCore.QPoint(17, 0), False),
            (QtCore.QPoint(12, 12), False),
            (QtCore.QPoint(11, 11), True),
            (None, False),
        ):
            with self.subTest(point=point):
                self.assertEqual(view._is_over_rotate_handle(point), hit)
        view._rotate_handle_item = None
        self.assertFalse(view._is_over_rotate_handle(QtCore.QPoint(0, 0)))

    def test_viewport_cursor_position_requires_pointer_inside_viewport(self):
        view = self._cursor_view()
        view.viewport = lambda: None
        self.assertIsNone(view._current_viewport_cursor_pos())
        view.viewport = lambda: FakeCursorViewport()
        for point, expected in (
            (QtCore.QPoint(50, 60), QtCore.QPoint(50, 60)),
            (QtCore.QPoint(250, 60), None),
            (QtCore.QPoint(50, 250), None),
        ):
            with self.subTest(point=point):
                with patch.object(
                    input_handler_module,
                    "QCursor",
                    SimpleNamespace(pos=lambda point=point: point),
                ):
                    self.assertEqual(view._current_viewport_cursor_pos(), expected)

    def test_update_cursor_prefers_explicit_then_live_then_last_pointer(self):
        view = self._cursor_view()
        viewport = FakeCursorViewport()
        view.viewport = lambda: viewport
        resolved = []
        view._resolve_cursor = (
            lambda pos: resolved.append(pos) or Qt.CursorShape.CrossCursor
        )
        view._last_mouse_vp_pos = QtCore.QPoint(1, 1)
        with patch.object(
            input_handler_module,
            "QCursor",
            SimpleNamespace(pos=lambda: QtCore.QPoint(60, 70)),
        ):
            InputHandlerMixin._update_cursor(view, QtCore.QPoint(9, 9))
            InputHandlerMixin._update_cursor(view)
        with patch.object(
            input_handler_module,
            "QCursor",
            SimpleNamespace(pos=lambda: QtCore.QPoint(900, 900)),
        ):
            InputHandlerMixin._update_cursor(view)
        self.assertEqual(
            resolved, [QtCore.QPoint(9, 9), QtCore.QPoint(60, 70), QtCore.QPoint(1, 1)]
        )
        self.assertEqual(viewport.cursor, Qt.CursorShape.CrossCursor)

    def _band_sync_view(self):
        view = self._make_view()
        view.geometry = []
        view._rubber_band = SimpleNamespace(setGeometry=view.geometry.append)
        view.cursor_updates = []
        view._update_cursor = lambda *a: view.cursor_updates.append(a)
        view._last_mouse_vp_pos = QtCore.QPoint(30, 40)
        return view

    def test_rubber_band_sync_follows_the_last_pointer_for_each_band_kind(self):
        view = self._band_sync_view()
        view._last_mouse_vp_pos = None
        view._select_band_active = True
        view._select_band_origin = QtCore.QPointF(5.0, 5.0)
        view._sync_rubber_band_to_viewport()
        self.assertEqual((view.geometry, view.cursor_updates), ([], []))
        view = self._band_sync_view()
        view._select_band_active = True
        view._select_band_origin = QtCore.QPointF(5.0, 6.0)
        view._sync_rubber_band_to_viewport()
        self.assertEqual(
            view.geometry,
            [QtCore.QRect(QtCore.QPoint(5, 6), QtCore.QPoint(30, 40)).normalized()],
        )
        self.assertEqual(view.cursor_updates, [])
        view = self._band_sync_view()
        view._rubber_band_origin = QtCore.QPointF(50.0, 60.0)
        view._sync_rubber_band_to_viewport()
        self.assertEqual(
            view.geometry,
            [QtCore.QRect(QtCore.QPoint(50, 60), QtCore.QPoint(30, 40)).normalized()],
        )
        self.assertEqual(view.cursor_updates, [])
        view = self._band_sync_view()
        view._sync_rubber_band_to_viewport()
        self.assertEqual(view.geometry, [])
        self.assertEqual(view.cursor_updates, [()])


class AnnotationRotationHelperTests(unittest.TestCase):
    """Module-level annotation rotation helpers of input_handler."""

    def assertSequenceAlmostEqual(self, actual, expected):
        self.assertEqual(len(actual), len(expected), (actual, expected))
        for actual_value, expected_value in zip(actual, expected):
            self.assertAlmostEqual(actual_value, expected_value, places=9)

    def test_ink_prefix_helpers_strip_and_accumulate_the_rotation_prefix(self):
        strip = input_handler_module._ink_strip_prefix
        add = input_handler_module._ink_add_prefix
        self.assertEqual(strip([0.5, 1.0, 2.0, 3.0, 4.0]), [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(strip([1.0, 2.0, 3.0, 4.0]), [1.0, 2.0, 3.0, 4.0])
        self.assertSequenceAlmostEqual(
            add([9.0, 8.0], [0.5, 1.0, 2.0], 90.0), [0.5 + math.pi / 2.0, 9.0, 8.0]
        )
        self.assertSequenceAlmostEqual(
            add([9.0, 8.0], [1.0, 2.0], 90.0), [math.pi / 2.0, 9.0, 8.0]
        )

    def test_trailing_rotation_helper_accumulates_or_appends(self):
        update = input_handler_module._update_ann_trailing_rotation
        stored = [0.0, 0.0, 10.0, 0.0, 0.25]
        update(stored, 90.0)
        self.assertSequenceAlmostEqual(
            stored, [0.0, 0.0, 10.0, 0.0, 0.25 + math.pi / 2.0]
        )
        unrotated = [0.0, 0.0, 10.0, 0.0]
        update(unrotated, 90.0)
        self.assertSequenceAlmostEqual(unrotated, [0.0, 0.0, 10.0, 0.0, math.pi / 2.0])

    def test_compact_box_rotation_expands_to_rotated_corners_and_angle(self):
        rotate = input_handler_module._rotate_compact_box_annotation
        self.assertSequenceAlmostEqual(
            rotate([0.0, 0.0, 10.0, 4.0], 90.0, 20.0, 20.0),
            [36.0, 10.0, 40.0, 0.0, 40.0, 10.0, 36.0, 0.0, math.pi / 2.0],
        )
        rotated = rotate([0.0, 0.0, 10.0, 4.0, math.radians(30.0)], 90.0, 20.0, 20.0)
        self.assertAlmostEqual(rotated[-1], math.radians(120.0))

        def turn(point, degrees, center):
            radians = math.radians(degrees)
            dx, dy = point[0] - center[0], point[1] - center[1]
            return (
                center[0] + dx * math.cos(radians) - dy * math.sin(radians),
                center[1] + dx * math.sin(radians) + dy * math.cos(radians),
            )

        for index, source in enumerate(
            [(10.0, 4.0), (0.0, 0.0), (10.0, 0.0), (0.0, 4.0)]
        ):
            expected = turn(turn(source, 30.0, (5.0, 2.0)), 90.0, (20.0, 20.0))
            self.assertAlmostEqual(rotated[index * 2], expected[0], places=9)
            self.assertAlmostEqual(rotated[index * 2 + 1], expected[1], places=9)
        corners = list(zip(rotated[0:8:2], rotated[1:8:2]))
        self.assertAlmostEqual(sum(x for x, _y in corners) / 4.0, 38.0)
        self.assertAlmostEqual(sum(y for _x, y in corners) / 4.0, 5.0)
        ring = [corners[0], corners[3], corners[1], corners[2]]
        side_lengths = sorted(
            round(math.dist(ring[index], ring[(index + 1) % 4]), 6)
            for index in range(4)
        )
        self.assertEqual(side_lengths, [4.0, 4.0, 10.0, 10.0])

    def test_compact_box_rotation_rejects_non_box_geometry(self):
        rotate = input_handler_module._rotate_compact_box_annotation
        self.assertIsNone(rotate([0.0, 0.0, 10.0, 0.0, 10.0, 10.0], 90.0, 0.0, 0.0))
        self.assertIsNone(
            rotate([0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0, 0.5], 90.0, 0.0, 0.0)
        )

    def test_rotating_text_and_callout_moves_only_anchor_and_stored_angle(self):
        for annotation_type in ("text", ANNOTATION_TYPE_CALLOUT):
            with self.subTest(annotation_type=annotation_type):
                ann = BidAnnotation(uid="a", annotation_type=annotation_type)
                self.assertSequenceAlmostEqual(
                    input_handler_module._rotate_annotation(
                        ann, [10.0, 10.0, 40.0, 20.0], 90.0, 0.0, 0.0
                    ),
                    [-10.0, 10.0, 40.0, 20.0, math.pi / 2.0],
                )
                self.assertSequenceAlmostEqual(
                    input_handler_module._rotate_annotation(
                        ann, [10.0, 10.0, 40.0, 20.0, 0.5], 90.0, 0.0, 0.0
                    ),
                    [-10.0, 10.0, 40.0, 20.0, 0.5 + math.pi / 2.0],
                )

    def test_rotating_ink_rotates_points_and_accumulates_prefix(self):
        ann = BidAnnotation(uid="a", annotation_type="ink")
        self.assertSequenceAlmostEqual(
            input_handler_module._rotate_annotation(
                ann, [0.25, 10.0, 20.0, 30.0, 40.0], 90.0, 0.0, 0.0
            ),
            [0.25 + math.pi / 2.0, -20.0, 10.0, -40.0, 30.0],
        )
        self.assertSequenceAlmostEqual(
            input_handler_module._rotate_annotation(
                ann, [10.0, 20.0, 30.0, 40.0], 90.0, 0.0, 0.0
            ),
            [math.pi / 2.0, -20.0, 10.0, -40.0, 30.0],
        )

    def test_rotating_rect_and_highlight_expands_compact_boxes_only(self):
        for annotation_type in ("rect", "highlight"):
            with self.subTest(annotation_type=annotation_type):
                ann = BidAnnotation(uid="a", annotation_type=annotation_type)
                compact = input_handler_module._rotate_annotation(
                    ann, [0.0, 0.0, 10.0, 4.0], 90.0, 20.0, 20.0
                )
                self.assertEqual(len(compact), 9)
                expanded = input_handler_module._rotate_annotation(
                    ann,
                    [0.0, 0.0, 10.0, 0.0, 10.0, 4.0, 0.0, 4.0, 0.5],
                    90.0,
                    0.0,
                    0.0,
                )
                self.assertSequenceAlmostEqual(
                    expanded,
                    [0.0, 0.0, 0.0, 10.0, -4.0, 10.0, -4.0, 0.0, 0.5 + math.pi / 2.0],
                )

    def test_rotating_generic_annotations_appends_angle_except_vertex_types(self):
        square = [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
        rotated_square = [0.0, 0.0, 0.0, 10.0, -10.0, 10.0, -10.0, 0.0]
        for annotation_type in ("polygon", "cloud"):
            with self.subTest(annotation_type=annotation_type):
                ann = BidAnnotation(uid="a", annotation_type=annotation_type)
                self.assertSequenceAlmostEqual(
                    input_handler_module._rotate_annotation(
                        ann, square, 90.0, 0.0, 0.0
                    ),
                    rotated_square,
                )
        hotlink = BidAnnotation(uid="a", annotation_type="hotlink")
        self.assertSequenceAlmostEqual(
            input_handler_module._rotate_annotation(
                hotlink, [10.0, 0.0], 90.0, 0.0, 0.0
            ),
            [0.0, 10.0],
        )
        for annotation_type in ("line", "oval"):
            with self.subTest(annotation_type=annotation_type):
                ann = BidAnnotation(uid="a", annotation_type=annotation_type)
                self.assertSequenceAlmostEqual(
                    input_handler_module._rotate_annotation(
                        ann, [10.0, 0.0, 20.0, 0.0], 90.0, 0.0, 0.0
                    ),
                    [0.0, 10.0, 0.0, 20.0, math.pi / 2.0],
                )


class InputHandlerMixinApplyRotationTests(_CtrlDragFixture):
    """InputHandlerMixin._apply_single_rotation/_apply_multi_rotation."""

    def _rotation_view(self, selected):
        view = self._make_transform_view(selected)
        view.position_flushes = []
        view._flush_dirty_positions = lambda: view.position_flushes.append(
            (dict(view._dirty_positions), dict(view._dirty_ann_positions))
        )
        view.rotation_flushes = []
        view._flush_dirty_rotations = lambda: view.rotation_flushes.append(
            dict(view._dirty_rotations)
        )
        view._dirty_ann_positions = {}
        return view

    def assertPositionAlmostEqual(self, actual, expected):
        self.assertEqual(len(actual), len(expected), (actual, expected))
        for actual_value, expected_value in zip(actual, expected):
            self.assertAlmostEqual(actual_value, expected_value, places=9)

    def _annotation_rotation_view(self, annotation_type, position):
        view = self._rotation_view(set())
        annotation = BidAnnotation(
            uid="a1", annotation_type=annotation_type, position=list(position)
        )
        view._current_takeoffs = {}
        view._current_annotations = {"a1": annotation}
        view._selected_uids = {"a1"}
        view._rotation_drag_orig_positions = {"a1": list(position)}
        return view, annotation

    def test_single_annotation_rotates_around_its_element_center(self):
        view, annotation = self._annotation_rotation_view("rect", [0.0, 0.0, 10.0, 4.0])
        view._element_center = lambda uid, cs, mode: (
            (5.0, 2.0) if mode == "ost" else None
        )
        view._apply_single_rotation("a1", 90.0)
        expected = [3.0, 7.0, 7.0, -3.0, 7.0, 7.0, 3.0, -3.0, math.pi / 2.0]
        self.assertPositionAlmostEqual(annotation.position, expected)
        self.assertEqual(view._position_before_edit["a1"], [0.0, 0.0, 10.0, 4.0])
        self.assertEqual(
            view._dirty_ann_positions, {"a1": ("rect", annotation.position)}
        )
        self.assertEqual(len(view.position_flushes), 1)

    def test_single_annotation_without_element_center_rotates_about_first_point(self):
        view, annotation = self._annotation_rotation_view("rect", [0.0, 0.0, 10.0, 4.0])
        view._element_center = lambda uid, cs, mode: None
        view._apply_single_rotation("a1", 90.0)
        self.assertPositionAlmostEqual(
            annotation.position,
            [-4.0, 10.0, 0.0, 0.0, 0.0, 10.0, -4.0, 0.0, math.pi / 2.0],
        )

    def test_single_non_rotatable_annotation_is_left_untouched(self):
        view, annotation = self._annotation_rotation_view("hotlink", [10.0, 20.0])
        view._element_center = lambda uid, cs, mode: self.fail("must not measure")
        view._apply_single_rotation("a1", 90.0)
        self.assertEqual(annotation.position, [10.0, 20.0])
        self.assertEqual(view._dirty_ann_positions, {})
        self.assertEqual(view.position_flushes, [])
        self.assertEqual(view._position_before_edit, {})

    def test_single_count_rotation_adds_angle_and_records_rotation_edit(self):
        view = self._rotation_view({"count"})
        view._rotation_drag_orig_positions = {"count": [30.0, 5.0]}
        view._rotation_drag_orig_rotations = {"count": 0.5}
        view._apply_single_rotation("count", 90.0)
        takeoff = view._current_takeoffs["count"]
        self.assertAlmostEqual(takeoff.rotation, 0.5 + math.pi / 2.0)
        self.assertEqual(takeoff.position, [30.0, 5.0])
        self.assertEqual(view._rotation_before_edit, {"count": 0.5})
        self.assertEqual(view._dirty_rotations, {"count": takeoff.rotation})
        self.assertEqual(view.rotation_flushes, [{"count": takeoff.rotation}])
        self.assertEqual(view._dirty_positions, {})

    def test_single_linear_rotation_pivots_on_midpoint_and_flushes_positions(self):
        view = self._rotation_view({"linear"})
        view._rotation_drag_orig_positions = {"linear": [12.0, 2.0, 22.0, 2.0]}
        view._apply_single_rotation("linear", 90.0)
        takeoff = view._current_takeoffs["linear"]
        self.assertPositionAlmostEqual(takeoff.position, [17.0, -3.0, 17.0, 7.0])
        self.assertEqual(view._position_before_edit["linear"], [12.0, 2.0, 22.0, 2.0])
        self.assertEqual(view._dirty_positions, {"linear": takeoff.position})
        self.assertEqual(len(view.position_flushes), 1)
        self.assertEqual(view.flushed_transform_groups, [])

    def test_single_curved_linear_rotation_uses_curved_pivot(self):
        view = self._rotation_view({"linear"})
        original = [0.0, 0.0, 20.0, 0.0, 10.0, 8.0, -8.0]
        takeoff = view._current_takeoffs["linear"]
        takeoff.position = list(original)
        takeoff.curve = Takeoff.CURVE_ENABLED
        view._rotation_drag_orig_positions = {"linear": list(original)}
        view._apply_single_rotation("linear", 90.0)
        curved = rotate_position_coords_for_test(
            original, 90.0, False, True, True, view._linear_geom
        )
        straight = rotate_position_coords_for_test(
            original, 90.0, False, False, True, view._linear_geom
        )
        self.assertNotEqual(curved, straight)
        self.assertPositionAlmostEqual(takeoff.position, curved)

    def test_single_area_rotation_rotates_children_about_parent_centroid(self):
        view = self._rotation_view({"area"})
        original = list(view._current_takeoffs["area"].position)
        hole_position = [2.0, 2.0, 4.0, 2.0, 4.0, 4.0, 2.0, 4.0]
        view._current_takeoffs["hole"] = Takeoff(
            uid="hole", condition_uid="area", parent_uid="area", position=hole_position
        )
        view._rotation_drag_orig_positions = {"area": list(original)}
        view._apply_single_rotation("area", 90.0)
        centroid = input_handler_module.polygon_centroid(original, 4)
        expected_hole = input_handler_module.rotate_points_around(
            hole_position, 90.0, *centroid
        )
        self.assertPositionAlmostEqual(
            view._current_takeoffs["hole"].position, expected_hole
        )
        self.assertEqual(view._position_before_edit["hole"], hole_position)
        self.assertEqual(view._position_before_edit["area"], original)
        self.assertEqual(set(view._dirty_positions), {"area", "hole"})
        self.assertEqual(view._dirty_rotations, {})
        self.assertEqual(len(view.position_flushes), 1)
        self.assertEqual(view.flushed_transform_groups, [])

    def test_area_rotation_with_attachment_child_flushes_position_and_rotation_group(
        self,
    ):
        view = self._rotation_view({"area"})
        original = list(view._current_takeoffs["area"].position)
        view._current_takeoffs["attachment"].parent_uid = "area"
        attachment_rotation = view._current_takeoffs["attachment"].rotation
        view._rotation_drag_orig_positions = {"area": list(original)}
        view._apply_single_rotation("area", 90.0)
        attachment = view._current_takeoffs["attachment"]
        self.assertAlmostEqual(attachment.rotation, attachment_rotation + math.pi / 2.0)
        self.assertEqual(view.position_flushes, [])
        self.assertEqual(len(view.flushed_transform_groups), 1)
        position_changes, rotation_changes = view.flushed_transform_groups[0]
        self.assertEqual(
            {uid for uid, _o, _n in position_changes}, {"area", "attachment"}
        )
        self.assertEqual(
            rotation_changes, [("attachment", attachment_rotation, attachment.rotation)]
        )

    def test_area_children_rotation_skips_degenerate_parent_and_excluded_children(self):
        view = self._rotation_view({"area"})
        view._current_takeoffs["hole"] = Takeoff(
            uid="hole",
            condition_uid="area",
            parent_uid="area",
            position=[2.0, 2.0, 4.0, 2.0, 4.0, 4.0, 2.0, 4.0],
        )
        view._rotate_area_children("area", [0.0, 0.0, 10.0, 0.0], 90.0)
        self.assertEqual(view._dirty_positions, {})
        parent_position = list(view._current_takeoffs["area"].position)
        view._rotate_area_children("area", parent_position, 90.0, {"hole"})
        self.assertEqual(view._dirty_positions, {})
        view._rotate_area_children("area", parent_position, 90.0)
        self.assertEqual(set(view._dirty_positions), {"hole"})

    def test_area_children_rotate_point_orientation_for_count_and_attachment_only(self):
        for child_uid, rotates in (
            ("count", True),
            ("attachment", True),
            ("linear", False),
        ):
            with self.subTest(child_uid=child_uid):
                view = self._rotation_view({"area"})
                child = view._current_takeoffs[child_uid]
                child.parent_uid = "area"
                before = child.rotation
                view._rotate_area_children(
                    "area", list(view._current_takeoffs["area"].position), 90.0
                )
                if rotates:
                    self.assertAlmostEqual(child.rotation, before + math.pi / 2.0)
                    self.assertEqual(view._rotation_before_edit, {child_uid: before})
                    self.assertEqual(view._dirty_rotations, {child_uid: child.rotation})
                else:
                    self.assertEqual(child.rotation, before)
                    self.assertEqual(view._dirty_rotations, {})
                self.assertIn(child_uid, view._dirty_positions)

    def test_single_hole_rotation_is_rejected_and_restores_preview_when_invalid(self):
        for valid in (False, True):
            with self.subTest(valid=valid):
                view = self._rotation_view({"hole"})
                hole = Takeoff(
                    uid="hole",
                    condition_uid="area",
                    parent_uid="area",
                    position=[2.0, 2.0, 4.0, 2.0, 4.0, 4.0, 2.0, 4.0],
                )
                view._current_takeoffs["hole"] = hole
                item = QGraphicsPathItem()
                item.setRotation(20.0)
                item.setTransformOriginPoint(3.0, 3.0)
                view._uid_to_items = {"hole": [item]}
                view._rotation_drag_orig_positions = {"hole": list(hole.position)}
                view._validate_hole_position = (
                    lambda takeoff, position, valid=valid: valid
                )
                calls = []
                view.update_selection_visuals = lambda *a, **k: calls.append("visuals")
                view._create_rotate_handle = lambda uid: calls.append(("handle", uid))
                view._apply_single_rotation("hole", 90.0)
                if valid:
                    self.assertEqual(calls, [])
                    self.assertEqual(set(view._dirty_positions), {"hole"})
                    self.assertEqual(item.rotation(), 20.0)
                else:
                    self.assertEqual(calls, ["visuals", ("handle", "hole")])
                    self.assertEqual(
                        hole.position, [2.0, 2.0, 4.0, 2.0, 4.0, 4.0, 2.0, 4.0]
                    )
                    self.assertEqual(view._dirty_positions, {})
                    self.assertEqual(item.rotation(), 0.0)
                    self.assertEqual(
                        item.transformOriginPoint(), QtCore.QPointF(0.0, 0.0)
                    )

    def _multi_rotation_view(self, selected):
        view = self._rotation_view(selected)
        view._rotate_ost_center = (20.0, 5.0)
        view._rotation_drag_orig_positions = {
            uid: list(view._current_takeoffs[uid].position) for uid in selected
        }
        view._rotation_drag_orig_rotations = {
            uid: view._current_takeoffs[uid].rotation for uid in selected
        }
        return view

    def test_group_rotation_records_edits_and_flushes_one_transform_group(self):
        selected = {"linear", "count"}
        view = self._multi_rotation_view(selected)
        before_positions = {
            uid: list(view._current_takeoffs[uid].position) for uid in selected
        }
        before_rotation = view._current_takeoffs["count"].rotation
        view._apply_multi_rotation(90.0)
        expected_linear = input_handler_module.rotate_points_around(
            before_positions["linear"], 90.0, 20.0, 5.0
        )
        expected_count = input_handler_module.rotate_points_around(
            before_positions["count"], 90.0, 20.0, 5.0
        )
        self.assertPositionAlmostEqual(
            view._current_takeoffs["linear"].position, expected_linear
        )
        self.assertPositionAlmostEqual(
            view._current_takeoffs["count"].position, expected_count
        )
        self.assertAlmostEqual(
            view._current_takeoffs["count"].rotation, before_rotation + math.pi / 2.0
        )
        self.assertEqual(view._current_takeoffs["linear"].rotation, 0.0)
        self.assertEqual(len(view.flushed_transform_groups), 1)
        position_changes, rotation_changes = view.flushed_transform_groups[0]
        self.assertEqual(
            {uid: old for uid, old, _new in position_changes}, before_positions
        )
        self.assertEqual(
            rotation_changes,
            [("count", before_rotation, view._current_takeoffs["count"].rotation)],
        )

    def test_group_rotation_rotates_selected_annotations_and_skips_fixed_ones(self):
        view = self._multi_rotation_view(set())
        rect = BidAnnotation(
            uid="rect", annotation_type="rect", position=[0.0, 0.0, 10.0, 4.0]
        )
        hotlink = BidAnnotation(
            uid="hot", annotation_type="hotlink", position=[10.0, 20.0]
        )
        view._current_takeoffs = {}
        view._current_annotations = {"rect": rect, "hot": hotlink}
        view._selected_uids = {"rect", "hot"}
        view._rotation_drag_orig_positions = {
            "rect": [0.0, 0.0, 10.0, 4.0],
            "hot": [10.0, 20.0],
        }
        view._apply_multi_rotation(90.0)
        self.assertEqual(len(rect.position), 9)
        self.assertEqual(view._dirty_ann_positions, {"rect": ("rect", rect.position)})
        self.assertEqual(hotlink.position, [10.0, 20.0])
        self.assertEqual(len(view.flushed_transform_groups), 1)

    def test_group_rotation_of_a_fixed_annotation_alone_flushes_nothing(self):
        view = self._multi_rotation_view(set())
        hotlink = BidAnnotation(
            uid="hot", annotation_type="hotlink", position=[10.0, 20.0]
        )
        view._current_takeoffs = {}
        view._current_annotations = {"hot": hotlink}
        view._selected_uids = {"hot"}
        view._rotation_drag_orig_positions = {"hot": [10.0, 20.0]}
        view._apply_multi_rotation(90.0)
        self.assertEqual(view.flushed_transform_groups, [])
        self.assertEqual(view._dirty_ann_positions, {})

    def test_group_rotation_carries_unselected_area_children_and_their_orientation(
        self,
    ):
        view = self._multi_rotation_view({"area"})
        child = view._current_takeoffs["count"]
        child.parent_uid = "area"
        child_rotation = child.rotation
        child_before = list(child.position)
        view._apply_multi_rotation(90.0)
        self.assertPositionAlmostEqual(
            child.position,
            input_handler_module.rotate_points_around(child_before, 90.0, 20.0, 5.0),
        )
        self.assertAlmostEqual(child.rotation, child_rotation + math.pi / 2.0)
        position_changes, rotation_changes = view.flushed_transform_groups[0]
        self.assertEqual(
            {uid: old for uid, old, _n in position_changes}["count"], child_before
        )
        self.assertEqual({uid for uid, _o, _n in position_changes}, {"area", "count"})
        self.assertEqual(rotation_changes, [("count", child_rotation, child.rotation)])


def rotate_position_coords_for_test(
    position, degrees, is_area, is_curved, is_linear, geom
):
    return input_handler_module.rotate_position_coords(
        position, degrees, is_area, is_curved, is_linear, linear_geom=geom
    )


class InputHandlerMixinContextMenuActionTests(_CtrlDragFixture):
    """InputHandlerMixin.contextMenuEvent takeoff/background/overlay routing."""

    SIGNALS = (
        "assign_to_area_requested",
        "set_negative_requested",
        "set_curved_requested",
        "reassign_condition_requested",
    )

    def _menu_view(self, selected, *, edit_enabled=True):
        view = self._make_area_control_point_view(set(selected))
        for name in self.SIGNALS:
            setattr(view, name, FakeSignal())
        view._current_bid_ref = BidRef("db.mdb", "bid-1")
        view._current_page = Page(uid="page-1", name="Page")
        view.triggered_commands = []
        view._context_menu_command_trigger = view.triggered_commands.append
        view._context_menu_action_state = lambda key: {
            "enabled": edit_enabled,
            "checkable": key == "paste",
        }
        return view

    def _run_menu(self, view, choose=None, *, reassign=None, event_pos=(-100, -100)):
        CapturingMenu.instances = []
        CapturingMenu.action_text_to_return = choose
        reassign_patch = patch.object(
            input_handler_module,
            "add_reassign_condition_submenu",
            return_value=reassign,
        )
        style_patch = patch.object(
            input_handler_module,
            "add_selected_annotation_style_actions",
            return_value=SimpleNamespace(color_action=None, width_actions={}),
        )
        with patch.object(input_handler_module, "QMenu", CapturingMenu):
            with reassign_patch, style_patch:
                event = FakeContextMenuEvent(*event_pos)
                InputHandlerMixin.contextMenuEvent(view, event)
        self.assertTrue(event.accepted)
        return {
            action.text(): action
            for action in CapturingMenu.instances[0].actions
            if isinstance(action, QAction)
        }

    def test_takeoff_menu_shows_only_the_actions_for_the_selected_geometry(self):
        cases = (
            (
                {"linear1"},
                {
                    "Set as Curved Segment",
                    "Assign to Current Area",
                    "Count as Negative Quantity",
                },
            ),
            ({"area1"}, {"Assign to Current Area", "Count as Negative Quantity"}),
            (
                {"area1", "linear1"},
                {"Assign to Current Area", "Count as Negative Quantity"},
            ),
        )
        for selected, expected in cases:
            with self.subTest(selected=selected):
                actions = self._run_menu(self._menu_view(selected))
                shown = set(actions) & {
                    "Set as Curved Segment",
                    "Assign to Current Area",
                    "Count as Negative Quantity",
                }
                self.assertEqual(shown, expected)

    def test_hole_selection_offers_neither_assignment_nor_negative_quantity(self):
        view = self._make_area_control_point_view({"hole1"}, include_hole=True)
        for name in self.SIGNALS:
            setattr(view, name, FakeSignal())
        view._context_menu_action_state = lambda _key: {"enabled": True}
        actions = self._run_menu(view)
        self.assertFalse(
            set(actions)
            & {
                "Assign to Current Area",
                "Count as Negative Quantity",
                "Set as Curved Segment",
            }
        )

    def test_takeoff_property_actions_are_disabled_without_edit_access(self):
        view = self._menu_view({"linear1"}, edit_enabled=False)
        actions = self._run_menu(view)
        for text in (
            "Set as Curved Segment",
            "Assign to Current Area",
            "Count as Negative Quantity",
        ):
            self.assertFalse(actions[text].isEnabled(), text)
        view = self._menu_view({"linear1"})
        actions = self._run_menu(view)
        for text in (
            "Set as Curved Segment",
            "Assign to Current Area",
            "Count as Negative Quantity",
        ):
            self.assertTrue(actions[text].isEnabled(), text)

    def test_selected_menu_actions_emit_property_requests_for_selected_takeoffs(self):
        cases = (
            ("Assign to Current Area", "assign_to_area_requested", (["linear1"],)),
            (
                "Count as Negative Quantity",
                "set_negative_requested",
                (["linear1"], True),
            ),
            ("Set as Curved Segment", "set_curved_requested", (["linear1"], True)),
        )
        for text, signal, expected in cases:
            with self.subTest(text=text):
                view = self._menu_view({"linear1"})
                self._run_menu(view, choose=text)
                self.assertEqual(getattr(view, signal).emitted, [expected])
                for other in self.SIGNALS:
                    if other != signal:
                        self.assertEqual(getattr(view, other).emitted, [])

    def test_negative_and_curved_actions_toggle_from_the_current_state(self):
        view = self._menu_view({"linear1"})
        view._current_takeoffs["linear1"].is_negative = True
        view._current_takeoffs["linear1"].curve = Takeoff.CURVE_ENABLED
        actions = self._run_menu(view, choose="Count as Negative Quantity")
        self.assertTrue(actions["Count as Negative Quantity"].isChecked())
        self.assertTrue(actions["Set as Curved Segment"].isChecked())
        self.assertEqual(view.set_negative_requested.emitted, [(["linear1"], False)])
        view = self._menu_view({"linear1"})
        view._current_takeoffs["linear1"].curve = Takeoff.CURVE_ENABLED
        self._run_menu(view, choose="Set as Curved Segment")
        self.assertEqual(view.set_curved_requested.emitted, [(["linear1"], False)])

    def test_reassign_condition_choice_emits_selected_takeoffs_and_condition(self):
        view = self._menu_view({"linear1"})
        reassign_action = QAction("Other Condition")
        submenu = SimpleNamespace(actions={reassign_action: "other-condition"})

        class ReassignMenu(CapturingMenu):
            def exec(self, _pos):
                return reassign_action

        with patch.object(input_handler_module, "QMenu", ReassignMenu):
            with patch.object(
                input_handler_module,
                "add_reassign_condition_submenu",
                return_value=submenu,
            ) as add_submenu:
                InputHandlerMixin.contextMenuEvent(
                    view, FakeContextMenuEvent(-100, -100)
                )
        self.assertEqual(
            view.reassign_condition_requested.emitted,
            [(["linear1"], "other-condition")],
        )
        self.assertEqual(add_submenu.call_count, 1)
        self.assertEqual(add_submenu.call_args.kwargs, {"enabled": True})
        self.assertEqual(
            add_submenu.call_args.args[2],
            view._selected_takeoff_context_state().reassign_geometry_type,
        )
        self.assertIsNotNone(add_submenu.call_args.args[2])

    def test_takeoff_menu_choice_is_dropped_when_edit_access_is_lost(self):
        view = self._menu_view({"linear1"})
        access = {"enabled": True}
        view._context_menu_action_state = lambda _key: {"enabled": access["enabled"]}

        class RevokingMenu(CapturingMenu):
            def exec(self, _pos):
                access["enabled"] = False
                return next(
                    action
                    for action in self.actions
                    if isinstance(action, QAction)
                    and action.text() == "Set as Curved Segment"
                )

        with patch.object(input_handler_module, "QMenu", RevokingMenu):
            with patch.object(
                input_handler_module,
                "add_reassign_condition_submenu",
                return_value=None,
            ):
                InputHandlerMixin.contextMenuEvent(
                    view, FakeContextMenuEvent(-100, -100)
                )
        self.assertEqual(view.set_curved_requested.emitted, [])

    def test_takeoff_menu_choice_is_dropped_when_takeoff_object_is_replaced(self):
        view = self._menu_view({"linear1"})

        class ReplacingMenu(CapturingMenu):
            def exec(self, _pos):
                original = view._current_takeoffs["linear1"]
                view._current_takeoffs["linear1"] = Takeoff(
                    uid="linear1",
                    condition_uid="linear",
                    page_uid="page-1",
                    position=list(original.position),
                )
                return next(
                    action
                    for action in self.actions
                    if isinstance(action, QAction)
                    and action.text() == "Count as Negative Quantity"
                )

        with patch.object(input_handler_module, "QMenu", ReplacingMenu):
            with patch.object(
                input_handler_module,
                "add_reassign_condition_submenu",
                return_value=None,
            ):
                InputHandlerMixin.contextMenuEvent(
                    view, FakeContextMenuEvent(-100, -100)
                )
        self.assertEqual(view.set_negative_requested.emitted, [])

    def test_dismissed_takeoff_menu_emits_nothing_and_resets_ctrl_state(self):
        view = self._menu_view({"linear1"})
        view.ctrl_resets = []
        view.reset_ctrl_held = lambda: view.ctrl_resets.append(1)
        self._run_menu(view, choose=None)
        self.assertEqual(view.ctrl_resets, [1])
        for name in self.SIGNALS:
            self.assertEqual(getattr(view, name).emitted, [])

    def test_background_menu_offers_paste_through_the_owned_command_path(self):
        view = self._menu_view(set())
        actions = self._run_menu(view, choose="Paste")
        self.assertIn("Paste", actions)
        self.assertTrue(actions["Paste"].isCheckable())
        self.assertTrue(actions["Paste"].isEnabled())
        actions["Paste"].trigger()
        self.assertEqual(view.triggered_commands, ["paste"])
        view._current_page = Page(uid="page-1", name="Replacement")
        actions["Paste"].trigger()
        self.assertEqual(view.triggered_commands, ["paste"])

    def test_pdf_text_menu_offers_copy_state_and_paste(self):
        view = self._menu_view(set())
        view.has_selected_pdf_text = lambda: True
        view._selected_pdf_text_selection = object()
        view.copied = []
        view.copy_selected_pdf_text = lambda: view.copied.append(1) or True
        actions = self._run_menu(view)
        self.assertEqual(
            [text for text in actions if text in ("Copy", "Paste")], ["Copy", "Paste"]
        )
        self.assertTrue(actions["Copy"].isEnabled())
        actions["Copy"].trigger()
        self.assertEqual(view.copied, [1])
        view._selected_pdf_text_selection = object()
        actions["Copy"].trigger()
        self.assertEqual(view.copied, [1])
        view = self._menu_view(set())
        view.has_selected_pdf_text = lambda: False
        view._selected_pdf_text_selection = None
        actions = self._run_menu(view)
        self.assertNotIn("Copy", actions)

    def _overlay_menu_view(self, current_mode):
        view = self._menu_view(set())
        view._current_page = Page(
            uid="page-1", name="Page", image_show_mode=current_mode
        )
        overlay_action = QAction("Show Overlay Image")
        overlay_action.setCheckable(True)
        original_action = QAction("Show Original Image")
        original_action.setCheckable(True)
        view.overlay_actions = (overlay_action, original_action)
        view._add_common_context_submenus = lambda menu: (
            current_mode,
            overlay_action,
            original_action,
        )
        return view, overlay_action, original_action

    def test_overlay_menu_choice_triggers_image_mode_command_only_on_change(self):
        cases = (
            ("overlay", 0, True, "show_overlay_image"),
            ("overlay", 0, False, None),
            ("original", 2, False, "show_original_image"),
            ("original", 2, True, None),
        )
        for target, mode, checked, command in cases:
            with self.subTest(target=target, mode=mode, checked=checked):
                view, overlay_action, original_action = self._overlay_menu_view(mode)
                chosen = overlay_action if target == "overlay" else original_action
                chosen.setChecked(checked)

                class ChoosingMenu(CapturingMenu):
                    def exec(self, _pos, chosen=chosen):
                        return chosen

                with patch.object(input_handler_module, "QMenu", ChoosingMenu):
                    InputHandlerMixin.contextMenuEvent(
                        view, FakeContextMenuEvent(-100, -100)
                    )
                self.assertEqual(view.triggered_commands, [command] if command else [])

    def test_disabled_overlay_action_choice_triggers_nothing(self):
        view, overlay_action, _original_action = self._overlay_menu_view(0)
        overlay_action.setChecked(True)
        overlay_action.setEnabled(False)

        class ChoosingMenu(CapturingMenu):
            def exec(self, _pos):
                return overlay_action

        with patch.object(input_handler_module, "QMenu", ChoosingMenu):
            InputHandlerMixin.contextMenuEvent(view, FakeContextMenuEvent(-100, -100))
        self.assertEqual(view.triggered_commands, [])

    def test_overlay_choice_is_dropped_when_menu_owner_changes_during_exec(self):
        view, overlay_action, _original_action = self._overlay_menu_view(0)
        overlay_action.setChecked(True)

        class ReplacingMenu(CapturingMenu):
            def exec(self, _pos):
                view._current_page = Page(uid="page-1", name="Replacement")
                return overlay_action

        with patch.object(input_handler_module, "QMenu", ReplacingMenu):
            InputHandlerMixin.contextMenuEvent(view, FakeContextMenuEvent(-100, -100))
        self.assertEqual(view.triggered_commands, [])

    def test_right_pan_and_suppression_flags_swallow_the_context_menu(self):
        for right_pan, suppressed in ((True, False), (False, True)):
            with self.subTest(right_pan=right_pan, suppressed=suppressed):
                view = self._menu_view({"linear1"})
                view._right_pan_active = right_pan
                view._suppress_next_context_menu = suppressed
                CapturingMenu.instances = []
                with patch.object(input_handler_module, "QMenu", CapturingMenu):
                    event = FakeContextMenuEvent(-100, -100)
                    InputHandlerMixin.contextMenuEvent(view, event)
                self.assertTrue(event.accepted)
                self.assertEqual(CapturingMenu.instances, [])
                self.assertFalse(view._suppress_next_context_menu)

    def test_control_point_target_replaces_selection_before_menu_is_built(self):
        view = self._menu_view({"linear1"})
        view.selection_events = []
        view._flush_dirty_positions = lambda: view.selection_events.append("flush")
        view._on_selection_changed = lambda: view.selection_events.append("changed")
        view.update_selection_visuals = lambda *a, **k: view.selection_events.append(
            "visuals"
        )
        actions = self._run_menu(view, event_pos=(50.0, 0.0))
        self.assertEqual(view._selected_uids, {"area1"})
        self.assertEqual(view.selection_events, ["flush", "changed", "visuals"])
        self.assertIn("Add Control Point", actions)
        view = self._menu_view({"area1"})
        view.selection_events = []
        view._flush_dirty_positions = lambda: view.selection_events.append("flush")
        view._on_selection_changed = lambda: view.selection_events.append("changed")
        self._run_menu(view, event_pos=(50.0, 0.0))
        self.assertEqual(view.selection_events, [])
