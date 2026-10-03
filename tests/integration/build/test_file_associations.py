from __future__ import annotations
import importlib.util
import json
import unittest
import xml.etree.ElementTree as ET
from ost_visualizer.application.dtos.file_import_args import (
    PROJECT_IMPORT_EXTENSION_OSP,
    PROJECT_IMPORT_EXTENSION_OST,
    parse_project_file_args,
)
from ost_visualizer.infrastructure.windows.file_associations import (
    ASSOCIATIONS,
    FileAssociationRegistrar,
    FileAssociationRegistryError,
    WinRegRegistry,
    build_open_command,
)
from tests.paths import REPO_ROOT
from tests.helpers.startup_import import (
    MSI_CREATOR_ROOT as _startup_import_MSI_CREATOR_ROOT,
    OSP_PROG_ID as _startup_import_OSP_PROG_ID,
    OST_PROG_ID as _startup_import_OST_PROG_ID,
    REPO_MSI_CONFIG as _startup_import_REPO_MSI_CONFIG,
)


class InstalledFileAssociationTests(unittest.TestCase):
    def test_msi_config_contains_installed_file_associations(self):
        config = json.loads(_startup_import_REPO_MSI_CONFIG.read_text(encoding="utf-8"))
        entries = {
            (entry["root"], entry["key"], entry.get("name")): entry
            for entry in config["registry_entries"]
        }
        self.assertEqual(
            entries[
                ("HKLM", f"Software\\Classes\\{PROJECT_IMPORT_EXTENSION_OST}", None)
            ]["value"],
            _startup_import_OST_PROG_ID,
        )
        self.assertEqual(
            entries[
                ("HKLM", f"Software\\Classes\\{PROJECT_IMPORT_EXTENSION_OSP}", None)
            ]["value"],
            _startup_import_OSP_PROG_ID,
        )
        self.assertEqual(
            entries[
                (
                    "HKLM",
                    f"Software\\Classes\\{_startup_import_OST_PROG_ID}\\shell\\open\\command",
                    None,
                )
            ]["value"],
            '"[INSTALLDIR]Visualizer.exe" "%1"',
        )
        self.assertEqual(
            entries[
                (
                    "HKLM",
                    f"Software\\Classes\\{_startup_import_OSP_PROG_ID}\\shell\\open\\command",
                    None,
                )
            ]["value"],
            '"[INSTALLDIR]Visualizer.exe" "%1"',
        )
        # The installer registers the same class descriptions the runtime
        # registrar would write for each ProgID.
        for extension in (PROJECT_IMPORT_EXTENSION_OST, PROJECT_IMPORT_EXTENSION_OSP):
            prog_id, description = ASSOCIATIONS[extension]
            self.assertEqual(
                entries[("HKLM", f"Software\Classes\{prog_id}", None)]["value"],
                description,
            )

    def test_external_msi_config_matches_checked_in_source_when_available(self):
        external_config = _startup_import_MSI_CREATOR_ROOT / "ostvisualizer.json"
        if not external_config.exists():
            self.skipTest("msicreator-master checkout is not available")
        repo_config = json.loads(
            _startup_import_REPO_MSI_CONFIG.read_text(encoding="utf-8")
        )
        builder_config = json.loads(external_config.read_text(encoding="utf-8-sig"))
        self.assertEqual(
            builder_config["registry_entries"], repo_config["registry_entries"]
        )

    def test_msi_creator_omits_name_for_default_registry_value(self):
        module_path = _startup_import_MSI_CREATOR_ROOT / "createmsi.py"
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
                "key": f"Software\\Classes\\{PROJECT_IMPORT_EXTENSION_OST}",
                "name": None,
                "type": "string",
                "value": _startup_import_OST_PROG_ID,
                "key_path": "yes",
            },
        )
        value = component.find("RegistryKey/RegistryValue")
        self.assertIsNotNone(value)
        self.assertNotIn("Name", value.attrib)
        self.assertEqual(value.attrib["Value"], _startup_import_OST_PROG_ID)
        # Positive control: a named value keeps its Name attribute, so the
        # omission above is specific to the default (None) value.
        named_component = ET.Element("Component")
        module.PackageGenerator.create_registry_entries(
            None,
            named_component,
            {
                "root": "HKLM",
                "key": f"Software\\Classes\\{_startup_import_OST_PROG_ID}\\Application",
                "name": "ApplicationName",
                "type": "string",
                "value": "OST Visualizer",
                "key_path": "no",
            },
        )
        named_value = named_component.find("RegistryKey/RegistryValue")
        self.assertEqual(named_value.attrib["Name"], "ApplicationName")
