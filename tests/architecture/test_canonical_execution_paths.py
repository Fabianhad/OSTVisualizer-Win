import ast
import csv
import tempfile
import unittest
from pathlib import Path
from ost_visualizer.application.dtos.mesh_geometry_dto import MeshSceneIdentity
from ost_visualizer.application.services.visualization_service import (
    VisualizationService,
)
from ost_visualizer.presentation.components.mesh_view import OpenGLViewer
from ost_visualizer.presentation.coordinators.navigation_state_machine import (
    NavigationStateMachine,
)
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
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
from tests.paths import REPO_ROOT as _ROOT

# The three ledgers below are local, gitignored audit artefacts (build/ is in
# .gitignore, they were never committed and no generator exists). The tests
# that read them skip when they are absent; the validators themselves are
# proven against synthetic ledgers in ``LedgerValidatorTests`` on every machine.
_LEDGER_PATH = _ROOT / "build" / "duplicate_execution_path_audit.tsv"
_REGISTRY_PATH = _ROOT / "build" / "canonical_execution_paths.tsv"
_EVENT_MATRIX_PATH = _ROOT / "build" / "event_producer_consumer_audit.tsv"
_DECISION_COLUMNS = {
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
_REGISTRY_COLUMNS = {
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
_EVENT_MATRIX_COLUMNS = [
    "Event",
    "Producers",
    "Consumers",
    "PayloadIdentity",
    "CausalMeaning",
    "CanCoalesce",
    "DuplicateRisk",
    "Canonical",
    "Action",
]


def _read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise unittest.SkipTest(f"Local architecture ledger is absent: {path}")
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        return list(reader.fieldnames or ()), list(reader)


def _production_python_sources() -> list[Path]:
    return list((_ROOT / "ost_visualizer").rglob("*.py"))


def _structural_problems(rows, columns, key):
    """Report rows with blank, missing or surplus cells and duplicate keys."""
    problems = []
    seen = set()
    for number, row in enumerate(rows, start=2):
        if None in row:
            problems.append(f"line {number}: more cells than columns")
        for column in columns:
            if not row.get(column):
                problems.append(f"line {number}: {column} is blank")
        identifier = row.get(key)
        if identifier in seen:
            problems.append(f"line {number}: duplicate {key} {identifier}")
        seen.add(identifier)
    return problems


def _validate_decision_ledger(columns, rows):
    problems = []
    if set(columns) != _DECISION_COLUMNS:
        problems.append(
            "columns: missing "
            f"{sorted(_DECISION_COLUMNS - set(columns))} extra "
            f"{sorted(set(columns) - _DECISION_COLUMNS)}"
        )
        return problems
    if not rows:
        return ["ledger has no rows"]
    problems.extend(_structural_problems(rows, columns, "DecisionId"))
    by_id = {row["DecisionId"]: row for row in rows}
    for row in rows:
        decision = row["DecisionId"]
        try:
            review_count = int(row["ReviewCount"])
        except (TypeError, ValueError):
            problems.append(f"{decision}: ReviewCount is not an integer")
        else:
            if review_count < 1:
                problems.append(f"{decision}: ReviewCount below 1")
        if row["Status"] == "SUPERSEDED":
            replacement = row["SupersededBy"]
            if replacement not in by_id:
                problems.append(f"{decision}: SupersededBy {replacement} is unknown")
            elif by_id[replacement]["Supersedes"] != decision:
                problems.append(f"{decision}: {replacement} does not supersede it")
            if row["StillValid"] != "FALSE":
                problems.append(f"{decision}: superseded but StillValid is not FALSE")
        # The original contract also asserted that a StillValid == TRUE row is
        # not SUPERSEDED; that held by construction of the branch above.
    return problems


def _validate_canonical_registry(columns, rows):
    if set(columns) != _REGISTRY_COLUMNS:
        return [
            "columns: missing "
            f"{sorted(_REGISTRY_COLUMNS - set(columns))} extra "
            f"{sorted(set(columns) - _REGISTRY_COLUMNS)}"
        ]
    if not rows:
        return ["registry has no rows"]
    problems = _structural_problems(rows, columns, "PathId")
    seen_operations = set()
    for number, row in enumerate(rows, start=2):
        if row["Operation"] in seen_operations:
            problems.append(f"line {number}: duplicate Operation {row['Operation']}")
        seen_operations.add(row["Operation"])
        if row["Status"] != "ACTIVE":
            problems.append(f"line {number}: Status {row['Status']} is not ACTIVE")
        if row["Tests"] == "-":
            problems.append(f"line {number}: no Tests recorded")
    return problems


def _validate_event_matrix(columns, rows):
    if columns != _EVENT_MATRIX_COLUMNS:
        return [f"columns: expected {_EVENT_MATRIX_COLUMNS}, found {columns}"]
    if not rows:
        return ["event matrix has no rows"]
    problems = _structural_problems(rows, columns, "Event")
    for number, row in enumerate(rows, start=2):
        if row["Canonical"] != "YES":
            problems.append(f"line {number}: Canonical {row['Canonical']} is not YES")
    return problems


def _async_callback_report(tree, label):
    """Return (invalid callbacks, conditionally selected ``*_async_fn`` keywords).
    A ``*_async_fn`` argument must be chosen before invocation
    (``(lambda ...) if cond else None``); a lambda that decides at call time
    (``lambda ...: (lambda ...) if cond else None``) is invalid.
    """
    invalid = []
    selected = 0
    for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        for keyword in call.keywords:
            if not keyword.arg or not keyword.arg.endswith("_async_fn"):
                continue
            callbacks = [keyword.value]
            if isinstance(keyword.value, ast.IfExp):
                selected += 1
                callbacks = [keyword.value.body, keyword.value.orelse]
            for callback in callbacks:
                if not isinstance(callback, ast.Lambda) or not isinstance(
                    callback.body, ast.IfExp
                ):
                    continue
                returns_none = (
                    isinstance(callback.body.orelse, ast.Constant)
                    and callback.body.orelse.value is None
                )
                returns_callback = isinstance(
                    callback.body.body, ast.Lambda
                ) or isinstance(callback.body.orelse, ast.Lambda)
                if returns_none or returns_callback:
                    invalid.append(f"{label}:{callback.lineno}:{keyword.arg}")
    return invalid, selected


_FORBIDDEN_ATTRIBUTES = {
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
_FORBIDDEN_DEFINITIONS = {
    "build_for_bounds",
    "push_async",
    "queue_mutation",
    "queue_takeoff_insert",
}
_FORBIDDEN_EVENT_NAMES = {
    "NamedViewCreatedEvent",
    "NamedViewRenamedEvent",
    "NamedViewDeletedEvent",
    "QueuedMutationWorkResult",
}


def _legacy_symbol_findings(tree):
    """Return (attributes, class/function names, definitions, create calls)."""
    attributes = set()
    names = set()
    definitions = set()
    create_calls = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr in _FORBIDDEN_ATTRIBUTES:
                attributes.add(node.attr)
            if (
                node.attr == "create"
                and isinstance(node.value, ast.Name)
                and node.value.id == "MeshSceneIdentity"
            ):
                create_calls += 1
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in _FORBIDDEN_EVENT_NAMES:
                names.add(node.name)
            if node.name in _FORBIDDEN_DEFINITIONS:
                definitions.add(node.name)
    return attributes, names, definitions, create_calls


def _attribute_names(tree):
    return {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}


def _subscribes_event_to_handler(tree, event_name, handler_name):
    """True when ``(<..>.event_name, <..>.handler_name)`` appear as adjacent items.
    Covers ``subscribe(AppEvents.X, self._h)`` calls and ``(AppEvents.X, self._h)``
    pairs in subscription tables, however the source is wrapped.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            items = node.args
        elif isinstance(node, (ast.Tuple, ast.List)):
            items = node.elts
        else:
            continue
        for first, second in zip(items, items[1:]):
            if (
                isinstance(first, ast.Attribute)
                and first.attr == event_name
                and isinstance(second, ast.Attribute)
                and second.attr == handler_name
            ):
                return True
    return False


def _calls_method_on_name(tree, owner_name, method_name):
    return any(
        isinstance(node, ast.Attribute)
        and node.attr == method_name
        and isinstance(node.value, ast.Name)
        and node.value.id == owner_name
        for node in ast.walk(tree)
    )


def _defining_classes(owner, method, package_prefix):
    """Classes in ``owner``'s MRO from ``package_prefix`` that define ``method``.
    ``hasattr`` alone is satisfied by ``object`` (``__init__``) or by a Qt base
    class (``hideEvent``), so it cannot notice the project class losing the
    method.
    """
    return [
        klass
        for klass in owner.__mro__
        if klass.__module__.startswith(package_prefix) and method in vars(klass)
    ]


class CanonicalExecutionPathTests(unittest.TestCase):
    def test_optional_async_dialog_callbacks_are_selected_before_invocation(self):
        invalid_callbacks = []
        selected_keywords = 0
        presentation_root = _ROOT / "ost_visualizer" / "presentation"
        for path in presentation_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            invalid, selected = _async_callback_report(
                tree, str(path.relative_to(_ROOT))
            )
            invalid_callbacks.extend(invalid)
            selected_keywords += selected
        self.assertEqual(invalid_callbacks, [])
        # Positive control: about eighteen dialog calls pass a conditionally
        # selected ``*_async_fn`` (counted with grep); the scan must see them.
        self.assertGreaterEqual(selected_keywords, 12)

    def test_decision_ledger_is_complete_and_linked(self):
        columns, rows = _read_tsv(_LEDGER_PATH)
        self.assertEqual(_validate_decision_ledger(columns, rows), [])

    def test_canonical_registry_has_unique_complete_active_paths(self):
        columns, rows = _read_tsv(_REGISTRY_PATH)
        self.assertEqual(_validate_canonical_registry(columns, rows), [])

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
                    self.assertTrue(
                        _defining_classes(owner, method, "ost_visualizer"),
                        f"{owner.__name__}.{method} is not defined by a project class",
                    )

    def test_forbidden_legacy_symbols_are_absent_from_production_ast(self):
        found_attributes: set[str] = set()
        found_names: set[str] = set()
        found_definitions: set[str] = set()
        mesh_identity_create_calls = 0
        scanned = 0
        for path in _production_python_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            scanned += 1
            attributes, names, definitions, create_calls = _legacy_symbol_findings(tree)
            found_attributes |= attributes
            found_names |= names
            found_definitions |= definitions
            mesh_identity_create_calls += create_calls
        # Positive control: ~590 production modules exist (counted with find).
        self.assertGreaterEqual(scanned, 500)
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
        # Positive control: the tools tree is really being listed.
        self.assertIn("check_architecture.py", shipped)
        self.assertGreaterEqual(len(shipped), 5)
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
        # The same routes checked on the AST, which survives reformatting
        # (a line-wrapped subscription would defeat the substring checks).
        detached_tree = ast.parse(detached_source)
        builder_tree = ast.parse(builder_source)
        # Positive controls: the finders see real subscriptions and calls.
        self.assertTrue(
            _subscribes_event_to_handler(
                detached_tree, "DATABASE_REFRESHED", "_on_database_refreshed"
            )
        )
        self.assertIn("set_plan_texture_provider", _attribute_names(builder_tree))
        self.assertNotIn("NATIVE_SCENE_UPDATED", _attribute_names(detached_tree))
        self.assertFalse(
            _subscribes_event_to_handler(
                detached_tree,
                "DATABASE_CAPABILITIES_CHANGED",
                "_on_database_refreshed",
            )
        )
        self.assertFalse(
            _calls_method_on_name(builder_tree, "canvas", "set_plan_texture_provider")
        )

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
        self.assertEqual(_validate_event_matrix(columns, rows), [])


class CanonicalScannerSelfTests(unittest.TestCase):
    """Prove the source scanners flag violations on synthetic snippets."""

    def test_async_callback_scanner_flags_call_time_selection_only(self):
        invalid_forms = (
            "Dialog(save_async_fn=lambda c, d: None if x else None)",
            "Dialog(save_async_fn=lambda c, d: (lambda: 1) if x else None)",
            "Dialog(save_async_fn=lambda c, d: (lambda: 1) if x else (lambda: 2))",
            "Dialog(save_async_fn=(lambda c, d: g(c) if x else None) if y else None)",
        )
        for source in invalid_forms:
            with self.subTest(source=source):
                invalid, _selected = _async_callback_report(
                    ast.parse(source), "<snippet>"
                )
                self.assertEqual(len(invalid), 1)
                self.assertTrue(invalid[0].endswith(":save_async_fn"))

    def test_async_callback_scanner_accepts_pre_selected_callbacks(self):
        valid, selected = _async_callback_report(
            ast.parse(
                "Dialog(save_async_fn=((lambda c, d: g(c, d)) if x else None),"
                " other=lambda: None if y else 1,"
                " plain_async_fn=handler)"
            ),
            "<snippet>",
        )
        self.assertEqual(valid, [])
        self.assertEqual(selected, 1)

    def test_legacy_symbol_scanner_finds_attributes_definitions_and_creates(self):
        attributes, names, definitions, creates = _legacy_symbol_findings(
            ast.parse(
                "class NamedViewCreatedEvent: ...\n"
                "async def push_async(): ...\n"
                "def queue_mutation(): ...\n"
                "obj._last_mesh_args\n"
                "MeshSceneIdentity.create(1)\n"
            )
        )
        self.assertEqual(attributes, {"_last_mesh_args"})
        self.assertEqual(names, {"NamedViewCreatedEvent"})
        self.assertEqual(definitions, {"push_async", "queue_mutation"})
        self.assertEqual(creates, 1)
        self.assertEqual(
            _legacy_symbol_findings(ast.parse("def refresh_mesh_view(): ...\n")),
            (set(), set(), set(), 0),
        )

    def test_route_finders_see_wrapped_subscriptions_and_attribute_calls(self):
        wrapped = ast.parse(
            "table = [\n"
            "    (\n"
            "        AppEvents.DATABASE_CAPABILITIES_CHANGED,\n"
            "        self._on_database_refreshed,\n"
            "    ),\n"
            "]\n"
            "bus.subscribe(\n"
            "    AppEvents.DATABASE_CAPABILITIES_CHANGED, self._on_database_refreshed\n"
            ")\n"
        )
        self.assertTrue(
            _subscribes_event_to_handler(
                wrapped, "DATABASE_CAPABILITIES_CHANGED", "_on_database_refreshed"
            )
        )
        self.assertFalse(
            _subscribes_event_to_handler(
                wrapped, "DATABASE_REFRESHED", "_on_database_refreshed"
            )
        )
        self.assertTrue(
            _calls_method_on_name(
                ast.parse("canvas.set_plan_texture_provider(p)"),
                "canvas",
                "set_plan_texture_provider",
            )
        )
        self.assertFalse(
            _calls_method_on_name(
                ast.parse("handler.set_plan_texture_provider(p)"),
                "canvas",
                "set_plan_texture_provider",
            )
        )

    def test_defining_class_check_rejects_inherited_and_object_members(self):
        class Base:
            def shared(self):
                return 1

        class Derived(Base):
            def own(self):
                return 2

        prefix = __name__
        self.assertTrue(hasattr(Derived, "__init__"))
        self.assertEqual(_defining_classes(Derived, "__init__", prefix), [])
        self.assertEqual(_defining_classes(Derived, "shared", prefix), [Base])
        self.assertEqual(_defining_classes(Derived, "own", prefix), [Derived])
        self.assertEqual(_defining_classes(Derived, "missing", prefix), [])


class LedgerValidatorTests(unittest.TestCase):
    """Run the ledger validators against synthetic TSV files.
    The real ledgers are local and gitignored, so the tests above skip on a
    machine without them. These tests keep the validation logic itself
    exercised everywhere; they say nothing about the content of any real
    ledger.
    """

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def _tsv(self, columns, rows, name="ledger.tsv"):
        path = self.directory / name
        lines = ["\t".join(columns)]
        lines.extend("\t".join(row) for row in rows)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
        return _read_tsv(path)

    @staticmethod
    def _decision(identifier, **overrides):
        row = {column: "x" for column in _DECISION_COLUMNS}
        row.update(
            DecisionId=identifier,
            Status="ACTIVE",
            ReviewCount="1",
            Supersedes="-",
            SupersededBy="-",
            StillValid="TRUE",
        )
        row.update(overrides)
        return row

    def _decision_problems(self, *rows):
        columns = sorted(_DECISION_COLUMNS)
        return _validate_decision_ledger(
            *self._tsv(columns, [[row[c] for c in columns] for row in rows])
        )

    @staticmethod
    def _registry(identifier, **overrides):
        row = {column: "x" for column in _REGISTRY_COLUMNS}
        row.update(PathId=identifier, Operation=f"op-{identifier}", Status="ACTIVE")
        row.update(overrides)
        return row

    def _registry_problems(self, *rows):
        columns = sorted(_REGISTRY_COLUMNS)
        return _validate_canonical_registry(
            *self._tsv(columns, [[row[c] for c in columns] for row in rows])
        )

    @staticmethod
    def _event(name, **overrides):
        row = {column: "x" for column in _EVENT_MATRIX_COLUMNS}
        row.update(Event=name, Canonical="YES")
        row.update(overrides)
        return row

    def _event_problems(self, *rows, columns=None):
        columns = columns or _EVENT_MATRIX_COLUMNS
        return _validate_event_matrix(
            *self._tsv(columns, [[row.get(c, "x") for c in columns] for row in rows])
        )

    def test_read_tsv_skips_absent_ledger_and_parses_present_one(self):
        with self.assertRaises(unittest.SkipTest):
            _read_tsv(self.directory / "absent.tsv")
        columns, rows = self._tsv(["A", "B"], [["1", "2"], ["3", "4"]])
        self.assertEqual(columns, ["A", "B"])
        self.assertEqual(rows, [{"A": "1", "B": "2"}, {"A": "3", "B": "4"}])

    def test_decision_ledger_accepts_a_complete_linked_ledger(self):
        self.assertEqual(
            self._decision_problems(
                self._decision("D1"),
                self._decision(
                    "D2",
                    Status="SUPERSEDED",
                    SupersededBy="D3",
                    StillValid="FALSE",
                ),
                self._decision("D3", Supersedes="D2"),
            ),
            [],
        )

    def test_decision_ledger_reports_each_kind_of_defect(self):
        cases = {
            "blank cell": (
                (self._decision("D1", Notes=""),),
                ["line 2: Notes is blank"],
            ),
            "duplicate id": (
                (self._decision("D1"), self._decision("D1")),
                ["line 3: duplicate DecisionId D1"],
            ),
            "zero review count": (
                (self._decision("D1", ReviewCount="0"),),
                ["D1: ReviewCount below 1"],
            ),
            "non-numeric review count": (
                (self._decision("D1", ReviewCount="many"),),
                ["D1: ReviewCount is not an integer"],
            ),
            "unknown replacement": (
                (
                    self._decision(
                        "D1",
                        Status="SUPERSEDED",
                        SupersededBy="D9",
                        StillValid="FALSE",
                    ),
                ),
                ["D1: SupersededBy D9 is unknown"],
            ),
            "missing back link": (
                (
                    self._decision(
                        "D1",
                        Status="SUPERSEDED",
                        SupersededBy="D2",
                        StillValid="FALSE",
                    ),
                    self._decision("D2"),
                ),
                ["D1: D2 does not supersede it"],
            ),
            "superseded but valid": (
                (
                    self._decision(
                        "D1",
                        Status="SUPERSEDED",
                        SupersededBy="D2",
                        StillValid="TRUE",
                    ),
                    self._decision("D2", Supersedes="D1"),
                ),
                ["D1: superseded but StillValid is not FALSE"],
            ),
        }
        for name, (rows, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(self._decision_problems(*rows), expected)

    def test_decision_ledger_rejects_wrong_columns_and_empty_ledger(self):
        problems = _validate_decision_ledger(*self._tsv(["DecisionId", "Extra"], []))
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("columns: missing"))
        self.assertIn("'Extra'", problems[0])
        self.assertEqual(self._decision_problems(), ["ledger has no rows"])

    def test_registry_accepts_unique_complete_active_paths(self):
        self.assertEqual(
            self._registry_problems(self._registry("P1"), self._registry("P2")), []
        )

    def test_registry_reports_each_kind_of_defect(self):
        cases = {
            "duplicate path id": (
                (self._registry("P1"), self._registry("P1", Operation="other")),
                ["line 3: duplicate PathId P1"],
            ),
            "duplicate operation": (
                (self._registry("P1"), self._registry("P2", Operation="op-P1")),
                ["line 3: duplicate Operation op-P1"],
            ),
            "blank cell": (
                (self._registry("P1", CleanupOwner=""),),
                ["line 2: CleanupOwner is blank"],
            ),
            "inactive path": (
                (self._registry("P1", Status="RETIRED"),),
                ["line 2: Status RETIRED is not ACTIVE"],
            ),
            "path without tests": (
                (self._registry("P1", Tests="-"),),
                ["line 2: no Tests recorded"],
            ),
        }
        for name, (rows, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(self._registry_problems(*rows), expected)
        self.assertEqual(self._registry_problems(), ["registry has no rows"])
        problems = _validate_canonical_registry(*self._tsv(["PathId"], [["P1"]]))
        self.assertTrue(problems[0].startswith("columns: missing"))

    def test_event_matrix_accepts_one_canonical_row_per_event(self):
        self.assertEqual(self._event_problems(self._event("A"), self._event("B")), [])

    def test_event_matrix_reports_each_kind_of_defect(self):
        cases = {
            "duplicate event": (
                (self._event("A"), self._event("A")),
                ["line 3: duplicate Event A"],
            ),
            "blank cell": (
                (self._event("A", Action=""),),
                ["line 2: Action is blank"],
            ),
            "non canonical": (
                (self._event("A", Canonical="NO"),),
                ["line 2: Canonical NO is not YES"],
            ),
        }
        for name, (rows, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(self._event_problems(*rows), expected)
        self.assertEqual(self._event_problems(), ["event matrix has no rows"])
        reordered = list(reversed(_EVENT_MATRIX_COLUMNS))
        problems = self._event_problems(self._event("A"), columns=reordered)
        self.assertTrue(problems[0].startswith("columns: expected"))

    def test_structural_check_reports_short_and_surplus_rows(self):
        path = self.directory / "ragged.tsv"
        path.write_text("Event\tCanonical\nA\nB\tYES\tsurplus\n", encoding="utf-8")
        columns, rows = _read_tsv(path)
        self.assertEqual(
            _structural_problems(rows, columns, "Event"),
            [
                "line 2: Canonical is blank",
                "line 3: more cells than columns",
            ],
        )


if __name__ == "__main__":
    unittest.main()
