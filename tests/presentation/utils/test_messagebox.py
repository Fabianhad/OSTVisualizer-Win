import logging
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.utils import messagebox
from ost_visualizer.presentation.utils.messagebox import (
    application_shutting_down,
    confirm_delete_conditions,
    confirm_multi_delete,
    confirm_save_discard_cancel,
    log_user_notice,
    register_shutdown_probe,
    show_error,
    show_info,
    show_warning,
)
from PySide6 import QtCore, QtWidgets
from tests.presentation.utils.dialog_lifecycle_support import (
    _app as _dialog_lifecycle_support__app,
)
from ost_visualizer.presentation.texts import (
    MESSAGEBOX_BUTTON_YES_TO_ALL,
    MESSAGEBOX_MESSAGE_DELETE_ITEMS,
    MESSAGEBOX_MESSAGE_DELETE_THE_OTHER_ITEM,
    MESSAGEBOX_TITLE_DELETE,
)


class DialogLifecycleTests(unittest.TestCase):
    def test_repeated_condition_delete_prompts_release_message_boxes(self):
        app = _dialog_lifecycle_support__app()
        owner = QtWidgets.QWidget()
        try:
            with patch.object(
                QtWidgets.QMessageBox, "exec", return_value=0
            ), patch.object(QtWidgets.QMessageBox, "clickedButton", return_value=None):
                for index in range(100):
                    self.assertEqual(
                        confirm_delete_conditions(
                            owner, [(str(index), f"Condition {index}")]
                        ),
                        [],
                    )
            app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
            app.processEvents()
            self.assertEqual(owner.findChildren(QtWidgets.QMessageBox), [])
        finally:
            owner.deleteLater()


class ConfirmDeleteConditionsChoiceTests(unittest.TestCase):
    NAMES = [("u0", "Zero"), ("u1", "One"), ("u2", "Two")]

    def _confirm(self, choices):
        _dialog_lifecycle_support__app()
        owner = QtWidgets.QWidget()
        self.addCleanup(owner.deleteLater)
        remaining_choices = iter(choices)
        offered = []
        self.titles = []
        self.default_buttons = []
        selected = {}
        standard = QtWidgets.QMessageBox.StandardButton

        def pick(box):
            offered.append([button.text().replace("&", "") for button in box.buttons()])
            self.titles.append(box.windowTitle())
            self.default_buttons.append(box.standardButton(box.defaultButton()))
            choice = next(remaining_choices)
            for button in box.buttons():
                if choice == "all" and button.text() == MESSAGEBOX_BUTTON_YES_TO_ALL:
                    selected["button"] = button
                elif choice == "yes" and box.standardButton(button) == standard.Yes:
                    selected["button"] = button
                elif choice == "no" and box.standardButton(button) == standard.No:
                    selected["button"] = button
            return 0

        with patch.object(QtWidgets.QMessageBox, "exec", pick), patch.object(
            QtWidgets.QMessageBox, "clickedButton", lambda _box: selected["button"]
        ):
            result = confirm_delete_conditions(owner, self.NAMES)
        return result, offered, list(remaining_choices)

    def test_each_condition_is_confirmed_or_declined_individually(self):
        result, offered, unused = self._confirm(["yes", "no", "yes"])
        self.assertEqual(result, ["u0", "u2"])
        self.assertEqual(len(offered), 3)
        self.assertEqual(unused, [])
        self.assertEqual(
            self.titles,
            [
                MESSAGEBOX_TITLE_DELETE.format(name=name)
                for name in ("Zero", "One", "Two")
            ],
        )
        no = QtWidgets.QMessageBox.StandardButton.No
        self.assertEqual(self.default_buttons, [no, no, no])

    def test_declining_every_condition_deletes_nothing(self):
        result, offered, _unused = self._confirm(["no", "no", "no"])
        self.assertEqual(result, [])
        self.assertEqual(len(offered), 3)

    def test_yes_to_all_confirms_current_and_remaining_without_more_prompts(self):
        result, offered, _unused = self._confirm(["no", "all"])
        self.assertEqual(result, ["u1", "u2"])
        self.assertEqual(len(offered), 2)

    def test_yes_to_all_is_only_offered_while_more_conditions_remain(self):
        _result, offered, _unused = self._confirm(["yes", "yes", "yes"])
        self.assertEqual(
            [MESSAGEBOX_BUTTON_YES_TO_ALL in texts for texts in offered],
            [True, True, False],
        )


