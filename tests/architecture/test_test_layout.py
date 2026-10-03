"""Keep primary tests discoverable beside their production module's mirror."""

import ast
import os
import re
import tempfile
import unittest
from pathlib import Path
from tests.paths import REPO_ROOT, TESTS_ROOT

_DISCOVER_COMMAND = re.compile(r"unittest\s+discover\b")
_TOP_LEVEL_OPTION = re.compile(r"\s-t\s+\S")


def _unmirrored_modules(tests_root, repo_root):
    mismatches = []
    for path in tests_root.rglob("test_*.py"):
        relative = path.relative_to(tests_root)
        if relative.parts[0] in {"architecture", "integration"}:
            continue
        source = relative.with_name(path.name.removeprefix("test_"))
        candidates = [repo_root / "ost_visualizer" / source, repo_root / source]
        if relative.parts[0] == "helpers":
            candidates.append(tests_root / source)
        if not any(candidate.is_file() for candidate in candidates):
            mismatches.append(relative.as_posix())
    return mismatches


def _directories_without_init(tests_root, repo_root):
    missing = set()
    for path in tests_root.rglob("test_*.py"):
        directory = path.parent
        while directory != repo_root and directory != directory.parent:
            if not (directory / "__init__.py").is_file():
                missing.add(directory.relative_to(repo_root).as_posix())
            directory = directory.parent
    return missing


def _legacy_flat_imports(source):
    stale = []
    for node in ast.walk(ast.parse(source)):
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
                stale.append(module)
    return stale


def _discover_commands_missing_top_level(text):
    return [
        line.strip()
        for line in text.splitlines()
        if _DISCOVER_COMMAND.search(line) and not _TOP_LEVEL_OPTION.search(line)
    ]


def _count_files(root, prefix, suffix):
    return sum(
        name.startswith(prefix) and name.endswith(suffix)
        for _directory, _names, files in os.walk(root)
        for name in files
    )


class TestLayoutTests(unittest.TestCase):
    def test_primary_module_paths_mirror_production_or_local_fixture_subjects(self):
        # Positive control: hundreds of primary test modules are checked.
        self.assertGreaterEqual(_count_files(TESTS_ROOT, "test_", ".py"), 400)
        self.assertEqual(_unmirrored_modules(TESTS_ROOT, REPO_ROOT), [])

    def test_test_directories_are_importable_with_repository_top_level(self):
        self.assertGreaterEqual(_count_files(TESTS_ROOT, "test_", ".py"), 400)
        self.assertEqual(_directories_without_init(TESTS_ROOT, REPO_ROOT), set())

    def test_no_legacy_flat_test_imports_remain(self):
        scanned = 0
        stale = []
        for path in TESTS_ROOT.rglob("*.py"):
            scanned += 1
            stale.extend(
                (path.relative_to(TESTS_ROOT).as_posix(), module)
                for module in _legacy_flat_imports(path.read_text(encoding="utf-8-sig"))
            )
        # Positive control: the scan reached the real test tree.
        self.assertGreaterEqual(scanned, 500)
        self.assertEqual(stale, [])

    def test_documented_discovery_commands_pin_the_repository_top_level(self):
        # Without ``-t .`` unittest treats ``tests`` as the top level, so
        # ``tests/tools`` and ``tests/sql_server`` shadow the production
        # ``tools`` and ``sql_server`` packages and several modules fail to
        # import. Every documented discovery command must therefore carry -t.
        documents = [
            *REPO_ROOT.glob("*.md"),
            *TESTS_ROOT.glob("*.md"),
            *(REPO_ROOT / "scripts").glob("*.ps1"),
            *(REPO_ROOT / "scripts").glob("*.sh"),
        ]
        makefile = REPO_ROOT / "Makefile"
        if makefile.is_file():
            documents.append(makefile)
        commands = 0
        unpinned = []
        for path in documents:
            text = path.read_text(encoding="utf-8")
            commands += len(_DISCOVER_COMMAND.findall(text))
            unpinned.extend(
                f"{path.relative_to(REPO_ROOT).as_posix()}: {line}"
                for line in _discover_commands_missing_top_level(text)
            )
        # Positive control: AGENTS.md, README.md, tests/README.md and
        # scripts/run-sql-integration.ps1 hold ten documented commands.
        self.assertGreaterEqual(commands, 8)
        self.assertEqual(unpinned, [])


class TestLayoutScannerSelfTests(unittest.TestCase):
    """Prove each layout scanner reports a violation on a synthetic tree."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name).resolve()
        self.tests = self.repo / "tests"

    def _write(self, relative, text=""):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_mirror_scanner_reports_orphans_and_accepts_mirrors(self):
        self._write("tests/handlers/test_mirrored.py")
        self._write("ost_visualizer/handlers/mirrored.py")
        self._write("tests/handlers/test_orphan.py")
        self._write("tests/tools/test_script.py")
        self._write("tools/script.py")
        self._write("tests/helpers/test_local_fixture.py")
        self._write("tests/helpers/local_fixture.py")
        self._write("tests/architecture/test_exempt_contract.py")
        self.assertEqual(
            _unmirrored_modules(self.tests, self.repo), ["handlers/test_orphan.py"]
        )

    def test_importability_scanner_reports_directories_without_init(self):
        self._write("tests/__init__.py")
        self._write("tests/good/__init__.py")
        self._write("tests/good/test_a.py")
        self._write("tests/bad/test_b.py")
        self._write("tests/good/nested/test_c.py")
        self.assertEqual(
            _directories_without_init(self.tests, self.repo),
            {"tests/bad", "tests/good/nested"},
        )

    def test_legacy_import_scanner_flags_flat_modules_only(self):
        self.assertEqual(
            _legacy_flat_imports("from tests import test_old\nimport tests.test_x\n"),
            ["tests.test_old", "tests.test_x"],
        )
        self.assertEqual(
            _legacy_flat_imports("from tests.test_old import Thing\n"),
            ["tests.test_old"],
        )
        self.assertEqual(
            _legacy_flat_imports(
                "from tests.test_main import X\n"
                "from tests.paths import REPO_ROOT\n"
                "from tests.tools.test_x import Y\n"
            ),
            [],
        )

    def test_discovery_command_scanner_requires_a_top_level_option(self):
        self.assertEqual(
            _discover_commands_missing_top_level(
                "python -m unittest discover -s tests -v\n"
                "python -m unittest discover -s tests -t . -v\n"
                '& $python -m unittest discover -s (Join-Path $t "x") -t $repo `\n'
                "python -m unittest tests.pkg.test_mod\n"
            ),
            ["python -m unittest discover -s tests -v"],
        )
