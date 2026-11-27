import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.dialogs.set_scale_dialog import (
    ScaleSettings,
    SetScaleDialog,
)
from PySide6 import QtWidgets
from shiboken6 import delete
from ost_visualizer.presentation.texts import (
    SET_SCALE_DIALOG_MESSAGE_FAILED_TO_SAVE_PAGE_SCALE,
    SET_SCALE_DIALOG_MESSAGE_THE_SECOND_CUSTOM_SCALE_VALUE_IS_NOT,
    SET_SCALE_DIALOG_TITLE_INVALID_SCALE,
    SET_SCALE_DIALOG_TITLE_SAVE_FAILED,
)


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class SetScaleDialogAsyncLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_set_scale_failure_restores_interactive_retry(self):
        callbacks = []
        saved_settings = []
        dialog = SetScaleDialog(
            None,
            None,
            1.0,
            48.0,
            lambda _settings: self.fail("SQL must not use the synchronous save"),
            save_async_fn=lambda settings, completed: saved_settings.append(settings)
            or callbacks.append(completed)
            or True,
        )
        try:
            dialog._custom_radio.setChecked(True)
            dialog._custom_factor2_edit.setText("96")
            dialog._on_apply()
            self.assertFalse(dialog._ok_btn.isEnabled())
            self.assertFalse(dialog._custom_factor2_edit.isEnabled())
            with patch(
                "ost_visualizer.presentation.dialogs.set_scale_dialog.show_warning"
            ) as show_warning:
                callbacks[0](False)
            show_warning.assert_called_once_with(
                dialog,
                SET_SCALE_DIALOG_TITLE_SAVE_FAILED,
                SET_SCALE_DIALOG_MESSAGE_FAILED_TO_SAVE_PAGE_SCALE,
            )
            self.assertTrue(dialog._ok_btn.isEnabled())
            self.assertTrue(dialog._custom_factor2_edit.isEnabled())
            self.assertTrue(dialog._apply_btn.isEnabled())
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
            dialog._on_ok()
            self.assertEqual(len(callbacks), 2)
            self.assertEqual(saved_settings[0], saved_settings[1])
            self.assertEqual(saved_settings[1], ScaleSettings(1.0, 96.0, False))
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
            callbacks[1](True)
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_set_scale_completion_is_dropped_after_dialog_destruction(self):
        callbacks = []
        dialog = SetScaleDialog(
            None,
            None,
            1.0,
            48.0,
            lambda _settings: self.fail("SQL must not use the synchronous save"),
            save_async_fn=lambda _settings, completed: callbacks.append(completed)
            or True,
        )
        dialog._custom_radio.setChecked(True)
        dialog._custom_factor2_edit.setText("96")
        dialog._on_apply()
        self.assertEqual(len(callbacks), 1)
        delete(dialog)
        with patch(
            "ost_visualizer.presentation.dialogs.set_scale_dialog.show_warning"
        ) as show_warning:
            callbacks[0](True)
            callbacks[0](False)
        show_warning.assert_not_called()


class SetScaleDialogCustomValueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _dialog(self, sf1, sf2, saved):
        dialog = SetScaleDialog(None, None, sf1, sf2, lambda s: saved.append(s) or True)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_a_value_that_is_not_finite_is_refused_as_not_a_valid_number(self):
        for text in ("nan", "inf", "-nan", "1e999", "Infinity"):
            with self.subTest(text=text):
                saved = []
                dialog = self._dialog(1.0, 48.0, saved)
                dialog._custom_radio.setChecked(True)
                dialog._custom_factor2_edit.setText(text)
                with patch(
                    "ost_visualizer.presentation.dialogs.set_scale_dialog.show_warning"
                ) as show_warning:
                    dialog._on_apply()
                self.assertEqual(saved, [])
                show_warning.assert_called_once_with(
                    dialog,
                    SET_SCALE_DIALOG_TITLE_INVALID_SCALE,
                    SET_SCALE_DIALOG_MESSAGE_THE_SECOND_CUSTOM_SCALE_VALUE_IS_NOT.format(
                        entered_value=text
                    ),
                    validation=True,
                )

    def test_custom_fields_show_the_stored_value_at_full_precision(self):
        for sf2, shown in (
            (1234567.0, "1234567"),
            (48.0, "48"),
            (12.0000001, "12.0000001"),
            (0.1, "0.1"),
            (1e20, "1e+20"),
            (1 / 3, "0.3333333333333333"),
            (123456.789012345, "123456.789012345"),
        ):
            with self.subTest(sf2=sf2):
                dialog = self._dialog(1.0, sf2, [])
                self.assertEqual(dialog._custom_factor2_edit.text(), shown)
                self.assertEqual(float(dialog._custom_factor2_edit.text()), sf2)

    def test_ticking_only_apply_to_all_pages_resaves_the_exact_stored_scale(self):
        saved = []
        dialog = self._dialog(1.0, 1234567.0, saved)
        self.assertTrue(dialog._custom_radio.isChecked())
        dialog._apply_all_check.setChecked(True)
        dialog._on_apply()
        self.assertEqual(saved, [ScaleSettings(1.0, 1234567.0, True)])