class ConfirmMultiDeleteTests(unittest.TestCase):
    ITEMS = [("Used", "1"), ("Free", "2")]

    def test_only_unused_items_are_confirmed_and_returned(self):
        yes = QtWidgets.QMessageBox.StandardButton.Yes
        with patch.object(QtWidgets.QMessageBox, "question", return_value=yes) as ask:
            result = confirm_multi_delete(None, "Delete", self.ITEMS, {"1"})
        self.assertEqual(result, [("Free", "2")])
        self.assertEqual(ask.call_args.args[1], "Delete")
        self.assertEqual(
            ask.call_args.args[2],
            MESSAGEBOX_MESSAGE_DELETE_THE_OTHER_ITEM.format(
                in_use_lines='Cannot delete "Used" because it is in use.', item_count=1
            ),
        )
        self.assertEqual(ask.call_args.args[4], QtWidgets.QMessageBox.StandardButton.No)

    def test_declining_mixed_delete_returns_none(self):
        no = QtWidgets.QMessageBox.StandardButton.No
        with patch.object(QtWidgets.QMessageBox, "question", return_value=no):
            self.assertIsNone(confirm_multi_delete(None, "Delete", self.ITEMS, {"1"}))

    def test_all_items_in_use_warns_without_asking(self):
        with patch.object(QtWidgets.QMessageBox, "question") as ask, patch.object(
            QtWidgets.QMessageBox, "warning"
        ) as warn, self.assertLogs(
            "ost_visualizer.presentation.utils.messagebox", "WARNING"
        ) as logs:
            result = confirm_multi_delete(None, "Delete", self.ITEMS, {"1", "2"})
        self.assertIsNone(result)
        ask.assert_not_called()
        warn.assert_called_once()
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                'Delete: Cannot delete "Used" because it is in use.\n'
                'Cannot delete "Free" because it is in use.'
            ],
        )
        self.assertEqual(warn.call_args.args[1], "Delete")
        self.assertEqual(
            warn.call_args.args[2],
            'Cannot delete "Used" because it is in use.\n'
            'Cannot delete "Free" because it is in use.',
        )

    def test_unused_items_ask_with_count_and_yes_returns_all(self):
        yes = QtWidgets.QMessageBox.StandardButton.Yes
        with patch.object(QtWidgets.QMessageBox, "question", return_value=yes) as ask:
            result = confirm_multi_delete(None, "Delete", self.ITEMS, set())
        self.assertEqual(result, self.ITEMS)
        self.assertEqual(
            ask.call_args.args[2], MESSAGEBOX_MESSAGE_DELETE_ITEMS.format(item_count=2)
        )
        self.assertEqual(ask.call_args.args[4], QtWidgets.QMessageBox.StandardButton.No)


class ConfirmSaveDiscardCancelTests(unittest.TestCase):
    def test_reply_maps_to_save_discard_or_cancel(self):
        buttons = QtWidgets.QMessageBox.StandardButton
        for reply, expected in (
            (buttons.Yes, True),
            (buttons.No, False),
            (buttons.Cancel, None),
        ):
            with self.subTest(reply=reply):
                with patch.object(
                    QtWidgets.QMessageBox, "question", return_value=reply
                ) as ask:
                    self.assertIs(
                        confirm_save_discard_cancel(None, "Title", "Message"),
                        expected,
                    )
                self.assertEqual(ask.call_args.args[1:3], ("Title", "Message"))
                self.assertEqual(
                    ask.call_args.args[3], buttons.Yes | buttons.No | buttons.Cancel
                )
                # Cancel is the safe default so Enter never discards or saves.
                self.assertEqual(ask.call_args.args[4], buttons.Cancel)


CALLER_LOGGER = __name__
logger = logging.getLogger(CALLER_LOGGER)


