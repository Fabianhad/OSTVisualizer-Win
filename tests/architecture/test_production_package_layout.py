import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from tests.paths import REPO_ROOT

_SPEC = importlib.util.spec_from_file_location(
    "check_architecture_for_package_layout_tests",
    REPO_ROOT / "tools" / "check_architecture.py",
)
check_architecture = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_architecture)


class ProductionPackageLayoutTests(unittest.TestCase):
    def setUp(self):
        check_architecture.violations.clear()
        self.addCleanup(check_architecture.violations.clear)

    def test_an_init_file_in_a_production_package_is_a_violation(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            package = repo / "ost_visualizer" / "mcp_takeoff"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "proxy.py").write_text("", encoding="utf-8")
            with mock.patch.object(
                check_architecture, "REPO_ROOT", repo
            ), mock.patch.object(
                check_architecture, "OST_ROOT", repo / "ost_visualizer"
            ):
                check_architecture.check_package_layout()
                found = [
                    (
                        violation.category,
                        check_architecture.relpath(violation.filepath),
                    )
                    for violation in check_architecture.violations
                ]
        self.assertEqual(
            found, [("package layout", "ost_visualizer/mcp_takeoff/__init__.py")]
        )

    def test_the_production_tree_is_namespace_packages_only(self):
        check_architecture.check_package_layout()
        self.assertEqual(
            [str(violation) for violation in check_architecture.violations], []
        )
        self.assertEqual(list((REPO_ROOT / "ost_visualizer").rglob("__init__.py")), [])

    def test_the_full_scan_reports_the_package_layout_category(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = check_architecture.main()
        self.assertEqual(status, 0)
        self.assertIn("Package layout: PASS", output.getvalue())


if __name__ == "__main__":
    unittest.main()
