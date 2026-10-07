import logging
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.ai_takeoff_dtos import M1A_COMMANDS
from ost_visualizer.application.services.ai_takeoff_read_service import (
    AiTakeoffReadService,
)
from ost_visualizer.config.di_config import configure_application
from ost_visualizer.infrastructure.logging.logger_factory import LoggerFactory
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.services.ai_takeoff_bridge import (
    TakeoffCommandBridge,
)
from ost_visualizer.presentation.managers.ui_access_manager import UIAccessManager
from PySide6 import QtCore, QtWidgets


class MainWindowStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_main_window_constructs_from_configured_application(self):
        window = None
        controller = None
        with tempfile.TemporaryDirectory() as temp_dir, ExitStack() as stack:
            app_data_dir = Path(temp_dir)
            stack.enter_context(patch.object(Path, "home", return_value=app_data_dir))
            stack.enter_context(patch.object(LoggerFactory, "configure"))
            stack.enter_context(
                patch.object(
                    LoggerFactory,
                    "get_logger",
                    return_value=logging.getLogger("test.main_window.startup"),
                )
            )
            stack.enter_context(patch.object(QtCore.QTimer, "singleShot"))
            # Qt's offscreen platform exposes no installed system fonts. Font
            # resolution has its own tests and is unrelated to startup wiring.
            stack.enter_context(
                patch(
                    "ost_visualizer.presentation.utils.annotation_defaults."
                    "resolve_font_definition",
                    side_effect=lambda definition: definition,
                )
            )
            try:
                container = configure_application(log_dir=app_data_dir / "logs")
                controller = container.get("app_controller")
                window = MainWindow(controller)
                self.assertIs(window.app_controller, controller)
                self.assertIsInstance(window.ui_access_manager, UIAccessManager)
                self.assertIs(
                    window._workspace_state_model,
                    controller.get_service("workspace_state_model"),
                )
                self.assertIs(
                    window._annotation_view_manager._ui_access_manager,
                    window.ui_access_manager,
                )
                self.assertIs(
                    window._view_window_manager._ui_access_manager,
                    window.ui_access_manager,
                )
                left_splitter = window.get_left_splitter()
                self.assertEqual(left_splitter.minimumWidth(), 320)
                self.assertIs(left_splitter.widget(0), window._conditions_sidebar)
                self.assertIs(left_splitter.widget(1), window._bid_layers_sidebar)
                bridge = window._ai_takeoff_bridge
                self.assertIsInstance(bridge, TakeoffCommandBridge)
                self.assertEqual(bridge.commands, M1A_COMMANDS)
                self.assertIsInstance(
                    controller.get_service("ai_takeoff_read_service"),
                    AiTakeoffReadService,
                )
                token_path = (
                    app_data_dir / ".ost_visualizer" / "ai_takeoff" / "session.token"
                )
                self.assertTrue(token_path.is_file())
                self.assertFalse(window._ai_takeoff_access_allowed())
                window._ai_takeoff_bridge.cleanup()
                self.assertFalse(token_path.exists())
            finally:
                if window is not None:
                    window._workspace_state_coordinator.cleanup()
                    window.event_coordinator.cleanup()
                    window.handlers.ui_event.cleanup()
                    window.license_coordinator.cleanup()
                    window.ui_access_manager.cleanup()
                    window._mcp_context_bridge.cleanup()
                    window._ai_takeoff_bridge.cleanup()
                    window.hide()
                    window.deleteLater()
                if controller is not None:
                    controller.cleanup()
                if window is not None:
                    self.app.sendPostedEvents(window, QtCore.QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    unittest.main()
