import unittest
from unittest.mock import patch
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import delete, isValid
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    NAMED_VIEW_LABEL_ITEM_KIND,
)
from tests.test_viewer_sync_coordinator_overlay_refresh import (
    FakeAnnotationRenderer,
    FakeColorService,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakeRenderingService,
    FakeTakeoffRenderer,
)


class NamedViewInlineLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.qt_errors = []
        exception_hook = patch(
            "sys.excepthook", side_effect=lambda *error: self.qt_errors.append(error)
        )
        exception_hook.start()
        self.addCleanup(exception_hook.stop)
        self.addCleanup(lambda: self.assertEqual(self.qt_errors, []))
        self.view = TakeoffPlanView(
            color_service=FakeColorService(),
            rendering_service=FakeRenderingService(),
            load_coordinator=FakeLoadCoordinator(),
            takeoff_renderer=FakeTakeoffRenderer(),
            annotation_renderer=FakeAnnotationRenderer(),
            linear_geometry=FakeLinearGeometry(),
        )
        self.addCleanup(lambda: delete(self.view) if isValid(self.view) else None)
        self.view.set_editing_enabled(True)
        self.view.set_selection_enabled(True)
        self.changes = []
        self.view.annotation_text_properties_flushed.connect(self.changes.extend)
        self.label = self.add_named_view()
        self.assertTrue(self.view._begin_named_view_rename("nv1"))

    def add_named_view(self):
        annotation = BidAnnotation(
            uid="nv1",
            annotation_type="namedview",
            page_uid="p1",
            properties={"Text": "Before"},
        )
        label = QtWidgets.QGraphicsTextItem("Before")
        label.setData(0, "nv1")
        label.setData(2, NAMED_VIEW_LABEL_ITEM_KIND)
        self.view._scene.addItem(label)
        self.view._uid_to_items = {"nv1": [label]}
        self.view._takeoff_items = [label]
        self.view._current_annotations = {"nv1": annotation}
        return label

    def click_away(self):
        event = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.QPointF(900, 900),
            QtCore.QPointF(900, 900),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        self.view.mousePressEvent(event)

    def assert_edit_cleared(self):
        self.assertFalse(self.view.is_text_annotation_inline_edit_active())
        self.assertIsNone(self.view._editing_named_view_item)
        self.assertIsNone(self.view._editing_text_document)

    def test_normal_rename_and_repeated_cleanup_preserve_scene_selection(self):
        self.view._selected_uids = {"nv1"}
        self.label.setPlainText("After")
        cursor = self.label.textCursor()
        cursor.select(QtGui.QTextCursor.SelectionType.Document)
        self.label.setTextCursor(cursor)
        self.view._finish_active_inline_text_edit(commit=True)
        self.view._finish_active_inline_text_edit(commit=True)
        self.view._clear_inline_text_edit_state()
        self.assert_edit_cleared()
        self.assertEqual(len(self.changes), 1)
        self.assertEqual(self.changes[0][3], {"Text": "After"})
        self.assertFalse(self.label.textCursor().hasSelection())
        self.assertEqual(self.view._selected_uids, {"nv1"})
        self.assertEqual(
            self.label.textInteractionFlags(),
            QtCore.Qt.TextInteractionFlag.NoTextInteraction,
        )

    def test_escape_restores_original_text_without_persistence(self):
        self.label.setPlainText("After")
        self.view.keyPressEvent(
            QtGui.QKeyEvent(
                QtCore.QEvent.Type.KeyPress,
                QtCore.Qt.Key.Key_Escape,
                QtCore.Qt.KeyboardModifier.NoModifier,
            )
        )
        self.assert_edit_cleared()
        self.assertEqual(self.label.toPlainText(), "Before")
        self.assertEqual(self.changes, [])

    def test_scene_clear_while_empty_draft_refuses_commit(self):
        self.view._finish_active_inline_text_edit(commit=False)
        self.assertTrue(
            self.view.begin_named_view_draft([0, 0, 40, 0, 40, 40, 0, 40], "p1")
        )
        item = self.view._editing_named_view_item
        self.view.clear()
        self.assert_edit_cleared()
        self.assertIsNone(self.view._draft_named_view_uid)
        # Draft removal transfers ownership out of the scene before clearing.
        self.assertTrue(not isValid(item) or item.scene() is None)

    def test_scene_clear_while_validation_rejects_commit(self):
        self.view.set_named_view_name_validator(lambda _name, _uid: False)
        self.view.clear()
        self.assertFalse(isValid(self.label))
        self.assert_edit_cleared()
        self.view._clear_inline_text_edit_state()
        self.assertEqual(self.changes, [])

    def test_validator_replaces_same_uid_target(self):
        replacement = []

        def validate(_name, _uid):
            self.view.clear()
            replacement.append(self.add_named_view())
            return True

        self.label.setPlainText("Old draft")
        self.view.set_named_view_name_validator(validate)
        self.view._finish_active_inline_text_edit(commit=True)
        self.assert_edit_cleared()
        self.assertEqual(self.changes, [])
        self.assertEqual(replacement[0].toPlainText(), "Before")

    def test_edit_mode_notification_cannot_redirect_commit_to_replacement(self):
        replacement = []

        def replace_on_finish(active):
            if not active:
                self.view.clear()
                replacement.append(self.add_named_view())

        self.view.text_annotation_edit_mode_changed.connect(replace_on_finish)
        self.label.setPlainText("Old draft")
        self.view._finish_active_inline_text_edit(commit=True)
        self.assert_edit_cleared()
        self.assertEqual(self.changes, [])
        self.assertEqual(replacement[0].toPlainText(), "Before")

    def test_overlay_rebuild_releases_removed_target(self):
        page = Page(uid="p1", name="Page")
        annotation = self.view._current_annotations["nv1"]
        self.view._refresh_overlays_impl_unflushed(
            page, [], {}, {}, [annotation], None, None
        )
        self.assert_edit_cleared()
        self.assertIsNone(self.label.scene())
        self.assertIsNot(self.view._named_view_label_item("nv1"), self.label)
        self.click_away()

    def test_destroyed_target_then_press_double_click_starts_one_connection(self):
        self.label.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(
            self.label, QtCore.QEvent.Type.DeferredDelete
        )
        self.assert_edit_cleared()
        self.click_away()
        replacement = self.add_named_view()
        point = QtCore.QPointF(
            self.view.mapFromScene(
                replacement.mapToScene(replacement.boundingRect().center())
            )
        )
        with patch.object(
            self.view,
            "_refresh_active_inline_text_visuals",
            wraps=self.view._refresh_active_inline_text_visuals,
        ) as refresh:
            self.view.mouseDoubleClickEvent(
                QtGui.QMouseEvent(
                    QtCore.QEvent.Type.MouseButtonDblClick,
                    point,
                    point,
                    QtCore.Qt.MouseButton.LeftButton,
                    QtCore.Qt.MouseButton.LeftButton,
                    QtCore.Qt.KeyboardModifier.NoModifier,
                )
            )
            self.assertIs(self.view._editing_named_view_item, replacement)
            self.assertTrue(self.view._begin_named_view_rename("nv1"))
            refresh.reset_mock()
            replacement.setPlainText("New")
            refresh.assert_called_once_with()
            self.view._finish_active_inline_text_edit(commit=True)
        self.assert_edit_cleared()
        self.assertEqual(len(self.changes), 1)

    def test_document_replacement_releases_destroyed_signal_source(self):
        document = self.label.document()
        replacement = QtGui.QTextDocument(self.label)
        self.label.setDocument(replacement)
        self.assertFalse(isValid(document))
        self.assert_edit_cleared()
        self.view._clear_inline_text_document()
        self.view._clear_inline_text_document()
        self.assertTrue(self.view._begin_named_view_rename("nv1"))
        self.assertIs(self.view._editing_text_document, replacement)
        self.view._finish_active_inline_text_edit(commit=False)
        self.assert_edit_cleared()

    def test_start_rename_after_native_document_replacement(self):
        document = self.label.document()
        self.label.setDocument(QtGui.QTextDocument(self.label))
        self.assertFalse(isValid(document))
        self.assertTrue(self.view._begin_named_view_rename("nv1"))
        self.view._finish_active_inline_text_edit(commit=False)
        self.assert_edit_cleared()

    def test_annotation_removal_releases_edit_before_same_uid_replacement(self):
        self.label.setPlainText("Obsolete draft")
        self.view._remove_annotation_overlay_items({"nv1"})
        self.assert_edit_cleared()
        self.assertIsNone(self.label.scene())
        replacement = self.add_named_view()
        self.click_away()
        self.assertEqual(self.changes, [])
        self.assertEqual(replacement.toPlainText(), "Before")

    def test_view_native_teardown_releases_inline_ownership(self):
        document = self.label.document()
        delete(self.view)
        self.assertFalse(isValid(self.label))
        self.assertFalse(isValid(document))
        self.assert_edit_cleared()

    def test_cleanup_during_rename_is_idempotent(self):
        self.view.cleanup()
        self.view.cleanup()
        self.assert_edit_cleared()

    def test_commit_rebuilds_scene_before_returning_to_click_cleanup(self):
        document = self.label.document()
        self.label.setPlainText("After")
        replacement = []

        def rebuild(_changes):
            self.view.clear()
            replacement.append(self.add_named_view())

        self.view.annotation_text_properties_flushed.connect(rebuild)
        self.click_away()
        self.assertFalse(isValid(self.label))
        self.assertFalse(isValid(document))
        self.assert_edit_cleared()
        self.assertIs(self.view._named_view_label_item("nv1"), replacement[0])
        self.assertEqual(replacement[0].toPlainText(), "Before")
        self.assertEqual(len(self.changes), 1)
        self.click_away()

    def test_deferred_target_deletion_before_finish(self):
        document = self.label.document()
        self.label.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(
            self.label, QtCore.QEvent.Type.DeferredDelete
        )
        self.assertFalse(isValid(self.label))
        self.assertFalse(isValid(document))
        self.view._finish_active_inline_text_edit(commit=True)
        self.assert_edit_cleared()
        self.assertEqual(self.changes, [])


if __name__ == "__main__":
    unittest.main()
