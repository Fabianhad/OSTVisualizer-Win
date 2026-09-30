import unittest
from tests.paths import REPO_ROOT


class TreeIndentationConstructionContractTests(unittest.TestCase):
    def test_presentation_tree_construction_sites_use_shared_indentation_helper(self):
        root = REPO_ROOT
        presentation_root = root / "ost_visualizer" / "presentation"
        tree_files = sorted(
            path
            for path in presentation_root.rglob("*.py")
            if path.name != "condition_tree_style.py"
            and (
                "QtWidgets.QTreeWidget(" in path.read_text(encoding="utf-8")
                or "QtWidgets.QTreeView(" in path.read_text(encoding="utf-8")
                or "(QtWidgets.QTreeWidget)" in path.read_text(encoding="utf-8")
                or "(QtWidgets.QTreeView)" in path.read_text(encoding="utf-8")
            )
        )
        missing = [
            str(path.relative_to(root))
            for path in tree_files
            if "apply_tree_indentation" not in path.read_text(encoding="utf-8")
            and "apply_condition_tree_style" not in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(missing, [])
