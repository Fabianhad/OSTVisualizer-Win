from ost_visualizer.domain.entities.workspace_state import (
    WORKSPACE_VALID_ACTIVE_VIEWS,
    HeaderLayoutState,
    TakeoffWorkspaceState,
    WorkspaceState,
)
import unittest
import os
from pathlib import Path
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.workspace_state import TakeoffWorkspaceState
from ost_visualizer.presentation.utils.annotation_defaults import (
    apply_config_owned_annotation_defaults,
    build_placed_annotation_spec,
    set_annotation_styles_by_tool,
)
from PySide6 import QtCore, QtGui, QtWidgets


class WorkspaceStateSerializationTests(unittest.TestCase):
    def test_workspace_active_view_constants_are_immutable_shared_state(self):
        self.assertIsInstance(TakeoffWorkspaceState.VALID_ACTIVE_VIEWS, frozenset)
        self.assertEqual(
            TakeoffWorkspaceState.VALID_ACTIVE_VIEWS, WORKSPACE_VALID_ACTIVE_VIEWS
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


class WorkspaceFontColorCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        set_annotation_styles_by_tool({}, Config())
        self.app.processEvents()

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
