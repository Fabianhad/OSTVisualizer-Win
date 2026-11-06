from ost_visualizer.domain.entities.workspace_state import (
    WORKSPACE_VALID_ACTIVE_VIEWS,
    HeaderLayoutState,
    TakeoffWorkspaceState,
    WorkspaceState,
)
import unittest


class WorkspaceStateSerializationTests(unittest.TestCase):
    def test_unsaved_and_explicitly_collapsed_project_expansion_remain_distinct_on_reload(
        self,
    ):
        for keys in (None, [], ["database:example"]):
            with self.subTest(keys=keys):
                state = WorkspaceState()
                state.project_workspace.expanded_node_keys = keys
                for _ in range(3):
                    state = WorkspaceState.from_dict(state.to_dict())
                    self.assertEqual(state.project_workspace.expanded_node_keys, keys)

    def test_workspace_active_view_constants_are_immutable_shared_state(self):
        self.assertIsInstance(TakeoffWorkspaceState.VALID_ACTIVE_VIEWS, frozenset)
        self.assertEqual(
            TakeoffWorkspaceState.VALID_ACTIVE_VIEWS, WORKSPACE_VALID_ACTIVE_VIEWS
        )
        self.assertEqual(WORKSPACE_VALID_ACTIVE_VIEWS, {"2d", "3d"})
        self.assertEqual(
            TakeoffWorkspaceState.from_dict({"active_view": "2D"}).active_view, "2d"
        )
        self.assertEqual(
            TakeoffWorkspaceState.from_dict({"active_view": "invalid"}).active_view,
            "3d",
        )

    def test_workspace_annotation_styles_round_trip_and_clamp_values(self):
        state = WorkspaceState.from_dict(
            {
                "takeoff_workspace": {
                    "annotation_styles": {
                        "arrow": {
                            "color": "336699",
                            "line_width": 99,
                        },
                        "rect": {
                            "color": "00aa00",
                            "line_width": 2,
                        },
                    }
                }
            }
        )
        self.assertEqual(
            state.takeoff_workspace.annotation_styles["arrow"].color, "#336699"
        )
        self.assertEqual(
            state.takeoff_workspace.annotation_styles["arrow"].line_width, 16.0
        )
        self.assertEqual(
            state.takeoff_workspace.annotation_styles["rect"].color, "#00aa00"
        )
        self.assertEqual(
            state.takeoff_workspace.annotation_styles["rect"].line_width, 2.0
        )
        payload = state.to_dict()
        self.assertEqual(
            payload["takeoff_workspace"]["annotation_styles"]["arrow"]["color"],
            "#336699",
        )
        self.assertEqual(
            payload["takeoff_workspace"]["annotation_styles"]["arrow"]["line_width"],
            16.0,
        )
        self.assertEqual(WorkspaceState.from_dict(payload), state)

    def test_workspace_annotation_styles_default_to_empty_map(self):
        state = WorkspaceState.from_dict({})
        self.assertEqual(state.takeoff_workspace.annotation_styles, {})

    def test_workspace_annotation_styles_recover_from_non_finite_integer_fields(self):
        state = WorkspaceState.from_dict(
            {
                "takeoff_workspace": {
                    "annotation_styles": {
                        "text": {
                            "font_size": float("inf"),
                            "text_align": float("-inf"),
                        }
                    }
                }
            }
        )
        style = state.takeoff_workspace.annotation_styles["text"]
        self.assertEqual(style.font_size, 12)
        self.assertEqual(style.text_align, 0)

    def test_workspace_summary_state_defaults_to_type_area_grouping(self):
        state = WorkspaceState.from_dict({})
        self.assertTrue(state.takeoff_workspace.summary_group_by_area)
        self.assertTrue(state.takeoff_workspace.summary_group_by_type)
        self.assertFalse(state.takeoff_workspace.summary_group_by_page)
        self.assertEqual(state.header_layouts, {})
        self.assertEqual(state.dialog_sizes, {})
        self.assertEqual(state.dialog_maximized, {})

    def test_workspace_dialog_window_state_round_trips_and_ignores_invalid_values(
        self,
    ):
        state = WorkspaceState.from_dict(
            {
                "dialog_sizes": {
                    "cover_sheet": ["900", "650"],
                    "zero_width": [0, 500],
                    "missing_height": [700],
                    "invalid": ["wide", "tall"],
                },
                "dialog_maximized": {
                    "cover_sheet": True,
                    "windowed": False,
                    "invalid": 1,
                },
            }
        )
        self.assertEqual(state.dialog_sizes, {"cover_sheet": [900, 650]})
        self.assertEqual(
            state.dialog_maximized,
            {"cover_sheet": True, "windowed": False},
        )
        self.assertEqual(
            state.to_dict()["dialog_sizes"],
            {"cover_sheet": [900, 650]},
        )
        self.assertEqual(
            state.to_dict()["dialog_maximized"],
            {"cover_sheet": True, "windowed": False},
        )

    def test_workspace_semantic_header_state_round_trips_and_ignores_invalid_values(
        self,
    ):
        state = WorkspaceState.from_dict(
            {
                "takeoff_workspace": {
                    "summary_group_by_area": False,
                    "summary_group_by_type": True,
                    "summary_group_by_page": True,
                },
                "header_layouts": {
                    "condition_summary": {
                        "widths": {
                            "name": "220",
                            "area": 0,
                            "notes": 5000,
                            "quantity_1": "bad",
                        },
                        "order": ["name", "area"],
                        "sort_column": "name",
                        "sort_descending": True,
                    },
                },
            }
        )
        self.assertFalse(state.takeoff_workspace.summary_group_by_area)
        self.assertTrue(state.takeoff_workspace.summary_group_by_type)
        self.assertTrue(state.takeoff_workspace.summary_group_by_page)
        layout = state.header_layouts["condition_summary"]
        self.assertEqual(layout.widths, {"name": 220})
        self.assertEqual(layout.order, ["name", "area"])
        self.assertEqual(layout.sort_column, "name")
        self.assertTrue(layout.sort_descending)
        payload = state.to_dict()
        self.assertEqual(
            payload["header_layouts"]["condition_summary"]["widths"],
            {"name": 220},
        )
        takeoff_payload = payload["takeoff_workspace"]
        self.assertFalse(takeoff_payload["summary_group_by_area"])
        self.assertTrue(takeoff_payload["summary_group_by_type"])
        self.assertTrue(takeoff_payload["summary_group_by_page"])

    def test_corrupt_header_order_resets_only_that_header_layout(self):
        state = WorkspaceState.from_dict(
            {
                "header_layouts": {
                    "corrupt": {
                        "widths": {"name": 220},
                        "order": ["name", "name"],
                        "sort_column": "name",
                        "sort_descending": True,
                    },
                    "valid": {
                        "widths": {"name": 230},
                        "order": ["name"],
                        "sort_column": "name",
                        "sort_descending": False,
                    },
                }
            }
        )
        self.assertEqual(state.header_layouts["corrupt"], HeaderLayoutState())
        self.assertEqual(state.header_layouts["valid"].widths, {"name": 230})

    def test_workspace_dropdown_popup_sizes_ignore_invalid_values(self):
        state = WorkspaceState.from_dict(
            {
                "takeoff_workspace": {
                    "dropdown_popup_sizes": {
                        "annotation_page": [0, 360],
                        "view_page": ["700", "500"],
                        "main_page": ["bad", 400],
                    }
                }
            }
        )
        self.assertEqual(
            state.takeoff_workspace.dropdown_popup_sizes,
            {"view_page": [700, 500]},
        )

    def test_workspace_detached_window_missing_fullscreen_defaults_false(self):
        state = WorkspaceState.from_dict(
            {
                "detached_windows": {
                    "annotation_view": {
                        "open": True,
                        "geometry_b64": "saved-geometry",
                        "is_maximized": False,
                    }
                }
            }
        )
        annotation_state = state.detached_windows.annotation_view
        self.assertTrue(annotation_state.open)
        self.assertEqual(annotation_state.geometry_b64, "saved-geometry")
        self.assertFalse(annotation_state.is_maximized)
        self.assertFalse(annotation_state.is_fullscreen)

    def test_workspace_invalid_boolean_scalars_use_field_defaults(self):
        state = WorkspaceState.from_dict(
            {
                "main_window": {
                    "is_maximized": "false",
                    "status_bar_visible": 0,
                },
                "takeoff_workspace": {
                    "view_2d_tab_visible": [],
                    "summary_group_by_page": "true",
                },
                "toolbar_visibility": {
                    "main_toolbar_visible": 0,
                },
                "detached_windows": {
                    "annotation_view": {
                        "open": 1,
                        "is_maximized": "true",
                        "is_fullscreen": {},
                    }
                },
            }
        )
        self.assertTrue(state.main_window.is_maximized)
        self.assertTrue(state.main_window.status_bar_visible)
        self.assertTrue(state.takeoff_workspace.view_2d_tab_visible)
        self.assertFalse(state.takeoff_workspace.summary_group_by_page)
        self.assertTrue(state.toolbar_visibility.main_toolbar_visible)
        self.assertFalse(state.detached_windows.annotation_view.open)
        self.assertFalse(state.detached_windows.annotation_view.is_maximized)
        self.assertFalse(state.detached_windows.annotation_view.is_fullscreen)


