import ast
import csv
import unittest
from pathlib import Path
from ost_visualizer.application.dtos.mesh_geometry_dto import MeshSceneIdentity
from ost_visualizer.application.services.visualization_service import (
    VisualizationService,
)
from ost_visualizer.presentation.components.mesh_view import OpenGLViewer
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.coordinators.navigation_state_machine import (
    NavigationStateMachine,
)
from ost_visualizer.presentation.coordinators.viewer_sync_coordinator import (
    ViewerSyncCoordinator,
)
from ost_visualizer.presentation.handlers.plan_view_action_handler import (
    PlanViewActionHandler,
)
from ost_visualizer.presentation.managers.detached_page_view_manager import (
    DetachedPageViewManager,
)
from ost_visualizer.presentation.services.annotation_write_coordinator import (
    AnnotationWriteCoordinator,
)
from ost_visualizer.presentation.visualization.native_page_plane import (
    NativePageImagePlaneProvider,
)
from ost_visualizer.presentation.visualization.pdf.services.page_render_prefetch_coordinator import (
    PageRenderPrefetchCoordinator,
)

_ROOT = Path(__file__).resolve().parents[1]
_LEDGER_PATH = _ROOT / "build" / "duplicate_execution_path_audit.tsv"
_REGISTRY_PATH = _ROOT / "build" / "canonical_execution_paths.tsv"
_EVENT_MATRIX_PATH = _ROOT / "build" / "event_producer_consumer_audit.tsv"


def _read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise unittest.SkipTest(f"Local architecture ledger is absent: {path}")
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        return list(reader.fieldnames or ()), list(reader)


def _production_python_sources() -> list[Path]:
    return list((_ROOT / "ost_visualizer").rglob("*.py"))


