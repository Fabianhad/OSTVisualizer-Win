import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.hotlink_dto import HotlinkDto
from ost_visualizer.application.services.page_load_strategy_service import (
    LoadStrategy,
    PageLoadStrategyService,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    DIMENSION_LABEL_ITEM_KIND,
    NAMED_VIEW_LABEL_BACKGROUND_ITEM_KIND,
    NAMED_VIEW_LABEL_ITEM_KIND,
    ClippedTextGraphicsItem,
    ImageBackgroundItem,
    TileGraphicsItem,
)
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
from ost_visualizer.presentation.controllers.menu_controller import MenuController
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.managers.ui_access_manager import (
    Feature,
    PlanSurfaceAccessState,
)
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
    FakeCoordinateSystem,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakeRenderingService,
    RecordingPathTakeoffRenderer,
)


class PlanSelectionSidebarWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def test_select_all_and_current_area_reproject_real_conditions_sidebar(self):
        conditions = {
            "linear": Condition(
                uid="linear",
                name="Linear",
                condition_type=Condition.TYPE_LINEAR,
                ref_no=1,
            ),
            "area": Condition(
                uid="area",
                name="Area",
                condition_type=Condition.TYPE_AREA,
                ref_no=2,
            ),
            "count": Condition(
                uid="count",
                name="Count",
                condition_type=Condition.TYPE_COUNT,
                ref_no=3,
            ),
            "attachment": Condition(
                uid="attachment",
                name="Attachment",
                condition_type=Condition.TYPE_ATTACHMENT,
                ref_no=4,
            ),
            "hidden": Condition(
                uid="hidden",
                name="Hidden",
                condition_type=Condition.TYPE_COUNT,
                layer_visible=False,
                ref_no=5,
            ),
        }
        rows = (
            ("1", "linear", "area-1"),
            ("2", "area", "area-1"),
            ("3", "count", "area-1"),
            ("4", "attachment", "area-1"),
            ("5", "linear", "area-1"),
            ("6", "hidden", "area-1"),
            ("7", "count", "area-2"),
            ("8", "attachment", "area-1"),
        )
        page_takeoffs = [
            Takeoff(
                uid=uid,
                condition_uid=condition_uid,
                page_uid="page-1",
                area_uid=area_uid,
                position=[float(index), 0.0, float(index + 1), 1.0],
            )
            for index, (uid, condition_uid, area_uid) in enumerate(rows)
        ]
        other_page_takeoff = Takeoff(
            uid="9",
            condition_uid="area",
            page_uid="page-2",
            area_uid="area-1",
            position=[0.0, 0.0, 1.0, 1.0],
        )
        all_takeoffs = [*page_takeoffs, other_page_takeoff]
        takeoff_by_uid = {takeoff.uid: takeoff for takeoff in all_takeoffs}
        view = TakeoffPlanView(
            color_service=FakeColorService(),
            rendering_service=FakeRenderingService(),
            load_coordinator=FakeLoadCoordinator(),
            takeoff_renderer=RecordingPathTakeoffRenderer(),
            annotation_renderer=FakeAnnotationRenderer(),
            linear_geometry=FakeLinearGeometry(),
        )
        self.addCleanup(delete, view)
        self.addCleanup(view.cleanup)
        view.set_selection_enabled(True)
        page = Page(uid="page-1", name="Page 1")
        self.assertTrue(
            view.load_page(
                page,
                page_takeoffs,
                conditions,
                {uid: "#000000" for uid in conditions},
                page_area_selections={page.uid: "area-1"},
            )
        )
        view.set_pending_mutation_uids({"8"})
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        sidebar.load_conditions(conditions, {}, "Project")
        sidebar.resize(420, 320)
        sidebar.show()
        sidebar.tree.setFocus()

        class UiState:
            def __init__(self):
                self.highlighted_condition_uids = set()

            def set_highlighted_conditions(self, uids):
                self.highlighted_condition_uids = set(uids)

            @staticmethod
            def get_selected_bid_ref():
                return None

        class Placement:
            def __init__(self):
                self.is_active = False
                self.condition_uid = None

            def enter(self, condition_uid, _condition_uids):
                self.is_active = True
                self.condition_uid = condition_uid
                return True

            def force_exit(self):
                self.is_active = False
                self.condition_uid = None

        class Toolbar:
            @staticmethod
            def refresh():
                pass

            @staticmethod
            def is_takeoff_2d_view_active():
                return True

            @staticmethod
            def set_select_checked():
                pass

        ui_state = UiState()
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = ui_state
        coordinator.project_data = SimpleNamespace(
            get_all_takeoffs=lambda: all_takeoffs,
            get_bid_conditions=lambda: conditions,
        )
        coordinator.conditions_sidebar = sidebar
        coordinator.plan_view = view
        coordinator.opengl_viewer = None
        coordinator._mesh_window = None
        coordinator._placement = Placement()
        coordinator._toolbar = Toolbar()
        coordinator._tab_widget = SimpleNamespace(
            currentIndex=lambda: TAB_INDEX_TAKEOFF
        )
        coordinator._nav = SimpleNamespace(is_refreshing=False)
        coordinator._selected_takeoff_uids = ()
        coordinator._selection_projected_condition_uids = set()
        coordinator.main_window = SimpleNamespace()
        selection_events = []
        view.takeoff_selection_changed.connect(
            lambda uids: selection_events.append(("changed", tuple(sorted(uids))))
        )
        view.takeoff_selection_command_applied.connect(
            lambda uids: selection_events.append(("command", tuple(sorted(uids))))
        )
        view.takeoff_selection_changed.connect(
            coordinator._on_takeoff_selection_changed
        )
        view.takeoff_selection_command_applied.connect(
            coordinator._on_takeoff_selection_command_applied
        )
        condition_events = []
        sidebar.condition_selected.connect(condition_events.append)
        sidebar.condition_selected.connect(coordinator._on_condition_selected)

        class Access:
            @staticmethod
            def is_allowed(feature):
                return feature is Feature.SELECT_PLAN_ITEMS

        class SelectAllAction:
            _select_all = MainWindow._select_all

            @staticmethod
            def _handle_inline_text_shortcut(_action_key):
                return False

        select_all_action = SelectAllAction()
        select_all_action.tab_widget = SimpleNamespace(
            currentIndex=lambda: TAB_INDEX_TAKEOFF
        )
        select_all_action.ui_access_manager = Access()
        select_all_action.plan_view = view
        select_all_action.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(refresh_toolbar=lambda: None)
        )

        class CurrentAreaAction:
            _select_objects_in_current_area = (
                MenuController._select_objects_in_current_area
            )

            @staticmethod
            def _current_area_selection_context():
                return SimpleNamespace(
                    plan_view=view,
                    area_uid="area-1",
                    parent=sidebar,
                )

        current_area_action = CurrentAreaAction()
        current_area_action.ui_access_manager = Access()
        current_area_action.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(refresh_toolbar=lambda: None)
        )

        def represented_conditions():
            return {
                takeoff_by_uid[uid].condition_uid
                for uid in view.get_selected_takeoff_uids()
            }

        def assert_projection(expected_uids, expected_conditions):
            self.assertEqual(set(view.get_selected_takeoff_uids()), expected_uids)
            self.assertEqual(represented_conditions(), expected_conditions)
            self.assertEqual(
                set(sidebar.get_selected_condition_uids()), expected_conditions
            )
            self.assertEqual(ui_state.highlighted_condition_uids, expected_conditions)

        # Model an active condition restored during file/bid/page activation and
        # invoke the real Main Window handler before draining queued UI work.
        coordinator.highlight_sidebar({"linear"})
        select_all_action._select_all()
        all_selected = {"1", "2", "3", "4", "5", "7"}
        represented = {"linear", "area", "count", "attachment"}
        assert_projection(all_selected, represented)
        self.assertEqual(
            selection_events,
            [
                ("changed", tuple(sorted(all_selected))),
                ("command", tuple(sorted(all_selected))),
            ],
        )
        condition_count = len(condition_events)
        self.app.processEvents()
        assert_projection(all_selected, represented)
        self.assertEqual(len(condition_events), condition_count)
        # A real sidebar click replaces the multi-row projection without
        # changing the already selected plan objects.
        linear_item = sidebar._condition_items["linear"]
        sidebar.tree.scrollToItem(linear_item)
        self.app.processEvents()
        QtTest.QTest.mouseClick(
            sidebar.tree.viewport(),
            QtCore.Qt.MouseButton.LeftButton,
            pos=sidebar.tree.visualItemRect(linear_item).center(),
        )
        self.app.processEvents()
        self.assertEqual(sidebar.get_selected_condition_uids(), ["linear"])
        self.assertEqual(set(view.get_selected_takeoff_uids()), all_selected)
        coordinator._placement.force_exit()
        view.set_cursor_mode(CURSOR_MODE_SELECT)
        # The IDs are unchanged, so only the explicit command notification is
        # expected. It must nevertheless reclaim and repair the projection.
        event_count = len(selection_events)
        condition_count = len(condition_events)
        select_all_action._select_all()
        self.assertEqual(
            selection_events[event_count:],
            [("command", tuple(sorted(all_selected)))],
        )
        assert_projection(all_selected, represented)
        self.app.processEvents()
        assert_projection(all_selected, represented)
        self.assertEqual(len(condition_events), condition_count)
        coordinator.highlight_sidebar({"linear"})
        current_area_action._select_objects_in_current_area()
        area_selected = {"1", "2", "3", "4", "5"}
        assert_projection(area_selected, represented)
        self.app.processEvents()
        assert_projection(area_selected, represented)
        # Select All following another command and a same-page refresh must use
        # the same canonical projection, including its unchanged-selection path.
        select_all_action._select_all()
        assert_projection(all_selected, represented)
        coordinator.highlight_sidebar({"linear"})
        sidebar.load_conditions(conditions, {}, "Project")
        self.assertTrue(
            view.load_page(
                page,
                page_takeoffs,
                conditions,
                {uid: "#000000" for uid in conditions},
                page_area_selections={page.uid: "area-1"},
            )
        )
        self.assertEqual(sidebar.get_selected_condition_uids(), ["linear"])
        select_all_action._select_all()
        self.app.processEvents()
        assert_projection(all_selected, represented)