class PanSidebarWorkspaceStateTests(unittest.TestCase):
    def test_pan_sidebar_defaults_to_hidden_with_no_saved_sizes(self):
        state = TakeoffWorkspaceState()
        self.assertIs(state.pan_sidebar_visible, False)
        self.assertEqual(state.left_column_pan_first_sizes, [])
        payload = state.to_dict()
        self.assertIs(payload["pan_sidebar_visible"], False)
        self.assertEqual(payload["left_column_pan_first_sizes"], [])

    def test_visibility_and_vertical_sizes_round_trip(self):
        state = WorkspaceState()
        state.takeoff_workspace.pan_sidebar_visible = True
        state.takeoff_workspace.left_column_pan_first_sizes = [640, 220]
        restored = WorkspaceState.from_dict(state.to_dict())
        self.assertIs(restored.takeoff_workspace.pan_sidebar_visible, True)
        self.assertEqual(
            restored.takeoff_workspace.left_column_pan_first_sizes, [640, 220]
        )
        again = WorkspaceState.from_dict(restored.to_dict())
        self.assertEqual(again.to_dict(), restored.to_dict())

    def test_old_files_without_the_keys_load_with_the_defaults(self):
        old = TakeoffWorkspaceState.from_dict(
            {
                "conditions_sidebar_visible": False,
                "layers_sidebar_visible": True,
                "left_splitter_sizes": [300, 200],
            }
        )
        self.assertIs(old.pan_sidebar_visible, False)
        self.assertEqual(old.left_column_pan_first_sizes, [])
        self.assertIs(old.conditions_sidebar_visible, False)
        self.assertEqual(old.left_splitter_sizes, [300, 200])

    def test_invalid_values_fall_back_without_touching_the_siblings(self):
        state = TakeoffWorkspaceState.from_dict(
            {
                "pan_sidebar_visible": "yes",
                "left_column_pan_first_sizes": ["a", -5, 7.9, None],
                "layers_sidebar_visible": False,
            }
        )
        self.assertIs(state.pan_sidebar_visible, False)
        self.assertEqual(state.left_column_pan_first_sizes, [0, 7])
        self.assertIs(state.layers_sidebar_visible, False)

    def test_the_sibling_sidebar_keys_still_round_trip(self):
        state = TakeoffWorkspaceState(
            conditions_sidebar_visible=False,
            layers_sidebar_visible=False,
            left_splitter_sizes=[1, 2],
            pan_sidebar_visible=True,
        )
        restored = TakeoffWorkspaceState.from_dict(state.to_dict())
        self.assertEqual(restored, state)


