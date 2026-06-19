import math
import os
import unittest
from dataclasses import fields
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsTextItem
from ost_visualizer.domain.entities import pattern as pattern_values
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.condition_folder import BidConditionFolder
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.condition_quantity_service import (
    compute_page_quantities,
)
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar
from ost_visualizer.presentation.components.area_combo import AreaComboBox
from ost_visualizer.presentation.dialogs.edit_condition_dialog import (
    EditConditionDialog,
)
from ost_visualizer.presentation.utils.view_context_menu import (
    build_selected_takeoff_context_state,
)
from ost_visualizer.presentation.visualization.pdf.renderers.takeoff_renderer import (
    TakeoffRenderer,
)
from tests.single_action import SingleCallRecorder


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class FakeReadService:
    def display_to_inches(self, text, _metric):
        try:
            return float(text)
        except ValueError:
            return None

    def inches_to_display(self, value, _metric):
        return "" if not value else str(value)

    def get_quantity_options_for_type(self, _condition_type):
        return []

    def get_valid_uoms_for_calc_type(self, _calc_type, _metric):
        return []


class FakeCoordinateSystem:
    page_info = {"view_scale": 1.0}

    def update_page_info(self, page_info):
        self.page_info.update(page_info)

    def parse_position(self, position):
        return list(position)

    def transform_vertices_to_2d(self, position):
        return list(position)

    def ost_to_pdf_points(self, value):
        return float(value)


class FakeColorService:
    def should_gray_out_takeoff(self, _takeoff, _page_area_selections):
        return False