class CanonicalExecutionPathTests(unittest.TestCase):
    def test_decision_ledger_is_complete_and_linked(self):
        columns, rows = _read_tsv(_LEDGER_PATH)
        required = {
            "DecisionId",
            "Category",
            "Operation",
            "CanonicalOwner",
            "SecondaryOwner",
            "Decision",
            "Status",
            "Reason",
            "Evidence",
            "CallersReviewed",
            "CalleesReviewed",
            "Tests",
            "IntroducedByCommit",
            "LastReviewedCommit",
            "ReviewCount",
            "Supersedes",
            "SupersededBy",
            "StillValid",
            "Notes",
        }
        self.assertEqual(set(columns), required)
        self.assertEqual(len({row["DecisionId"] for row in rows}), len(rows))
        self.assertTrue(all(all(row[column] for column in columns) for row in rows))
        by_id = {row["DecisionId"]: row for row in rows}
        for row in rows:
            self.assertGreaterEqual(int(row["ReviewCount"]), 1)
            if row["Status"] == "SUPERSEDED":
                replacement = row["SupersededBy"]
                self.assertIn(replacement, by_id)
                self.assertEqual(by_id[replacement]["Supersedes"], row["DecisionId"])
                self.assertEqual(row["StillValid"], "FALSE")
            elif row["StillValid"] == "TRUE":
                self.assertNotEqual(row["Status"], "SUPERSEDED")

    def test_canonical_registry_has_unique_complete_active_paths(self):
        columns, rows = _read_tsv(_REGISTRY_PATH)
        required = {
            "PathId",
            "Subsystem",
            "Operation",
            "EntryPoint",
            "CanonicalOwner",
            "CanonicalMethod",
            "StateOwner",
            "EventSource",
            "EventName",
            "ThreadBoundary",
            "IdentityContract",
            "LifecycleStart",
            "LifecycleEnd",
            "CleanupOwner",
            "AllowedSecondaryPaths",
            "ForbiddenLegacyPaths",
            "Tests",
            "LastReviewedCommit",
            "Status",
        }
        self.assertEqual(set(columns), required)
        self.assertEqual(len({row["PathId"] for row in rows}), len(rows))
        self.assertEqual(len({row["Operation"] for row in rows}), len(rows))
        self.assertTrue(all(all(row[column] for column in columns) for row in rows))
        self.assertTrue(all(row["Status"] == "ACTIVE" for row in rows))
        self.assertTrue(all(row["Tests"] != "-" for row in rows))

    def test_registered_canonical_methods_exist(self):
        expected_methods = {
            MeshSceneIdentity: {"__init__", "__post_init__"},
            VisualizationService: {
                "refresh_mesh_view",
                "_start_mesh_generation_locked",
                "_mesh_worker_loop",
                "_on_scene_ready",
                "_claim_mesh_result",
                "_publish_empty_mesh_scene",
            },
            UIEventCoordinator: {
                "_update_page_selection",
                "_request_or_defer_mesh_refresh",
                "_on_native_scene_updated",
                "_replay_mesh_if_current",
                "_clear_mesh_views_for_scene_update",
                "handle_bid_selection",
                "_on_database_refreshed",
                "_on_takeoffs_changed",
                "_discard_mesh_camera_states",
                "_update_export_menu_state",
                "_sync_navigation_for_active_page",
            },
            NavigationStateMachine: {"compute_state_for"},
            OpenGLViewer: {
                "suspend_rendering",
                "hideEvent",
                "_save_current_camera",
                "_restore_saved_camera",
                "_initialize_camera_for_current_scene",
                "_connect_surface_notifications",
                "apply_scene_failure",
                "clear_scene",
                "cleanup",
            },
            ViewerSyncCoordinator: {"clear_plan_view"},
            NativePageImagePlaneProvider: {"build_for_scene"},
            PageRenderPrefetchCoordinator: {"cancel_pending"},
            PlanViewActionHandler: {
                "_publish_takeoffs_changed_for_pages",
                "on_positions_flushed",
            },
            AnnotationWriteCoordinator: {"publish_annotations_changed_for_pages"},
            DetachedPageViewManager: {
                "_on_takeoffs_changed",
                "_on_annotations_changed",
                "shutdown",
            },
        }
        for owner, methods in expected_methods.items():
            for method in methods:
                with self.subTest(owner=owner.__name__, method=method):
                    self.assertTrue(hasattr(owner, method))

    def test_forbidden_legacy_symbols_are_absent_from_production_ast(self):
        forbidden_attributes = {
            "_last_mesh_args",
            "_last_mesh_options",
            "_clear_plan_view",
            "build_for_bounds",
            "on_page_selection",
            "push_async",
            "queue_mutation",
            "queue_takeoff_insert",
            "reconcile_local_commit",
            "update_named_view_name",
            "set_plan_texture_visibility",
        }
        forbidden_definitions = {
            "build_for_bounds",
            "push_async",
            "queue_mutation",
            "queue_takeoff_insert",
        }
        forbidden_event_names = {
            "NamedViewCreatedEvent",
            "NamedViewRenamedEvent",
            "NamedViewDeletedEvent",
            "QueuedMutationWorkResult",
        }
        found_attributes: set[str] = set()
        found_names: set[str] = set()
        found_definitions: set[str] = set()
        mesh_identity_create_calls = 0
        for path in _production_python_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    if node.attr in forbidden_attributes:
                        found_attributes.add(node.attr)
                    if (
                        node.attr == "create"
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "MeshSceneIdentity"
                    ):
                        mesh_identity_create_calls += 1
                elif isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                    if node.name in forbidden_event_names:
                        found_names.add(node.name)
                    if node.name in forbidden_definitions:
                        found_definitions.add(node.name)
        self.assertEqual(found_attributes, set())
        self.assertEqual(found_names, set())
        self.assertEqual(found_definitions, set())
        self.assertEqual(mesh_identity_create_calls, 0)

    def test_no_sql_schema_migration_utility_is_shipped(self):
        forbidden_names = {
            "_temporary_migrate_local_sql_collaboration.py",
            "migrate_sql_collaboration.py",
        }
        shipped = {
            path.name for path in (_ROOT / "tools").rglob("*.py") if path.is_file()
        }
        self.assertTrue(forbidden_names.isdisjoint(shipped))

    def test_removed_event_and_refresh_routes_remain_absent(self):
        detached_source = (
            _ROOT
            / "ost_visualizer"
            / "presentation"
            / "managers"
            / "detached_page_view_manager.py"
        ).read_text(encoding="utf-8")
        builder_source = (
            _ROOT
            / "ost_visualizer"
            / "presentation"
            / "builders"
            / "component_builder.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("AppEvents.NATIVE_SCENE_UPDATED", detached_source)
        self.assertNotIn(
            "DATABASE_CAPABILITIES_CHANGED, self._on_database_refreshed",
            detached_source,
        )
        self.assertNotIn("canvas.set_plan_texture_provider", builder_source)

    def test_composite_menu_refresh_paths_do_not_refresh_toolbar_twice(self):
        coordinator_path = (
            _ROOT
            / "ost_visualizer"
            / "presentation"
            / "coordinators"
            / "ui_event_coordinator.py"
        )
        tree = ast.parse(
            coordinator_path.read_text(encoding="utf-8"),
            filename=str(coordinator_path),
        )
        target_methods = {
            "_on_tab_changed",
            "_finish_refresh",
            "update_layer_visibility_deferred",
            "update_all_layers_visibility_deferred",
        }
        methods = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name in target_methods
        }
        self.assertEqual(set(methods), target_methods)
        for method_name, method in methods.items():
            direct_toolbar_refreshes = [
                call
                for call in ast.walk(method)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "refresh"
                and isinstance(call.func.value, ast.Attribute)
                and call.func.value.attr == "_toolbar"
            ]
            with self.subTest(method=method_name):
                self.assertEqual(direct_toolbar_refreshes, [])

    def test_event_matrix_has_one_canonical_row_per_event(self):
        columns, rows = _read_tsv(_EVENT_MATRIX_PATH)
        self.assertEqual(
            columns,
            [
                "Event",
                "Producers",
                "Consumers",
                "PayloadIdentity",
                "CausalMeaning",
                "CanCoalesce",
                "DuplicateRisk",
                "Canonical",
                "Action",
            ],
        )
        self.assertEqual(len({row["Event"] for row in rows}), len(rows))
        self.assertTrue(all(all(row[column] for column in columns) for row in rows))
        self.assertTrue(all(row["Canonical"] == "YES" for row in rows))


if __name__ == "__main__":
    unittest.main()