class WorkspaceFontColorCompatibilityTests(unittest.TestCase):
    def test_legacy_workspace_overlap_is_ignored_and_stripped(self):
        state = TakeoffWorkspaceState.from_dict(
            {
                "annotation_styles": {
                    "text": {
                        "color": "#123456",
                        "font_name": "Legacy",
                        "font_size": 33,
                        "text_align": 2,
                    },
                    "dimension": {"color": "#654321"},
                    "highlight": {"color": "#111111"},
                    "hotlink": {"color": "#222222"},
                    "rect": {"color": "#abcdef", "line_width": 7},
                }
            }
        )
        self.assertEqual(state.annotation_styles["text"].text_align, 2)
        self.assertEqual(state.annotation_styles["text"].color, "#ff0000")
        self.assertNotIn("dimension", state.annotation_styles)
        self.assertNotIn("highlight", state.annotation_styles)
        self.assertNotIn("hotlink", state.annotation_styles)
        serialized = state.to_dict()["annotation_styles"]
        self.assertEqual(serialized["text"], {"text_align": 2})
        self.assertEqual(serialized["rect"]["color"], "#abcdef")


class WorkspaceCorruptDimensionTests(unittest.TestCase):
    def test_nonfinite_schema_version_uses_current_schema_without_losing_other_state(
        self,
    ):
        for invalid in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(invalid=invalid):
                state = WorkspaceState.from_dict(
                    {"schema_version": invalid, "dialog_sizes": {"valid": [900, 650]}}
                )
                self.assertEqual(
                    state.schema_version, WorkspaceState.CURRENT_SCHEMA_VERSION
                )
                self.assertEqual(state.dialog_sizes, {"valid": [900, 650]})

    def test_nonfinite_saved_sizes_do_not_abort_unrelated_workspace_restoration(self):
        for invalid in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(invalid=invalid):
                state = WorkspaceState.from_dict(
                    {
                        "dialog_sizes": {"bad": [invalid, 500], "valid": [900, 650]},
                        "takeoff_workspace": {
                            "takeoff_splitter_sizes": [300, invalid, 400]
                        },
                    }
                )
                self.assertEqual(state.dialog_sizes, {"valid": [900, 650]})
                self.assertEqual(
                    state.takeoff_workspace.takeoff_splitter_sizes, [300, 400]
                )

    def test_nonfinite_header_widths_do_not_discard_valid_sibling_columns(self):
        for invalid in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(invalid=invalid):
                state = WorkspaceState.from_dict(
                    {
                        "header_layouts": {
                            "summary": {
                                "widths": {"name": 220, "invalid": invalid},
                                "order": ["name"],
                            }
                        }
                    }
                )
                self.assertEqual(state.header_layouts["summary"].widths, {"name": 220})
                self.assertEqual(state.header_layouts["summary"].order, ["name"])


