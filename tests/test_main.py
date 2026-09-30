from __future__ import annotations
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from ost_visualizer import main as application_main
import tempfile
from pathlib import Path
from ost_visualizer.application.dtos.file_import_args import (
    PROJECT_IMPORT_EXTENSION_OSP,
    PROJECT_IMPORT_EXTENSION_OST,
    parse_project_file_args,
)
from ost_visualizer.main import (
    _install_single_instance_handler,
    _project_file_args_from_payload,
    _project_file_args_to_payload,
)
from tests.helpers.startup_import import (
    FakeLocalServer as _startup_import_FakeLocalServer,
    FakeSignal as _startup_import_FakeSignal,
    FakeSocketBytes as _startup_import_FakeSocketBytes,
    FragmentedLocalSocket as _startup_import_FragmentedLocalSocket,
)


class ApplicationStartupFailureTests(unittest.TestCase):
    def test_main_window_construction_failure_shuts_down_configured_application(self):
        shutdown_calls = []
        lifecycle = SimpleNamespace(shutdown=lambda: shutdown_calls.append(True))
        controller = SimpleNamespace(
            get_service=lambda name: (
                lifecycle if name == "lifecycle_orchestrator" else None
            )
        )
        container = SimpleNamespace(get=lambda name: controller)
        app = SimpleNamespace(
            platformName=lambda: "windows",
            style=lambda: SimpleNamespace(objectName=lambda: "windowsvista"),
            setStyle=Mock(),
            processEvents=lambda: None,
        )
        socket = SimpleNamespace(
            connectToServer=lambda _name: None,
            waitForConnected=lambda _timeout: False,
        )
        server = SimpleNamespace(
            removeServer=lambda _name: None,
            listen=lambda _name: True,
        )
        splash = SimpleNamespace(show=lambda: None)
        logger = SimpleNamespace(
            info=lambda *_args: None, exception=lambda *_args: None
        )
        with patch.object(
            application_main, "_install_runtime_logging", return_value=logger
        ), patch.object(
            application_main,
            "parse_project_file_args",
            return_value=SimpleNamespace(has_file_args=False),
        ), patch.object(
            application_main.QtWidgets, "QApplication", return_value=app
        ), patch.object(
            application_main, "QLocalSocket", return_value=socket
        ), patch.object(
            application_main, "QLocalServer", return_value=server
        ), patch.object(
            application_main, "SplashScreen", return_value=splash
        ), patch.object(
            application_main, "configure_application", return_value=container
        ), patch.object(
            application_main.MainWindow,
            "__new__",
            side_effect=RuntimeError("window construction failed"),
        ), self.assertRaisesRegex(
            RuntimeError, "window construction failed"
        ):
            application_main.main()
        self.assertEqual(shutdown_calls, [True])
        app.setStyle.assert_called_once_with("Fusion")

    def test_event_loop_exit_shuts_down_application_without_window_close(self):
        shutdown_calls = []
        lifecycle = SimpleNamespace(shutdown=lambda: shutdown_calls.append(True))
        controller = SimpleNamespace(
            get_service=lambda name: (
                lifecycle if name == "lifecycle_orchestrator" else None
            )
        )
        container = SimpleNamespace(get=lambda _name: controller)
        app = SimpleNamespace(
            platformName=lambda: "windows",
            style=lambda: SimpleNamespace(objectName=lambda: "windowsvista"),
            setStyle=Mock(),
            processEvents=lambda: None,
            exec=lambda: 7,
        )
        socket = SimpleNamespace(
            connectToServer=lambda _name: None,
            waitForConnected=lambda _timeout: False,
        )
        server = SimpleNamespace(
            removeServer=lambda _name: None,
            listen=lambda _name: True,
        )
        splash = SimpleNamespace(show=lambda: None)
        logger = SimpleNamespace(
            info=lambda *_args: None, exception=lambda *_args: None
        )
        with patch.object(
            application_main, "_install_runtime_logging", return_value=logger
        ), patch.object(
            application_main,
            "parse_project_file_args",
            return_value=SimpleNamespace(has_file_args=False),
        ), patch.object(
            application_main.QtWidgets, "QApplication", return_value=app
        ), patch.object(
            application_main, "QLocalSocket", return_value=socket
        ), patch.object(
            application_main, "QLocalServer", return_value=server
        ), patch.object(
            application_main, "SplashScreen", return_value=splash
        ), patch.object(
            application_main, "configure_application", return_value=container
        ), patch.object(
            application_main, "MainWindow", return_value=object()
        ), patch.object(
            application_main, "_install_single_instance_handler"
        ), self.assertRaisesRegex(
            SystemExit, "7"
        ):
            application_main.main()
        self.assertEqual(shutdown_calls, [True])
        app.setStyle.assert_called_once_with("Fusion")


class SingleInstanceFileArgumentTests(unittest.TestCase):
    def test_socket_payload_round_trip_preserves_file_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.ost"
            source.write_text("ost")
            args = parse_project_file_args([str(source), str(Path(tmp) / "bad.txt")])
            restored = _project_file_args_from_payload(
                _project_file_args_to_payload(args)
            )
            self.assertEqual(restored.files, args.files)
            self.assertEqual(restored.rejected, args.rejected)

    def test_single_instance_handler_buffers_fragmented_socket_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.ost"
            source.write_text("ost")
            args = parse_project_file_args([str(source)])
            payload = _project_file_args_to_payload(args)
            socket = _startup_import_FragmentedLocalSocket()
            server = _startup_import_FakeLocalServer(socket)
            queued = []
            window = SimpleNamespace(enqueue_project_file_args=queued.append)
            logger = SimpleNamespace(warning=lambda *_args, **_kwargs: None)
            _install_single_instance_handler(server, window, logger)
            midpoint = len(payload) // 2
            socket.push(payload[:midpoint])
            socket.push(payload[midpoint:])
            self.assertEqual(queued, [])
            socket.disconnect()
            self.assertEqual(queued, [args])
            self.assertEqual(socket.delete_later_calls, 1)
