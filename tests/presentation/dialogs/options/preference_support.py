import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.snap_preferences_dto import SnapPreferencesDto
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.presentation.config import OPTIONS_LABEL_RESET_ALL_SETTINGS
from PySide6 import QtGui, QtWidgets


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _submenu_by_title(menu, title):
    return next(
        action.menu()
        for action in menu.actions()
        if action.menu() and action.menu().title() == title
    )


class FakeConfigRepository:
    config_path = "memory"

    def __init__(self, config=None):
        self.saved = []
        self._config = config or Config()

    def load(self):
        return self._config

    def save(self, config):
        self._config = config
        self.saved.append(config.to_dict())


class FakeEventBus:
    def __init__(self):
        self.events = []

    def publish(self, event_type, **event_payload):
        self.events.append((event_type, event_payload))


class _FakePaintDevice:
    def __init__(self, device_pixel_ratio):
        self._device_pixel_ratio = device_pixel_ratio

    def devicePixelRatioF(self):
        return self._device_pixel_ratio


class _FakePainter:
    def __init__(self, transform=None, device_pixel_ratio=1.0):
        self._transform = transform or QtGui.QTransform()
        self._device = _FakePaintDevice(device_pixel_ratio)

    def worldTransform(self):
        return self._transform

    def device(self):
        return self._device


def _app_config_event(value):
    return (AppEvents.APP_CONFIG_UPDATED, {"setting": "options", "value": value})


SNAP_PREF_UPDATE = SnapPreferencesDto(
    snap_to_grid_enabled=False,
    snap_to_grid_threshold_px=0,
    snap_to_pdf_lines_enabled=False,
    snap_to_pdf_lines_threshold_px=12,
    snap_to_takeoffs_enabled=False,
    snap_to_takeoffs_threshold_px=16,
    snap_to_right_angle_enabled=False,
    snap_to_right_angle_threshold_px=20,
).to_options()
SNAP_PREF_CHANGED_KEYS = list(SNAP_PREF_UPDATE)


def _assert_snap_pref_update_applied(test_case, aggregate):
    test_case.assertEqual(
        aggregate.snap_to_grid_enabled,
        SNAP_PREF_UPDATE["snap_to_grid_enabled"],
    )
    test_case.assertEqual(
        aggregate.snap_to_grid_threshold_px,
        SNAP_PREF_UPDATE["snap_to_grid_threshold_px"],
    )
    test_case.assertEqual(
        aggregate.snap_to_pdf_lines_enabled,
        SNAP_PREF_UPDATE["snap_to_pdf_lines_enabled"],
    )
    test_case.assertEqual(
        aggregate.snap_to_pdf_lines_threshold_px,
        SNAP_PREF_UPDATE["snap_to_pdf_lines_threshold_px"],
    )
    test_case.assertEqual(
        aggregate.snap_to_takeoffs_enabled,
        SNAP_PREF_UPDATE["snap_to_takeoffs_enabled"],
    )
    test_case.assertEqual(
        aggregate.snap_to_takeoffs_threshold_px,
        SNAP_PREF_UPDATE["snap_to_takeoffs_threshold_px"],
    )
    test_case.assertEqual(
        aggregate.snap_to_right_angle_enabled,
        SNAP_PREF_UPDATE["snap_to_right_angle_enabled"],
    )
    test_case.assertEqual(
        aggregate.snap_to_right_angle_threshold_px,
        SNAP_PREF_UPDATE["snap_to_right_angle_threshold_px"],
    )


def _visible_texts(dialog):
    texts = []
    for widget_type in (QtWidgets.QLabel, QtWidgets.QCheckBox, QtWidgets.QRadioButton):
        texts.extend(
            widget.text()
            for widget in dialog.findChildren(widget_type)
            if widget.text()
        )
    return texts


def _apply_button(dialog):
    buttons = dialog.findChild(QtWidgets.QDialogButtonBox)
    return buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Apply)


def _reset_all_button(dialog):
    matches = [
        button
        for button in dialog.findChildren(QtWidgets.QPushButton)
        if button.text() == OPTIONS_LABEL_RESET_ALL_SETTINGS
    ]
    return matches[0] if matches else None
