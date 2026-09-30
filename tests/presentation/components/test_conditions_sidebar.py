from PySide6 import QtCore, QtWidgets
from shiboken6 import delete
from PySide6 import QtWidgets
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.domain.entities.cdn_type import CdnType
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.condition_folder import BidConditionFolder
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.presentation.components import (
    conditions_sidebar as conditions_sidebar_module,
)
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar
from ost_visualizer.presentation.managers.icon_manager import IconId, IconManager
from ost_visualizer.presentation.managers.shortcut_manager import ShortcutManager
from ost_visualizer.presentation.utils.compact_context_menu import (
    COMPACT_CONTEXT_MENU_MAX_VISIBLE_ROWS,
    COMPACT_CONTEXT_MENU_NEXT_TEXT,
    COMPACT_CONTEXT_MENU_PREVIOUS_TEXT,
)
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from ost_visualizer.application.use_cases.project.condition_summary_service import (
    ConditionSummaryService,
)
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.uom_service import CALC_COUNT, UOM_EACH
from ost_visualizer.presentation.components.condition_summary import ConditionSummaryTab
from ost_visualizer.presentation.utils.persistent_header import (
    PersistentHeaderController,
)
from tests.helpers.workspace_state import make_workspace_state_model

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _attach_summary_header(tab):
    controller = PersistentHeaderController(
        tab.tree,
        "condition_summary_test",
        tab.column_keys,
        make_workspace_state_model(),
        sorting=True,
        movable=True,
        default_sort_column="name",
    )
    tab.columns_about_to_change.connect(controller.begin_columns_update)
    tab.columns_changed.connect(controller.end_columns_update)
    return controller


