import ast
import unittest
from tests.paths import REPO_ROOT

_COORDINATOR = (
    REPO_ROOT
    / "ost_visualizer"
    / "presentation"
    / "coordinators"
    / "ui_event_coordinator.py"
)


def _function_nodes(source, name):
    return [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]


def _identifier_names(function):
    names = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


class BidLockPermissionTests(unittest.TestCase):
    def test_area_dialog_without_selected_bid_has_no_stale_presence_reference(self):
        methods = _function_nodes(
            _COORDINATOR.read_text(encoding="utf-8"), "open_areas_dialog"
        )
        self.assertEqual(len(methods), 1)
        names = _identifier_names(methods[0])
        # Positive control: this is the real method (it reads the selected bid
        # and returns early when there is none), so the scan is not vacuous.
        self.assertIn("get_selected_bid_ref", names)
        self.assertIn("bid_ref", names)
        self.assertNotIn("prev_bid_ref", names)

    def test_identifier_scan_reports_a_stale_presence_reference(self):
        source = (
            "class C:\n"
            "    def open_areas_dialog(self):\n"
            "        bid_ref = self.get_selected_bid_ref()\n"
            "        if prev_bid_ref and bid_ref != prev_bid_ref:\n"
            "            return\n"
        )
        (method,) = _function_nodes(source, "open_areas_dialog")
        self.assertIn("prev_bid_ref", _identifier_names(method))
        clean = source.replace("prev_bid_ref", "bid_ref")
        (method,) = _function_nodes(clean, "open_areas_dialog")
        self.assertNotIn("prev_bid_ref", _identifier_names(method))
