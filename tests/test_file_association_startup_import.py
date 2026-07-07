from __future__ import annotations
import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from ost_visualizer.application.dtos.file_import_args import parse_project_file_args
from ost_visualizer.application.use_cases.project import (
    import_project_files_from_args_use_case as import_args_use_case,
)
from ost_visualizer.domain.entities.file_state import FileEntry
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.workspace_state import (
    ProjectTreeSelectionState,
    WorkspaceState,
    WORKSPACE_NODE_KIND_BID,
    WORKSPACE_NODE_KIND_PROJECT,
)
from ost_visualizer.infrastructure.windows.file_associations import (
    ASSOCIATIONS,
    FileAssociationRegistrar,
    FileAssociationRegistryError,
    WinRegRegistry,
    build_open_command,
)
from ost_visualizer.main import (
    _project_file_args_from_payload,
    _project_file_args_to_payload,
)
from ost_visualizer.presentation.main_window import MainWindow

REPO_ROOT = Path(__file__).resolve().parents[1]
MSI_CREATOR_ROOT = REPO_ROOT.parent / "msicreator-master"
REPO_MSI_CONFIG = REPO_ROOT / "installer" / "ostvisualizer.json"


class FakeImportService:
    def __init__(self, project_data=None, new_project_uid=None, reload_result=True):
        self.calls = []
        self.reloads = []
        self.project_data = project_data
        self.new_project_uid = new_project_uid
        self.reload_result = reload_result

    def import_ost(self, source, target_db, project_uid, refresh=True):
        self.calls.append(("ost", source, target_db, project_uid, refresh))
        self._add_project(target_db)
        return True

    def import_osp(self, source, target_db, project_uid, refresh=True):
        self.calls.append(("osp", source, target_db, project_uid, refresh))
        self._add_project(target_db)
        return True

    def reload_and_notify(self, target_db):
        self.reloads.append(target_db)
        return self.reload_result

    def _add_project(self, target_db):
        if self.project_data is None or self.new_project_uid is None:
            return
        entry = self.project_data.hierarchy.loaded_files[0]
        entry.bid_projects[self.new_project_uid] = HierarchyProjectInfo(
            name="Imported Project"
        )


class FakeProjectData:
    def __init__(self, file_path):
        self.hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path=file_path,
                    bid_projects={
                        "stored-project": HierarchyProjectInfo(
                            name="Stored Project",
                            bids=[HierarchyBidInfo(uid="stored-bid")],
                        )
                    },
                )
            ]
        )

    def get_hierarchy(self):
        return self.hierarchy


class FakeRegistry:
    def __init__(self):
        self.values = {}
        self.deleted = []

    def set_value(self, key_path, name, value):
        self.values[(key_path, name)] = value

    def delete_tree(self, key_path):
        self.deleted.append(key_path)


class FakeProjectView:
    def __init__(self):
        self.project_selections = []
        self.file_selections = []

    def restore_project_selection(self, project_uid, file_path=None):
        self.project_selections.append((project_uid, file_path))

    def restore_file_selection(self, file_path):
        self.file_selections.append(file_path)