from ost_visualizer.domain.entities import workspace_state as ws
from ost_visualizer.domain.entities.annotation_style import AnnotationStyle


def custom_workspace():
    state = WorkspaceState()
    state.main_window = ws.MainWindowWorkspaceState("Z2VvbQ==", "c3RhdGU=", False, False)
    state.takeoff_workspace = TakeoffWorkspaceState(
        active_view="2d",
        view_2d_tab_visible=False,
        view_3d_tab_visible=False,
        conditions_sidebar_visible=False,
        layers_sidebar_visible=False,
        takeoff_splitter_sizes=[300, 700],
        left_splitter_sizes=[120, 480],
        pan_sidebar_visible=True,
        left_column_pan_first_sizes=[90, 210],
        dropdown_popup_sizes={"conditions": [320, 240]},
        conditions_group_by_type=False,
        summary_group_by_area=False,
        summary_group_by_type=False,
        summary_group_by_page=True,
        annotation_styles={"rect": AnnotationStyle(color="#123456", line_width=6.0)},
    )
    state.project_workspace = ws.ProjectWorkspaceState(
        expanded_node_keys=["db:1", "bid:2"],
        group_by_job_status=True,
        selected_node=ws.ProjectTreeSelectionState("bid", "C:/a.mdb", bid_uid="7"),
    )
    state.toolbar_visibility = ws.ToolbarVisibilityState(False, False, False)
    state.detached_windows = ws.DetachedWindowsState(
        mesh_view=ws.DetachedWindowState(True, "bWVzaA==", True, False),
        annotation_view=ws.DetachedWindowState(True, "YW5u", False, True),
        view_window=ws.DetachedWindowState(False, "dmlldw==", True, True),
    )
    state.header_layouts = {
        "tree": HeaderLayoutState({"name": 120, "qty": 80}, ["name", "qty"], "qty", True)
    }
    state.dialog_sizes = {"layers": [640, 480]}
    state.dialog_maximized = {"layers": True, "areas": False}
    return state


