import ast
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from tests.paths import REPO_ROOT

_SPEC = importlib.util.spec_from_file_location(
    "check_architecture_for_shared_texts_tests",
    REPO_ROOT / "tools" / "check_architecture.py",
)
check_architecture = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_architecture)


class SharedTextsLayerTests(unittest.TestCase):
    def setUp(self):
        check_architecture.violations.clear()
        self.addCleanup(check_architecture.violations.clear)

    def run_checks(self, files):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            for relative, source in files.items():
                path = repo / "ost_visualizer" / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding="utf-8")
            with mock.patch.object(
                check_architecture, "REPO_ROOT", repo
            ), mock.patch.object(
                check_architecture, "OST_ROOT", repo / "ost_visualizer"
            ):
                check_architecture.check_layer_boundaries()
                check_architecture.check_shared_module()
                return sorted(
                    (
                        violation.category,
                        check_architecture.relpath(violation.filepath),
                        violation.line,
                    )
                    for violation in check_architecture.violations
                )

    def test_a_shared_module_that_imports_project_code_is_a_violation(self):
        found = self.run_checks(
            {
                "shared/texts.py": (
                    "import re\n"
                    "from ost_visualizer.domain import entities\n"
                    "from ..application import services\n"
                    "import ost_visualizer.presentation\n"
                    'GREETING = "Hello"\n'
                ),
            }
        )
        self.assertEqual(
            found,
            [
                ("shared module", "ost_visualizer/shared/texts.py", 2),
                ("shared module", "ost_visualizer/shared/texts.py", 3),
                ("shared module", "ost_visualizer/shared/texts.py", 4),
            ],
        )

    def test_domain_may_import_the_shared_module_but_still_not_the_outer_layers(self):
        found = self.run_checks(
            {
                "shared/texts.py": 'GREETING = "Hello"\n',
                "domain/entity.py": (
                    "from ..shared.texts import GREETING\n"
                    "from ost_visualizer.shared.texts import GREETING as AGAIN\n"
                    "from ..application import services\n"
                    "from ..infrastructure import sql\n"
                    "from ..presentation import texts\n"
                ),
            }
        )
        self.assertEqual(
            found,
            [
                ("layer", "ost_visualizer/domain/entity.py", 3),
                ("layer", "ost_visualizer/domain/entity.py", 4),
                ("layer", "ost_visualizer/domain/entity.py", 5),
            ],
        )

    def test_the_real_shared_texts_module_holds_only_string_constants(self):
        path = REPO_ROOT / "ost_visualizer" / "shared" / "texts.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        self.assertTrue(tree.body)
        for node in tree.body:
            self.assertIsInstance(node, ast.Assign, ast.dump(node)[:80])
            self.assertIsInstance(ast.literal_eval(node.value), (str, tuple))
        check_architecture.check_shared_module()
        self.assertEqual(
            [str(violation) for violation in check_architecture.violations], []
        )


if __name__ == "__main__":
    unittest.main()