def _raised(text):
    try:
        raise ValueError(text)
    except ValueError as exc:
        return exc


class _Probe:
    def __init__(self, shutting_down):
        self.shutting_down = shutting_down
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.shutting_down

    def check(self):
        return self()


class ShowErrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _dialog_lifecycle_support__app()

    def setUp(self):
        self._saved_probes = list(messagebox._shutdown_probes)
        messagebox._shutdown_probes.clear()

    def tearDown(self):
        messagebox._shutdown_probes[:] = self._saved_probes

    def test_error_logs_at_error_with_the_traceback_and_shows_a_critical_box(self):
        exc = _raised("disk is full")
        with patch.object(QtWidgets.QMessageBox, "critical") as box, self.assertLogs(
            CALLER_LOGGER, "ERROR"
        ) as logs:
            show_error(None, "Save Failed", "Failed to save the bid.", exc)
        box.assert_called_once_with(None, "Save Failed", "Failed to save the bid.")
        self.assertEqual(len(logs.records), 1)
        record = logs.records[0]
        self.assertEqual(record.levelno, logging.ERROR)
        self.assertEqual(record.exc_info[1], exc)
        self.assertEqual(record.getMessage(), "Save Failed: Failed to save the bid.")
        self.assertEqual(
            record.funcName,
            "test_error_logs_at_error_with_the_traceback_and_shows_a_critical_box",
        )

    def test_warning_and_info_log_at_their_own_level_and_show_their_own_box(self):
        cases = (
            (show_warning, "warning", logging.WARNING),
            (show_info, "information", logging.INFO),
        )
        for helper, static, level in cases:
            with self.subTest(static):
                with patch.object(
                    QtWidgets.QMessageBox, static
                ) as box, self.assertLogs(CALLER_LOGGER, "INFO") as logs:
                    helper(None, "Import", "The import finished with problems.")
                box.assert_called_once_with(
                    None, "Import", "The import finished with problems."
                )
                self.assertEqual([r.levelno for r in logs.records], [level])
                self.assertEqual(
                    logs.records[0].getMessage(),
                    "Import: The import finished with problems.",
                )

    def test_a_warning_dialog_for_a_failure_with_an_exception_logs_at_error(self):
        exc = _raised("connection reset")
        with patch.object(QtWidgets.QMessageBox, "warning") as box, self.assertLogs(
            CALLER_LOGGER, "WARNING"
        ) as logs:
            show_warning(None, "Bid Areas", "The bid areas could not be saved.", exc)
        box.assert_called_once_with(
            None, "Bid Areas", "The bid areas could not be saved."
        )
        self.assertEqual([r.levelno for r in logs.records], [logging.ERROR])
        self.assertIs(logs.records[0].exc_info[1], exc)

    def test_an_input_validation_warning_logs_at_info_and_shows_a_warning_box(self):
        with patch.object(QtWidgets.QMessageBox, "warning") as box, self.assertLogs(
            CALLER_LOGGER, "DEBUG"
        ) as logs:
            show_warning(
                None, "Edit Condition", "Rise must be a number.", validation=True
            )
        box.assert_called_once_with(None, "Edit Condition", "Rise must be a number.")
        self.assertEqual(
            [(r.levelno, r.getMessage(), r.exc_info) for r in logs.records],
            [(logging.INFO, "Edit Condition: Rise must be a number.", None)],
        )

    def test_every_input_validation_warning_in_the_repository_logs_at_info(self):
        import ast
        import re
        from pathlib import Path

        vocabulary = re.compile(
            r"_MESSAGE_[A-Z_]*(MUST_BE|CANNOT_BE_EMPTY|ALREADY_EXISTS|IS_NOT_A_VALID|"
            r"PLEASE_ENTER|ENTER_A|ENTER_BOTH|SELECT_A_|MATCHES_MORE_THAN_ONE|"
            r"WAS_NOT_FOUND|VALUE_IS_NOT|VALUES_CANNOT|VALUES_MUST)"
        )
        root = Path(messagebox.__file__).resolve().parents[1]
        missing, flagged = [], 0
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "show_warning"
                    and len(node.args) >= 3
                ):
                    continue
                current, plain_value_error = node, False
                while current in parents:
                    current = parents[current]
                    if isinstance(current, ast.ExceptHandler):
                        plain_value_error = (
                            ast.unparse(current.type or ast.Name("x")) == "ValueError"
                        )
                        break
                    if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        break
                looks_like_validation = bool(
                    vocabulary.search(ast.unparse(node.args[2]))
                ) or (plain_value_error and len(node.args) == 3)
                marked = any(
                    k.arg == "validation"
                    and isinstance(k.value, ast.Constant)
                    and k.value.value
                    for k in node.keywords
                )
                flagged += marked
                if looks_like_validation and not marked:
                    missing.append(f"{path.name}:{node.lineno}")
        self.assertEqual(missing, [])
        self.assertGreaterEqual(flagged, 40)

    def test_a_non_modal_warning_logs_and_opens_a_box_that_does_not_block(self):
        parent = QtWidgets.QWidget()
        try:
            with patch.object(
                QtWidgets.QMessageBox, "warning"
            ) as blocking, self.assertLogs(CALLER_LOGGER, "WARNING") as logs:
                box = show_warning(
                    parent,
                    "Takeoff Placement",
                    "1 takeoff was not placed.",
                    modal=False,
                )
            blocking.assert_not_called()
            self.assertIsInstance(box, QtWidgets.QMessageBox)
            self.assertFalse(box.isModal())
            self.assertTrue(box.isVisible())
            self.assertIs(box.parent(), parent)
            self.assertEqual(
                (box.windowTitle(), box.text(), box.icon()),
                (
                    "Takeoff Placement",
                    "1 takeoff was not placed.",
                    QtWidgets.QMessageBox.Icon.Warning,
                ),
            )
            self.assertTrue(
                box.testAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
            )
            self.assertEqual(
                [r.getMessage() for r in logs.records],
                ["Takeoff Placement: 1 takeoff was not placed."],
            )
            box.close()
        finally:
            parent.deleteLater()

    def test_a_non_modal_warning_during_shutdown_only_logs(self):
        probe = _Probe(True)
        register_shutdown_probe(probe.check)
        with self.assertLogs(CALLER_LOGGER, "WARNING") as logs:
            box = show_warning(
                None, "Takeoff Placement", "1 takeoff was not placed.", modal=False
            )
        self.assertIsNone(box)
        self.assertTrue(
            logs.records[0]
            .getMessage()
            .endswith("(not shown: the application is shutting down)")
        )

    def test_a_call_stack_shallower_than_expected_falls_back_silently(self):
        self.assertIs(messagebox._caller_logger(None, 100_000), messagebox._LOGGER)
        with patch.object(
            messagebox.sys, "_getframe", side_effect=RuntimeError("broken")
        ):
            with self.assertRaises(RuntimeError):
                messagebox._caller_logger(None, 1)

    def test_without_an_exception_the_record_has_no_traceback(self):
        with patch.object(QtWidgets.QMessageBox, "critical"), self.assertLogs(
            CALLER_LOGGER, "ERROR"
        ) as logs:
            show_error(None, "Open", "The file could not be opened.")
        self.assertIsNone(logs.records[0].exc_info)

    def test_context_is_logged_with_the_shown_text_in_one_record(self):
        with patch.object(QtWidgets.QMessageBox, "warning"), self.assertLogs(
            CALLER_LOGGER, "WARNING"
        ) as logs:
            show_warning(
                None,
                "Rename",
                "Failed to rename the layer.",
                context="Layer 12 rename refused",
            )
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(
            logs.records[0].getMessage(),
            "Layer 12 rename refused [shown: Rename: Failed to rename the layer.]",
        )

    def test_an_explicit_logger_receives_the_record(self):
        named = logging.getLogger("tests.error_dialogs.explicit")
        with patch.object(QtWidgets.QMessageBox, "critical"), self.assertLogs(
            named, "ERROR"
        ) as logs:
            show_error(None, "Export", "Failed to export the PDF.", logger=named)
        self.assertEqual(logs.records[0].name, "tests.error_dialogs.explicit")

    def test_text_taken_from_the_exception_is_not_logged_twice(self):
        exc = _raised("The database is read-only.")
        with patch.object(QtWidgets.QMessageBox, "critical") as box, self.assertLogs(
            CALLER_LOGGER, "ERROR"
        ) as logs:
            show_error(None, "Save", str(exc), exc)
        box.assert_called_once_with(None, "Save", "The database is read-only.")
        self.assertEqual(logs.output[0].count("The database is read-only."), 1)
        self.assertNotIn("The database is read-only.", logs.records[0].getMessage())

    def test_a_missing_parent_shows_an_unparented_box(self):
        with patch.object(QtWidgets.QMessageBox, "warning") as box, self.assertLogs(
            CALLER_LOGGER, "WARNING"
        ):
            show_warning(None, "Paste", "Nothing to paste.")
        self.assertIsNone(box.call_args.args[0])

    def test_a_deleted_parent_falls_back_to_an_unparented_box(self):
        widget = QtWidgets.QWidget()
        with patch.object(messagebox, "isValid", return_value=False), patch.object(
            QtWidgets.QMessageBox, "critical"
        ) as box, self.assertLogs(CALLER_LOGGER, "ERROR"):
            show_error(widget, "Delete", "Failed to delete the page.")
        self.assertIsNone(box.call_args.args[0])
        widget.deleteLater()

    def test_a_valid_parent_is_kept(self):
        widget = QtWidgets.QWidget()
        with patch.object(QtWidgets.QMessageBox, "critical") as box, self.assertLogs(
            CALLER_LOGGER, "ERROR"
        ):
            show_error(widget, "Delete", "Failed to delete the page.")
        self.assertIs(box.call_args.args[0], widget)
        widget.deleteLater()

    def test_a_failing_logger_still_shows_the_dialog_and_never_raises(self):
        broken = logging.getLogger("tests.error_dialogs.broken")
        with patch.object(
            broken, "log", side_effect=RuntimeError("handler down")
        ), patch.object(QtWidgets.QMessageBox, "critical") as box:
            show_error(
                None, "Save", "Failed to save the bid.", _raised("x"), logger=broken
            )
        box.assert_called_once_with(None, "Save", "Failed to save the bid.")

    def test_a_failing_dialog_never_raises_and_is_logged(self):
        with patch.object(
            QtWidgets.QMessageBox, "warning", side_effect=RuntimeError("no screen")
        ), self.assertLogs(CALLER_LOGGER, "WARNING") as logs:
            show_warning(None, "Reload", "Reload the database.")
        self.assertEqual(logs.records[0].getMessage(), "Reload: Reload the database.")
        failure = [
            r for r in logs.records if r.exc_info and str(r.exc_info[1]) == "no screen"
        ]
        self.assertEqual(len(failure), 1)

    def test_an_interrupt_while_showing_is_not_swallowed(self):
        with patch.object(
            QtWidgets.QMessageBox, "critical", side_effect=KeyboardInterrupt
        ), self.assertLogs(CALLER_LOGGER, "ERROR"):
            with self.assertRaises(KeyboardInterrupt):
                show_error(None, "Save", "Failed to save the bid.")

    def test_no_dialog_during_application_shutdown_but_the_failure_is_logged(self):
        probe = _Probe(True)
        register_shutdown_probe(probe.check)
        with patch.object(QtWidgets.QMessageBox, "critical") as box, self.assertLogs(
            CALLER_LOGGER, "ERROR"
        ) as logs:
            show_error(None, "Save", "Failed to save the bid.")
        box.assert_not_called()
        self.assertEqual(
            logs.records[0].getMessage(),
            "Save: Failed to save the bid. (not shown: the application is shutting down)",
        )

    def test_no_dialog_while_qt_is_closing_down(self):
        with patch.object(
            QtCore.QCoreApplication, "closingDown", return_value=True
        ), patch.object(QtWidgets.QMessageBox, "warning") as box, self.assertLogs(
            CALLER_LOGGER, "WARNING"
        ):
            show_warning(None, "Close", "Failed to close the bid.")
        box.assert_not_called()

    def test_a_probe_that_is_not_shutting_down_lets_the_dialog_show(self):
        probe = _Probe(False)
        register_shutdown_probe(probe.check)
        with patch.object(QtWidgets.QMessageBox, "critical") as box, self.assertLogs(
            CALLER_LOGGER, "ERROR"
        ):
            show_error(None, "Save", "Failed to save the bid.")
        box.assert_called_once()
        self.assertEqual(probe.calls, 1)

    def test_a_collected_probe_owner_is_dropped(self):
        probe = _Probe(True)
        register_shutdown_probe(probe.check)
        del probe
        self.assertFalse(application_shutting_down())
        self.assertEqual(messagebox._shutdown_probes, [])

    def test_a_user_notice_is_logged_once_without_any_dialog(self):
        exc = _raised("lock lost")
        with patch.object(QtWidgets.QMessageBox, "critical") as critical, patch.object(
            QtWidgets.QMessageBox, "warning"
        ) as warning, patch.object(
            QtWidgets.QMessageBox, "information"
        ) as information, self.assertLogs(
            CALLER_LOGGER, "WARNING"
        ) as logs:
            log_user_notice(
                logging.WARNING, "Undo", "The change could not be undone.", exc
            )
        for box in (critical, warning, information):
            box.assert_not_called()
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(
            logs.records[0].getMessage(), "Undo: The change could not be undone."
        )
        self.assertIs(logs.records[0].exc_info[1], exc)
        self.assertEqual(
            logs.records[0].funcName,
            "test_a_user_notice_is_logged_once_without_any_dialog",
        )

    def test_a_caller_without_a_logger_falls_back_to_the_messagebox_logger(self):
        namespace = {
            "show_warning": show_warning,
            "__name__": "tests.error_dialogs.no_logger",
        }
        exec(
            "def fail():\n    show_warning(None, 'Paste', 'Nothing to paste.')\n",
            namespace,
        )
        with patch.object(QtWidgets.QMessageBox, "warning"), self.assertLogs(
            "ost_visualizer.presentation.utils.messagebox", "WARNING"
        ) as logs:
            namespace["fail"]()
        self.assertEqual(logs.records[0].funcName, "fail")

    def test_every_reporting_helper_logs_each_call_exactly_once(self):
        statics = {
            "show_error": "critical",
            "show_warning": "warning",
            "show_info": "information",
        }
        helpers = sorted(
            name
            for name, value in vars(messagebox).items()
            if callable(value)
            and getattr(value, "__module__", None) == messagebox.__name__
            and (name.startswith("show_") or name == "log_user_notice")
        )
        self.assertEqual(
            helpers, ["log_user_notice", "show_error", "show_info", "show_warning"]
        )
        for name in helpers:
            for exc in (None, _raised("boom")):
                with self.subTest(helper=name, exc=exc is not None):
                    with patch.object(QtWidgets.QMessageBox, "critical"), patch.object(
                        QtWidgets.QMessageBox, "warning"
                    ), patch.object(
                        QtWidgets.QMessageBox, "information"
                    ), self.assertLogs(
                        CALLER_LOGGER, "INFO"
                    ) as logs:
                        if name == "log_user_notice":
                            messagebox.log_user_notice(logging.WARNING, "T", "M", exc)
                        elif name == "show_info":
                            messagebox.show_info(None, "T", "M")
                        else:
                            getattr(messagebox, name)(None, "T", "M", exc)
                    self.assertEqual(len(logs.records), 1)
                    self.assertTrue(logs.records[0].getMessage().startswith("T: "))
                    if exc is not None and name != "show_info":
                        self.assertIs(logs.records[0].exc_info[1], exc)
        self.assertEqual(set(statics), set(helpers) - {"log_user_notice"})

    def test_a_failing_probe_counts_as_not_shutting_down(self):
        class Broken:
            def check(self):
                raise RuntimeError("deleted window")

        owner = Broken()
        register_shutdown_probe(owner.check)
        self.assertFalse(application_shutting_down())
