import ast
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.services.config_service import ConfigService
from PySide6 import QtCore, QtGui, QtWidgets
from tests.paths import REPO_ROOT
from tests.presentation.dialogs.options.preference_support import (
    _app as _preferences_support__app,
)

_APP_CONFIG_EVENT_NAMES = {"APP_CONFIG_UPDATED", "AppConfigUpdatedEvent"}


def _publishes_app_config_updated(tree):
    """True when any ``*.publish(<app config event>, ...)`` call is present.
    The event may be named through ``AppEvents.APP_CONFIG_UPDATED``, a bare or
    qualified ``AppConfigUpdatedEvent``, so none of those routes bypasses the
    single-publisher rule.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        event_arg = node.args[0]
        if not (isinstance(func, ast.Attribute) and func.attr == "publish"):
            continue
        if isinstance(event_arg, ast.Attribute) and (
            event_arg.attr in _APP_CONFIG_EVENT_NAMES
        ):
            return True
        if isinstance(event_arg, ast.Name) and event_arg.id in _APP_CONFIG_EVENT_NAMES:
            return True
    return False


class PreferencesContractPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_config_service_public_api_is_single_app_config_write_path(self):
        public_methods = {
            name
            for name, value in ConfigService.__dict__.items()
            if callable(value) and not name.startswith("_")
        }
        self.assertEqual(
            public_methods,
            {"get_config_snapshot", "update_app_options"},
        )

    def test_app_config_updated_is_published_only_by_config_service(self):
        publishers = []
        scanned = 0
        for path in (REPO_ROOT / "ost_visualizer").rglob("*.py"):
            scanned += 1
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if _publishes_app_config_updated(tree):
                publishers.append(path.relative_to(REPO_ROOT).as_posix())
        # Positive control: ~590 production modules exist (counted with find).
        self.assertGreaterEqual(scanned, 500)
        self.assertEqual(
            publishers,
            ["ost_visualizer/application/services/config_service.py"],
        )

    def test_user_facing_reset_view_actions_use_plan_view_reset_view(self):
        component_builder = (
            REPO_ROOT
            / "ost_visualizer"
            / "presentation"
            / "builders"
            / "component_builder.py"
        ).read_text(encoding="utf-8")
        detached_window = (
            REPO_ROOT
            / "ost_visualizer"
            / "presentation"
            / "windows"
            / "components"
            / "window.py"
        ).read_text(encoding="utf-8")
        self.assertIn("plan_view.reset_view()", component_builder)
        self.assertNotIn("plan_view.fit_to_page()", component_builder)
        self.assertIn(
            "self._btn_fit.clicked.connect(self.plan_view.reset_view)",
            detached_window,
        )
        self.assertNotIn(
            "self._btn_fit.clicked.connect(self.plan_view.fit_to_page)",
            detached_window,
        )

    def test_project_database_write_paths_do_not_depend_on_config_service(self):
        write_path_roots = [
            REPO_ROOT / "ost_visualizer" / "infrastructure",
            REPO_ROOT / "ost_visualizer" / "application" / "services",
        ]
        scanned = []
        for root in write_path_roots:
            for path in root.rglob("*.py"):
                if path.name == "config_service.py":
                    continue
                text = path.read_text(encoding="utf-8")
                if (
                    "write" in path.name.lower()
                    or "mdb" in path.relative_to(root).parts
                ):
                    scanned.append(path)
                    self.assertNotIn("config_service", text)
                    self.assertNotIn("ConfigService", text)
        # Positive control: ~43 write/mdb modules exist (counted with find).
        self.assertGreaterEqual(len(scanned), 30)


class AppConfigPublisherScannerSelfTests(unittest.TestCase):
    def test_scanner_flags_every_route_to_the_app_config_event(self):
        for call in (
            "bus.publish(AppEvents.APP_CONFIG_UPDATED, setting='x')",
            "self.event_bus.publish(events.AppEvents.APP_CONFIG_UPDATED)",
            "bus.publish(AppConfigUpdatedEvent, setting='x')",
            "bus.publish(app_events.AppConfigUpdatedEvent)",
        ):
            with self.subTest(call=call):
                self.assertTrue(_publishes_app_config_updated(ast.parse(call)))

    def test_scanner_ignores_other_events_subscriptions_and_non_publish_calls(self):
        for call in (
            "bus.publish(AppEvents.PRESENCE_CHANGED)",
            "bus.subscribe(AppEvents.APP_CONFIG_UPDATED, handler)",
            "log(AppEvents.APP_CONFIG_UPDATED)",
            "bus.publish()",
        ):
            with self.subTest(call=call):
                self.assertFalse(_publishes_app_config_updated(ast.parse(call)))
