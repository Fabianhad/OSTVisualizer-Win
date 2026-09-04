import unittest
from types import SimpleNamespace
from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.domain.entities.cover_sheet import CoverSheetData, JobStatus
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.cdn_type import CdnType
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyData,
    HierarchyFileEntry,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.domain.services.takeoff_domain_service import (
    common_reassign_geometry_type,
    condition_reassign_geometry_type,
    takeoffs_can_reassign_to_condition,
)
from ost_visualizer.domain.entities.workspace_state import (
    WORKSPACE_VALID_ACTIVE_VIEWS,
    HeaderLayoutState,
    TakeoffWorkspaceState,
    WorkspaceState,
)


class DomainLifecycleTests(unittest.TestCase):
    def test_hierarchy_reconstruction_refreshes_condition_type_label_by_uid(self):
        condition = Condition(
            uid="condition-1",
            cdn_type_uid="type-a",
            cdn_type_name="Old name",
        )

        class _Repository:
            active_file_path = "C:/Data/Test.mdb"
            cdn_types = {}

            @classmethod
            def get_cdn_types(cls, _file_path):
                return dict(cls.cdn_types)

        class _FileManager:
            project_repository = _Repository()

            @staticmethod
            def register_loaded_hierarchy(_file_entry, cdn_types):
                _Repository.cdn_types = dict(cdn_types)
                return HierarchyData()

        model = SimpleNamespace(
            file_manager=_FileManager(),
            cdn_types={},
            current_bid_ref=BidRef("c:\\data\\test.mdb", "bid-1"),
            bid_conditions={condition.uid: condition},
            set_hierarchy=lambda _hierarchy: None,
            projects=[],
        )
        ProjectDataService(model).replace_database_hierarchy(
            HierarchyFileEntry(file_path="C:/Data/Test.mdb"),
            {"type-b": CdnType(uid="type-b", name="Old name")},
        )
        self.assertEqual(condition.cdn_type_uid, "type-a")
        self.assertEqual(condition.cdn_type_name, "Unknown")
        ProjectDataService(model).replace_database_hierarchy(
            HierarchyFileEntry(file_path="C:/Data/Test.mdb"),
            {"type-a": CdnType(uid="type-a", name="Renamed")},
        )
        self.assertEqual(condition.cdn_type_uid, "type-a")
        self.assertEqual(condition.cdn_type_name, "Renamed")

    def test_sql_projection_snapshots_do_not_expose_authoritative_mutable_state(self):
        service = ProjectDataService(SimpleNamespace())
        layer = BidLayer(
            uid="layer-1", bid_uid="8", name="Original", show=True, sequence=1
        )
        job_status = JobStatus(uid="status-1", name="Open")
        employee = Employee(uid="employee-1", first_name="Ada")
        pay_class = PayClass(uid="pay-class-1", name="Estimator")
        cover_sheet = CoverSheetData(
            bid_uid="8",
            job_status_uid="status-1",
            job_name="Original bid",
            estimator_uid="",
            notes="",
            bid_date="",
            bid_no="",
            job_id="",
            job_statuses=[JobStatus(uid="status-1", name="Open")],
        )
        defaults = {"nested": {"value": "original"}}
        service.replace_database_settings(
            "database",
            default_layers=[layer],
            job_statuses=[job_status],
            employees=[employee],
            pay_classes=[pay_class],
        )
        service.replace_cover_sheet_data("database", "8", cover_sheet)
        service.replace_settings_defaults("database", defaults)
        layer.name = "Mutated input"
        job_status.name = "Mutated input"
        employee.first_name = "Mutated input"
        pay_class.name = "Mutated input"
        cover_sheet.job_name = "Mutated input"
        defaults["nested"]["value"] = "mutated input"
        layer_snapshot = service.get_default_layer_snapshot("database")
        job_status_snapshot = service.get_job_status_snapshot("database")
        employee_snapshot = service.get_employee_snapshot("database")
        pay_class_snapshot = service.get_pay_class_snapshot("database")
        cover_sheet_snapshot = service.get_cover_sheet_snapshot("database", "8")
        defaults_snapshot = service.get_settings_defaults_snapshot("database")
        layer_snapshot[0].name = "Mutated output"
        job_status_snapshot[0].name = "Mutated output"
        employee_snapshot[0].first_name = "Mutated output"
        pay_class_snapshot[0].name = "Mutated output"
        cover_sheet_snapshot.job_statuses[0].name = "Mutated output"
        defaults_snapshot["nested"]["value"] = "mutated output"
        self.assertEqual(
            service.get_default_layer_snapshot("database")[0].name, "Original"
        )
        self.assertEqual(service.get_job_status_snapshot("database")[0].name, "Open")
        self.assertEqual(service.get_employee_snapshot("database")[0].first_name, "Ada")
        self.assertEqual(
            service.get_pay_class_snapshot("database")[0].name, "Estimator"
        )
        current_cover_sheet = service.get_cover_sheet_snapshot("database", "8")
        self.assertEqual(current_cover_sheet.job_name, "Original bid")
        self.assertEqual(current_cover_sheet.job_statuses[0].name, "Open")
        self.assertEqual(
            service.get_settings_defaults_snapshot("database"),
            {"nested": {"value": "original"}},
        )

    def test_config_rejects_truthy_string_for_boolean_field(self):
        with self.assertRaisesRegex(TypeError, "show_toolbar_text"):
            Config.from_dict({"show_toolbar_text": "false"})

    def test_condition_reassignment_preserves_geometry_compatibility_policy(self):
        conditions = {
            "linear-a": Condition(uid="linear-a", condition_type=Condition.TYPE_LINEAR),
            "linear-b": Condition(uid="linear-b", condition_type=Condition.TYPE_LINEAR),
            "area-a": Condition(uid="area-a", condition_type=Condition.TYPE_AREA),
            "area-b": Condition(uid="area-b", condition_type=Condition.TYPE_AREA),
            "count": Condition(uid="count", condition_type=Condition.TYPE_COUNT),
            "attachment": Condition(
                uid="attachment", condition_type=Condition.TYPE_ATTACHMENT
            ),
        }
        linear = Takeoff(uid="linear", condition_uid="linear-a")
        area = Takeoff(uid="area", condition_uid="area-a")
        hole = Takeoff(uid="hole", condition_uid="area-a", parent_uid="area")
        count = Takeoff(uid="count", condition_uid="count")
        attachment = Takeoff(uid="attachment", condition_uid="attachment")
        self.assertTrue(
            takeoffs_can_reassign_to_condition([linear], conditions, "linear-b")
        )
        self.assertTrue(
            takeoffs_can_reassign_to_condition([area, hole], conditions, "area-b")
        )
        self.assertFalse(
            takeoffs_can_reassign_to_condition([linear], conditions, "area-b")
        )
        self.assertFalse(
            takeoffs_can_reassign_to_condition([area], conditions, "linear-b")
        )
        self.assertTrue(
            takeoffs_can_reassign_to_condition([count], conditions, "attachment")
        )
        self.assertTrue(
            takeoffs_can_reassign_to_condition([attachment], conditions, "count")
        )
        self.assertIsNone(common_reassign_geometry_type([linear, area], conditions))
        self.assertFalse(
            takeoffs_can_reassign_to_condition([linear, area], conditions, "linear-b")
        )
        self.assertFalse(takeoffs_can_reassign_to_condition([], conditions, "linear-b"))
        self.assertFalse(
            takeoffs_can_reassign_to_condition([linear], conditions, "missing")
        )
        self.assertEqual(
            condition_reassign_geometry_type(conditions["attachment"]),
            Condition.TYPE_COUNT,
        )

    def test_validation_constants_are_immutable_shared_state(self):
        self.assertIsInstance(ConfigAggregate.VALID_DISPLAY_MODES, frozenset)
        self.assertIsInstance(ConfigAggregate.VALID_ROPING_SELECTION_METHODS, frozenset)
        self.assertIsInstance(ConfigAggregate.VALID_HOTLINK_TARGETS, frozenset)
        self.assertIsInstance(ConfigAggregate.VALID_MOUSE_SNAP_ANGLES, frozenset)

    def test_workspace_active_view_constants_are_immutable_shared_state(self):
        self.assertIsInstance(TakeoffWorkspaceState.VALID_ACTIVE_VIEWS, frozenset)
        self.assertEqual(
            TakeoffWorkspaceState.VALID_ACTIVE_VIEWS, WORKSPACE_VALID_ACTIVE_VIEWS
        )

    def test_takeoff_root_parent_sentinels_are_canonical(self):
        self.assertFalse(Takeoff(uid="1", condition_uid="c1", parent_uid="0").is_hole)
        self.assertFalse(Takeoff(uid="1", condition_uid="c1", parent_uid="").is_hole)
        self.assertTrue(Takeoff(uid="1", condition_uid="c1", parent_uid="None").is_hole)
        self.assertTrue(Takeoff(uid="2", condition_uid="c1", parent_uid="1").is_hole)

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


if __name__ == "__main__":
    unittest.main()