class ConditionsSidebarConditionBehaviorTests(unittest.TestCase):
    def _make_conditions(self, count: int, prefix: str = "c"):
        return {
            f"{prefix}{index}": Condition(
                uid=f"{prefix}{index}",
                name=f"Condition {index}",
                ref_no=index,
            )
            for index in range(1, count + 1)
        }

    def _foldered_conditions(self):
        conditions = {
            "c1": Condition(uid="c1", name="Condition 1", ref_no=1, folder_uid="f1"),
            "c2": Condition(uid="c2", name="Condition 2", ref_no=2, folder_uid="f2"),
        }
        folders = {
            "f1": BidConditionFolder(uid="f1", name="Folder 1"),
            "f2": BidConditionFolder(uid="f2", name="Folder 2"),
        }
        return conditions, folders

    def _show_compact_sidebar(self, sidebar: ConditionsSidebar) -> None:
        sidebar.resize(260, 180)
        sidebar.show()
        self.app.processEvents()

    def test_condition_assignment_context_submenus_use_compact_overflow_menus(self):
        sidebar = ConditionsSidebar(None)
        try:
            sidebar._conditions = {
                "c1": Condition(
                    uid="c1",
                    layer_uid="layer-10",
                    cdn_type_uid="type-10",
                )
            }
            sidebar.set_available_layers(
                [
                    BidLayer(
                        uid=f"layer-{index}",
                        bid_uid="bid",
                        name=f"Layer {index:02d}",
                        show=True,
                        sequence=index,
                    )
                    for index in range(1, 81)
                ]
            )
            sidebar.set_available_condition_types(
                [
                    CdnType(uid=f"type-{index}", name=f"Type {index:02d}")
                    for index in range(1, 81)
                ]
            )
            menu = QtWidgets.QMenu()
            try:
                sidebar._add_condition_assignment_submenus(menu, ["c1"], True)
                submenus = [action.menu() for action in menu.actions()]
                self.assertEqual(
                    [submenu.title() for submenu in submenus],
                    ["Set Layer", "Set Type"],
                )
                for submenu in submenus:
                    with self.subTest(submenu=submenu.title()):
                        self.assertTrue(submenu.property("ost_compact_overflow_menu"))
                        self.assertEqual(
                            submenu.property("ost_compact_overflow_max_visible_rows"),
                            COMPACT_CONTEXT_MENU_MAX_VISIBLE_ROWS,
                        )
                        self.assertEqual(
                            submenu.property("ost_compact_overflow_item_count"), 80
                        )
                        self.assertEqual(
                            len(submenu.actions()),
                            COMPACT_CONTEXT_MENU_MAX_VISIBLE_ROWS,
                        )
                        self.assertEqual(
                            submenu.actions()[-1].text(),
                            COMPACT_CONTEXT_MENU_NEXT_TEXT,
                        )
                        checked = [
                            action.data()
                            for action in submenu.actions()
                            if action.isChecked()
                        ]
                        self.assertEqual(len(checked), 1)
                        self.assertTrue(str(checked[0]).endswith("-10"))
                        submenu.show()
                        submenu.actions()[-1].defaultWidget().click()
                        self.app.processEvents()
                        submenu.close()
                        self.assertEqual(
                            submenu.actions()[0].text(),
                            COMPACT_CONTEXT_MENU_PREVIOUS_TEXT,
                        )
            finally:
                menu.deleteLater()
        finally:
            sidebar.deleteLater()

    def test_delayed_condition_assignment_overflow_rejects_rebuilt_tree(self):
        sidebar = ConditionsSidebar(None)
        assigned = []
        sidebar.condition_layer_change_requested.connect(
            lambda uids, layer_uid: assigned.append((list(uids), layer_uid))
        )
        sidebar.load_conditions(self._make_conditions(1), {}, "Project")
        sidebar.set_edit_enabled(True)
        sidebar.set_available_layers(
            [
                BidLayer(
                    uid=f"layer-{index}",
                    bid_uid="bid",
                    name=f"Layer {index:02d}",
                    show=True,
                    sequence=index,
                )
                for index in range(1, 81)
            ]
        )
        menu = QtWidgets.QMenu()
        sidebar._add_layer_submenu(menu, ["c1"], True)
        submenu = menu.actions()[0].menu()
        submenu.show()
        submenu.actions()[-1].defaultWidget().click()
        sidebar.load_conditions(
            {"c1": Condition(uid="c1", name="Replacement", ref_no=1)},
            {},
            "Project",
        )
        self.app.processEvents()
        submenu.close()
        next(
            action
            for action in submenu.actions()
            if action.data() and str(action.data()).startswith("layer-")
        ).trigger()
        self.assertEqual(assigned, [])

    def test_condition_sidebar_rebuild_clears_stale_selection_cache(self):
        sidebar = ConditionsSidebar(None)
        sidebar.load_conditions(
            {"c1": Condition(uid="c1", name="Condition 1", ref_no=1)},
            {},
            "Project",
        )
        sidebar.highlight_conditions({"c1"})
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c1"])
        sidebar.load_conditions(
            {"c2": Condition(uid="c2", name="Condition 2", ref_no=2)},
            {},
            "Project",
        )
        self.assertEqual(sidebar.get_selected_condition_uids(), [])

    def test_condition_sidebar_passive_reload_does_not_reapply_stale_scroll(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        self._show_compact_sidebar(sidebar)
        sidebar.load_conditions(self._make_conditions(80, "a"), {}, "Project A")
        self.app.processEvents()
        scrollbar = sidebar.tree.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self.assertGreater(scrollbar.value(), 0)
        sidebar.load_conditions(self._make_conditions(80, "b"), {}, "Project B")
        self.app.processEvents()
        self.assertEqual(scrollbar.value(), 0)

    def test_condition_sidebar_highlight_scrolls_to_revealed_condition(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        self._show_compact_sidebar(sidebar)
        sidebar.load_conditions(self._make_conditions(80), {}, "Project")
        self.app.processEvents()
        scrollbar = sidebar.tree.verticalScrollBar()
        scrollbar.setValue(0)
        sidebar.highlight_conditions({"c80"})
        self.app.processEvents()
        self.assertGreater(scrollbar.value(), 0)
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c80"])

    def test_condition_sidebar_explicit_highlight_expands_condition_path(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions, folders = self._foldered_conditions()
        sidebar.load_conditions(conditions, folders, "Project")
        folder = sidebar._folder_items["f1"]
        cdn_type = folder.child(0)
        folder.setExpanded(False)
        cdn_type.setExpanded(False)
        sidebar.highlight_conditions({"c1"})
        self.assertTrue(folder.isExpanded())
        self.assertTrue(cdn_type.isExpanded())
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c1"])

    def test_programmatic_multi_highlight_uses_focused_condition_as_active(self):
        class OrderedUidSet(set):
            def __iter__(self):
                return iter(("linear", "area"))

        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions = {
            "linear": Condition(
                uid="linear",
                name="Linear",
                ref_no=1,
                condition_type=Condition.TYPE_LINEAR,
            ),
            "area": Condition(
                uid="area",
                name="Area",
                ref_no=2,
                condition_type=Condition.TYPE_AREA,
            ),
        }
        sidebar.load_conditions(conditions, {}, "Project")
        sidebar.highlight_conditions(OrderedUidSet(("linear", "area")))
        current_data = sidebar.tree.currentItem().data(
            0, QtCore.Qt.ItemDataRole.UserRole
        )
        self.assertEqual(current_data, ("condition", "linear"))
        self.assertEqual(sidebar.get_selected_condition_uids(), ["linear", "area"])
        self.assertEqual(sidebar.get_active_condition_uid(), "linear")
        emitted = []
        sidebar.condition_selected.connect(emitted.append)
        sidebar._emit_selected_conditions()
        self.assertEqual(emitted, ["linear"])

    def test_passive_multi_highlight_preserves_active_condition_after_rebuild(self):
        class ForwardUidSet(set):
            def __iter__(self):
                return iter(("linear", "area"))

        class ReverseUidSet(set):
            def __iter__(self):
                return iter(("area", "linear"))

        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions = {
            "linear": Condition(
                uid="linear",
                name="Linear",
                ref_no=1,
                condition_type=Condition.TYPE_LINEAR,
            ),
            "area": Condition(
                uid="area",
                name="Area",
                ref_no=2,
                condition_type=Condition.TYPE_AREA,
            ),
        }
        selected = ForwardUidSet(("linear", "area"))
        sidebar.load_conditions(conditions, {}, "Project")
        sidebar.highlight_conditions(selected)
        self.assertEqual(sidebar.get_active_condition_uid(), "linear")
        # The authoritative rebuild preserves the current row. Passive state
        # projection must not replace it based on a set's iteration order.
        sidebar.load_conditions(conditions, {}, "Project")
        sidebar.highlight_conditions(ReverseUidSet(("linear", "area")), reveal=False)
        self.assertEqual(set(sidebar.get_selected_condition_uids()), {"linear", "area"})
        self.assertEqual(sidebar.get_active_condition_uid(), "linear")

    def test_condition_sidebar_passive_restore_does_not_expand_condition_path(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions, folders = self._foldered_conditions()
        sidebar.load_conditions(conditions, folders, "Project")
        folder = sidebar._folder_items["f1"]
        folder.setExpanded(False)
        sidebar._restore_context_selection(["c1"], [])
        self.assertFalse(folder.isExpanded())
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c1"])

    def test_condition_sidebar_passive_reload_preserves_visible_highlight_without_scroll(
        self,
    ):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        self._show_compact_sidebar(sidebar)
        sidebar.load_conditions(self._make_conditions(80), {}, "Project")
        self.app.processEvents()
        scrollbar = sidebar.tree.verticalScrollBar()
        scrollbar.setValue(0)
        sidebar.highlight_conditions({"c1"}, reveal=False)
        self.app.processEvents()
        sidebar.load_conditions(self._make_conditions(80), {}, "Project")
        self.app.processEvents()
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c1"])
        self.assertTrue(sidebar._condition_items["c1"].isSelected())
        self.assertEqual(scrollbar.value(), 0)

    def test_condition_sidebar_passive_reload_preserves_hidden_selection_without_expanding(
        self,
    ):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions, folders = self._foldered_conditions()
        sidebar.load_conditions(conditions, folders, "Project")
        folder = sidebar._folder_items["f1"]
        folder.setExpanded(False)
        sidebar._restore_context_selection(["c1"], [])
        sidebar.load_conditions(dict(conditions), folders, "Project")
        self.assertFalse(sidebar._folder_items["f1"].isExpanded())
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c1"])

    def test_condition_sidebar_passive_reload_preserves_scroll_for_same_project(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        self._show_compact_sidebar(sidebar)
        sidebar.load_conditions(self._make_conditions(80), {}, "Project")
        self.app.processEvents()
        scrollbar = sidebar.tree.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum() // 2)
        expected = scrollbar.value()
        sidebar.load_conditions(self._make_conditions(80), {}, "Project")
        self.app.processEvents()
        self.assertEqual(scrollbar.value(), expected)

    def test_condition_sidebar_highlight_visible_condition_does_not_scroll(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        self._show_compact_sidebar(sidebar)
        sidebar.load_conditions(self._make_conditions(80), {}, "Project")
        self.app.processEvents()
        scrollbar = sidebar.tree.verticalScrollBar()
        scrollbar.setValue(0)
        sidebar.highlight_conditions({"c1"})
        self.app.processEvents()
        self.assertEqual(scrollbar.value(), 0)

    def test_condition_sidebar_reveal_above_viewport_positions_near_top(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        self._show_compact_sidebar(sidebar)
        sidebar.load_conditions(self._make_conditions(80), {}, "Project")
        self.app.processEvents()
        sidebar.tree.verticalScrollBar().setValue(
            sidebar.tree.verticalScrollBar().maximum()
        )
        sidebar.highlight_conditions({"c1"})
        self.app.processEvents()
        rect = sidebar.tree.visualItemRect(sidebar._condition_items["c1"])
        self.assertLess(rect.center().y(), sidebar.tree.viewport().rect().center().y())

    def test_condition_sidebar_reveal_below_viewport_positions_near_bottom(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        self._show_compact_sidebar(sidebar)
        sidebar.load_conditions(self._make_conditions(80), {}, "Project")
        self.app.processEvents()
        sidebar.tree.verticalScrollBar().setValue(0)
        sidebar.highlight_conditions({"c80"})
        self.app.processEvents()
        rect = sidebar.tree.visualItemRect(sidebar._condition_items["c80"])
        self.assertGreater(
            rect.center().y(), sidebar.tree.viewport().rect().center().y()
        )

    def test_condition_sidebar_reload_preserves_expanded_state(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions, folders = self._foldered_conditions()
        sidebar.load_conditions(conditions, folders, "Project")
        sidebar._folder_items["f1"].setExpanded(False)
        sidebar._folder_items["f2"].setExpanded(True)
        sidebar.load_conditions(dict(conditions), folders, "Project")
        self.assertFalse(sidebar._folder_items["f1"].isExpanded())
        self.assertTrue(sidebar._folder_items["f2"].isExpanded())

    def test_condition_sidebar_delete_refresh_preserves_expanded_state(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions, folders = self._foldered_conditions()
        sidebar.load_conditions(conditions, folders, "Project")
        sidebar._folder_items["f1"].setExpanded(False)
        sidebar._folder_items["f2"].setExpanded(False)
        replacement_uid = sidebar.condition_selection_after_delete(["c2"])
        remaining = {"c1": conditions["c1"]}
        sidebar.load_conditions(remaining, folders, "Project")
        if replacement_uid:
            sidebar.highlight_conditions({replacement_uid}, reveal=False)
        self.assertFalse(sidebar._folder_items["f1"].isExpanded())
        self.assertFalse(sidebar._folder_items["f2"].isExpanded())
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c1"])

    def test_condition_sidebar_duplicate_refresh_preserves_expanded_state(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions, folders = self._foldered_conditions()
        sidebar.load_conditions(conditions, folders, "Project")
        sidebar._folder_items["f1"].setExpanded(False)
        sidebar._folder_items["f2"].setExpanded(False)
        duplicated = dict(conditions)
        duplicated["c3"] = Condition(
            uid="c3", name="Condition 3", ref_no=3, folder_uid="f2"
        )
        sidebar.load_conditions(duplicated, folders, "Project")
        sidebar.highlight_conditions({"c3"}, reveal=False)
        self.assertFalse(sidebar._folder_items["f1"].isExpanded())
        self.assertFalse(sidebar._folder_items["f2"].isExpanded())
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c3"])

    def test_condition_sidebar_delete_replacement_selects_previous_logical_condition(
        self,
    ):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions = self._make_conditions(4)
        sidebar.load_conditions(conditions, {}, "Project")
        self.assertEqual(sidebar.condition_selection_after_delete(["c3"]), "c2")

    def test_condition_sidebar_delete_replacement_uses_next_when_no_previous(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions = self._make_conditions(3)
        sidebar.load_conditions(conditions, {}, "Project")
        self.assertEqual(sidebar.condition_selection_after_delete(["c1"]), "c2")

    def test_condition_sidebar_delete_replacement_uses_previous_for_multi_delete(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions = self._make_conditions(5)
        sidebar.load_conditions(conditions, {}, "Project")
        self.assertEqual(sidebar.condition_selection_after_delete(["c3", "c4"]), "c2")

    def test_condition_sidebar_delete_replacement_clears_when_all_deleted(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        conditions = self._make_conditions(2)
        sidebar.load_conditions(conditions, {}, "Project")
        self.assertIsNone(sidebar.condition_selection_after_delete(["c1", "c2"]))

    def test_condition_sidebar_layer_visibility_update_preserves_quantities(self):
        sidebar = ConditionsSidebar(None)
        condition = Condition(uid="c1", name="Condition 1", ref_no=1)
        sidebar.load_conditions({"c1": condition}, {}, "Project")
        sidebar.update_quantities({"c1": (12.0, 0.0, 0.0)})
        item = sidebar._condition_items["c1"]
        before = [item.text(col) for col in range(2, 5)]
        condition.layer_visible = False
        sidebar.apply_layer_visibility_state({"c1": condition})
        self.assertEqual([item.text(col) for col in range(2, 5)], before)
        self.assertFalse(sidebar.is_condition_placeable("c1"))

    def test_condition_sidebar_layer_visibility_updates_only_matching_layer_rows(self):
        sidebar = ConditionsSidebar(None)
        condition_a = Condition(
            uid="c1", name="Condition 1", ref_no=1, layer_uid="layer-a"
        )
        condition_b = Condition(
            uid="c2", name="Condition 2", ref_no=2, layer_uid="layer-b"
        )
        try:
            sidebar.load_conditions(
                {"c1": condition_a, "c2": condition_b}, {}, "Project"
            )
            condition_a.layer_visible = False
            with patch.object(
                conditions_sidebar_module,
                "make_condition_color_icon",
                wraps=conditions_sidebar_module.make_condition_color_icon,
            ) as make_icon:
                sidebar.apply_layer_visibility_state(
                    {"c1": condition_a, "c2": condition_b},
                    layer_uid="layer-a",
                )
            self.assertEqual(make_icon.call_count, 1)
            self.assertFalse(sidebar.is_condition_placeable("c1"))
            self.assertTrue(sidebar.is_condition_placeable("c2"))
        finally:
            sidebar.deleteLater()

    def test_condition_sidebar_refreshes_restore_caller_owned_tree_state(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        condition = Condition(uid="c1", name="Condition 1", ref_no=1)
        sidebar.load_conditions({"c1": condition}, {}, "Project")
        sidebar.tree.setSortingEnabled(False)
        sidebar.tree.setUpdatesEnabled(False)
        sidebar.tree.blockSignals(True)
        sidebar._block_item_changed = True
        sidebar.load_conditions({"c1": condition}, {}, "Project")
        sidebar.apply_layer_visibility_state({"c1": condition})
        sidebar.update_quantities({"c1": (12.0, 0.0, 0.0)})
        self.assertFalse(sidebar.tree.isSortingEnabled())
        self.assertFalse(sidebar.tree.updatesEnabled())
        self.assertTrue(sidebar.tree.signalsBlocked())
        self.assertTrue(sidebar._block_item_changed)

    def test_condition_sidebar_rebuild_restores_tree_state_after_failure(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        condition = Condition(uid="c1", name="Condition 1", ref_no=1)
        original_state = (
            sidebar.tree.isSortingEnabled(),
            sidebar.tree.updatesEnabled(),
            sidebar.tree.signalsBlocked(),
            sidebar._block_item_changed,
        )
        with patch.object(
            sidebar, "_build_folder_tree", side_effect=RuntimeError("build failed")
        ):
            with self.assertRaisesRegex(RuntimeError, "build failed"):
                sidebar.load_conditions({"c1": condition}, {}, "Project")
        self.assertEqual(
            (
                sidebar.tree.isSortingEnabled(),
                sidebar.tree.updatesEnabled(),
                sidebar.tree.signalsBlocked(),
                sidebar._block_item_changed,
            ),
            original_state,
        )

    def test_condition_cut_paste_to_root_and_folder_uses_structure_permission(self):
        sidebar = ConditionsSidebar(None)
        pasted = []
        sidebar.paste_requested.connect(
            lambda uids, target: pasted.append((list(uids), dict(target)))
        )
        sidebar.load_conditions(
            {"c1": Condition(uid="c1", name="Condition 1", ref_no=1)},
            {"f1": BidConditionFolder(uid="f1", name="Folder")},
            "Project",
        )
        sidebar.set_duplicate_enabled(False)
        sidebar.set_copy_enabled(True)
        sidebar.set_edit_enabled(False)
        sidebar.set_create_folder_enabled(True)
        sidebar.highlight_conditions({"c1"})
        sidebar._cut_selected_conditions()
        root = sidebar.tree.topLevelItem(0)
        folder = sidebar._folder_items["f1"]
        self.assertTrue(sidebar._can_paste_to_item(root))
        self.assertTrue(sidebar._can_paste_context_target("root", root))
        sidebar._paste_copied_conditions(folder)
        self.assertEqual(pasted[0][0], ["c1"])
        self.assertEqual(pasted[0][1]["kind"], "folder")
        self.assertEqual(pasted[0][1]["folder_uid"], "f1")
        self.assertTrue(pasted[0][1]["cut"])

    def test_condition_cut_clipboard_retains_unconfirmed_and_partial_sources(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        sidebar.load_conditions(
            {
                "c1": Condition(uid="c1", name="First", ref_no=1),
                "c2": Condition(uid="c2", name="Second", ref_no=2),
            },
            {"f1": BidConditionFolder(uid="f1", name="Folder")},
            "Project",
        )
        sidebar.set_copy_enabled(True)
        sidebar.set_create_folder_enabled(True)
        sidebar.highlight_conditions({"c1", "c2"})
        sidebar._cut_selected_conditions()
        sidebar._paste_copied_conditions(sidebar._folder_items["f1"])
        self.assertEqual(set(sidebar._copied_condition_uids), {"c1", "c2"})
        self.assertTrue(sidebar._condition_clipboard_cut)
        clipboard_revision = sidebar._condition_clipboard_revision
        sidebar.complete_cut_paste(["c1"], clipboard_revision)
        self.assertEqual(sidebar._copied_condition_uids, ["c2"])
        self.assertTrue(sidebar._condition_clipboard_cut)
        self.assertTrue(sidebar._can_paste_to_item(sidebar._folder_items["f1"]))
        sidebar.complete_cut_paste(["c2"], sidebar._condition_clipboard_revision)
        self.assertEqual(sidebar._copied_condition_uids, [])
        self.assertFalse(sidebar._condition_clipboard_cut)

    def test_older_condition_cut_completion_preserves_newer_cut_clipboard(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        pasted = []
        sidebar.paste_requested.connect(
            lambda uids, target: pasted.append((list(uids), dict(target)))
        )
        sidebar.load_conditions(
            {
                "c1": Condition(uid="c1", name="First", ref_no=1),
                "c2": Condition(uid="c2", name="Second", ref_no=2),
            },
            {"f1": BidConditionFolder(uid="f1", name="Folder")},
            "Project",
        )
        sidebar.set_copy_enabled(True)
        sidebar.set_create_folder_enabled(True)
        sidebar.highlight_conditions({"c1"})
        sidebar._cut_selected_conditions()
        sidebar._paste_copied_conditions(sidebar._folder_items["f1"])
        clipboard_revision = pasted[0][1]["clipboard_revision"]
        sidebar.highlight_conditions({"c1"})
        sidebar._cut_selected_conditions()
        sidebar.complete_cut_paste(["c1"], clipboard_revision)
        self.assertTrue(sidebar._condition_clipboard_cut)
        self.assertEqual(sidebar._copied_condition_uids, ["c1"])

    def test_stale_condition_context_targets_are_rejected_after_tree_rebuild(self):
        sidebar = ConditionsSidebar(None)
        pasted = []
        sidebar.paste_requested.connect(
            lambda uids, target: pasted.append((list(uids), dict(target)))
        )
        sidebar.load_conditions(
            {"c1": Condition(uid="c1", name="Original", ref_no=1)},
            {},
            "Project",
        )
        sidebar.set_edit_enabled(True)
        sidebar.set_duplicate_enabled(True)
        sidebar._copied_condition_uids = ["c1"]
        original_item = sidebar._condition_items["c1"]
        sidebar.highlight_conditions({"c1"})
        sidebar.load_conditions(
            {"c1": Condition(uid="c1", name="Replacement", ref_no=1)},
            {},
            "Project",
        )
        sidebar._rename_context_target(original_item)
        sidebar._paste_copied_conditions(original_item)
        self.assertEqual(pasted, [])
        self.assertNotEqual(
            sidebar.tree.state(),
            QtWidgets.QAbstractItemView.State.EditingState,
        )

    def test_condition_clipboard_drops_sources_deleted_by_remote_rebuild(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        pasted = []
        sidebar.paste_requested.connect(
            lambda uids, target: pasted.append((list(uids), dict(target)))
        )
        sidebar.load_conditions(
            {"c1": Condition(uid="c1", name="Original", ref_no=1)},
            {},
            "Project",
        )
        sidebar.set_duplicate_enabled(True)
        sidebar.set_copy_enabled(True)
        sidebar.highlight_conditions({"c1"})
        sidebar._copy_selected_conditions()
        sidebar.load_conditions({}, {}, "Project")
        root = sidebar.tree.topLevelItem(0)
        self.assertFalse(sidebar._can_paste_to_item(root))
        sidebar._paste_copied_conditions(root)
        self.assertEqual(pasted, [])

    def test_condition_clipboard_pastes_only_survivors_of_remote_rebuild(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        pasted = []
        sidebar.paste_requested.connect(
            lambda uids, target: pasted.append((list(uids), dict(target)))
        )
        sidebar.load_conditions(
            {
                "c1": Condition(uid="c1", name="First", ref_no=1),
                "c2": Condition(uid="c2", name="Second", ref_no=2),
            },
            {},
            "Project",
        )
        sidebar.set_duplicate_enabled(True)
        sidebar.set_copy_enabled(True)
        sidebar.highlight_conditions({"c1", "c2"})
        sidebar._copy_selected_conditions()
        sidebar.load_conditions(
            {"c2": Condition(uid="c2", name="Second", ref_no=2)},
            {},
            "Project",
        )
        root = sidebar.tree.topLevelItem(0)
        sidebar._paste_copied_conditions(root)
        self.assertEqual(pasted[0][0], ["c2"])

    def test_condition_context_delete_keeps_original_selection_target(self):
        sidebar = ConditionsSidebar(None)
        deleted = []
        sidebar.delete_requested.connect(lambda uids: deleted.append(list(uids)))
        sidebar.load_conditions(self._make_conditions(2), {}, "Project")
        sidebar.set_delete_enabled(True)
        sidebar.highlight_conditions({"c1"})
        menu = QtWidgets.QMenu()
        sidebar._add_condition_command_actions(
            menu,
            sidebar._condition_items["c1"],
            conditions_sidebar_module._TYPE_CONDITION,
            ["c1"],
            False,
            False,
        )
        sidebar.highlight_conditions({"c2"})
        next(action for action in menu.actions() if action.text() == "Delete").trigger()
        self.assertEqual(deleted, [["c1"]])

    def test_condition_context_new_keeps_right_clicked_folder_target(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        created = []
        sidebar.create_requested.connect(created.append)
        sidebar.load_conditions(
            {},
            {
                "f1": BidConditionFolder(uid="f1", name="First"),
                "f2": BidConditionFolder(uid="f2", name="Second"),
            },
            "Project",
        )
        sidebar.set_create_enabled(True)
        first = sidebar._folder_items["f1"]
        second = sidebar._folder_items["f2"]
        sidebar.tree.setCurrentItem(first)
        first.setSelected(True)
        menu = QtWidgets.QMenu(sidebar)
        sidebar._add_new_submenu(menu, first)
        sidebar.tree.setCurrentItem(second)
        second.setSelected(True)
        new_menu = menu.actions()[0].menu()
        next(
            action for action in new_menu.actions() if action.text() == "Condition"
        ).trigger()
        self.assertEqual(created, ["f1"])

    def test_condition_tree_rebuild_cancels_active_drag_identity(self):
        sidebar = ConditionsSidebar(None)
        sidebar.load_conditions(self._make_conditions(1), {}, "Project")
        sidebar.tree._drag_uid = "c1"
        sidebar.load_conditions(
            {"c1": Condition(uid="c1", name="Replacement", ref_no=1)},
            {},
            "Project",
        )
        self.assertIsNone(sidebar.tree._drag_uid)

    def test_condition_drop_after_model_rebuild_is_ignored_without_mutation(self):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)
        moved = []
        sidebar.condition_folder_move_requested.connect(
            lambda condition_uid, folder_uid: moved.append((condition_uid, folder_uid))
        )
        sidebar.load_conditions(self._make_conditions(1), {}, "Project")
        sidebar.set_create_folder_enabled(True)
        sidebar.tree._drag_uid = "c1"
        sidebar.load_conditions(
            {"c1": Condition(uid="c1", name="Replacement", ref_no=1)},
            {},
            "Project",
        )
        target = sidebar.tree.topLevelItem(0)
        sidebar.tree.itemAt = lambda _position: target
        accepted = []
        ignored = []
        event = SimpleNamespace(
            position=lambda: QtCore.QPointF(),
            acceptProposedAction=lambda: accepted.append(True),
            ignore=lambda: ignored.append(True),
        )
        sidebar.tree.dropEvent(event)
        self.assertEqual(accepted, [])
        self.assertEqual(ignored, [True])
        self.assertEqual(moved, [])

    def test_condition_tree_rebuild_cancels_active_folder_editor(self):
        sidebar = ConditionsSidebar(None)
        sidebar.load_conditions(
            {}, {"f1": BidConditionFolder(uid="f1", name="Original")}, "Project"
        )
        sidebar.set_create_folder_enabled(True)
        sidebar.start_folder_edit("f1")
        self.assertIsNotNone(sidebar._editing_folder)
        sidebar.load_conditions(
            {}, {"f1": BidConditionFolder(uid="f1", name="Replacement")}, "Project"
        )
        sidebar._on_folder_editor_closed()
        self.assertIsNone(sidebar._editing_folder)
        self.assertEqual(sidebar._folder_items["f1"].text(0), "Replacement")

    def test_condition_folder_rename_reverts_when_structure_access_is_revoked(self):
        sidebar = ConditionsSidebar(None)
        renamed = []
        sidebar.folder_renamed.connect(lambda uid, name: renamed.append((uid, name)))
        sidebar.load_conditions(
            {}, {"f1": BidConditionFolder(uid="f1", name="Original")}, "Project"
        )
        sidebar.set_create_folder_enabled(True)
        sidebar.start_folder_edit("f1")
        item = sidebar._folder_items["f1"]
        item.setText(0, "Unauthorized rename")
        sidebar.set_create_folder_enabled(False)
        sidebar._on_folder_editor_closed()
        self.assertEqual(renamed, [])
        self.assertEqual(item.text(0), "Original")

    def test_pending_condition_folder_edit_does_not_open_after_access_loss(self):
        sidebar = ConditionsSidebar(None)
        sidebar.load_conditions(
            {}, {"f1": BidConditionFolder(uid="f1", name="Original")}, "Project"
        )
        sidebar.start_folder_edit("f1")
        self.assertIsNone(sidebar._editing_folder)

    def test_condition_folder_delete_uses_structure_not_condition_delete(self):
        sidebar = ConditionsSidebar(None)
        deleted = []
        sidebar.folder_delete_requested.connect(lambda uids: deleted.append(list(uids)))
        sidebar.load_conditions(
            {},
            {"f1": BidConditionFolder(uid="f1", name="Folder")},
            "Project",
        )
        sidebar.set_delete_enabled(False)
        sidebar.set_create_folder_enabled(True)
        folder = sidebar._folder_items["f1"]
        sidebar.tree.setCurrentItem(folder)
        folder.setSelected(True)
        sidebar._sync_button_states()
        self.assertTrue(sidebar._delete_btn.isEnabled())
        sidebar._delete_btn.click()
        self.assertEqual(deleted, [["f1"]])
        sidebar.set_create_folder_enabled(False)
        sidebar.set_delete_enabled(True)
        sidebar._request_folder_delete()
        self.assertEqual(deleted, [["f1"]])

    def test_condition_folder_nodes_use_folder_icon(self):
        sidebar = ConditionsSidebar(None)
        sidebar.load_conditions(
            {},
            {"f1": BidConditionFolder(uid="f1", name="Folder")},
            "Project",
        )
        folder = sidebar._folder_items["f1"]
        self.assertFalse(folder.icon(0).isNull())
        self.assertEqual(
            folder.icon(0).cacheKey(),
            IconManager.icon(IconId.FOLDER).cacheKey(),
        )

    def test_condition_sidebar_cdn_type_group_rows_are_bold(self):
        sidebar = ConditionsSidebar(None)
        sidebar.load_conditions(
            {
                "c1": Condition(
                    uid="c1",
                    name="Condition 1",
                    ref_no=1,
                    cdn_type_uid="type-1",
                    cdn_type_name="Type 1",
                )
            },
            {},
            "Project",
        )
        root = sidebar.tree.topLevelItem(0)
        cdn_type_item = root.child(0)
        condition_item = cdn_type_item.child(0)
        self.assertEqual(cdn_type_item.text(0), "Type 1")
        self.assertTrue(cdn_type_item.font(0).bold())
        self.assertFalse(condition_item.font(0).bold())

    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls._quit_on_last_window_closed = cls.app.quitOnLastWindowClosed()
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.setQuitOnLastWindowClosed(cls._quit_on_last_window_closed)

    def tearDown(self):
        self.app.processEvents()

    def _make_sidebar_with_selected_condition(self):
        sidebar = ConditionsSidebar(None)
        deleted = []
        sidebar.delete_requested.connect(lambda uids: deleted.append(list(uids)))
        sidebar.load_conditions(
            {"c1": Condition(uid="c1", name="Condition 1", ref_no=1)},
            {},
            "Project",
        )
        sidebar.set_delete_enabled(True)
        sidebar.highlight_conditions({"c1"})
        return sidebar, deleted

    def test_delete_key_invokes_condition_delete_for_tree_selection(self):
        sidebar, deleted = self._make_sidebar_with_selected_condition()
        sidebar.show()
        sidebar.tree.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        self.app.processEvents()
        QTest.keyClick(sidebar.tree, Qt.Key.Key_Delete)
        self.app.processEvents()
        self.assertEqual(deleted, [["c1"]])
        sidebar.close()

    def test_condition_delete_shortcut_wins_over_enabled_window_action(self):
        window = QtWidgets.QMainWindow()
        self.addCleanup(self.app.processEvents)
        self.addCleanup(window.close)
        sidebar = ConditionsSidebar(window)
        window.setCentralWidget(sidebar)
        deleted = []
        plan_delete_calls = []
        sidebar.delete_requested.connect(lambda uids: deleted.append(list(uids)))
        sidebar.load_conditions(self._make_conditions(1), {}, "Project")
        sidebar.set_delete_enabled(True)
        sidebar.highlight_conditions({"c1"})
        shared_delete = QtGui.QAction("Delete", window)
        ShortcutManager.apply_to_action(shared_delete, "delete")
        shared_delete.triggered.connect(lambda: plan_delete_calls.append(True))
        window.addAction(shared_delete)
        window.show()
        sidebar.tree.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        self.app.processEvents()
        QTest.keyClick(sidebar.tree, Qt.Key.Key_Delete)
        self.app.processEvents()
        self.assertEqual(deleted, [["c1"]])
        self.assertEqual(plan_delete_calls, [])

    def test_condition_duplicate_shortcut_wins_over_enabled_window_action(self):
        window = QtWidgets.QMainWindow()
        self.addCleanup(self.app.processEvents)
        self.addCleanup(window.close)
        sidebar = ConditionsSidebar(window)
        window.setCentralWidget(sidebar)
        duplicated = []
        plan_duplicate_calls = []
        sidebar.duplicate_requested.connect(lambda uids: duplicated.append(list(uids)))
        sidebar.load_conditions(self._make_conditions(1), {}, "Project")
        sidebar.set_duplicate_enabled(True)
        sidebar.highlight_conditions({"c1"})
        shared_duplicate = QtGui.QAction("Duplicate", window)
        ShortcutManager.apply_to_action(shared_duplicate, "duplicate")
        shared_duplicate.triggered.connect(lambda: plan_duplicate_calls.append(True))
        window.addAction(shared_duplicate)
        window.show()
        sidebar.tree.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        self.app.processEvents()
        QTest.keyClick(
            sidebar.tree,
            Qt.Key.Key_D,
            Qt.KeyboardModifier.ControlModifier,
        )
        QTest.keyRelease(sidebar.tree, Qt.Key.Key_Control)
        self.app.processEvents()
        self.assertEqual(duplicated, [["c1"]])
        self.assertEqual(plan_duplicate_calls, [])

    def test_condition_cut_shortcut_owns_condition_clipboard(self):
        sidebar, _deleted = self._make_sidebar_with_selected_condition()
        self.addCleanup(self.app.processEvents)
        self.addCleanup(sidebar.close)
        sidebar.set_create_folder_enabled(True)
        sidebar.show()
        sidebar.tree.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        self.app.processEvents()
        QTest.keyClick(
            sidebar.tree,
            Qt.Key.Key_X,
            Qt.KeyboardModifier.ControlModifier,
        )
        QTest.keyRelease(sidebar.tree, Qt.Key.Key_Control)
        self.app.processEvents()
        self.assertEqual(sidebar._copied_condition_uids, ["c1"])
        self.assertTrue(sidebar._condition_clipboard_cut)

    def test_delete_key_is_ignored_while_text_input_has_focus(self):
        sidebar, deleted = self._make_sidebar_with_selected_condition()
        text_input = QtWidgets.QLineEdit(sidebar.tree)
        text_input.setText("typing")
        text_input.show()
        sidebar.show()
        text_input.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        self.app.processEvents()
        QTest.keyClick(text_input, Qt.Key.Key_Delete)
        self.app.processEvents()
        self.assertEqual(deleted, [])
        sidebar.close()

    def test_double_click_non_name_condition_cell_requests_edit_dialog(self):
        sidebar, _deleted = self._make_sidebar_with_selected_condition()
        edits = []
        sidebar.edit_requested.connect(lambda uids: edits.append(list(uids)))
        sidebar.set_edit_enabled(True)
        sidebar._on_item_double_clicked(sidebar._condition_items["c1"], 0)
        self.assertEqual(edits, [["c1"]])
        sidebar.close()

    def test_double_click_name_condition_cell_keeps_inline_rename_behavior(self):
        sidebar, _deleted = self._make_sidebar_with_selected_condition()
        edits = []
        sidebar.edit_requested.connect(lambda uids: edits.append(list(uids)))
        sidebar.set_edit_enabled(True)
        sidebar._on_item_double_clicked(sidebar._condition_items["c1"], 1)
        self.assertEqual(edits, [])
        sidebar.close()

    def test_inline_condition_rename_reverts_when_edit_access_is_revoked(self):
        sidebar, _deleted = self._make_sidebar_with_selected_condition()
        renamed = []
        sidebar.condition_renamed.connect(lambda uid, name: renamed.append((uid, name)))
        sidebar.set_edit_enabled(True)
        item = sidebar._condition_items["c1"]
        sidebar.set_edit_enabled(False)
        item.setText(1, "Unauthorized rename")
        self.assertEqual(renamed, [])
        self.assertEqual(item.text(1), "Condition 1")
        sidebar.close()


class ConditionFolderContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_pending_folder_editor_does_not_survive_owner_transition(self):
        for transition in (
            "current",
            "hide",
            "close",
            "reopen",
            "disable",
            "reenable",
            "access",
            "clear",
            "repeat",
        ):
            with self.subTest(transition=transition):
                sidebar = ConditionsSidebar(None)
                try:
                    sidebar.load_conditions({}, {}, "Project")
                    sidebar.set_create_folder_enabled(True)
                    sidebar.show()
                    self.app.processEvents()
                    sidebar.set_pending_folder_edit("new")
                    if transition == "repeat":
                        sidebar.set_pending_folder_edit("new")
                    elif transition in ("hide", "reopen"):
                        sidebar.hide()
                        if transition == "reopen":
                            sidebar.show()
                    elif transition == "close":
                        sidebar.close()
                    elif transition in ("disable", "reenable"):
                        sidebar.setEnabled(False)
                        if transition == "reenable":
                            sidebar.setEnabled(True)
                    elif transition == "access":
                        sidebar.set_create_folder_enabled(False)
                    elif transition == "clear":
                        sidebar.clear()
                        sidebar.set_create_folder_enabled(True)
                    with patch.object(
                        sidebar.tree, "editItem", wraps=sidebar.tree.editItem
                    ) as edit:
                        sidebar.load_conditions(
                            {},
                            {"new": BidConditionFolder(uid="new", name="New")},
                            "Project",
                        )
                        self.assertEqual(
                            edit.call_count, int(transition in ("current", "repeat"))
                        )
                        if transition not in ("current", "repeat"):
                            self.assertIsNone(sidebar._editing_folder)
                finally:
                    sidebar.close()
                    delete(sidebar)


class ConditionsSidebarReactivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_hidden_condition_refresh_preserves_valid_selection_and_current_row(self):
        for change in ("rename", "delete_current", "delete_all"):
            with self.subTest(change=change):
                sidebar = ConditionsSidebar(None)
                try:
                    conditions = {
                        uid: Condition(uid=uid, name=uid, ref_no=int(uid))
                        for uid in ("3", "5", "7")
                    }
                    sidebar.load_conditions(conditions, {}, "Project")
                    sidebar.resize(500, 300)
                    sidebar.show()
                    self.app.processEvents()
                    sidebar.tree.setCurrentItem(sidebar._condition_items["3"])
                    sidebar._condition_items["5"].setSelected(True)
                    sidebar.tree.setCurrentItem(
                        sidebar._condition_items["5"],
                        0,
                        QtCore.QItemSelectionModel.SelectionFlag.NoUpdate,
                    )
                    sidebar.hide()
                    surviving = (
                        ("3", "5", "7")
                        if change == "rename"
                        else (("3", "7") if change == "delete_current" else ("7",))
                    )
                    refreshed = {
                        uid: Condition(uid=uid, name="Updated " + uid, ref_no=int(uid))
                        for uid in surviving
                    }
                    with patch.object(
                        sidebar, "_rebuild_tree", wraps=sidebar._rebuild_tree
                    ) as rebuild:
                        sidebar.load_conditions(refreshed, {}, "Project")
                        sidebar.show()
                        self.app.processEvents()
                        self.assertEqual(rebuild.call_count, 1)
                    expected = (
                        {"3", "5"}
                        if change == "rename"
                        else ({"3"} if change == "delete_current" else set())
                    )
                    self.assertEqual(
                        set(sidebar.get_selected_condition_uids()), expected
                    )
                    current = sidebar.tree.currentItem()
                    if change == "rename":
                        self.assertIs(current, sidebar._condition_items["5"])
                        self.assertEqual(current.text(1), "Updated 5")
                    else:
                        self.assertIsNone(current)
                    self.assertIs(sidebar._conditions, refreshed)
                finally:
                    sidebar.close()
                    delete(sidebar)

    def test_hidden_refresh_keeps_folder_current_without_losing_condition_selection(
        self,
    ):
        sidebar = ConditionsSidebar(None)
        try:
            sidebar.load_conditions(
                {"same": Condition(uid="same", name="Condition")},
                {"same": BidConditionFolder(uid="same", name="Folder")},
                "Project",
            )
            sidebar.show()
            self.app.processEvents()
            sidebar.tree.setCurrentItem(sidebar._condition_items["same"])
            sidebar._folder_items["same"].setSelected(True)
            sidebar.tree.setCurrentItem(
                sidebar._folder_items["same"],
                0,
                QtCore.QItemSelectionModel.SelectionFlag.NoUpdate,
            )
            sidebar.hide()
            sidebar.load_conditions(
                {"same": Condition(uid="same", name="New Condition")},
                {"same": BidConditionFolder(uid="same", name="New Folder")},
                "Project",
            )
            sidebar.show()
            self.app.processEvents()
            self.assertEqual(sidebar.get_selected_condition_uids(), ["same"])
            self.assertTrue(sidebar._folder_items["same"].isSelected())
            self.assertIs(sidebar.tree.currentItem(), sidebar._folder_items["same"])
            self.assertEqual(sidebar.tree.currentItem().text(0), "New Folder")
        finally:
            sidebar.close()
            delete(sidebar)


class ConditionsSidebarUnusedRowsTests(unittest.TestCase):
    def setUp(self):
        _app()
        self.service = ConditionSummaryService()
        self.condition = Condition(
            uid="c1",
            name="Fdn1",
            condition_type=Condition.TYPE_COUNT,
            height=24.0,
            color_fill=0x336699,
            cdn_type_uid="t1",
            cdn_type_name="AB - Spread Interior FTG",
            uom1=UOM_EACH,
            calc_type1=CALC_COUNT,
            ref_no=1,
        )
        self.conditions = {"c1": self.condition}
        self.pages = [Page(uid="p1", name="S-100.pdf", sequence=1)]
        self.areas = [
            BidArea(uid="a1", bid_uid="b1", parent_uid="", name="L-0 FDN", sequence=1),
            BidArea(uid="a2", bid_uid="b1", parent_uid="", name="L-2 FDN", sequence=2),
        ]
        self.takeoffs = [
            Takeoff(uid="tk1", condition_uid="c1", page_uid="p1", area_uid="a1"),
            Takeoff(uid="tk2", condition_uid="c1", page_uid="p1", area_uid="a2"),
        ]
        self.tab = ConditionSummaryTab(
            None,
            uom_label_fn=lambda code: "EA" if code == UOM_EACH else "",
            copy_allowed_fn=lambda: True,
            delete_allowed_fn=lambda: True,
        )
        self.header_controller = _attach_summary_header(self.tab)

    def tearDown(self):
        self.tab.deleteLater()

    def test_conditions_sidebar_still_shows_unused_conditions(self):
        sidebar = ConditionsSidebar(None, uom_label_fn=lambda _code: "")
        try:
            sidebar.load_conditions(
                {
                    "c1": self.condition,
                    "unused": Condition(uid="unused", name="Unused", ref_no=2),
                },
                {},
                "Project",
            )
            self.assertEqual(
                set(sidebar.collect_ordered_condition_uids()), {"c1", "unused"}
            )
        finally:
            sidebar.deleteLater()


class ConditionsSidebarZeroQuantityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_zero_remaining_quantity_keeps_the_condition_uom_visible(self):
        sidebar = ConditionsSidebar(
            None, uom_label_fn=lambda code: {7: "EA"}.get(code, "")
        )
        condition = Condition(uid="condition-1", name="Concrete", uom1=7)
        try:
            sidebar.load_conditions(
                {condition.uid: condition}, {}, "Bid", grayscale=False
            )
            sidebar.update_quantities({})
            item = sidebar._condition_items[condition.uid]
            self.assertEqual(item.text(2), "0 EA")
        finally:
            sidebar.deleteLater()
