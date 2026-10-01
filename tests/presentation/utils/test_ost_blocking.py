import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.utils.ost_blocking import exec_with_ost_blocking
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete
from tests.presentation.utils.dialog_lifecycle_support import (
    _app as _dialog_lifecycle_support__app,
)


class DialogLifecycleTests(unittest.TestCase):
    def test_ost_blocking_skips_access_change_after_dialog_is_destroyed(self):
        _dialog_lifecycle_support__app()
        event_bus = EventBus()

        class Signal:
            def __init__(self):
                self.callback = None

            def connect(self, callback):
                self.callback = callback

            def emit(self, active):
                self.callback(active)

        class Signaler:
            def __init__(self):
                self.ost_changed = Signal()

            def deleteLater(self):
                pass

        class Dialog(QtWidgets.QDialog):
            def set_interactive(self, enabled):
                self.setEnabled(enabled)

            def exec(self):
                event_bus.publish(AppEvents.OST_STATUS_CHANGED, active=True)
                return QtWidgets.QDialog.DialogCode.Rejected

        dialog = Dialog()
        event_bus.subscribe(
            AppEvents.OST_STATUS_CHANGED,
            lambda **_payload: delete(dialog),
        )
        with patch(
            "ost_visualizer.presentation.utils.ost_blocking.OstSignaler",
            Signaler,
        ):
            result = exec_with_ost_blocking(dialog, event_bus)
        self.assertEqual(result, QtWidgets.QDialog.DialogCode.Rejected)


class _Signal:
    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback

    def emit(self, active):
        self.callback(active)


def _fake_signaler(deleted):
    class Signaler:
        def __init__(self):
            self.ost_changed = _Signal()

        def deleteLater(self):
            deleted.append(True)

    return Signaler


OST_SIGNALER = "ost_visualizer.presentation.utils.ost_blocking.OstSignaler"


class OstBlockingLifecycleTests(unittest.TestCase):
    def test_active_ost_disables_dialog_and_inactive_reenables_it(self):
        _dialog_lifecycle_support__app()
        event_bus = EventBus()
        states = []

        class Dialog(QtWidgets.QDialog):
            def set_interactive(self, enabled):
                states.append(enabled)

            def exec(self):
                event_bus.publish(AppEvents.OST_STATUS_CHANGED, active=True)
                event_bus.publish(AppEvents.OST_STATUS_CHANGED, active=False)
                return QtWidgets.QDialog.DialogCode.Accepted

        dialog = Dialog()
        try:
            with patch(OST_SIGNALER, _fake_signaler([])):
                result = exec_with_ost_blocking(dialog, event_bus)
            self.assertEqual(result, QtWidgets.QDialog.DialogCode.Accepted)
            self.assertEqual(states, [False, True])
        finally:
            dialog.deleteLater()

    def test_subscription_and_signaler_are_released_after_exec(self):
        _dialog_lifecycle_support__app()
        event_bus = EventBus()
        states = []

        class Dialog(QtWidgets.QDialog):
            def set_interactive(self, enabled):
                states.append(enabled)

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Rejected

        dialog = Dialog()
        deleted = []
        try:
            with patch(OST_SIGNALER, _fake_signaler(deleted)):
                exec_with_ost_blocking(dialog, event_bus)
            event_bus.publish(AppEvents.OST_STATUS_CHANGED, active=True)
            self.assertEqual(states, [])
            self.assertEqual(deleted, [True])
        finally:
            dialog.deleteLater()

    def test_subscription_is_released_when_exec_raises(self):
        _dialog_lifecycle_support__app()
        event_bus = EventBus()
        deleted = []

        class Dialog(QtWidgets.QDialog):
            def set_interactive(self, enabled):
                pass

            def exec(self):
                raise RuntimeError("exec failed")

        dialog = Dialog()
        try:
            with patch(OST_SIGNALER, _fake_signaler(deleted)):
                with self.assertRaises(RuntimeError):
                    exec_with_ost_blocking(dialog, event_bus)
            self.assertEqual(deleted, [True])
            self.assertNotIn(AppEvents.OST_STATUS_CHANGED, event_bus._subscribers)
        finally:
            dialog.deleteLater()
