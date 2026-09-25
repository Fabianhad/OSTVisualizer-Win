import unittest
from unittest.mock import patch
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.modes.cursor import (
    CURSOR_MODE_ANNOTATION_PLACE,
    CURSOR_MODE_PLACE,
)
from ost_visualizer.presentation.utils.annotation_defaults import (
    PLACEABLE_ANNOTATION_TYPES,
)
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest
from shiboken6 import delete, isValid
from tests.test_viewer_sync_coordinator_overlay_refresh import (
    FakeAnnotationRenderer,
    FakeColorService,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakeRenderingService,
    FakeTakeoffRenderer,
)


class AnnotationPlacementKeyboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        errors = []
        hook = patch("sys.excepthook", side_effect=lambda *error: errors.append(error))
        hook.start()
        self.addCleanup(hook.stop)
        self.addCleanup(lambda: self.assertEqual(errors, []))

    def make_view(self, *, detached=False):
        window = QtWidgets.QMainWindow()
        view = TakeoffPlanView(
            color_service=FakeColorService(),
            rendering_service=FakeRenderingService(),
            load_coordinator=FakeLoadCoordinator(),
            takeoff_renderer=FakeTakeoffRenderer(),
            annotation_renderer=FakeAnnotationRenderer(),
            linear_geometry=FakeLinearGeometry(),
        )
        self.addCleanup(lambda: delete(window) if isValid(window) else None)
        if detached:
            window.setCentralWidget(view)
            view.set_annotation_only_selection(True)
        else:
            stack = QtWidgets.QStackedWidget()
            stack.addWidget(view)
            window.setCentralWidget(stack)
        view.set_editing_enabled(True)
        view.set_selection_enabled(True)
        view._current_bid_page_uid = "p1"
        view._snap_increments = 1.0
        view.setSceneRect(0, 0, 2000, 2000)
        window.resize(480, 360)
        window.show()
        self.app.setActiveWindow(window)
        view.setFocus()
        view.centerOn(1000, 1000)
        self.assertTrue(view.hasFocus())
        return view

    def project_annotation(self, view, annotation_type, position, properties=None):
        # Stand in for successful persistence/projection at the placement signal;
        # retain the real Plan selection, focus, keyboard and flush implementations.
        annotation = BidAnnotation(
            uid="1",
            annotation_type=annotation_type,
            page_uid="p1",
            position=list(position),
            properties=properties or {},
        )
        key = "annotation:1"
        item = QtWidgets.QGraphicsRectItem(0, 0, 20, 10)
        item.setData(0, key)
        view._scene.addItem(item)
        view._uid_to_items[key] = [item]
        view._current_annotations[key] = annotation
        view._ann_db_uid_map[key] = annotation.uid
        view.set_selected_uids({key})
        return annotation, item

    def scroll_position(self, view):
        return view.horizontalScrollBar().value(), view.verticalScrollBar().value()

    def assert_nudge(self, view, annotation, item):
        original = list(annotation.position)
        original_item_position = item.pos()
        scroll = self.scroll_position(view)
        changes = []
        view.positions_flushed.connect(lambda *args: changes.append(args))
        for key, dx, dy in (
            (QtCore.Qt.Key.Key_Right, 1, 0),
            (QtCore.Qt.Key.Key_Down, 0, 1),
            (QtCore.Qt.Key.Key_Left, -1, 0),
            (QtCore.Qt.Key.Key_Up, 0, -1),
        ):
            before = list(annotation.position)
            expected = list(before)
            start = 1 if annotation.is_ink and len(before) % 2 else 0
            end = 2 if annotation.is_text else len(before) - len(before) % 2 + start
            for index in range(start, end, 2):
                expected[index] += dx
                expected[index + 1] += dy
            QTest.keyPress(view, key)
            self.assertEqual(self.scroll_position(view), scroll)
            self.assertEqual(annotation.position, expected)
            self.assertEqual(view._selected_uids, {"annotation:1"})
            self.assertTrue(view.hasFocus())
            count = len(changes)
            QTest.keyRelease(view, key)
            self.assertEqual(len(changes), count + 1)
            self.assertEqual(
                changes[-1], ([], [("1", annotation.annotation_type, before, expected)])
            )
        self.assertEqual(annotation.position, original)
        self.assertEqual(item.pos(), original_item_position)

    def test_dimension_mouse_placement_then_arrows_nudge_without_scrolling(self):
        for detached in (False, True):
            with self.subTest(detached=detached):
                view = self.make_view(detached=detached)
                created = []
                view.annotation_created.connect(
                    lambda kind, position, page: created.append(
                        self.project_annotation(view, kind, position)
                    )
                )
                self.assertTrue(view.activate_annotation_placement("dimension"))
                QTest.mousePress(
                    view.viewport(),
                    QtCore.Qt.MouseButton.LeftButton,
                    pos=QtCore.QPoint(100, 100),
                )
                QTest.mouseRelease(
                    view.viewport(),
                    QtCore.Qt.MouseButton.LeftButton,
                    pos=QtCore.QPoint(180, 140),
                )
                self.assertEqual(len(created), 1)
                self.assertEqual(view._cursor_mode, CURSOR_MODE_ANNOTATION_PLACE)
                self.assert_nudge(view, *created[0])

    def test_every_movable_annotation_after_placement(self):
        positions = {
            "arrow": [10, 20, 40, 60],
            "callout": [10, 20, 40, 60],
            "cloud": [10, 20, 40, 20, 40, 60],
            "dimension": [10, 20, 40, 60],
            "highlight": [10, 20, 40, 60],
            "hotlink": [10, 20],
            "ink": [0.25, 10, 20, 40, 60, 70, 80],
            "line": [10, 20, 40, 60],
            "namedview": [10, 20, 40, 20, 40, 60, 10, 60],
            "oval": [10, 20, 40, 60],
            "polygon": [10, 20, 40, 20, 40, 60],
            "rect": [10, 20, 40, 60],
            "text": [10, 20, 40, 60, 0.25],
        }
        self.assertEqual(set(positions), BidAnnotation.INTERACTIVE_TYPES)
        for detached in (False, True):
            for kind, position in positions.items():
                with self.subTest(detached=detached, kind=kind):
                    view = self.make_view(detached=detached)
                    # Callouts can be moved but have no placement tool.
                    tool = kind if kind in PLACEABLE_ANNOTATION_TYPES else "arrow"
                    self.assertTrue(view.activate_annotation_placement(tool))
                    annotation, item = self.project_annotation(view, kind, position)
                    self.assert_nudge(view, annotation, item)

    def test_no_selection_still_scrolls_in_annotation_placement_mode(self):
        view = self.make_view()
        self.assertTrue(view.activate_annotation_placement("dimension"))
        before = self.scroll_position(view)
        QTest.keyClick(view, QtCore.Qt.Key.Key_Right)
        self.assertGreater(view.horizontalScrollBar().value(), before[0])
        self.assertEqual(view.verticalScrollBar().value(), before[1])

    def test_placement_completion_for_every_annotation_tool(self):
        for kind in sorted(PLACEABLE_ANNOTATION_TYPES):
            with self.subTest(kind=kind):
                view = self.make_view()
                created = []

                def complete(annotation_type, position, properties=None):
                    created.append(
                        self.project_annotation(
                            view, annotation_type, position, properties
                        )
                    )
                    if annotation_type in {"text", "namedview", "hotlink"}:
                        self.assertTrue(
                            view.activate_annotation_placement(annotation_type)
                        )

                view.annotation_created.connect(
                    lambda annotation_type, position, page: complete(
                        annotation_type, position
                    )
                )
                view.text_annotation_created.connect(
                    lambda position, page, props: complete("text", position, props)
                )
                view.named_view_created.connect(
                    lambda position, page, props: complete("namedview", position, props)
                )
                view.hotlink_placement_requested.connect(
                    lambda position, page: complete("hotlink", position)
                )
                self.assertTrue(view.activate_annotation_placement(kind))
                if kind == "hotlink":
                    QTest.mouseClick(
                        view.viewport(),
                        QtCore.Qt.MouseButton.LeftButton,
                        pos=QtCore.QPoint(100, 100),
                    )
                else:
                    position = [10, 20, 40, 60]
                    if kind in {"polygon", "cloud"}:
                        position = [10, 20, 40, 20, 40, 60]
                    self.assertTrue(view._commit_annotation_placement(kind, position))
                    if kind in {"text", "namedview"}:
                        item = view._active_inline_text_item()
                        item.setPlainText("Example")
                        cursor = item.textCursor()
                        cursor.setPosition(0)
                        item.setTextCursor(cursor)
                        before = item.pos()
                        QTest.keyClick(view, QtCore.Qt.Key.Key_Right)
                        self.assertEqual(item.textCursor().position(), 1)
                        self.assertEqual(item.pos(), before)
                        self.assertEqual(created, [])
                        view._finish_active_inline_text_edit(commit=True)
                self.assertEqual(len(created), 1)
                self.assertFalse(view.is_text_annotation_inline_edit_active())
                self.assertEqual(view._cursor_mode, CURSOR_MODE_ANNOTATION_PLACE)
                self.assert_nudge(view, *created[0])

    def test_pending_geometry_lease_prevents_nudge_and_scroll(self):
        view = self.make_view()
        self.assertTrue(view.activate_annotation_placement("dimension"))
        annotation, _item = self.project_annotation(view, "dimension", [10, 20, 40, 60])
        view.set_geometry_edit_lease_pending({"annotation:1"})
        requests = []
        view.geometry_edit_lease_requested.connect(requests.append)
        before = self.scroll_position(view)
        QTest.keyClick(view, QtCore.Qt.Key.Key_Right)
        self.assertEqual(annotation.position, [10, 20, 40, 60])
        self.assertEqual(self.scroll_position(view), before)
        self.assertEqual(requests, [["annotation:1"]])
        self.assertEqual(view._dirty_ann_positions, {})

    def test_takeoff_still_nudges_in_takeoff_placement_mode(self):
        view = self.make_view()
        takeoff = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", position=[10, 20, 40, 60]
        )
        view._current_takeoffs = {"t1": takeoff}
        view._selected_uids = {"t1"}
        view._cursor_mode = CURSOR_MODE_PLACE
        changes = []
        view.positions_flushed.connect(lambda *args: changes.append(args))
        before = self.scroll_position(view)
        QTest.keyClick(view, QtCore.Qt.Key.Key_Right)
        self.assertEqual(takeoff.position, [11, 20, 41, 60])
        self.assertEqual(self.scroll_position(view), before)
        self.assertEqual(changes, [([("t1", [10, 20, 40, 60], [11, 20, 41, 60])], [])])


if __name__ == "__main__":
    unittest.main()
