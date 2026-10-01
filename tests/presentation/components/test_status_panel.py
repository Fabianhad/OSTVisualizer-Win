import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.components.status_panel import StatusPanel
from PySide6 import QtWidgets


class _CountingLabel(QtWidgets.QLabel):
    def __init__(self, text=""):
        super().__init__(text)
        self.text_updates = 0
        self.visibility_updates = 0

    def setText(self, text):
        self.text_updates += 1
        super().setText(text)

    def setVisible(self, visible):
        self.visibility_updates += 1
        super().setVisible(visible)


class StatusPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_pending_and_uncertain_mutations_override_presence_projection(self):
        panel = StatusPanel()
        panel.set_collaboration_state("healthy", "Connected")
        panel.set_collaboration_presence(
            [
                SimpleNamespace(
                    mode=SimpleNamespace(value="editing"),
                    display_name="Editor",
                    application_version="1",
                )
            ]
        )
        self.assertEqual(panel.collaboration_label.text(), "SQL: 0 VIEWING / 1 EDITING")
        self.assertEqual(panel.collaboration_label.toolTip(), "Editor (editing, 1)")
        panel.set_collaboration_mutation_state("executing", 2, "Saving")
        self.assertEqual(panel.collaboration_label.text(), "SQL: SAVING")
        self.assertEqual(panel.collaboration_label.toolTip(), "Saving")
        panel.set_collaboration_mutation_state("projecting", 1, "Applying")
        self.assertEqual(panel.collaboration_label.text(), "SQL: COMMITTED, SYNCING")
        self.assertEqual(panel.collaboration_label.toolTip(), "Applying")
        panel.set_collaboration_mutation_state("uncertain", 1, "Unknown")
        self.assertEqual(panel.collaboration_label.text(), "SQL: COMMIT UNKNOWN")
        self.assertEqual(panel.collaboration_label.toolTip(), "Unknown")
        panel.set_collaboration_mutation_state("queued", 0)
        self.assertEqual(panel.collaboration_label.text(), "SQL: 0 VIEWING / 1 EDITING")
        self.assertEqual(panel.collaboration_label.toolTip(), "Editor (editing, 1)")
        self.assertFalse(panel.collaboration_label.isHidden())
        panel.set_collaboration_state("conflicted", "Refresh required")
        self.assertEqual(panel.collaboration_label.text(), "SQL: CONFLICT")
        self.assertEqual(panel.collaboration_label.toolTip(), "Refresh required")
        panel.set_collaboration_state("stopped")
        self.assertTrue(panel.collaboration_label.isHidden())
        panel.deleteLater()

    def test_presence_counts_viewers_and_editors_with_per_user_tooltip(self):
        panel = StatusPanel()
        panel.set_collaboration_state("catching_up", "Synchronizing")
        users = [
            SimpleNamespace(
                mode=SimpleNamespace(value=mode),
                display_name=name,
                application_version=version,
            )
            for mode, name, version in (
                ("viewing", "Ann", "1.0"),
                ("editing", "Bob", "1.1"),
                ("viewing", "Cy", "1.2"),
            )
        ]
        panel.set_collaboration_presence(users)
        self.assertEqual(panel.collaboration_label.text(), "SQL: 2 VIEWING / 1 EDITING")
        self.assertEqual(
            panel.collaboration_label.toolTip(),
            "Ann (viewing, 1.0)\nBob (editing, 1.1)\nCy (viewing, 1.2)",
        )
        panel.set_collaboration_presence([])
        self.assertEqual(panel.collaboration_label.text(), "SQL: SYNCING")
        self.assertEqual(panel.collaboration_label.toolTip(), "Synchronizing")
        panel.deleteLater()

    def test_every_connection_state_renders_its_label_and_message(self):
        panel = StatusPanel()
        expected = {
            "connecting": "SQL: CONNECTING",
            "catching_up": "SQL: SYNCING",
            "healthy": "SQL: CONNECTED",
            "disconnected": "SQL: DISCONNECTED",
            "credential_required": "SQL: SIGN IN REQUIRED",
            "read_only": "SQL: READ ONLY",
            "conflicted": "SQL: CONFLICT",
            "reconciliation_required": "SQL: REFRESH REQUIRED",
        }
        for state, text in expected.items():
            with self.subTest(state=state):
                panel.set_collaboration_state(state, f"{state} message")
                self.assertEqual(panel.collaboration_label.text(), text)
                self.assertEqual(
                    panel.collaboration_label.toolTip(), f"{state} message"
                )
                self.assertFalse(panel.collaboration_label.isHidden())
        panel.deleteLater()

    def test_pending_mutation_without_message_falls_back_to_connection_message(self):
        panel = StatusPanel()
        panel.set_collaboration_state("healthy", "Connected")
        panel.set_collaboration_mutation_state("executing", 1)
        self.assertEqual(panel.collaboration_label.text(), "SQL: SAVING")
        self.assertEqual(panel.collaboration_label.toolTip(), "Connected")
        panel.set_collaboration_mutation_state("uncertain", -3, "Ignored")
        self.assertEqual(panel.collaboration_label.text(), "SQL: CONNECTED")
        panel.deleteLater()

    def test_terminal_connection_state_overrides_recovering_mutation(self):
        panel = StatusPanel()
        panel.set_collaboration_state("connecting", "Recovering")
        panel.set_collaboration_mutation_state("recovering", 1, "Projecting")
        self.assertEqual(panel.collaboration_label.text(), "SQL: RECOVERING")
        panel.set_collaboration_state(
            "reconciliation_required",
            "Authoritative recovery failed.",
        )
        self.assertEqual(panel.collaboration_label.text(), "SQL: REFRESH REQUIRED")
        self.assertEqual(
            panel.collaboration_label.toolTip(), "Authoritative recovery failed."
        )
        panel.set_collaboration_state("disconnected", "Connection unavailable")
        self.assertEqual(panel.collaboration_label.text(), "SQL: DISCONNECTED")
        panel.set_collaboration_state("stopped")
        self.assertTrue(panel.collaboration_label.isHidden())
        panel.deleteLater()

    def test_uncertain_commit_remains_visible_during_disconnect(self):
        panel = StatusPanel()
        panel.set_collaboration_state("disconnected", "Connection unavailable")
        panel.set_collaboration_mutation_state("uncertain", 1, "Status unknown")
        self.assertEqual(panel.collaboration_label.text(), "SQL: COMMIT UNKNOWN")
        self.assertEqual(panel.collaboration_label.toolTip(), "Status unknown")
        panel.deleteLater()

    def test_saving_and_recovery_return_to_connected_when_pending_reaches_zero(self):
        panel = StatusPanel()
        panel.set_collaboration_state("healthy", "Connected")
        panel.set_collaboration_mutation_state("queued", 2, "Queued")
        self.assertEqual(panel.collaboration_label.text(), "SQL: SAVING")
        panel.set_collaboration_mutation_state("recovering", 1, "Recovering")
        self.assertEqual(panel.collaboration_label.text(), "SQL: RECOVERING")
        panel.set_collaboration_mutation_state("queued", 0)
        self.assertEqual(panel.collaboration_label.text(), "SQL: CONNECTED")
        self.assertEqual(panel.collaboration_label.toolTip(), "Connected")
        panel.deleteLater()

    def test_failed_recovery_remains_a_clear_terminal_status(self):
        panel = StatusPanel()
        panel.set_collaboration_state("catching_up", "Synchronizing")
        panel.set_collaboration_mutation_state("recovering", 1, "Recovering")
        panel.set_collaboration_state(
            "reconciliation_required",
            "Authoritative recovery failed.",
        )
        self.assertEqual(panel.collaboration_label.text(), "SQL: REFRESH REQUIRED")
        self.assertEqual(
            panel.collaboration_label.toolTip(), "Authoritative recovery failed."
        )
        panel.deleteLater()

    def test_license_projection_cannot_hide_connection_status(self):
        panel = StatusPanel()
        panel.set_collaboration_state("disconnected", "Server unavailable")
        panel.set_license_active(True)
        self.assertEqual(panel.license_label.text(), " ACTIVATED")
        self.assertEqual(panel.collaboration_label.text(), "SQL: DISCONNECTED")
        self.assertFalse(panel.collaboration_label.isHidden())
        panel.deleteLater()

    def test_identical_status_projection_does_not_rewrite_widgets(self):
        panel = StatusPanel()
        collaboration_label = _CountingLabel()
        collaboration_label.hide()
        collaboration_label.visibility_updates = 0
        panel.collaboration_label = collaboration_label
        page_label = _CountingLabel()
        panel.page_info_label = page_label
        license_label = _CountingLabel(" NOT ACTIVATED")
        panel.license_label = license_label
        panel.set_collaboration_state("healthy", "Connected")
        panel.set_collaboration_state("healthy", "Connected")
        panel.set_collaboration_presence([])
        panel.set_page_info("Page One")
        panel.set_page_info("Page One")
        panel.set_license_active(False)
        panel.set_license_active(False)
        self.assertEqual(collaboration_label.text_updates, 1)
        self.assertEqual(collaboration_label.visibility_updates, 1)
        self.assertEqual(page_label.text_updates, 1)
        self.assertEqual(license_label.text_updates, 0)
        panel.set_collaboration_state("healthy", "Connected again")
        panel.set_page_info("Page Two")
        panel.set_license_active(True)
        self.assertEqual(collaboration_label.text_updates, 2)
        self.assertEqual(collaboration_label.visibility_updates, 2)
        self.assertEqual(page_label.text_updates, 2)
        self.assertEqual(page_label.text(), "Page Two")
        self.assertEqual(license_label.text_updates, 1)
        self.assertEqual(license_label.text(), " ACTIVATED")
        panel.deleteLater()


if __name__ == "__main__":
    unittest.main()
