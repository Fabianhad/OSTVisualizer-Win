import re
import unittest
from tests.paths import REPO_ROOT

_TREE_CONSTRUCTION = re.compile(
    r"QtWidgets\.QTree(?:Widget|View)\(|\(QtWidgets\.QTree(?:Widget|View)\)"
)
# The helper must be called, not merely imported or mentioned in a comment.
_INDENTATION_CALL = re.compile(r"\bapply_(?:tree_indentation|condition_tree_style)\(")


def _constructs_tree(text):
    return _TREE_CONSTRUCTION.search(text) is not None


def _applies_indentation_helper(text):
    return _INDENTATION_CALL.search(text) is not None


class TreeIndentationConstructionContractTests(unittest.TestCase):
    def test_presentation_tree_construction_sites_use_shared_indentation_helper(self):
        root = REPO_ROOT
        presentation_root = root / "ost_visualizer" / "presentation"
        texts = {
            path: path.read_text(encoding="utf-8")
            for path in sorted(presentation_root.rglob("*.py"))
            if path.name != "condition_tree_style.py"
        }
        tree_files = [path for path, text in texts.items() if _constructs_tree(text)]
        # Positive control: twelve presentation modules construct or subclass
        # Qt tree widgets today (found independently with grep).
        self.assertGreaterEqual(len(tree_files), 10)
        self.assertIn(
            presentation_root / "components" / "project_tree_view.py", tree_files
        )
        missing = [
            str(path.relative_to(root))
            for path in tree_files
            if not _applies_indentation_helper(texts[path])
        ]
        self.assertEqual(missing, [])

    def test_scanner_requires_a_helper_call_not_just_a_mention(self):
        constructed = "tree = QtWidgets.QTreeWidget(parent)\n"
        subclass = "class T(QtWidgets.QTreeView):\n    pass\n"
        self.assertTrue(_constructs_tree(constructed))
        self.assertTrue(_constructs_tree(subclass))
        self.assertFalse(_constructs_tree("label = QtWidgets.QLabel()\n"))
        self.assertTrue(
            _applies_indentation_helper(constructed + "apply_tree_indentation(tree)\n")
        )
        self.assertTrue(
            _applies_indentation_helper(
                constructed + "apply_condition_tree_style(tree)\n"
            )
        )
        self.assertFalse(_applies_indentation_helper(constructed))
        self.assertFalse(
            _applies_indentation_helper(
                "from .condition_tree_style import apply_tree_indentation\n"
                + constructed
            )
        )
