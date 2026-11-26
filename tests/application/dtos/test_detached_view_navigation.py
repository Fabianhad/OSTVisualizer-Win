import ast
import unittest
from ost_visualizer.application.dtos.detached_view_navigation import (
    USER_NAVIGATION_SOURCES,
    DetachedViewNavigationSource,
)
from tests.paths import REPO_ROOT

_ENTRY_POINTS = {"open_view", "load_view", "_create_window"}


class DetachedViewNavigationSourceTests(unittest.TestCase):
    def test_every_source_has_a_stable_value_and_unknown_is_not_one(self):
        self.assertEqual(
            {source.value for source in DetachedViewNavigationSource},
            {
                "hotlink",
                "combobox",
                "named_view_combo",
                "window_toggle",
                "restore",
                "refresh",
            },
        )
        with self.assertRaises(ValueError):
            DetachedViewNavigationSource("unknown")

    def test_only_the_user_gestures_are_user_navigation(self):
        self.assertEqual(
            USER_NAVIGATION_SOURCES,
            {
                DetachedViewNavigationSource.HOTLINK,
                DetachedViewNavigationSource.PAGE_COMBO,
                DetachedViewNavigationSource.NAMED_VIEW_COMBO,
                DetachedViewNavigationSource.WINDOW_TOGGLE,
            },
        )
        self.assertNotIn(DetachedViewNavigationSource.RESTORE, USER_NAVIGATION_SOURCES)
        self.assertNotIn(DetachedViewNavigationSource.REFRESH, USER_NAVIGATION_SOURCES)


class NoCallerPassesAnUnknownSourceTests(unittest.TestCase):
    def test_every_detached_view_entry_point_call_names_its_source(self):
        missing, unknown, checked = [], [], 0
        for path in sorted((REPO_ROOT / "ost_visualizer").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value == "unknown":
                    parent_line = node.lineno
                    source = path.read_text(encoding="utf-8").splitlines()[
                        parent_line - 1
                    ]
                    if "navigation" in source:
                        unknown.append(f"{path.name}:{parent_line}")
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = (
                    func.attr
                    if isinstance(func, ast.Attribute)
                    else getattr(func, "id", "")
                )
                if name not in _ENTRY_POINTS:
                    continue
                if name == "open_view" and not (
                    isinstance(func, ast.Attribute)
                    and "manager" in ast.unparse(func.value)
                    or path.name == "open_annotation_view_use_case.py"
                ):
                    continue
                checked += 1
                keywords = {k.arg for k in node.keywords}
                positional_source = name == "_create_window" and len(node.args) >= 6
                if "navigation_source" not in keywords and not positional_source:
                    missing.append(f"{path.name}:{node.lineno} {name}")
        self.assertEqual(unknown, [])
        self.assertEqual(missing, [])
        self.assertGreaterEqual(checked, 9)

    def test_the_window_toggle_actions_and_the_restore_name_their_source(self):
        presentation = REPO_ROOT / "ost_visualizer" / "presentation"
        expected = {
            "builders/component_builder.py": "WINDOW_TOGGLE",
            "coordinators/workspace_state_coordinator.py": "RESTORE",
        }
        for relative, member in expected.items():
            tree = ast.parse((presentation / relative).read_text(encoding="utf-8"))
            for setter in ("set_annotation_window_visible", "set_view_window_visible"):
                with self.subTest(file=relative, setter=setter):
                    sites = [
                        ast.unparse(node)
                        for node in ast.walk(tree)
                        if isinstance(node, ast.Call)
                        and setter in ast.unparse(node.func)
                        or isinstance(node, ast.Call)
                        and any(setter in ast.unparse(arg) for arg in node.args)
                        and "connect" in ast.unparse(node.func)
                    ]
                    self.assertTrue(sites)
                    for site in sites:
                        self.assertIn(
                            f"navigation_source=DetachedViewNavigationSource.{member}",
                            site,
                        )


if __name__ == "__main__":
    unittest.main()
