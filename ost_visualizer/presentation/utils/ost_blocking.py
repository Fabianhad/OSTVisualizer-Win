from PySide6 import QtWidgets
from ...application.events.app_events import AppEvents
from .qt_callback_bridge import OstSignaler


def exec_with_ost_blocking(dialog: QtWidgets.QDialog, event_bus) -> int:
    signaler = OstSignaler()

    def _ost_callback(active: bool = False, **_) -> None:
        signaler.ost_changed.emit(active)

    signaler.ost_changed.connect(lambda active: dialog.set_interactive(not active))
    event_bus.subscribe(AppEvents.OST_STATUS_CHANGED, _ost_callback)
    try:
        return dialog.exec()
    finally:
        event_bus.unsubscribe(AppEvents.OST_STATUS_CHANGED, _ost_callback)
        signaler.deleteLater()
