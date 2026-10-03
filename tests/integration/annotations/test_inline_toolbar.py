import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.hotlink_dto import HotlinkDto
from ost_visualizer.application.services.page_load_strategy_service import (
    LoadStrategy,
    PageLoadStrategyService,
)
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
from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
from ost_visualizer.presentation.coordinators.toolbar_state_coordinator import (
    ToolbarStateCoordinator,
)
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
    FakeTakeoffRenderer,
)


class PlanInlineTextToolbarWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def test_tool_dropdown_color_changes_default_without_mutating_annotations(self):
        from ost_visualizer.presentation.utils.annotation_defaults import (
            build_placed_annotation_spec,
            get_annotation_style_for_tool,
            set_annotation_style_for_tool,
        )
        from ost_visualizer.presentation.utils.annotation_style_controls import (
            create_annotation_style_button,
        )

        view = self._make_plan_view()
        selected = BidAnnotation(
            uid="a1",
            annotation_type="rect",
            position=[1.0, 2.0, 13.0, 14.0],
            color="#ff0000",
            width=4.0,
        )
        other = BidAnnotation(
            uid="a2",
            annotation_type="rect",
            position=[20.0, 22.0, 33.0, 34.0],
            color="#0000ff",
            width=5.0,
        )
        view._current_annotations = {"a1": selected, "a2": other}
        view._selected_uids = {"a1"}
        emitted = []
        view.annotation_styles_flushed.connect(lambda changes: emitted.extend(changes))
        original_style = get_annotation_style_for_tool("rect")
        set_annotation_style_for_tool("rect", color="#00aa00", line_width=6.0)
        button = create_annotation_style_button(
            view,
            lambda: get_annotation_style_for_tool("rect"),
            lambda color=None, line_width=None: set_annotation_style_for_tool(
                "rect", color=color, line_width=line_width
            ),
        )
        try:
            color_action = button.menu().actions()[-1]
            self.assertEqual(color_action.text(), "Select Color...")
            with patch.object(QColorDialog, "getColor", return_value=QColor("#445566")):
                color_action.trigger()
            self.assertEqual(get_annotation_style_for_tool("rect").color, "#445566")
            self.assertEqual(selected.color, "#ff0000")
            self.assertEqual(selected.width, 4.0)
            self.assertEqual(other.color, "#0000ff")
            self.assertEqual(other.width, 5.0)
            self.assertEqual(emitted, [])
            new_spec = build_placed_annotation_spec(
                "rect", "page-1", [0.0, 0.0, 20.0, 20.0]
            )
            self.assertEqual(new_spec.color, "#445566")
            self.assertEqual(new_spec.width, 6.0)
            # Positive control: the selection style channel the dropdown must
            # NOT drive is live, so the unchanged colours above are meaningful.
            view.apply_annotation_style_to_selection(color="#778899")
            self.assertEqual(selected.color, "#778899")
            self.assertEqual(other.color, "#0000ff")
            self.assertEqual(
                emitted, [("a1", "rect", {"Color": "#ff0000"}, {"Color": "#778899"})]
            )
        finally:
            set_annotation_style_for_tool(
                "rect", color=original_style.color, line_width=original_style.line_width
            )
            button.deleteLater()
            view.cleanup()

    def test_qt_double_click_keeps_main_surface_inline_text_editor_active(self):
        class InlineEditAccess:
            def __init__(self):
                self.inline_edit_active = False
                self.listeners = []

            def current_plan_surface_context(self):
                return object()

            def get_plan_surface_access(self, _context):
                return PlanSurfaceAccessState(
                    can_select_plan_items=not self.inline_edit_active,
                    can_edit_plan_items=not self.inline_edit_active,
                    can_edit_annotations=not self.inline_edit_active,
                    can_edit_annotation_text=True,
                )

            def is_allowed(self, feature):
                state = self.get_plan_surface_access(None)
                return {
                    Feature.SELECT_PLAN_ITEMS: state.can_select_plan_items,
                    Feature.EDIT_PLAN_ITEMS: state.can_edit_plan_items,
                    Feature.EDIT_ANNOTATION_TEXT: state.can_edit_annotation_text,
                }.get(feature, False)

            def subscribe_access_state_changed(self, callback):
                self.listeners.append(callback)

            def unsubscribe_access_state_changed(self, callback):
                self.listeners.remove(callback)

            def set_inline_edit_active(self, active):
                self.inline_edit_active = bool(active)
                for callback in list(self.listeners):
                    callback()

        class ToolbarUiState:
            selected_project_uid = None
            selected_file_path = "bid.mdb"
            selected_page_uids = ["page-1"]
            active_page_uid = "page-1"
            place_condition_uid = None

            def get_selected_bid_refs(self):
                return []

            def get_selected_bid_ref(self):
                return None

        class ToolbarProjectData:
            def get_bid_conditions(self):
                return {}

            def is_current_bid_locked(self):
                return False

        class TakeoffTab:
            def currentIndex(self):
                return TAB_INDEX_TAKEOFF

        view = self._make_plan_view()
        _annotation, item = self._add_text_annotation(
            view,
            position=[100.0, 100.0, 120.0, 40.0],
        )
        item.setPos(100.0, 100.0)
        view._current_bid_page_uid = "page-1"
        view._cursor_mode = CURSOR_MODE_SELECT
        view.setSceneRect(0.0, 0.0, 500.0, 350.0)
        view.resize(500, 350)
        access = InlineEditAccess()
        toolbar = ToolbarStateCoordinator(
            ToolbarUiState(),
            access,
            ToolbarProjectData(),
        )
        toolbar.set_tab_widget(TakeoffTab())
        toolbar.set_plan_view(view)
        toolbar.refresh()
        mode_changes = []

        def on_mode_changed(active):
            mode_changes.append(bool(active))
            access.set_inline_edit_active(active)

        view.text_annotation_edit_mode_changed.connect(on_mode_changed)
        view.show()
        QApplication.processEvents()
        target = view.mapFromScene(item.sceneBoundingRect().center())
        QtTest.QTest.mouseDClick(
            view.viewport(),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
            target,
        )
        QApplication.processEvents()
        self.assertTrue(view.is_text_annotation_inline_edit_active())
        self.assertEqual(view._editing_text_annotation_uid, "a1")
        self.assertEqual(view.get_selected_uids(), [])
        self.assertFalse(view._selection_enabled)
        self.assertTrue(view._condition_text_toolbar.isVisible())
        self.assertTrue(item.hasFocus())
        self.assertEqual(
            item.textInteractionFlags(),
            QtCore.Qt.TextInteractionFlag.TextEditorInteraction,
        )
        self.assertEqual(mode_changes, [True])
        self.assertTrue(access.get_plan_surface_access(None).can_edit_annotation_text)
        toolbar.cleanup()
        view.cleanup()
        view.close()

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
