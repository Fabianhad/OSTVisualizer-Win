import json
import logging
import tempfile
import unittest
from pathlib import Path
from ost_visualizer.mcp_server.registry import DatabaseRegistry


class DatabaseRegistryTests(unittest.TestCase):
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
            txt_path = root / "notes.txt"
            txt_path.write_text("", encoding="utf-8")
            (root / "file_state.json").write_text(
                json.dumps(
                    {
                        "file_entries": [
                            {"file_path": str(db_path), "is_checked": True},
                            {"file_path": str(unchecked_path), "is_checked": False},
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
                        "takeoff_workspace": {"active_view": "2d"},
                        "project_workspace": {
                            "selected_node": {
                                "kind": "bid",
                                "file_path": str(db_path),
                                "bid_uid": "bid-1",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            registry = DatabaseRegistry(app_data_dir=root, logger=self._quiet_logger())
            selection = registry.workspace_selection
            self.assertEqual(selection.selected_node_kind, "bid")
            self.assertEqual(selection.bid_uid, "bid-1")
            self.assertEqual(selection.active_view, "2d")
            self.assertEqual(selection.database_id, registry.databases[0].database_id)


if __name__ == "__main__":
    unittest.main()
