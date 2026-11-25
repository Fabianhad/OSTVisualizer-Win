import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QPointF, Qt
from ost_visualizer.application.dtos.create_condition_spec_dto import (
    CreateConditionSpec,
)
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.presentation.components.plan_view.components import (
    input_handler as input_handler_module,
)
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
from ost_visualizer.presentation.coordinators.viewer_sync_coordinator import (
    ViewerSyncCoordinator,
)
from ost_visualizer.presentation.handlers.plan_view_action_handler import (
    PlanViewActionHandler,
)
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.managers.deferred_persistence_manager import (
    DeferredPersistenceManager,
)
from ost_visualizer.presentation.services.undo_redo_service import UndoRedoService
from tests.integration.ai_takeoff.access_app_support import (
    configured_app,
    run_in_access_child,
    temporary_home,
)
import tests.helpers.mdb.schema_support as access

ANNOTATION_TABLES = ("BidALines", "BidAnnotationPolygons")


def _seed(path: Path) -> dict:
    if not access.DatabaseCreator().create_database(path, "ContextDelete"):
        raise AssertionError("Access database creation failed")
    connections = access.MdbConnectionManager()
    try:
        writer = access.MdbWriter(connections)
        db = str(path)
        bid = writer.create_bid(
            db,
            None,
            {
                "job_name": "Context delete",
                "pages": [
                    {
                        "name": "P1",
                        "width": 42.0,
                        "height": 30.0,
                        "scale_factor1": 1.0,
                        "scale_factor2": 1.0,
                        "index": 1,
                    }
                ],
            },
        )
        page = str(sorted(access.MdbReader(connections).get_bid_data(db, bid)[3])[0])

        def condition(name, condition_type, **extra):
            return writer.insert_condition(
                db,
                bid,
                CreateConditionSpec(name=name, condition_type=condition_type, **extra),
            )

        area = condition("Area", Condition.TYPE_AREA)
        backout = condition("Backout", Condition.TYPE_AREA, backout=True)
        linear = condition("Linear", Condition.TYPE_LINEAR)
        count = condition("Count", Condition.TYPE_COUNT)
        a1, a2, l1, c1 = writer.insert_takeoffs(
            db,
            bid,
            [
                InsertTakeoffSpec(area, page, "0", [2, 2, 12, 2, 12, 10, 2, 10]),
                InsertTakeoffSpec(area, page, "0", [20, 2, 30, 2, 30, 10, 20, 10]),
                InsertTakeoffSpec(linear, page, "0", [2, 14, 12, 14]),
                InsertTakeoffSpec(count, page, "0", [20, 14]),
            ],
        )
        (b1,) = writer.insert_takeoffs(
            db,
            bid,
            [
                InsertTakeoffSpec(
                    backout, page, "0", [4, 4, 8, 4, 8, 8, 4, 8], parent_uid=str(a1)
                )
            ],
        )
        writer.insert_annotations(
            db,
            bid,
            [
                InsertAnnotationSpec(page, "line", [32, 12, 40, 12], "#00ff00", 2.0),
                InsertAnnotationSpec(
                    page, "polygon", [32, 16, 40, 16, 36, 22], "#0000ff", 2.0
                ),
            ],
        )
        return {
            "bid": str(bid),
            "page": page,
            "takeoffs": {
                "A1": str(a1),
                "A2": str(a2),
                "L1": str(l1),
                "C1": str(c1),
                "B1": str(b1),
            },
        }
    finally:
        connections.close()


def _rows(path: Path) -> dict:
    connection = access._connect_mdb(path)
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT [UID] FROM [BidTakeoffs]")
        rows = {"takeoffs": sorted(str(row[0]) for row in cursor.fetchall())}
        for table in ANNOTATION_TABLES:
            cursor.execute(f"SELECT [UID] FROM [{table}]")
            rows[table] = sorted(str(row[0]) for row in cursor.fetchall())
        return rows
    finally:
        connection.close()


class _UiState:
    def __init__(self, bid_ref, page_uid):
        self._bid_ref = bid_ref
        self.active_page_uid = page_uid
        self.state = SimpleNamespace(
            display_mode_2d="condition",
            display_mode_3d="condition",
            display_modes_synced=True,
            grayscale_enabled=False,
        )
        self.place_condition_uid = None
        self.place_condition_uids = []
        self.highlighted_condition_uids = set()

    def get_selected_bid_ref(self):
        return self._bid_ref

    def set_highlighted_conditions(self, uids):
        self.highlighted_condition_uids = set(uids)


class _AllowAll:
    @staticmethod
    def is_allowed(_feature):
        return True


class _PageBar:
    @staticmethod
    def get_current_area_uid():
        return "0"


