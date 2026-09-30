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
    ANNOTATION_TYPE_CLOUD,
    ANNOTATION_TYPE_DIMENSION,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_POLYGON,
    BidAnnotation,
)
from ost_visualizer.domain.entities.config import Config
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
                position=[0, 0, 10, 0],
                rotation=0.0,
            ),
        }
        self._rotation_drag_uid = ""
        self._rotation_drag_orig_rotations = {}
        self._rotation_before_edit = {}
        self._dirty_rotations = {}
        self.flushed_rotations = []

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


class InputHandlerMixinFlipSelectedTakeoffsTests(_CtrlDragFixture):
    """InputHandlerMixin.flip_selected_takeoffs."""

    def test_each_takeoff_type_flips_about_its_complete_footprint(self):
        for uid in ("linear", "count", "area", "attachment"):
            for horizontal in (True, False):
                with self.subTest(uid=uid, horizontal=horizontal):
                    view = self._make_transform_view({uid})
                    before = self._rendered_takeoff_selection_bounds(view, {uid})
                    view.flip_selected_takeoffs(horizontal)
                    after = self._rendered_takeoff_selection_bounds(view, {uid})
                    self._assert_bounds_almost_equal(before, after)

    def test_every_pairwise_type_flip_preserves_group_bounds(self):
        takeoff_types = ("linear", "count", "area", "attachment")
        for selected in combinations(takeoff_types, 2):
            for horizontal in (True, False):
                with self.subTest(selected=selected, horizontal=horizontal):
                    view = self._make_transform_view(set(selected))
                    before = self._rendered_takeoff_selection_bounds(view, selected)
                    view.flip_selected_takeoffs(horizontal)
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
                    view.rotate_selected_takeoffs(degrees)
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
                    view.rotate_selected_takeoffs(degrees)
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