class ConditionUiBehaviorTests(unittest.TestCase):
    def _path_line_angle(self, item):
        path = item.path()
        first = path.elementAt(0)
        second = path.elementAt(1)
        return math.atan2(second.y - first.y, second.x - first.x)

    def _line_path_items(self, items):
        return [
            item
            for item in items
            if isinstance(item, QGraphicsPathItem) and item.path().elementCount() >= 2
        ]

    def _path_midpoint(self, item):
        path = item.path()
        first = path.elementAt(0)
        second = path.elementAt(1)
        return ((first.x + second.x) / 2.0, (first.y + second.y) / 2.0)

    def _line_spacing(self, first_item, second_item):
        line_angle = self._path_line_angle(first_item)
        normal_angle = line_angle + math.pi / 2.0
        first_projection = self._point_projection(
            self._path_midpoint(first_item), normal_angle
        )
        second_projection = self._point_projection(
            self._path_midpoint(second_item), normal_angle
        )
        return abs(second_projection - first_projection)

    def _point_projection(self, point, angle):
        return point[0] * math.cos(angle) + point[1] * math.sin(angle)

    def _assert_parallel_angle(self, actual, expected):
        diff = abs((actual - expected + math.pi / 2.0) % math.pi - math.pi / 2.0)
        self.assertLess(diff, 0.01)

    def _render_takeoff_items(self, condition, takeoff):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        rendered = renderer.create_all_path_items(
            [takeoff],
            {condition.uid: condition},
            {condition.uid: SimpleNamespace(hex="#123456", opacity=1.0)},
        )
        items = rendered[0][1]
        return items if isinstance(items, list) else [items]

    def test_condition_entity_does_not_expose_label_style_fields(self):
        condition_fields = {field.name for field in fields(Condition)}
        self.assertFalse(
            {
                "name_font_name",
                "name_font_color",
                "name_font_size",
                "name_font_bold",
                "name_font_italic",
                "name_font_underline",
            }
            & condition_fields
        )

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

    def test_takeoff_renderer_creates_items_for_hidden_condition_layers(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        condition = Condition(
            uid="c1",
            name="Hidden Layer Condition",
            condition_type=Condition.TYPE_LINEAR,
            layer_visible=False,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 10.0, 0.0],
        )
        rendered = renderer.create_all_path_items(
            [takeoff],
            {"c1": condition},
            {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
        )
        self.assertEqual([uid for uid, _item in rendered], ["t1"])

    def test_condition_cut_paste_to_root_and_folder_uses_edit_permission(self):
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
        sidebar.set_edit_enabled(True)
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

    def test_area_combo_clears_deleted_selected_area_uid_on_reload(self):
        combo = AreaComboBox(None)
        combo.load_areas(
            [BidArea(uid="a1", bid_uid="b1", parent_uid="", name="Area 1", sequence=1)],
            selected_uid="a1",
        )
        self.assertEqual(combo.get_current_area_uid(), "a1")
        combo.load_areas([], selected_uid=None)
        self.assertEqual(combo.get_current_area_uid(), "")
        combo.set_current_area_uid("deleted")
        self.assertEqual(combo.get_current_area_uid(), "")

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

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

    def _make_dialog(self, condition):
        return EditConditionDialog(
            None,
            None,
            condition,
            ["c1"],
            {"c1": condition},
            {},
            {},
            lambda _uid: False,
            lambda _uid, _dto: True,
            read_service=FakeReadService(),
        )

    def test_edit_condition_ok_click_saves_once(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=1,
        )
        save_calls = SingleCallRecorder(
            lambda _uid, _dto: SimpleNamespace(success=True)
        )
        dialog = EditConditionDialog(
            None,
            None,
            condition,
            ["c1"],
            {"c1": condition},
            {},
            {},
            lambda _uid: False,
            save_calls,
            read_service=FakeReadService(),
        )
        dialog._name_edit.setText("Updated Condition")
        dialog._ok_btn.click()
        save_calls.assert_called_once(self, "Edit Condition OK click")
        self.assertEqual(save_calls.calls[0][0][0], "c1")
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        dialog.close()

    def test_edit_condition_dimension_inputs_use_consistent_heights(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_COUNT,
            height=12.0,
            width=24.0,
            depth=6.0,
            display_size=100.0,
        )
        dialog = self._make_dialog(condition)
        dialog.show()
        self.app.processEvents()
        expected_height = dialog._display_size_edit.height()
        self.assertEqual(dialog._dim_r0c1_stack.height(), expected_height)
        self.assertEqual(dialog._dim_r0c3_stack.height(), expected_height)
        self.assertEqual(dialog._height_edit.height(), expected_height)
        self.assertEqual(dialog._width_edit.height(), expected_height)
        dialog.close()

    def test_delete_key_invokes_condition_delete_for_tree_selection(self):
        sidebar, deleted = self._make_sidebar_with_selected_condition()
        sidebar.show()
        sidebar.tree.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        self.app.processEvents()
        QTest.keyClick(sidebar.tree, Qt.Key.Key_Delete)
        self.app.processEvents()
        self.assertEqual(deleted, [["c1"]])
        sidebar.close()

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

    def test_edit_condition_dialog_initializes_style_locked_when_takeoffs_exist(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_AREA,
            ref_no=1,
        )
        dialog = EditConditionDialog(
            None,
            None,
            condition,
            ["c1"],
            {"c1": condition},
            {},
            {},
            lambda uid: uid == "c1",
            lambda _uid, _dto: True,
            read_service=FakeReadService(),
        )
        self.assertFalse(dialog._style_combo.isEnabled())
        self.assertEqual(
            dialog._style_combo.toolTip(),
            "Condition style cannot be changed after takeoffs have been placed.",
        )
        dialog.close()

    def test_count_attachment_advanced_properties_show_only_display_name(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_COUNT,
            ref_no=1,
        )
        dialog = self._make_dialog(condition)
        self.assertIsNotNone(dialog._display_name_check)
        dialog.close()

    def test_linear_advanced_properties_show_measurement_controls(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=1,
        )
        dialog = self._make_dialog(condition)
        self.assertIsNotNone(dialog._round_qty_check)
        self.assertIsNotNone(dialog._round_to_edit)
        self.assertIsNotNone(dialog._drop_run_check)
        self.assertIsNotNone(dialog._add_length_edit)
        self.assertIsNotNone(dialog._trim_check)
        self.assertIsNotNone(dialog._curved_check)
        dialog.close()

    def test_linear_advanced_groups_use_equal_layout_stretch(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=1,
        )
        dialog = self._make_dialog(condition)
        layout = dialog._advanced_tab.layout()
        self.assertEqual(layout.count(), 2)
        self.assertEqual(layout.stretch(0), 1)
        self.assertEqual(layout.stretch(1), 1)
        self.assertEqual(layout.itemAt(0).widget().title(), "Measurement")
        self.assertEqual(layout.itemAt(1).widget().title(), "Properties")
        dialog.close()

    def test_area_advanced_properties_show_grid_and_display_controls(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_AREA,
            ref_no=1,
        )
        dialog = self._make_dialog(condition)
        self.assertIsNotNone(dialog._grid_check)
        self.assertIsNotNone(dialog._tile1_edit)
        self.assertIsNotNone(dialog._tile2_edit)
        self.assertIsNotNone(dialog._display_pattern_check)
        self.assertIsNotNone(dialog._display_dim_check)
        self.assertIsNotNone(dialog._display_name_check)
        dialog.close()

    def test_trim_disables_curved_segment_control(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            ref_no=1,
        )
        dialog = self._make_dialog(condition)
        dialog._trim_check.setChecked(True)
        self.assertFalse(dialog._curved_check.isChecked())
        self.assertFalse(dialog._curved_check.isEnabled())
        dialog._dirty = False
        dialog.close()

    def test_trim_condition_hides_curved_context_action(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_LINEAR,
            trim=True,
        )
        takeoff = Takeoff(uid="t1", condition_uid="c1", position=[0, 0, 12, 0])
        state = build_selected_takeoff_context_state(
            ["t1"], lambda _uid: takeoff, {"c1": condition}
        )
        self.assertFalse(state.show_curved)

    def test_new_area_condition_does_not_enable_display_dimension_by_default(self):
        condition = Condition(
            uid="c1",
            name="Condition 1",
            condition_type=Condition.TYPE_AREA,
            ref_no=1,
        )
        dialog = EditConditionDialog(
            None,
            None,
            condition,
            ["c1"],
            {"c1": condition},
            {},
            {},
            lambda _uid: False,
            lambda _uid, _dto: True,
            read_service=FakeReadService(),
        )
        dialog._populate_defaults_for_type(Condition.TYPE_AREA)
        self.assertFalse(dialog._display_dim_check.isChecked())
        dialog.close()

    def test_round_quantity_rounds_linear_and_area_results_without_mutating_geometry(
        self,
    ):
        linear = Condition(
            uid="linear",
            condition_type=Condition.TYPE_LINEAR,
            calc_type1=1,
            uom1=1,
            round_quantity=True,
            round_up=12.0,
        )
        area = Condition(
            uid="area",
            condition_type=Condition.TYPE_AREA,
            calc_type1=11,
            uom1=4,
            round_quantity=True,
            round_up=12.0,
        )
        linear_takeoff = Takeoff(
            uid="t1", condition_uid="linear", position=[0.0, 0.0, 13.0, 0.0]
        )
        area_takeoff = Takeoff(
            uid="t2",
            condition_uid="area",
            position=[0.0, 0.0, 13.0, 0.0, 13.0, 13.0, 0.0, 13.0],
        )
        results = compute_page_quantities(
            {"linear": linear, "area": area}, [linear_takeoff, area_takeoff]
        )
        self.assertEqual(results["linear"][0], 24.0)
        self.assertEqual(results["area"][0], 180.0)
        self.assertEqual(linear_takeoff.position, [0.0, 0.0, 13.0, 0.0])

    def test_display_name_dimension_and_grid_render_as_scene_items(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        condition = Condition(
            uid="c1",
            name="Area Label",
            condition_type=Condition.TYPE_AREA,
            color_fill=0,
            pattern=0,
            spacing=0.0,
            grid=True,
            grid_size1=3.0,
            grid_size2=3.0,
            display_name=True,
            display_dimension=True,
            calc_type1=11,
            uom1=4,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 12.0, 0.0, 12.0, 12.0, 0.0, 12.0],
        )
        rendered = renderer.create_all_path_items(
            [takeoff],
            {"c1": condition},
            {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
        )
        items = rendered[0][1]
        items = items if isinstance(items, list) else [items]
        text_items = [item for item in items if isinstance(item, QGraphicsTextItem)]
        grid_items = [
            item
            for item in items
            if isinstance(item, QGraphicsPathItem)
            and item.data(2) != "condition_label"
            and not item.path().boundingRect().isNull()
        ]
        dimension_label = next(
            item for item in text_items if item.data(3) == "display_dimension"
        )
        name_label = next(item for item in text_items if item.data(3) == "display_name")
        self.assertIn("Area Label", name_label.toPlainText())
        self.assertIn("144.00 SQ IN", dimension_label.toPlainText())
        name_center = name_label.mapToScene(name_label.boundingRect().center())
        dimension_center = dimension_label.mapToScene(
            dimension_label.boundingRect().center()
        )
        self.assertAlmostEqual(dimension_center.x(), 6.0)
        self.assertAlmostEqual(dimension_center.y(), 6.0)
        self.assertAlmostEqual(name_center.x(), dimension_center.x())
        self.assertGreater(name_center.y(), dimension_center.y())
        self.assertNotEqual(name_center, dimension_center)
        self.assertGreater(len(grid_items), 1)

    def test_linear_horizontal_pattern_follows_linear_direction(self):
        condition = Condition(
            uid="c1",
            condition_type=Condition.TYPE_LINEAR,
            color_fill=0,
            pattern=pattern_values.HORIZONTAL,
            spacing=2.0,
            thickness=8.0,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 20.0, 20.0],
        )
        items = self._render_takeoff_items(condition, takeoff)
        pattern_item = items[1]
        self._assert_parallel_angle(self._path_line_angle(pattern_item), math.pi / 4.0)

    def test_linear_vertical_pattern_is_perpendicular_to_linear_direction(self):
        condition = Condition(
            uid="c1",
            condition_type=Condition.TYPE_LINEAR,
            color_fill=0,
            pattern=pattern_values.VERTICAL,
            spacing=2.0,
            thickness=8.0,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 20.0, 20.0],
        )
        items = self._render_takeoff_items(condition, takeoff)
        pattern_item = items[1]
        self._assert_parallel_angle(self._path_line_angle(pattern_item), -math.pi / 4.0)

    def test_oriented_linear_diagonal_pattern_uses_configured_spacing(self):
        condition = Condition(
            uid="c1",
            condition_type=Condition.TYPE_LINEAR,
            color_fill=0,
            pattern=pattern_values.BACKWARD_DIAG,
            spacing=2.0,
            thickness=12.0,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 20.0, 20.0],
        )
        items = self._render_takeoff_items(condition, takeoff)
        pattern_items = self._line_path_items(items[1:])
        self.assertGreaterEqual(len(pattern_items), 2)
        self.assertAlmostEqual(
            self._line_spacing(pattern_items[0], pattern_items[1]), 2.0, delta=0.01
        )

    def test_fixed_axis_area_diagonal_pattern_keeps_configured_spacing(self):
        condition = Condition(
            uid="c1",
            condition_type=Condition.TYPE_AREA,
            color_fill=0,
            pattern=pattern_values.BACKWARD_DIAG,
            spacing=2.0,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 20.0, 0.0, 20.0, 20.0, 0.0, 20.0],
        )
        items = self._render_takeoff_items(condition, takeoff)
        pattern_items = self._line_path_items(items[1:])
        self.assertGreaterEqual(len(pattern_items), 2)
        self.assertAlmostEqual(
            self._line_spacing(pattern_items[0], pattern_items[1]), 2.0, delta=0.01
        )

    def test_area_display_name_uses_centroid_when_dimension_is_not_present(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        condition = Condition(
            uid="c1",
            name="Area Label",
            condition_type=Condition.TYPE_AREA,
            color_fill=0,
            pattern=0,
            spacing=0.0,
            display_name=True,
            display_dimension=False,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 12.0, 0.0, 12.0, 12.0, 0.0, 12.0],
        )
        rendered = renderer.create_all_path_items(
            [takeoff],
            {"c1": condition},
            {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
        )
        items = rendered[0][1]
        items = items if isinstance(items, list) else [items]
        name_label = next(
            item
            for item in items
            if isinstance(item, QGraphicsTextItem) and item.data(3) == "display_name"
        )
        name_center = name_label.mapToScene(name_label.boundingRect().center())
        self.assertAlmostEqual(name_center.x(), 6.0)
        self.assertAlmostEqual(name_center.y(), 6.0)

    def test_area_display_dimension_uses_negative_indicator_centroid_anchor(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        condition = Condition(
            uid="c1",
            name="Area Label",
            condition_type=Condition.TYPE_AREA,
            color_fill=0,
            pattern=0,
            spacing=0.0,
            display_dimension=True,
            calc_type1=11,
            uom1=4,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 12.0, 0.0, 12.0, 12.0, 0.0, 12.0],
            is_negative=True,
        )
        rendered = renderer.create_all_path_items(
            [takeoff],
            {"c1": condition},
            {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
        )
        items = rendered[0][1]
        items = items if isinstance(items, list) else [items]
        dimension_label = next(
            item
            for item in items
            if isinstance(item, QGraphicsTextItem)
            and item.data(3) == "display_dimension"
        )
        negative_box = next(
            item
            for item in items
            if isinstance(item, QGraphicsPathItem) and item.zValue() == 10
        )
        dimension_center = dimension_label.mapToScene(
            dimension_label.boundingRect().center()
        )
        self.assertEqual(dimension_center, negative_box.pos())

    def test_condition_label_style_fields_render_after_overlay_rebuild(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        condition = Condition(
            uid="c1",
            name="Area Label",
            condition_type=Condition.TYPE_AREA,
            display_name=True,
            display_dimension=True,
            calc_type1=11,
            uom1=4,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 12.0, 0.0, 12.0, 12.0, 0.0, 12.0],
            dimension_font_name="Segoe UI",
            dimension_font_color=0x332211,
            dimension_font_size=24,
            dimension_font_bold=True,
            dimension_font_italic=True,
            dimension_font_underline=True,
            name_font_name="Calibri",
            name_font_color=0x665544,
            name_font_size=18,
            name_font_bold=True,
            name_font_italic=False,
            name_font_underline=True,
        )
        rendered = renderer.create_all_path_items(
            [takeoff],
            {"c1": condition},
            {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
        )
        items = rendered[0][1]
        items = items if isinstance(items, list) else [items]
        dimension_label = next(
            item
            for item in items
            if isinstance(item, QGraphicsTextItem)
            and item.data(3) == "display_dimension"
        )
        name_label = next(
            item
            for item in items
            if isinstance(item, QGraphicsTextItem) and item.data(3) == "display_name"
        )
        self.assertEqual(dimension_label.defaultTextColor().name(), "#112233")
        self.assertEqual(dimension_label.font().family(), "Segoe UI")
        self.assertEqual(dimension_label.font().pointSize(), 24)
        self.assertTrue(dimension_label.font().bold())
        self.assertTrue(dimension_label.font().italic())
        self.assertTrue(dimension_label.font().underline())
        self.assertEqual(name_label.defaultTextColor().name(), "#445566")
        self.assertEqual(name_label.font().family(), "Calibri")
        self.assertEqual(name_label.font().pointSize(), 18)
        self.assertTrue(name_label.font().bold())
        self.assertFalse(name_label.font().italic())
        self.assertTrue(name_label.font().underline())


if __name__ == "__main__":
    unittest.main()
