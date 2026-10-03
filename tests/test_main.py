from __future__ import annotations
import contextlib
import io
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from ost_visualizer import main as application_main
import tempfile
from pathlib import Path
from ost_visualizer.application.dtos.file_import_args import (
    PROJECT_IMPORT_EXTENSION_OSP,
    PROJECT_IMPORT_EXTENSION_OST,
    ParsedProjectFileArg,
    ProjectFileArgs,
    RejectedProjectFileArg,
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
        with (
            patch.object(
                application_main, "_install_runtime_logging", return_value=logger
            ),
            patch.object(
                application_main,
                "parse_project_file_args",
                return_value=SimpleNamespace(has_file_args=False),
            ),
            patch.object(application_main.QtWidgets, "QApplication", return_value=app),
            patch.object(application_main, "QLocalSocket", return_value=socket),
            patch.object(application_main, "QLocalServer", return_value=server),
            patch.object(application_main, "SplashScreen", return_value=splash),
            patch.object(
                application_main, "configure_application", return_value=container
            ),
            patch.object(
                application_main.MainWindow,
                "__new__",
                side_effect=RuntimeError("window construction failed"),
            ),
            self.assertRaisesRegex(RuntimeError, "window construction failed"),
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
        with (
            patch.object(
                application_main, "_install_runtime_logging", return_value=logger
            ),
            patch.object(
                application_main,
                "parse_project_file_args",
                return_value=SimpleNamespace(has_file_args=False),
            ),
            patch.object(application_main.QtWidgets, "QApplication", return_value=app),
            patch.object(application_main, "QLocalSocket", return_value=socket),
            patch.object(application_main, "QLocalServer", return_value=server),
            patch.object(application_main, "SplashScreen", return_value=splash),
            patch.object(
                application_main, "configure_application", return_value=container
            ),
            patch.object(application_main, "MainWindow", return_value=object()),
            patch.object(application_main, "_install_single_instance_handler"),
            self.assertRaises(SystemExit) as raised,
        ):
            application_main.main()
        self.assertEqual(raised.exception.code, 7)
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


class FakeLogger:
    def __init__(self):
        self.records = []

    def info(self, message, *args):
        self.records.append(("info", message % args if args else message))

    def warning(self, message, *args, **_kwargs):
        self.records.append(("warning", message % args if args else message))

    def critical(self, message, *args):
        self.records.append(("critical", message % args if args else message))

    def exception(self, message, *args):
        self.records.append(("exception", message % args if args else message))

    def messages(self, level):
        return [text for kind, text in self.records if kind == level]


class FakeClientSocket:
    def __init__(self, connects):
        self.connects = connects
        self.connected_to = []
        self.written = []
        self.events = []

    def connectToServer(self, name):
        self.connected_to.append(name)

    def waitForConnected(self, timeout):
        self.events.append(("wait", timeout))
        return self.connects

    def write(self, data):
        self.written.append(bytes(data))

    def flush(self):
        self.events.append("flush")

    def waitForBytesWritten(self, timeout):
        self.events.append(("written", timeout))

    def close(self):
        self.events.append("close")


class FakeApplication:
    def __init__(self, exit_code=0):
        self.exit_code = exit_code
        self.events = []

    def processEvents(self):
        self.events.append("processEvents")

    def exec(self):
        self.events.append("exec")
        return self.exit_code


class ApplicationStartupWiringTests(unittest.TestCase):
    """main() with every Qt and DI collaborator replaced by an explicit fake."""

    def setUp(self):
        self.logger = FakeLogger()
        self.app = FakeApplication()
        self.shutdowns = []
        self.lifecycle = SimpleNamespace(
            shutdown=lambda: self.shutdowns.append("shutdown")
        )
        self.controller = SimpleNamespace(
            get_service=lambda name: (
                self.lifecycle if name == "lifecycle_orchestrator" else None
            )
        )
        self.container = SimpleNamespace(get=lambda name: self.controller)
        self.server_events = []
        self.server = SimpleNamespace(
            removeServer=lambda name: self.server_events.append(("remove", name)),
            listen=lambda name: self.server_events.append(("listen", name)) or True,
        )
        self.splash_events = []
        self.splash = SimpleNamespace(show=lambda: self.splash_events.append("show"))
        self.windows = []

    def run_main(
        self,
        *,
        file_args=None,
        connects=False,
        window_factory=None,
        handler=None,
        configure_error=None,
    ):
        self.socket = FakeClientSocket(connects)
        args = file_args or ProjectFileArgs()
        self.style_calls = []

        def build_window(controller, **kwargs):
            window = SimpleNamespace(controller=controller, kwargs=kwargs)
            self.windows.append(window)
            return window

        patches = (
            patch.object(
                application_main, "_install_runtime_logging", return_value=self.logger
            ),
            patch.object(
                application_main, "parse_project_file_args", return_value=args
            ),
            patch.object(
                application_main.QtWidgets, "QApplication", return_value=self.app
            ),
            patch.object(
                application_main,
                "configure_application_style",
                side_effect=self.style_calls.append,
            ),
            patch.object(application_main, "QLocalSocket", return_value=self.socket),
            patch.object(application_main, "QLocalServer", return_value=self.server),
            patch.object(application_main, "SplashScreen", return_value=self.splash),
            patch.object(
                application_main,
                "configure_application",
                **(
                    {"side_effect": configure_error}
                    if configure_error
                    else {"return_value": self.container}
                ),
            ),
            patch.object(
                application_main, "MainWindow", window_factory or build_window
            ),
            patch.object(
                application_main,
                "_install_single_instance_handler",
                handler or (lambda *_args: None),
            ),
            patch.object(sys, "argv", ["Visualizer.py", "plan.ost"]),
        )
        with contextlib.ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            with self.assertRaises(SystemExit) as raised:
                application_main.main()
        return raised.exception.code

    def test_second_instance_forwards_file_args_and_exits_without_starting_a_window(
        self,
    ):
        args = ProjectFileArgs(
            files=[ParsedProjectFileArg("C:/plans/a.ost", ".ost")],
            rejected=[RejectedProjectFileArg("b.txt", "Unsupported")],
        )
        code = self.run_main(file_args=args, connects=True)
        self.assertEqual(code, 0)
        self.assertEqual(self.socket.connected_to, ["OSTVisualizer"])
        self.assertEqual(self.socket.written, [_project_file_args_to_payload(args)])
        self.assertEqual(
            self.socket.events,
            [("wait", 200), "flush", ("written", 1000), "close"],
        )
        self.assertEqual(self.server_events, [])
        self.assertEqual(self.splash_events, [])
        self.assertEqual(self.windows, [])
        self.assertEqual(self.shutdowns, [])
        self.assertEqual(self.app.events, [])

    def test_second_instance_without_file_args_sends_nothing(self):
        code = self.run_main(file_args=ProjectFileArgs(), connects=True)
        self.assertEqual(code, 0)
        self.assertEqual(self.socket.written, [])
        self.assertEqual(self.socket.events, [("wait", 200), "close"])
        self.assertEqual(self.windows, [])

    def test_first_instance_owns_the_server_and_hands_file_args_to_the_window(self):
        args = ProjectFileArgs(files=[ParsedProjectFileArg("C:/plans/a.ost", ".ost")])
        handlers = []
        self.app.exit_code = 3
        code = self.run_main(
            file_args=args,
            handler=lambda server, window, logger: handlers.append(
                (server, window, logger)
            ),
        )
        self.assertEqual(code, 3)
        self.assertEqual(self.style_calls, [self.app])
        self.assertEqual(
            self.server_events,
            [("remove", "OSTVisualizer"), ("listen", "OSTVisualizer")],
        )
        self.assertIs(self.app._single_instance_server, self.server)
        self.assertEqual(self.splash_events, ["show"])
        (window,) = self.windows
        self.assertIs(window.controller, self.controller)
        self.assertEqual(
            window.kwargs,
            {"splash_screen": self.splash, "startup_project_file_args": args},
        )
        self.assertIs(self.app.main_window, window)
        self.assertEqual(handlers, [(self.server, window, self.logger)])
        self.assertEqual(self.app.events, ["processEvents", "exec"])
        self.assertEqual(self.shutdowns, ["shutdown"])
        self.assertEqual(
            self.logger.messages("info")[-1], "Application exiting with code 3"
        )
        self.assertEqual(self.socket.written, [])

    def test_shutdown_failure_on_exit_is_logged_and_keeps_the_exit_code(self):
        def failing_shutdown():
            raise OSError("cleanup failed")

        self.lifecycle.shutdown = failing_shutdown
        self.app.exit_code = 5
        self.assertEqual(self.run_main(), 5)
        self.assertEqual(
            self.logger.messages("exception"), ["Application exit cleanup failed"]
        )

    def test_startup_cleanup_failure_is_logged_and_the_startup_error_still_propagates(
        self,
    ):
        def failing_shutdown():
            raise OSError("cleanup failed")

        def failing_window(*_args, **_kwargs):
            raise RuntimeError("window construction failed")

        self.lifecycle.shutdown = failing_shutdown
        with self.assertRaisesRegex(RuntimeError, "window construction failed"):
            self.run_main(window_factory=failing_window)
        self.assertEqual(
            self.logger.messages("exception"), ["Application startup cleanup failed"]
        )
        self.assertNotIn("exec", self.app.events)

    def test_failure_before_the_lifecycle_exists_has_nothing_to_shut_down(self):
        with self.assertRaisesRegex(RuntimeError, "configuration failed"):
            self.run_main(configure_error=RuntimeError("configuration failed"))
        self.assertEqual(self.shutdowns, [])
        self.assertEqual(self.logger.messages("exception"), [])
        self.assertEqual(self.windows, [])


class SingleInstancePayloadTests(unittest.TestCase):
    def test_payload_wire_format_is_compact_typed_json(self):
        args = ProjectFileArgs(
            files=[ParsedProjectFileArg("C:/plans/a.ost", ".ost")],
            rejected=[RejectedProjectFileArg("b.txt", "Unsupported")],
        )
        self.assertEqual(
            _project_file_args_to_payload(args),
            b'{"type":"open_project_files","files":[{"path":"C:/plans/a.ost",'
            b'"extension":".ost"}],"rejected":[{"value":"b.txt","reason":"Unsupported"}]}',
        )

    def test_payload_decoding_normalizes_extensions_and_defaults_missing_lists(self):
        decoded = _project_file_args_from_payload(
            b'{"type":"open_project_files","files":[{"path":"C:/a.OST","extension":".OST"}]}'
        )
        self.assertEqual(decoded.files, [ParsedProjectFileArg("C:/a.OST", ".ost")])
        self.assertEqual(decoded.rejected, [])
        empty = _project_file_args_from_payload(
            bytearray(b'{"type":"open_project_files"}')
        )
        self.assertEqual((empty.files, empty.rejected), ([], []))
        self.assertFalse(empty.has_file_args)

    def test_payload_decoding_rejects_other_types_and_malformed_data(self):
        cases = {
            "other type": (b'{"type":"shutdown","files":[]}', ValueError),
            "no type": (b'{"files":[]}', ValueError),
            "not json": (b"{nope", ValueError),
            "not utf8": (b"\xff\xfe", ValueError),
            "missing path": (
                b'{"type":"open_project_files","files":[{"extension":".ost"}]}',
                KeyError,
            ),
            "missing reason": (
                b'{"type":"open_project_files","rejected":[{"value":"x"}]}',
                KeyError,
            ),
        }
        for label, (data, error) in cases.items():
            with self.subTest(label):
                with self.assertRaises(error):
                    _project_file_args_from_payload(data)

    def test_sender_writes_the_payload_then_flushes_and_waits_one_second(self):
        socket = FakeClientSocket(True)
        args = ProjectFileArgs(files=[ParsedProjectFileArg("C:/a.ost", ".ost")])
        application_main._send_project_file_args(socket, args)
        self.assertEqual(socket.written, [_project_file_args_to_payload(args)])
        self.assertEqual(socket.events, ["flush", ("written", 1000)])

    def install(self, socket):
        server = _startup_import_FakeLocalServer(socket)
        queued = []
        logger = FakeLogger()
        window = SimpleNamespace(enqueue_project_file_args=queued.append)
        _install_single_instance_handler(server, window, logger)
        return server, queued, logger

    def payload(self, **kwargs):
        args = ProjectFileArgs(**kwargs)
        return args, _project_file_args_to_payload(args)

    def test_each_new_connection_is_drained_and_queued_once_when_it_disconnects(self):
        args, payload = self.payload(files=[ParsedProjectFileArg("C:/a.ost", ".ost")])
        socket = _startup_import_FragmentedLocalSocket()
        server = _startup_import_FakeLocalServer(socket)
        server._pending = []
        queued = []
        window = SimpleNamespace(enqueue_project_file_args=queued.append)
        _install_single_instance_handler(server, window, FakeLogger())
        self.assertEqual(len(server.newConnection.callbacks), 1)
        server._pending.append(socket)
        server.newConnection.emit()
        socket.push(payload)
        socket.disconnect()
        socket.disconnect()
        self.assertEqual(queued, [args, args])
        self.assertEqual(socket.delete_later_calls, 2)

    def test_every_pending_connection_is_accepted_not_just_the_first(self):
        args, payload = self.payload(files=[ParsedProjectFileArg("C:/a.ost", ".ost")])
        first = _startup_import_FragmentedLocalSocket()
        second = _startup_import_FragmentedLocalSocket()
        server = _startup_import_FakeLocalServer(first)
        server._pending.append(second)
        queued = []
        window = SimpleNamespace(enqueue_project_file_args=queued.append)
        _install_single_instance_handler(server, window, FakeLogger())
        self.assertEqual(server._pending, [])
        first.push(payload)
        second.push(payload)
        second.disconnect()
        first.disconnect()
        self.assertEqual(queued, [args, args])
        self.assertEqual((first.delete_later_calls, second.delete_later_calls), (1, 1))

    def test_connection_that_closed_before_the_handler_ran_is_processed_immediately(
        self,
    ):
        args, payload = self.payload(
            rejected=[RejectedProjectFileArg("x.txt", "Unsupported")]
        )
        socket = _startup_import_FragmentedLocalSocket()
        socket.push(payload)
        socket.disconnect()
        server, queued, logger = self.install(socket)
        self.assertEqual(queued, [args])
        self.assertEqual(logger.records, [])

    def test_malformed_payloads_are_logged_and_never_reach_the_window(self):
        for label, data in {
            "not json": b"{nope",
            "wrong type": b'{"type":"shutdown"}',
            "missing key": b'{"type":"open_project_files","files":[{"extension":".ost"}]}',
        }.items():
            with self.subTest(label):
                socket = _startup_import_FragmentedLocalSocket()
                server, queued, logger = self.install(socket)
                socket.push(data)
                socket.disconnect()
                self.assertEqual(queued, [])
                self.assertEqual(
                    logger.messages("warning"),
                    ["Ignoring malformed single-instance payload"],
                )
                self.assertEqual(socket.delete_later_calls, 1)

    def test_empty_or_argument_free_connections_do_not_enqueue_anything(self):
        socket = _startup_import_FragmentedLocalSocket()
        server, queued, logger = self.install(socket)
        socket.disconnect()
        self.assertEqual((queued, logger.records), ([], []))
        free_args, payload = self.payload()
        silent = _startup_import_FragmentedLocalSocket()
        server, queued, logger = self.install(silent)
        silent.push(payload)
        silent.disconnect()
        self.assertEqual((queued, logger.records), ([], []))


class CrashReportingTests(unittest.TestCase):
    def setUp(self):
        for name, getter in (
            ("excepthook", lambda: sys.excepthook),
            ("threading", lambda: threading.excepthook),
            ("unraisable", lambda: sys.unraisablehook),
        ):
            original = getter()
            self.addCleanup(
                {
                    "excepthook": lambda o=original: setattr(sys, "excepthook", o),
                    "threading": lambda o=original: setattr(threading, "excepthook", o),
                    "unraisable": lambda o=original: setattr(sys, "unraisablehook", o),
                }[name]
            )
        self.addCleanup(
            setattr,
            application_main,
            "_crash_log_stream",
            application_main._crash_log_stream,
        )
        self.addCleanup(
            setattr, application_main, "_app_version", application_main._app_version
        )

    def test_crash_reports_are_skipped_until_a_log_stream_exists(self):
        application_main._crash_log_stream = None
        application_main._write_crash_report("Anything", "details")

    def test_crash_report_has_a_header_with_runtime_identity_and_the_details(self):
        stream = io.StringIO()
        application_main._crash_log_stream = stream
        application_main._app_version = "9.8.7"
        application_main._write_crash_report(
            "Unhandled Python exception", "Traceback body"
        )
        text = stream.getvalue()
        self.assertTrue(
            text.startswith(
                "\n" + "=" * 80 + "\nCrash type: Unhandled Python exception\n"
            )
        )
        for expected in (
            "Timestamp: ",
            "App version: 9.8.7\n",
            f"Executable: {sys.executable}\n",
            "Platform: ",
            "Python: ",
            "Working directory: ",
        ):
            self.assertIn(expected, text)
        self.assertRegex(text, r"Timestamp: \d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\n")
        self.assertTrue(text.endswith("\n\nTraceback body\n"))
        stream.seek(0)
        stream.truncate()
        application_main._write_crash_report("Again", "ends already\n")
        self.assertTrue(stream.getvalue().endswith("\n\nends already\n"))

    def test_crash_report_is_flushed_so_it_survives_a_hard_exit(self):
        class Stream(io.StringIO):
            flushes = 0

            def flush(self):
                Stream.flushes += 1
                super().flush()

        application_main._crash_log_stream = Stream()
        application_main._write_crash_report("Kind", "details")
        self.assertEqual(Stream.flushes, 1)

    def test_existing_crash_log_content_is_appended_to_not_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            crash_log = Path(tmp) / "crash.log"
            crash_log.write_text("previous crash\n", encoding="utf-8")
            with patch.object(application_main.faulthandler, "enable"):
                application_main._enable_faulthandler(Path(tmp), FakeLogger())
            stream = application_main._crash_log_stream
            try:
                stream.write("new crash\n")
            finally:
                stream.close()
            self.assertEqual(
                crash_log.read_text(encoding="utf-8"), "previous crash\nnew crash\n"
            )

    def test_faulthandler_writes_to_the_crash_log_and_survives_setup_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / "logs"
            logger = FakeLogger()
            with patch.object(application_main.faulthandler, "enable") as enable:
                application_main._enable_faulthandler(log_dir, logger)
                stream = application_main._crash_log_stream
            try:
                enable.assert_called_once_with(file=stream, all_threads=True)
                self.assertEqual(Path(stream.name), log_dir / "crash.log")
            finally:
                stream.close()
            self.assertEqual(logger.records, [])
            blocker = Path(tmp) / "blocked"
            blocker.write_text("file, not directory", encoding="utf-8")
            with patch.object(application_main.faulthandler, "enable") as enable:
                application_main._enable_faulthandler(blocker / "logs", logger)
            enable.assert_not_called()
            self.assertEqual(
                logger.messages("exception"), ["Failed to enable faulthandler"]
            )

    def test_logging_is_flushed_through_every_root_handler(self):
        flushed = []
        handlers = [
            SimpleNamespace(flush=lambda n=n: flushed.append(n)) for n in range(3)
        ]
        with patch.object(
            application_main, "_root_logger", SimpleNamespace(handlers=handlers)
        ):
            application_main._flush_logging()
        self.assertEqual(flushed, [0, 1, 2])

    def test_unhandled_exceptions_are_logged_reported_and_forwarded(self):
        stream = io.StringIO()
        application_main._crash_log_stream = stream
        logger = FakeLogger()
        forwarded = []
        with (
            patch.object(application_main, "_flush_logging") as flush,
            patch.object(
                sys, "__excepthook__", lambda *args: forwarded.append(args[0])
            ),
        ):
            application_main._install_exception_hooks(logger)
            try:
                raise ValueError("boom")
            except ValueError:
                sys.excepthook(*sys.exc_info())
            sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        self.assertEqual(forwarded, [ValueError, KeyboardInterrupt])
        (message,) = logger.messages("critical")
        self.assertTrue(message.startswith("Unhandled exception\n"))
        self.assertIn("ValueError: boom", message)
        self.assertIn("Crash type: Unhandled Python exception", stream.getvalue())
        self.assertIn("ValueError: boom", stream.getvalue())
        flush.assert_called_once_with()

    def test_thread_exceptions_name_the_thread_and_ignore_keyboard_interrupts(self):
        stream = io.StringIO()
        application_main._crash_log_stream = stream
        logger = FakeLogger()
        forwarded = []
        with (
            patch.object(application_main, "_flush_logging"),
            patch.object(
                threading,
                "__excepthook__",
                lambda args: forwarded.append(args.exc_type),
            ),
        ):
            application_main._install_exception_hooks(logger)
            for thread, exc_type in (
                (SimpleNamespace(name="Worker-1"), RuntimeError),
                (None, OSError),
                (SimpleNamespace(name="Quiet"), KeyboardInterrupt),
            ):
                threading.excepthook(
                    SimpleNamespace(
                        exc_type=exc_type,
                        exc_value=exc_type("failed"),
                        exc_traceback=None,
                        thread=thread,
                    )
                )
        self.assertEqual(forwarded, [RuntimeError, OSError])
        criticals = logger.messages("critical")
        self.assertEqual(len(criticals), 2)
        self.assertTrue(
            criticals[0].startswith("Unhandled thread exception in Worker-1\n")
        )
        self.assertTrue(
            criticals[1].startswith("Unhandled thread exception in <unknown>\n")
        )
        self.assertIn(
            "Crash type: Unhandled thread exception in Worker-1", stream.getvalue()
        )

    def test_unraisable_exceptions_are_logged_reported_and_forwarded(self):
        stream = io.StringIO()
        application_main._crash_log_stream = stream
        logger = FakeLogger()
        forwarded = []
        marker = object()
        with (
            patch.object(application_main, "_flush_logging") as flush,
            patch.object(sys, "__unraisablehook__", forwarded.append),
        ):
            application_main._install_exception_hooks(logger)
            unraisable = SimpleNamespace(
                exc_type=ZeroDivisionError,
                exc_value=ZeroDivisionError("division"),
                exc_traceback=None,
                object=marker,
            )
            sys.unraisablehook(unraisable)
        self.assertEqual(forwarded, [unraisable])
        (message,) = logger.messages("critical")
        self.assertIn(repr(marker), message)
        self.assertIn("ZeroDivisionError: division", message)
        self.assertIn(
            f"Crash type: Unraisable exception in {marker!r}", stream.getvalue()
        )
        flush.assert_called_once_with()

    def test_runtime_logging_is_installed_in_a_fixed_order_and_records_the_version(
        self,
    ):
        order = []
        logger = FakeLogger()
        with (
            patch.object(
                application_main,
                "_bootstrap_logging",
                lambda: order.append("bootstrap") or logger,
            ),
            patch.object(
                application_main,
                "get_app_data_dir",
                lambda: order.append("dir") or Path("data"),
            ),
            patch.object(
                application_main,
                "_enable_faulthandler",
                lambda directory, log: order.append(("faulthandler", directory, log)),
            ),
            patch.object(
                application_main,
                "_install_exception_hooks",
                lambda log: order.append(("hooks", log)),
            ),
            patch.object(
                application_main, "_resolve_app_version", return_value="4.5.6"
            ),
            patch.object(
                application_main,
                "install_qt_message_handler",
                lambda: order.append("qt"),
            ),
        ):
            result = application_main._install_runtime_logging()
        self.assertIs(result, logger)
        self.assertEqual(
            order,
            [
                "bootstrap",
                "dir",
                ("faulthandler", Path("data"), logger),
                ("hooks", logger),
                "qt",
            ],
        )
        self.assertEqual(application_main._app_version, "4.5.6")

    def test_bootstrap_logging_configures_the_factory_with_the_app_data_dir(self):
        with (
            patch.object(
                application_main, "get_app_data_dir", return_value=Path("data")
            ),
            patch.object(application_main, "LoggerFactory", autospec=True) as factory,
        ):
            logger = application_main._bootstrap_logging()
        factory.configure.assert_called_once_with(Path("data"))
        factory.get_logger.assert_called_once_with("ost_visualizer.bootstrap")
        self.assertIs(logger, factory.get_logger.return_value)
