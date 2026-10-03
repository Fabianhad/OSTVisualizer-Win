import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.workspace_state import (
    WORKSPACE_ACTIVE_VIEW_2D,
    WORKSPACE_KEY_ACTIVE_VIEW,
    WORKSPACE_KEY_BID_UID,
    WORKSPACE_KEY_FILE_PATH,
    WORKSPACE_KEY_KIND,
    WORKSPACE_KEY_PROJECT_UID,
    WORKSPACE_KEY_PROJECT_WORKSPACE,
    WORKSPACE_KEY_SELECTED_NODE,
    WORKSPACE_KEY_TAKEOFF_WORKSPACE,
    WORKSPACE_NODE_KIND_BID,
)
from ost_visualizer.mcp_server.output_artifacts import MCP_OUTPUT_DIR_NAME
from ost_visualizer.mcp_server.registry import (
    DatabaseRegistry,
    McpWorkspaceSelection,
)


class DatabaseRegistryTests(unittest.TestCase):
    def test_reads_checked_access_descriptor_from_version_two_file_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_data_dir = Path(temp_dir)
            db_path = app_data_dir / "canonical.mdb"
            db_path.touch()
            descriptor = DatabaseDescriptor.for_access(str(db_path))
            (app_data_dir / "file_state.json").write_text(
                json.dumps(
                    {
                        "version": 2,
                        "database_entries": [
                            {
                                "descriptor": descriptor.to_dict(),
                                "is_checked": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            registry = DatabaseRegistry(app_data_dir=app_data_dir)
            self.assertEqual(len(registry.databases), 1)
            self.assertEqual(registry.databases[0].file_path, str(db_path.resolve()))

    def _quiet_logger(self):
        logger = logging.getLogger("test_mcp_registry")
        logger.handlers.clear()
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        return logger

    def test_empty_app_state_has_no_databases(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = DatabaseRegistry(
                app_data_dir=Path(tmp), logger=self._quiet_logger()
            )
            self.assertEqual(registry.databases, [])
            self.assertIsNone(registry.workspace_selection.database_id)

    def test_file_state_allows_existing_checked_mdb_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "demo.mdb"
            db_path.write_text("", encoding="utf-8")
            unchecked_path = root / "unchecked.mdb"
            unchecked_path.write_text("", encoding="utf-8")
            unspecified_path = root / "unspecified.mdb"
            unspecified_path.write_text("", encoding="utf-8")
            txt_path = root / "notes.txt"
            txt_path.write_text("", encoding="utf-8")
            (root / "file_state.json").write_text(
                json.dumps(
                    {
                        "file_entries": [
                            {"file_path": str(db_path), "is_checked": True},
                            {"file_path": str(unchecked_path), "is_checked": False},
                            {"file_path": str(unspecified_path)},
                            {"file_path": str(txt_path), "is_checked": True},
                            str(root / "string-entry.mdb"),
                            {
                                "file_path": str(root / "missing.mdb"),
                                "is_checked": True,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            registry = DatabaseRegistry(app_data_dir=root, logger=self._quiet_logger())
            self.assertEqual(len(registry.databases), 1)
            self.assertEqual(registry.databases[0].file_path, str(db_path.resolve()))

    def test_workspace_selection_resolves_to_registered_database_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "demo.mdb"
            db_path.write_text("", encoding="utf-8")
            (root / "file_state.json").write_text(
                json.dumps(
                    {"file_entries": [{"file_path": str(db_path), "is_checked": True}]}
                ),
                encoding="utf-8",
            )
            (root / "workspace_state.json").write_text(
                json.dumps(
                    {
                        WORKSPACE_KEY_TAKEOFF_WORKSPACE: {
                            WORKSPACE_KEY_ACTIVE_VIEW: WORKSPACE_ACTIVE_VIEW_2D
                        },
                        WORKSPACE_KEY_PROJECT_WORKSPACE: {
                            WORKSPACE_KEY_SELECTED_NODE: {
                                WORKSPACE_KEY_KIND: WORKSPACE_NODE_KIND_BID,
                                WORKSPACE_KEY_FILE_PATH: str(db_path),
                                WORKSPACE_KEY_BID_UID: "bid-1",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            registry = DatabaseRegistry(app_data_dir=root, logger=self._quiet_logger())
            selection = registry.workspace_selection
            self.assertEqual(selection.selected_node_kind, WORKSPACE_NODE_KIND_BID)
            self.assertEqual(selection.bid_uid, "bid-1")
            self.assertEqual(selection.active_view, WORKSPACE_ACTIVE_VIEW_2D)
            self.assertEqual(selection.database_id, registry.databases[0].database_id)


class DatabaseRegistryValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.logger = logging.getLogger("test_mcp_registry_validation")
        self.logger.handlers.clear()
        self.logger.addHandler(logging.NullHandler())
        self.logger.propagate = False

    def make_db(self, name="demo.mdb"):
        path = self.root / name
        path.write_text("", encoding="utf-8")
        return path

    def write_state(self, filename, payload):
        text = payload if isinstance(payload, str) else json.dumps(payload)
        (self.root / filename).write_text(text, encoding="utf-8")

    def registry(self):
        return DatabaseRegistry(app_data_dir=self.root, logger=self.logger)

    @staticmethod
    def access_entry(path, checked=True):
        return {
            "descriptor": DatabaseDescriptor.for_access(str(path)).to_dict(),
            "is_checked": checked,
        }

    def test_descriptor_entries_keep_only_checked_existing_access_mdb_files(self):
        good = self.make_db("good.mdb")
        unchecked = self.make_db("unchecked.mdb")
        text = self.make_db("notes.txt")
        folder = self.root / "folder.mdb"
        folder.mkdir()
        sql_descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="sql.example.invalid", database="Ost"),
            schema_version=1,
        )
        entries = [
            self.access_entry(good),
            self.access_entry(unchecked, checked=False),
            self.access_entry(text),
            self.access_entry(folder),
            self.access_entry(self.root / "missing.mdb"),
            {"descriptor": sql_descriptor.to_dict(), "is_checked": True},
            {"descriptor": {"backend": "access"}, "is_checked": True},
            {"descriptor": "not-a-dict", "is_checked": True},
            "not-a-dict",
        ]
        self.write_state("file_state.json", {"version": 2, "database_entries": entries})
        registry = self.registry()
        self.assertEqual(
            [(db.display_name, db.file_path) for db in registry.databases],
            [("good", str(good.resolve()))],
        )

    def test_descriptor_entries_take_precedence_over_legacy_file_entries(self):
        descriptor_db = self.make_db("descriptor.mdb")
        legacy_db = self.make_db("legacy.mdb")
        self.write_state(
            "file_state.json",
            {
                "database_entries": [self.access_entry(descriptor_db)],
                "file_entries": [{"file_path": str(legacy_db), "is_checked": True}],
            },
        )
        self.assertEqual(
            [db.display_name for db in self.registry().databases], ["descriptor"]
        )

    def test_only_boolean_true_counts_as_checked(self):
        db = self.make_db()
        for flag in ("true", 1, None):
            with self.subTest(flag=flag):
                self.write_state(
                    "file_state.json",
                    {"file_entries": [{"file_path": str(db), "is_checked": flag}]},
                )
                self.assertEqual(self.registry().databases, [])
                entry = self.access_entry(db)
                entry["is_checked"] = flag
                self.write_state("file_state.json", {"database_entries": [entry]})
                self.assertEqual(self.registry().databases, [])
        self.write_state(
            "file_state.json", {"database_entries": [self.access_entry(db)]}
        )
        self.assertEqual(len(self.registry().databases), 1)

    def test_paths_are_resolved_and_home_relative_paths_are_expanded(self):
        db = self.make_db()
        (self.root / "sub").mkdir()
        self.write_state(
            "file_state.json",
            {
                "file_entries": [
                    {
                        "file_path": str(self.root / "sub" / ".." / "demo.mdb"),
                        "is_checked": True,
                    }
                ]
            },
        )
        self.assertEqual(
            [d.file_path for d in self.registry().databases], [str(db.resolve())]
        )
        self.write_state(
            "file_state.json",
            {"file_entries": [{"file_path": "~/demo.mdb", "is_checked": True}]},
        )
        home = {"USERPROFILE": str(self.root), "HOME": str(self.root)}
        with patch.dict(os.environ, home):
            registry = self.registry()
        self.assertEqual([d.file_path for d in registry.databases], [str(db.resolve())])

    def test_duplicate_paths_collapse_to_one_database(self):
        db = self.make_db()
        (self.root / "sub").mkdir()
        roundabout = self.root / "sub" / ".." / "demo.mdb"
        self.write_state(
            "file_state.json",
            {
                "file_entries": [
                    {"file_path": str(db), "is_checked": True},
                    {"file_path": str(roundabout), "is_checked": True},
                    {"file_path": str(db), "is_checked": True},
                ]
            },
        )
        registry = self.registry()
        self.assertEqual([d.file_path for d in registry.databases], [str(db.resolve())])

    def test_database_ids_are_stable_distinct_and_hide_the_path(self):
        first = self.make_db("first.mdb")
        second = self.make_db("second.mdb")
        self.write_state(
            "file_state.json",
            {
                "file_entries": [
                    {"file_path": str(first), "is_checked": True},
                    {"file_path": str(second), "is_checked": True},
                ]
            },
        )
        ids = [db.database_id for db in self.registry().databases]
        self.assertEqual(len(set(ids)), 2)
        for database_id in ids:
            self.assertRegex(database_id, r"^[0-9a-f]{16}$")
        self.assertEqual([db.database_id for db in self.registry().databases], ids)
        self.assertEqual(self.registry().get_database_id_for_path(str(first)), ids[0])
        roundabout = self.root / "." / "second.mdb"
        self.assertEqual(
            self.registry().get_database_id_for_path(str(roundabout)), ids[1]
        )
        self.assertIsNone(
            self.registry().get_database_id_for_path(str(self.root / "other.mdb"))
        )

    def test_reload_picks_up_state_changes_and_returned_lists_are_copies(self):
        db = self.make_db()
        registry = self.registry()
        self.assertEqual(registry.databases, [])
        self.write_state(
            "file_state.json",
            {"file_entries": [{"file_path": str(db), "is_checked": True}]},
        )
        self.assertEqual(registry.databases, [])
        registry.reload()
        self.assertEqual(len(registry.databases), 1)
        registry.databases.clear()
        selection = registry.workspace_selection
        selection.bid_uid = "changed"
        self.assertEqual(len(registry.databases), 1)
        self.assertIsNone(registry.workspace_selection.bid_uid)
        self.write_state("file_state.json", {"file_entries": []})
        registry.reload()
        self.assertEqual(registry.databases, [])

    def test_unreadable_state_files_yield_empty_registry_and_default_selection(self):
        db = self.make_db()
        for payload in ("{not json", "[1, 2]", '"text"', ""):
            with self.subTest(payload=payload):
                self.write_state("file_state.json", payload)
                self.write_state("workspace_state.json", payload)
                registry = self.registry()
                self.assertEqual(registry.databases, [])
                self.assertEqual(registry.workspace_selection, McpWorkspaceSelection())
        self.write_state(
            "file_state.json",
            {"file_entries": [{"file_path": str(db), "is_checked": True}]},
        )
        self.assertEqual(len(self.registry().databases), 1)

    def test_rejected_paths_are_logged_without_revealing_them(self):
        secret_dir = self.root / "secret-client"
        secret_dir.mkdir()
        (secret_dir / "gone.mdb").parent.mkdir(exist_ok=True)
        text = secret_dir / "notes.txt"
        text.write_text("", encoding="utf-8")
        self.write_state(
            "file_state.json",
            {
                "file_entries": [
                    {"file_path": str(secret_dir / "gone.mdb"), "is_checked": True},
                    {"file_path": str(text), "is_checked": True},
                ]
            },
        )
        with self.assertLogs(self.logger, level="WARNING") as logged:
            self.registry()
        self.assertEqual(
            sorted(record.getMessage() for record in logged.records),
            [
                "Ignoring configured database path that is missing",
                "Ignoring configured database path with non-MDB suffix",
            ],
        )
        self.assertNotIn("secret-client", "\n".join(logged.output))

    def test_workspace_selection_defaults_and_active_view_normalization(self):
        db = self.make_db()
        self.write_state(
            "file_state.json",
            {"file_entries": [{"file_path": str(db), "is_checked": True}]},
        )
        selected = {
            WORKSPACE_KEY_KIND: "project",
            WORKSPACE_KEY_FILE_PATH: str(db),
            WORKSPACE_KEY_PROJECT_UID: "proj-1",
        }
        for stored, expected in (
            ("2D", "2d"),
            ("2d", "2d"),
            ("sideways", "3d"),
        ):
            with self.subTest(stored=stored):
                self.write_state(
                    "workspace_state.json",
                    {
                        WORKSPACE_KEY_TAKEOFF_WORKSPACE: {
                            WORKSPACE_KEY_ACTIVE_VIEW: stored
                        },
                        WORKSPACE_KEY_PROJECT_WORKSPACE: {
                            WORKSPACE_KEY_SELECTED_NODE: selected
                        },
                    },
                )
                selection = self.registry().workspace_selection
                self.assertEqual(selection.active_view, expected)
                self.assertEqual(selection.selected_node_kind, "project")
                self.assertEqual(selection.project_uid, "proj-1")
                self.assertIsNone(selection.bid_uid)
                self.assertEqual(selection.file_path, str(db))
        self.write_state("workspace_state.json", {})
        self.assertEqual(self.registry().workspace_selection, McpWorkspaceSelection())

    def test_workspace_selection_of_unregistered_file_has_no_database_id(self):
        db = self.make_db()
        self.write_state(
            "workspace_state.json",
            {
                WORKSPACE_KEY_PROJECT_WORKSPACE: {
                    WORKSPACE_KEY_SELECTED_NODE: {
                        WORKSPACE_KEY_KIND: WORKSPACE_NODE_KIND_BID,
                        WORKSPACE_KEY_FILE_PATH: str(db),
                        WORKSPACE_KEY_BID_UID: "",
                    }
                }
            },
        )
        selection = self.registry().workspace_selection
        self.assertIsNone(selection.database_id)
        self.assertEqual(selection.file_path, str(db))
        self.assertIsNone(selection.bid_uid)

    def test_malformed_selected_node_is_ignored(self):
        self.write_state(
            "workspace_state.json",
            {WORKSPACE_KEY_PROJECT_WORKSPACE: {WORKSPACE_KEY_SELECTED_NODE: "bid-1"}},
        )
        self.assertEqual(self.registry().workspace_selection, McpWorkspaceSelection())
        self.write_state(
            "workspace_state.json", {WORKSPACE_KEY_PROJECT_WORKSPACE: ["bid-1"]}
        )
        self.assertEqual(self.registry().workspace_selection, McpWorkspaceSelection())

    def test_output_artifacts_dir_lives_under_the_app_data_dir(self):
        self.assertEqual(
            self.registry().output_artifacts_dir, self.root / MCP_OUTPUT_DIR_NAME
        )
        self.assertEqual(MCP_OUTPUT_DIR_NAME, "mcp_outputs")


if __name__ == "__main__":
    unittest.main()