class WorkspaceStateFullRoundTripTests(unittest.TestCase):
    def test_every_section_round_trips_from_a_non_default_value_with_the_stored_key_names(self):
        state = custom_workspace()
        payload = state.to_dict()
        self.assertEqual(
            set(payload),
            {
                "schema_version",
                "main_window",
                "takeoff_workspace",
                "project_workspace",
                "toolbar_visibility",
                "detached_windows",
                "header_layouts",
                "dialog_sizes",
                "dialog_maximized",
            },
        )
        self.assertEqual(payload["schema_version"], 3)
        self.assertEqual(
            payload["main_window"],
            {"geometry_b64": "Z2VvbQ==", "state_b64": "c3RhdGU=", "is_maximized": False, "status_bar_visible": False},
        )
        self.assertEqual(
            payload["toolbar_visibility"],
            {"main_toolbar_visible": False, "view_toolbar_visible": False, "plan_tools_toolbar_visible": False},
        )
        self.assertEqual(
            payload["project_workspace"],
            {
                "expanded_node_keys": ["db:1", "bid:2"],
                "group_by_job_status": True,
                "selected_node": {"kind": "bid", "file_path": "C:/a.mdb", "bid_uid": "7", "project_uid": None},
            },
        )
        self.assertEqual(
            payload["detached_windows"]["annotation_view"],
            {"open": True, "geometry_b64": "YW5u", "is_maximized": False, "is_fullscreen": True},
        )
        self.assertEqual(set(payload["detached_windows"]), {"mesh_view", "annotation_view", "view_window"})
        self.assertEqual(
            payload["header_layouts"],
            {"tree": {"widths": {"name": 120, "qty": 80}, "order": ["name", "qty"], "sort_column": "qty", "sort_descending": True}},
        )
        self.assertEqual(payload["dialog_sizes"], {"layers": [640, 480]})
        self.assertEqual(payload["dialog_maximized"], {"layers": True, "areas": False})
        restored = WorkspaceState.from_dict(payload)
        self.assertEqual(restored, state)
        self.assertEqual(restored.to_dict(), payload)

    def test_takeoff_section_payload_has_every_key_and_round_trips(self):
        takeoff = custom_workspace().takeoff_workspace
        payload = takeoff.to_dict()
        self.assertEqual(
            set(payload),
            {
                "active_view",
                "view_2d_tab_visible",
                "view_3d_tab_visible",
                "conditions_sidebar_visible",
                "layers_sidebar_visible",
                "takeoff_splitter_sizes",
                "left_splitter_sizes",
                "pan_sidebar_visible",
                "left_column_pan_first_sizes",
                "dropdown_popup_sizes",
                "conditions_group_by_type",
                "summary_group_by_area",
                "summary_group_by_type",
                "summary_group_by_page",
                "annotation_styles",
            },
        )
        self.assertEqual(TakeoffWorkspaceState.from_dict(payload), takeoff)
        for name, value in payload.items():
            if name == "annotation_styles":
                continue
            with self.subTest(key=name):
                single = TakeoffWorkspaceState.from_dict({name: value})
                self.assertEqual(single.to_dict()[name], value)

    def test_defaults_are_the_documented_first_run_layout(self):
        state = WorkspaceState()
        self.assertEqual(state.schema_version, 3)
        self.assertEqual(WorkspaceState.CURRENT_SCHEMA_VERSION, 3)
        self.assertEqual(
            (state.main_window.geometry_b64, state.main_window.state_b64, state.main_window.is_maximized, state.main_window.status_bar_visible),
            (None, None, True, True),
        )
        takeoff = state.takeoff_workspace
        self.assertEqual(
            (
                takeoff.active_view,
                takeoff.view_2d_tab_visible,
                takeoff.view_3d_tab_visible,
                takeoff.conditions_sidebar_visible,
                takeoff.layers_sidebar_visible,
                takeoff.pan_sidebar_visible,
                takeoff.conditions_group_by_type,
                takeoff.summary_group_by_area,
                takeoff.summary_group_by_type,
                takeoff.summary_group_by_page,
            ),
            ("3d", True, True, True, True, False, True, True, True, False),
        )
        self.assertEqual(
            (takeoff.takeoff_splitter_sizes, takeoff.left_splitter_sizes, takeoff.left_column_pan_first_sizes, takeoff.dropdown_popup_sizes, takeoff.annotation_styles),
            ([], [], [], {}, {}),
        )
        project = state.project_workspace
        self.assertEqual((project.expanded_node_keys, project.group_by_job_status, project.selected_node), (None, False, None))
        self.assertEqual(
            (state.toolbar_visibility.main_toolbar_visible, state.toolbar_visibility.view_toolbar_visible, state.toolbar_visibility.plan_tools_toolbar_visible),
            (True, True, True),
        )
        for window in (state.detached_windows.mesh_view, state.detached_windows.annotation_view, state.detached_windows.view_window):
            self.assertEqual((window.open, window.geometry_b64, window.is_maximized, window.is_fullscreen), (False, None, False, False))
        self.assertEqual((state.header_layouts, state.dialog_sizes, state.dialog_maximized), ({}, {}, {}))
        self.assertIsNot(WorkspaceState().takeoff_workspace, state.takeoff_workspace)

    def test_empty_and_non_object_documents_load_as_defaults(self):
        for value in (None, [], "x", 5, {}):
            with self.subTest(value=value):
                self.assertEqual(WorkspaceState.from_dict(value), WorkspaceState())
        for section in (
            ws.MainWindowWorkspaceState,
            TakeoffWorkspaceState,
            ws.ProjectWorkspaceState,
            ws.ToolbarVisibilityState,
            ws.DetachedWindowsState,
            ws.DetachedWindowState,
            HeaderLayoutState,
        ):
            for value in (None, [], "x", 5):
                with self.subTest(section=section.__name__, value=value):
                    self.assertEqual(section.from_dict(value), section())

    def test_schema_version_is_at_least_one_and_unusable_values_use_the_current_version(self):
        self.assertEqual(WorkspaceState.from_dict({"schema_version": 5}).schema_version, 5)
        self.assertEqual(WorkspaceState.from_dict({"schema_version": "2"}).schema_version, 2)
        self.assertEqual(WorkspaceState.from_dict({"schema_version": 0}).schema_version, 1)
        self.assertEqual(WorkspaceState.from_dict({"schema_version": -4}).schema_version, 1)
        self.assertEqual(WorkspaceState.from_dict({"schema_version": 1}).schema_version, 1)
        self.assertEqual(WorkspaceState.from_dict({"schema_version": "x"}).schema_version, 3)
        self.assertEqual(WorkspaceState.from_dict({"schema_version": None}).schema_version, 3)
        # The written version is always the current schema, whatever was read.
        self.assertEqual(WorkspaceState.from_dict({"schema_version": 9}).to_dict()["schema_version"], 3)


