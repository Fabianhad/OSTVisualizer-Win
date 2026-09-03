from PySide6 import QtWidgets
from shiboken6 import isValid
from ...application.events.app_events import AppEvents
from .qt_callback_bridge import OstSignaler


def exec_with_ost_blocking(dialog: QtWidgets.QDialog, event_bus) -> int:
    signaler = OstSignaler()

    def _ost_callback(active: bool = False) -> None:
        signaler.ost_changed.emit(active)

    def _set_interactive(active: bool) -> None:
        if isValid(dialog):
            dialog.set_interactive(not active)

    signaler.ost_changed.connect(_set_interactive)
    event_bus.subscribe(AppEvents.OST_STATUS_CHANGED, _ost_callback)
    try:
        return dialog.exec()
    finally:
        event_bus.unsubscribe(AppEvents.OST_STATUS_CHANGED, _ost_callback)
        signaler.deleteLater()