class FileAssociationStartupImportTests(unittest.TestCase):
    def test_parse_project_file_args_with_no_files_keeps_startup_path_empty(self):
        result = parse_project_file_args([])
        self.assertFalse(result.has_file_args)

    def test_parse_project_file_args_accepts_ost_osp_and_preserves_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ost = root / "project with spaces.ost"
            osp = root / "package.osp"
            ost.write_text("ost")
            osp.write_text("osp")
            result = parse_project_file_args([str(ost), str(osp)])
            self.assertEqual(
                [item.extension for item in result.files], [".ost", ".osp"]
            )
            self.assertEqual([item.path for item in result.files], [str(ost), str(osp)])
            self.assertEqual(result.rejected, [])

    def test_parse_project_file_args_rejects_unsupported_and_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unsupported = root / "notes.txt"
            missing = root / "missing.ost"
            unsupported.write_text("x")
            result = parse_project_file_args([str(unsupported), str(missing)])
            self.assertEqual(result.files, [])
            self.assertEqual(len(result.rejected), 2)
            self.assertIn("Unsupported file type", result.rejected[0].reason)
            self.assertEqual(result.rejected[1].reason, "File does not exist.")

    def test_import_use_case_uses_stored_project_before_first_checked_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            source = root / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            workspace = WorkspaceState()
            workspace.project_workspace.selected_node = ProjectTreeSelectionState(
                kind=WORKSPACE_NODE_KIND_PROJECT,
                file_path=str(target_db),
                project_uid="stored-project",
            )
            import_service = FakeImportService()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=FakeProjectData(str(target_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=workspace),
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]), lambda _path: True
            )
            self.assertEqual(result.succeeded, 1)
            self.assertEqual(import_service.calls[0][0], "ost")
            self.assertEqual(import_service.calls[0][2], str(target_db))
            self.assertEqual(import_service.calls[0][3], "stored-project")
            self.assertIs(import_service.calls[0][4], False)
            self.assertEqual(import_service.reloads, [str(target_db)])

    def test_import_use_case_resolves_stored_bid_to_project_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            source = root / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            workspace = WorkspaceState()
            workspace.project_workspace.selected_node = ProjectTreeSelectionState(
                kind=WORKSPACE_NODE_KIND_BID,
                file_path=str(target_db),
                bid_uid="stored-bid",
            )
            import_service = FakeImportService()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=FakeProjectData(str(target_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=workspace),
            )
            use_case.execute(parse_project_file_args([str(source)]), lambda _path: True)
            self.assertEqual(import_service.calls[0][3], "stored-project")

    def test_import_use_case_imports_multiple_files_sequentially(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            ost = root / "source.ost"
            osp = root / "source.osp"
            target_db.write_text("db")
            ost.write_text("ost")
            osp.write_text("osp")
            import_service = FakeImportService()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=FakeProjectData(str(target_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            result = use_case.execute(
                parse_project_file_args([str(ost), str(osp)]), lambda _path: True
            )
            self.assertEqual(result.succeeded, 2)
            self.assertEqual([call[0] for call in import_service.calls], ["ost", "osp"])
            self.assertEqual(import_service.reloads, [str(target_db)])

    def test_main_window_selects_batch_project_or_database_once(self):
        window = SimpleNamespace(project_view=FakeProjectView())
        project_result = import_args_use_case.ProjectFileImportBatchResult(
            target_db_path="target.mdb",
            selected_project_uid="project-1",
        )
        database_result = import_args_use_case.ProjectFileImportBatchResult(
            target_db_path="target.mdb",
        )
        MainWindow._select_project_file_import_result(window, project_result)
        MainWindow._select_project_file_import_result(window, database_result)
        self.assertEqual(
            window.project_view.project_selections, [("project-1", "target.mdb")]
        )
        self.assertEqual(window.project_view.file_selections, ["target.mdb"])

    def test_import_use_case_reports_missing_enabled_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.osp"
            source.write_text("osp")
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=FakeImportService(),
                project_data_service=FakeProjectData(str(Path(tmp) / "missing.mdb")),
                file_state_model=SimpleNamespace(file_entries=[]),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]), lambda _path: True
            )
            self.assertEqual(result.succeeded, 0)
            self.assertEqual(result.failed, 1)
            self.assertIn("Enable or store a database", result.results[0].message)

    def test_import_use_case_flush_failure_prevents_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            source = root / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            import_service = FakeImportService()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=FakeProjectData(str(target_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]),
                lambda _path: False,
            )
            self.assertEqual(result.failed, 1)
            self.assertEqual(import_service.calls, [])
            self.assertIn("Pending database changes", result.results[0].message)

    def test_import_use_case_reports_refresh_failure_after_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            source = root / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            import_service = FakeImportService(reload_result=False)
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=FakeProjectData(str(target_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]), lambda _path: True
            )
            self.assertEqual(result.failed, 1)
            self.assertIn("could not be refreshed", result.results[0].message)

    def test_import_use_case_prefers_current_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_db = root / "first.mdb"
            current_db = root / "current.mdb"
            source = root / "source.osp"
            first_db.write_text("db")
            current_db.write_text("db")
            source.write_text("osp")
            import_service = FakeImportService()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=FakeProjectData(str(current_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[
                        FileEntry(str(first_db), is_checked=True),
                        FileEntry(str(current_db), is_checked=True),
                    ]
                ),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            use_case.execute(
                parse_project_file_args([str(source)]),
                lambda _path: True,
                current_target=import_args_use_case.ProjectImportCurrentTarget(
                    file_path=str(current_db), project_uid="current-project"
                ),
            )
            self.assertEqual(import_service.calls[0][2], str(current_db))
            self.assertEqual(import_service.calls[0][3], "current-project")

    def test_import_use_case_detects_single_new_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            source = root / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            project_data = FakeProjectData(str(target_db))
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=FakeImportService(project_data, "new-project"),
                project_data_service=project_data,
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]), lambda _path: True
            )
            self.assertEqual(result.selected_project_uid, "new-project")
            self.assertEqual(result.results[0].project_name, "Imported Project")

    def test_socket_payload_round_trip_preserves_file_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.ost"
            source.write_text("ost")
            args = parse_project_file_args([str(source), str(Path(tmp) / "bad.txt")])
            restored = _project_file_args_from_payload(
                _project_file_args_to_payload(args)
            )
            self.assertEqual(restored.files, args.files)
            self.assertEqual(restored.rejected, args.rejected)

    def test_registry_register_and_unregister_keys(self):
        registry = FakeRegistry()
        exe = Path("C:/Program Files/OST Visualizer/Visualizer.exe")
        registrar = FileAssociationRegistrar(executable_path=exe, registry=registry)
        registrar.register()
        registrar.unregister()
        command = build_open_command(exe)
        self.assertEqual(
            command, '"C:\\Program Files\\OST Visualizer\\Visualizer.exe" "%1"'
        )
        for extension, (prog_id, description) in ASSOCIATIONS.items():
            self.assertEqual(
                registry.values[(f"Software\\Classes\\{extension}", "")],
                prog_id,
            )
            self.assertEqual(
                registry.values[(f"Software\\Classes\\{prog_id}", "")],
                description,
            )
            self.assertEqual(
                registry.values[
                    (f"Software\\Classes\\{prog_id}\\shell\\open\\command", "")
                ],
                command,
            )
            self.assertIn(f"Software\\Classes\\{extension}", registry.deleted)
            self.assertIn(f"Software\\Classes\\{prog_id}", registry.deleted)

    def test_registry_command_can_include_development_script(self):
        command = build_open_command(
            Path("C:/Python311/python.exe"),
            Path("C:/Projects/OST Visualizer/Visualizer.py"),
        )
        self.assertEqual(
            command,
            '"C:\\Python311\\python.exe" '
            '"C:\\Projects\\OST Visualizer\\Visualizer.py" "%1"',
        )

    def test_winreg_registry_reports_non_windows_import_failure(self):
        def missing_winreg(_name):
            raise ImportError("no winreg")

        with self.assertRaisesRegex(FileAssociationRegistryError, "only be registered"):
            WinRegRegistry(import_module=missing_winreg)

    def test_msi_config_contains_installed_file_associations(self):
        config = json.loads(REPO_MSI_CONFIG.read_text(encoding="utf-8"))
        entries = {
            (entry["root"], entry["key"], entry.get("name")): entry
            for entry in config["registry_entries"]
        }
        self.assertEqual(
            entries[("HKLM", "Software\\Classes\\.ost", None)]["value"],
            "OSTVisualizer.ost",
        )
        self.assertEqual(
            entries[("HKLM", "Software\\Classes\\.osp", None)]["value"],
            "OSTVisualizer.osp",
        )
        self.assertEqual(
            entries[
                (
                    "HKLM",
                    "Software\\Classes\\OSTVisualizer.ost\\shell\\open\\command",
                    None,
                )
            ]["value"],
            '"[INSTALLDIR]Visualizer.exe" "%1"',
        )
        self.assertEqual(
            entries[
                (
                    "HKLM",
                    "Software\\Classes\\OSTVisualizer.osp\\shell\\open\\command",
                    None,
                )
            ]["value"],
            '"[INSTALLDIR]Visualizer.exe" "%1"',
        )

    def test_external_msi_config_matches_checked_in_source_when_available(self):
        external_config = MSI_CREATOR_ROOT / "ostvisualizer.json"
        if not external_config.exists():
            self.skipTest("msicreator-master checkout is not available")
        repo_config = json.loads(REPO_MSI_CONFIG.read_text(encoding="utf-8"))
        builder_config = json.loads(external_config.read_text(encoding="utf-8-sig"))
        self.assertEqual(
            builder_config["registry_entries"], repo_config["registry_entries"]
        )

    def test_msi_creator_omits_name_for_default_registry_value(self):
        module_path = MSI_CREATOR_ROOT / "createmsi.py"
        if not module_path.exists():
            self.skipTest("msicreator-master checkout is not available")
        spec = importlib.util.spec_from_file_location("createmsi_external", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        component = ET.Element("Component")
        module.PackageGenerator.create_registry_entries(
            None,
            component,
            {
                "root": "HKLM",
                "key": "Software\\Classes\\.ost",
                "name": None,
                "type": "string",
                "value": "OSTVisualizer.ost",
                "key_path": "yes",
            },
        )
        value = component.find("RegistryKey/RegistryValue")
        self.assertIsNotNone(value)
        self.assertNotIn("Name", value.attrib)
        self.assertEqual(value.attrib["Value"], "OSTVisualizer.ost")


if __name__ == "__main__":
    unittest.main()
