"""Shared fakes and helpers for the SQL connection and database-properties dialog tests."""

from unittest.mock import patch
from PySide6 import QtWidgets


class RecordingIconProvider:
    """IWindowIconProvider fake recording every widget it was asked to icon."""

    def __init__(self):
        self.widgets = []

    def set_window_icon(self, widget):
        self.widgets.append(widget)


class NoModalWarnings:
    """Replaces both SQL dialogs' modal warning boxes with a recorder.
    A path that unexpectedly warns then fails an assertion on ``shown_warnings``
    instead of blocking the test run on a message box.
    """

    def setUp(self):
        super().setUp()
        self.shown_warnings = []
        for module in ("sql_connection_dialog", "sql_database_dialog"):
            patcher = patch(
                f"ost_visualizer.presentation.dialogs.{module}.show_warning",
                lambda parent, title, message: self.shown_warnings.append(
                    (parent, title, message)
                ),
            )
            patcher.start()
            self.addCleanup(patcher.stop)


def margins(layout):
    value = layout.contentsMargins()
    return (value.left(), value.top(), value.right(), value.bottom())


def form_rows(form):
    """(label text or None, field widget or layout) for every row of a QFormLayout."""
    rows = []
    for row in range(form.rowCount()):
        label_item = form.itemAt(row, QtWidgets.QFormLayout.ItemRole.LabelRole)
        field_item = form.itemAt(row, QtWidgets.QFormLayout.ItemRole.FieldRole)
        label = label_item.widget().text() if label_item is not None else None
        rows.append((label, field_item.widget() or field_item.layout()))
    return rows