class ContextMenuDeleteKeepsSelectionTests(unittest.TestCase):
    """Real plan view, renderers, handler, write services and Access database."""

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _plan(self, container, bid_ref, page_uid):
        color = container.get("color_service")
        coordinates = container.get("coordinate_transformer_factory").create()
        renderers = container.get("infrastructure_provider").create_plan_view_renderers(
            coordinates, color
        )
        plan = TakeoffPlanView(
            color,
            renderers.rendering_service,
            renderers.load_coordinator,
            renderers.takeoff_renderer,
            renderers.annotation_renderer,
            renderers.linear_geometry,
            renderers.prefetch_coordinator,
        )
        plan.resize(1200, 900)
        plan.set_selection_enabled(True)
        plan.set_editing_enabled(True)
        plan.show()
        ui_state = _UiState(bid_ref, page_uid)
        data = container.get("project_data_service")
        event_bus = container.get("event_bus")
        sync = ViewerSyncCoordinator(
            ui_state_manager=ui_state,
            ui_access_manager=None,
            color_service=color,
            project_data=data,
            callback_bridge=SimpleNamespace(
                dispatch=lambda callback, payload: callback(payload)
            ),
        )
        sync.plan_view = plan
        undo = UndoRedoService(event_bus=event_bus)
        undo.set_active_bid(bid_ref)
        write = container.get("project_write_service")
        handler = PlanViewActionHandler(
            plan_view=plan,
            ui_state_manager=ui_state,
            project_data_svc=data,
            project_write_svc=write,
            annotation_write_svc=container.get("annotation_write_service"),
            page_settings_bar=_PageBar(),
            undo_svc=undo,
            event_bus=event_bus,
            ui_access_manager=_AllowAll(),
            deferred_persistence_manager=DeferredPersistenceManager(
                write, container.get("sql_workspace_state_service")
            ),
        )
        handler.connect_signals()
        for event in (AppEvents.TAKEOFFS_CHANGED, AppEvents.ANNOTATIONS_CHANGED):
            event_bus.subscribe(event, lambda **_event: sync.update_plan_view(page_uid))
        sync.update_plan_view(page_uid)
        self.app.processEvents()

        def delete_from_main_window():
            window = SimpleNamespace(
                tab_widget=SimpleNamespace(currentIndex=lambda: TAB_INDEX_TAKEOFF),
                ui_access_manager=_AllowAll(),
                plan_view=plan,
            )
            window._handle_inline_text_shortcut = (
                lambda key: MainWindow._handle_inline_text_shortcut(window, key)
            )
            MainWindow._delete_selected(window)

        plan.set_context_menu_command_handlers(
            lambda key: delete_from_main_window() if key == "delete" else None,
            lambda key: {
                "enabled": True,
                "checkable": False,
                "checked": False,
                "text": {"delete": "Delete"}.get(key, key.title()),
            },
        )
        return plan

    @staticmethod
    def _control_point(plan, uid, kind):
        rect = QtCore.QRectF()
        for item in plan._uid_to_items.get(uid, []):
            rect = rect.united(item.sceneBoundingRect())
        for i in range(81):
            for j in range(81):
                scene = QPointF(
                    rect.left() + rect.width() * i / 80,
                    rect.top() + rect.height() * j / 80,
                )
                viewport = plan.mapFromScene(scene)
                target = plan.polygon_control_point_target_at(plan.mapToScene(viewport))
                if (
                    target is not None
                    and target.plan_item_uid == uid
                    and target.kind == kind
                ):
                    return viewport
        raise AssertionError(f"no {kind} target for {uid}")

    def _ctrl_a_then_menu_delete(self, plan, target):
        plan.setFocus()
        QtWidgets.QApplication.sendEvent(
            plan,
            QtGui.QKeyEvent(
                QtCore.QEvent.Type.KeyPress,
                Qt.Key.Key_A,
                Qt.KeyboardModifier.ControlModifier,
                "a",
            ),
        )
        self.app.processEvents()
        selected = set(plan._selected_uids)
        selection_in_menu = []
        deleted = []
        plan.elements_deleted.connect(lambda uids: deleted.append(set(uids)))

        def choose_delete(menu, _position):
            selection_in_menu.append(set(plan._selected_uids))
            action = next(a for a in menu.actions() if a.text() == "Delete")
            action.trigger()
            return action

        viewport = plan.viewport()
        with patch.object(
            input_handler_module, "exec_transient_menu", side_effect=choose_delete
        ):
            QtWidgets.QApplication.sendEvent(
                viewport,
                QtGui.QContextMenuEvent(
                    QtGui.QContextMenuEvent.Reason.Mouse,
                    target,
                    viewport.mapToGlobal(target),
                ),
            )
        self.app.processEvents()
        return selected, selection_in_menu, deleted

    def test_ctrl_a_then_delete_from_an_edge_or_vertex_menu_deletes_everything(self):
        if run_in_access_child(self):
            return
        cases = (
            ("area edge", "A2", "edge"),
            ("area vertex", "A2", "vertex"),
            ("polygon annotation edge", "polygon", "edge"),
            ("polygon annotation vertex", "polygon", "vertex"),
        )
        for label, owner, kind in cases:
            with self.subTest(
                label
            ), temporary_home() as home, tempfile.TemporaryDirectory(
                ignore_cleanup_errors=True
            ) as folder:
                db_path = Path(folder) / "context_delete.mdb"
                ids = _seed(db_path)
                self.assertEqual(len(_rows(db_path)["takeoffs"]), 5)
                with configured_app(Path(home), db_path, ids["bid"]) as (
                    container,
                    bid_ref,
                ):
                    plan = self._plan(container, bid_ref, ids["page"])
                    try:
                        uid = (
                            ids["takeoffs"][owner]
                            if owner in ids["takeoffs"]
                            else next(
                                key
                                for key, annotation in plan._current_annotations.items()
                                if annotation.annotation_type == owner
                            )
                        )
                        target = self._control_point(plan, uid, kind)
                        selected, in_menu, deleted = self._ctrl_a_then_menu_delete(
                            plan, target
                        )
                        self.assertEqual(len(selected), 7)
                        self.assertIn(uid, selected)
                        self.assertEqual(in_menu, [selected])
                        self.assertEqual(deleted, [selected])
                        self.assertEqual(plan._current_takeoffs, {})
                        self.assertEqual(plan._current_annotations, {})
                    finally:
                        plan.cleanup()
                        plan.close()
                self.assertEqual(
                    _rows(db_path),
                    {"takeoffs": [], "BidALines": [], "BidAnnotationPolygons": []},
                )


if __name__ == "__main__":
    unittest.main()