class WorkspaceStateCoercionTests(unittest.TestCase):
    def test_optional_text_treats_empty_and_none_as_absent_and_stringifies_the_rest(self):
        self.assertIsNone(ws._coerce_optional_str(None))
        self.assertIsNone(ws._coerce_optional_str(""))
        self.assertEqual(ws._coerce_optional_str(5), "5")
        self.assertEqual(ws._coerce_optional_str(0), "0")
        self.assertEqual(ws._coerce_optional_str(" x "), " x ")
        main = ws.MainWindowWorkspaceState.from_dict({"geometry_b64": "", "state_b64": 7})
        self.assertEqual((main.geometry_b64, main.state_b64), (None, "7"))

    def test_booleans_must_be_real_booleans_otherwise_the_field_default_applies(self):
        for value in (1, 0, "true", None, [], {}):
            self.assertIs(ws._coerce_bool(value, True), True)
            self.assertIs(ws._coerce_bool(value, False), False)
        self.assertIs(ws._coerce_bool(False, True), False)
        self.assertIs(ws._coerce_bool(True, False), True)

    def test_integer_lists_clamp_negatives_skip_junk_and_reject_non_lists(self):
        self.assertEqual(ws._coerce_int_list([5, "7", 3.9, -2, None, "x", [1]]), [5, 7, 3, 0])
        self.assertEqual(ws._coerce_int_list([]), [])
        for value in (None, (1, 2), "12", {"a": 1}, 5):
            self.assertEqual(ws._coerce_int_list(value), [])
        self.assertEqual(ws._coerce_int_list([float("inf"), 2, float("nan")]), [2])

    def test_size_dictionaries_keep_only_positive_pairs_truncated_to_two_values(self):
        self.assertEqual(
            ws._coerce_size_dict(
                {"ok": [640, 480], "long": [1, 2, 3], "zero_w": [0, 5], "zero_h": [5, 0], "neg": [-5, 5], "short": [5], "text": "x", 3: [2, 2], "strs": ["7", "8"]}
            ),
            {"ok": [640, 480], "long": [1, 2], "3": [2, 2], "strs": [7, 8]},
        )
        for value in (None, [], "x", 5):
            self.assertEqual(ws._coerce_size_dict(value), {})
        self.assertEqual(ws._coerce_size_dict({"one": [1, 1]}), {"one": [1, 1]})

    def test_boolean_dictionaries_keep_only_real_boolean_values_with_text_keys(self):
        self.assertEqual(
            ws._coerce_bool_dict({"a": True, "b": False, "c": 1, "d": "x", 5: True}),
            {"a": True, "b": False, "5": True},
        )
        for value in (None, [], "x", 5):
            self.assertEqual(ws._coerce_bool_dict(value), {})

    def test_positive_integer_dictionaries_convert_text_and_drop_non_positive_values(self):
        self.assertEqual(
            ws._coerce_positive_int_dict({"a": 5, "b": "7", "c": 0, "d": -3, "e": "x", "f": None, "g": 1, "h": 2.9, 4: 6}),
            {"a": 5, "b": 7, "g": 1, "h": 2, "4": 6},
        )
        self.assertEqual(ws._coerce_positive_int_dict({"inf": float("inf")}), {})
        for value in (None, [], "x"):
            self.assertEqual(ws._coerce_positive_int_dict(value), {})

    def test_string_lists_drop_empty_items_and_stringify_the_rest(self):
        self.assertEqual(ws._coerce_str_list(["a", "", None, 3, 0, "b"]), ["a", "3", "0", "b"])
        for value in (None, "ab", ("a",), {"a"}, 5):
            self.assertEqual(ws._coerce_str_list(value), [])
        self.assertEqual(ws._coerce_str_list([]), [])

    def test_header_order_must_be_a_list_of_distinct_non_empty_strings(self):
        self.assertEqual(ws._coerce_header_order(["a", "b"]), ["a", "b"])
        self.assertEqual(ws._coerce_header_order([]), [])
        returned = ["a"]
        self.assertIsNot(ws._coerce_header_order(returned), returned)
        for value in (None, "ab", ("a",), ["a", "a"], ["a", ""], ["a", 1], [None], ["", ""]):
            self.assertIsNone(ws._coerce_header_order(value), value)


