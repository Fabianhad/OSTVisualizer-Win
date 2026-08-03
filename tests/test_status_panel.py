import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from ost_visualizer.presentation.components.status_panel import StatusPanel


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
        panel.set_collaboration_mutation_state("executing", 2, "Saving")
        self.assertEqual(panel.collaboration_label.text(), "SQL: SAVING")
        panel.set_collaboration_mutation_state("projecting", 1, "Applying")
        self.assertEqual(panel.collaboration_label.text(), "SQL: COMMITTED, SYNCING")
        panel.set_collaboration_mutation_state("uncertain", 1, "Unknown")
        self.assertEqual(panel.collaboration_label.text(), "SQL: COMMIT UNKNOWN")
        panel.set_collaboration_mutation_state("queued", 0)
        self.assertEqual(panel.collaboration_label.text(), "SQL: 0 VIEWING / 1 EDITING")
        panel.set_collaboration_state("conflicted", "Refresh required")
        self.assertEqual(panel.collaboration_label.text(), "SQL: CONFLICT")
        self.assertEqual(panel.collaboration_label.toolTip(), "Refresh required")
        panel.set_collaboration_state("stopped")
        self.assertTrue(panel.collaboration_label.isHidden())
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


if __name__ == "__main__":
    unittest.main()
