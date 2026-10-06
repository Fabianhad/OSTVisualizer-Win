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