class WorkspaceStateSectionTests(unittest.TestCase):
    def test_dialog_sizes_and_flags_are_cleaned_on_write_and_on_read(self):
        state = WorkspaceState(
            dialog_sizes={"ok": [640, 480], "bad": [0, 5], "long": [1, 2, 3]},
            dialog_maximized={"a": True, "b": 1},
        )
        payload = state.to_dict()
        self.assertEqual(payload["dialog_sizes"], {"ok": [640, 480], "long": [1, 2]})
        self.assertEqual(payload["dialog_maximized"], {"a": True})
        loaded = WorkspaceState.from_dict(
            {"dialog_sizes": {"x": [5, 6, 7], "y": [1]}, "dialog_maximized": {"x": False, "y": "no"}}
        )
        self.assertEqual((loaded.dialog_sizes, loaded.dialog_maximized), ({"x": [5, 6]}, {"x": False}))
        for key in ("dialog_sizes", "dialog_maximized", "header_layouts"):
            for bad in (None, [], "x"):
                self.assertEqual(getattr(WorkspaceState.from_dict({key: bad}), key), {})

    def test_header_layout_widths_are_limited_to_30_through_2000_and_sort_is_normalized(self):
        layout = HeaderLayoutState.from_dict(
            {
                "widths": {"lo": 29, "min": 30, "mid": 100, "max": 2000, "hi": 2001, "text": "250", "bad": "x", "zero": 0},
                "order": ["a", "b"],
                "sort_column": 5,
                "sort_descending": True,
            }
        )
        self.assertEqual(layout.widths, {"min": 30, "mid": 100, "max": 2000, "text": 250})
        self.assertEqual((layout.order, layout.sort_column, layout.sort_descending), (["a", "b"], "5", True))
        written = HeaderLayoutState({"lo": 29, "min": 30, "max": 2000, "hi": 2001}, ["a"], "", 1).to_dict()
        self.assertEqual(written, {"widths": {"min": 30, "max": 2000}, "order": ["a"], "sort_column": None, "sort_descending": True})
        self.assertIs(HeaderLayoutState.from_dict({"order": [], "sort_descending": 1}).sort_descending, False)
        self.assertIs(HeaderLayoutState().sort_descending, False)

    def test_a_corrupt_header_order_resets_the_layout_on_read_and_write(self):
        self.assertEqual(HeaderLayoutState.from_dict({"order": ["a", "a"], "widths": {"a": 100}}), HeaderLayoutState())
        self.assertEqual(
            HeaderLayoutState(widths={"a": 100}, order=["a", "a"], sort_column="a", sort_descending=True).to_dict(),
            {"widths": {}, "order": [], "sort_column": None, "sort_descending": False},
        )
        self.assertEqual(HeaderLayoutState.from_dict({"widths": {"a": 100}}).order, [])

    def test_selected_node_requires_a_known_kind_a_path_and_the_identifier_its_kind_needs(self):
        parse = ws.ProjectTreeSelectionState.from_dict
        self.assertEqual(parse({"kind": "database", "file_path": "C:/a.mdb"}), ws.ProjectTreeSelectionState("database", "C:/a.mdb"))
        self.assertEqual(
            parse({"kind": "bid", "file_path": "C:/a.mdb", "bid_uid": 7, "project_uid": "9"}),
            ws.ProjectTreeSelectionState("bid", "C:/a.mdb", bid_uid="7", project_uid=None),
        )
        self.assertEqual(
            parse({"kind": "project", "file_path": "C:/a.mdb", "bid_uid": "3", "project_uid": "9"}),
            ws.ProjectTreeSelectionState("project", "C:/a.mdb", bid_uid=None, project_uid="9"),
        )
        self.assertEqual(
            parse({"kind": "database", "file_path": "C:/a.mdb", "bid_uid": "3", "project_uid": "9"}),
            ws.ProjectTreeSelectionState("database", "C:/a.mdb"),
        )
        rejected = (
            None,
            [],
            "x",
            {},
            {"kind": "folder", "file_path": "C:/a.mdb"},
            {"kind": None, "file_path": "C:/a.mdb"},
            {"kind": "database", "file_path": ""},
            {"kind": "database"},
            {"kind": "bid", "file_path": "C:/a.mdb"},
            {"kind": "bid", "file_path": "C:/a.mdb", "bid_uid": ""},
            {"kind": "bid", "file_path": "C:/a.mdb", "project_uid": "9"},
            {"kind": "project", "file_path": "C:/a.mdb"},
            {"kind": "project", "file_path": "C:/a.mdb", "bid_uid": "3"},
            {"kind": "project", "file_path": "", "project_uid": "9"},
        )
        for data in rejected:
            with self.subTest(data=data):
                self.assertIsNone(parse(data))
        self.assertEqual(
            ws.ProjectTreeSelectionState("bid", "p", "7").to_dict(),
            {"kind": "bid", "file_path": "p", "bid_uid": "7", "project_uid": None},
        )

    def test_project_workspace_distinguishes_missing_from_empty_expansion_and_cleans_items(self):
        loaded = ws.ProjectWorkspaceState.from_dict({"expanded_node_keys": ["a", "", None, 3], "group_by_job_status": 1})
        self.assertEqual(loaded.expanded_node_keys, ["a", "3"])
        self.assertIs(loaded.group_by_job_status, False)
        self.assertEqual(ws.ProjectWorkspaceState.from_dict({"expanded_node_keys": []}).expanded_node_keys, [])
        self.assertIsNone(ws.ProjectWorkspaceState.from_dict({}).expanded_node_keys)
        self.assertEqual(ws.ProjectWorkspaceState.from_dict({"expanded_node_keys": "ab"}).expanded_node_keys, [])
        self.assertIs(ws.ProjectWorkspaceState.from_dict({"group_by_job_status": True}).group_by_job_status, True)
        selected = {"kind": "database", "file_path": "C:/a.mdb"}
        state = ws.ProjectWorkspaceState.from_dict({"selected_node": selected})
        self.assertEqual(state.selected_node, ws.ProjectTreeSelectionState("database", "C:/a.mdb"))
        self.assertEqual(state.to_dict()["selected_node"], {"kind": "database", "file_path": "C:/a.mdb", "bid_uid": None, "project_uid": None})
        self.assertIsNone(ws.ProjectWorkspaceState().to_dict()["selected_node"])
        keys = ["x"]
        written = ws.ProjectWorkspaceState(expanded_node_keys=keys).to_dict()["expanded_node_keys"]
        self.assertEqual(written, ["x"])
        self.assertIsNot(written, keys)

    def test_each_boolean_scalar_has_its_own_default_when_invalid(self):
        bad = 1
        main = ws.MainWindowWorkspaceState.from_dict({"is_maximized": bad, "status_bar_visible": bad})
        self.assertEqual((main.is_maximized, main.status_bar_visible), (True, True))
        takeoff = TakeoffWorkspaceState.from_dict(
            {
                key: bad
                for key in (
                    "view_2d_tab_visible",
                    "view_3d_tab_visible",
                    "conditions_sidebar_visible",
                    "layers_sidebar_visible",
                    "pan_sidebar_visible",
                    "conditions_group_by_type",
                    "summary_group_by_area",
                    "summary_group_by_type",
                    "summary_group_by_page",
                )
            }
        )
        self.assertEqual(takeoff, TakeoffWorkspaceState())
        toolbar = ws.ToolbarVisibilityState.from_dict(
            {"main_toolbar_visible": bad, "view_toolbar_visible": bad, "plan_tools_toolbar_visible": bad}
        )
        self.assertEqual(toolbar, ws.ToolbarVisibilityState())
        window = ws.DetachedWindowState.from_dict({"open": bad, "is_maximized": bad, "is_fullscreen": bad, "geometry_b64": ""})
        self.assertEqual(window, ws.DetachedWindowState())
        explicit = ws.ToolbarVisibilityState.from_dict(
            {"main_toolbar_visible": False, "view_toolbar_visible": False, "plan_tools_toolbar_visible": False}
        )
        self.assertEqual((explicit.main_toolbar_visible, explicit.view_toolbar_visible, explicit.plan_tools_toolbar_visible), (False, False, False))

    def test_detached_windows_load_each_window_independently(self):
        loaded = ws.DetachedWindowsState.from_dict(
            {
                "mesh_view": {"open": True, "geometry_b64": "m"},
                "annotation_view": {"is_maximized": True},
                "view_window": {"is_fullscreen": True},
            }
        )
        self.assertEqual(loaded.mesh_view, ws.DetachedWindowState(True, "m", False, False))
        self.assertEqual(loaded.annotation_view, ws.DetachedWindowState(False, None, True, False))
        self.assertEqual(loaded.view_window, ws.DetachedWindowState(False, None, False, True))
        self.assertEqual(ws.DetachedWindowState.from_dict({}), ws.DetachedWindowState())
        self.assertEqual(ws.DetachedWindowsState.from_dict({}), ws.DetachedWindowsState())

    def test_takeoff_workspace_lists_and_dropdown_sizes_follow_the_coercion_rules(self):
        loaded = TakeoffWorkspaceState.from_dict(
            {
                "takeoff_splitter_sizes": [1, "2", -3],
                "left_splitter_sizes": "x",
                "left_column_pan_first_sizes": [4, None],
                "dropdown_popup_sizes": {"a": [10, 20, 30], "b": [0, 5]},
                "active_view": 5,
            }
        )
        self.assertEqual(loaded.takeoff_splitter_sizes, [1, 2, 0])
        self.assertEqual(loaded.left_splitter_sizes, [])
        self.assertEqual(loaded.left_column_pan_first_sizes, [4])
        self.assertEqual(loaded.dropdown_popup_sizes, {"a": [10, 20]})
        self.assertEqual(loaded.active_view, "3d")
        self.assertEqual(TakeoffWorkspaceState.from_dict({"active_view": "2D"}).active_view, "2d")
        self.assertEqual(TakeoffWorkspaceState.from_dict({"active_view": "3D"}).active_view, "3d")
        self.assertEqual(
            TakeoffWorkspaceState(dropdown_popup_sizes={1: [3, 4]}).to_dict()["dropdown_popup_sizes"], {"1": [3, 4]}
        )
        lists = TakeoffWorkspaceState(takeoff_splitter_sizes=[1, 2]).to_dict()["takeoff_splitter_sizes"]
        self.assertEqual(lists, [1, 2])
