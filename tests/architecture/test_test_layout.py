"""Keep primary tests discoverable beside their production module's mirror."""

import ast
import unittest
from pathlib import Path
from tests.paths import REPO_ROOT, TESTS_ROOT


class TestLayoutTests(unittest.TestCase):
    def test_primary_module_paths_mirror_production_or_local_fixture_subjects(self):
        mismatches = []
        for path in TESTS_ROOT.rglob("test_*.py"):
            relative = path.relative_to(TESTS_ROOT)
            if relative.parts[0] in {"architecture", "integration"}:
                continue
            source = relative.with_name(path.name.removeprefix("test_"))
            candidates = [REPO_ROOT / "ost_visualizer" / source, REPO_ROOT / source]
            if relative.parts[0] == "helpers":
                candidates.append(TESTS_ROOT / source)
            if not any(candidate.is_file() for candidate in candidates):
                mismatches.append(relative.as_posix())
        self.assertEqual(mismatches, [])

    def test_test_directories_are_importable_with_repository_top_level(self):
        missing = set()
        for path in TESTS_ROOT.rglob("test_*.py"):
            directory = path.parent
            while directory != REPO_ROOT:
                if not (directory / "__init__.py").is_file():
                    missing.add(directory.relative_to(REPO_ROOT).as_posix())
                directory = directory.parent
        self.assertEqual(missing, set())

    def test_no_legacy_flat_test_imports_remain(self):
        stale = []
        for path in TESTS_ROOT.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.Import):
                    modules.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    if node.module == "tests":
                        modules.extend("tests." + alias.name for alias in node.names)
                    elif node.module:
                        modules.append(node.module)
                for module in modules:
                    if module.startswith("tests.test_") and module != "tests.test_main":
                        stale.append((path.relative_to(TESTS_ROOT).as_posix(), module))
        self.assertEqual(stale, [])
