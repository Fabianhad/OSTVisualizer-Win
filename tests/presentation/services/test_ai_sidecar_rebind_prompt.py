import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.services.ai_takeoff_sidecar_service import (
    SidecarContext,
)
from ost_visualizer.domain.entities.ai_takeoff import SidecarWriteRefused
from ost_visualizer.presentation.services.ai_sidecar_rebind_prompt import (
    REBIND_PROMPT_TEXT,
    AiSidecarRebindPrompt,
)
from ost_visualizer.domain.entities.ai_takeoff import ai_takeoff_bid_key
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.database_descriptor import DatabaseBackend
from ost_visualizer.domain.entities.identity_refs import BidRef
from PySide6 import QtWidgets
from tests.application.services.test_ai_takeoff_read_service import ACCESS_PATH
from tests.application.services.test_ai_takeoff_sidecar_service import (
    SidecarServiceTestCase,
)


class FakeSidecars:
    def __init__(self, status="rebind_required", key="k" * 32):
        self.status = status
        self.key = key
        self.rebinds = 0
        self.expected_keys = []
        self.refuse = False

    def context(self):
        return SidecarContext(self.status, self.key)

    def rebind(self, expected_bid_key=None):
        self.expected_keys.append(expected_bid_key)
        if self.refuse:
            raise SidecarWriteRefused("fingerprint_mismatch")
        self.rebinds += 1
        return "ok"


class RebindPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.sidecars = FakeSidecars()
        self.prompt = AiSidecarRebindPrompt(self.sidecars)
        self.addCleanup(self.prompt.cleanup)

    def test_rebind_required_offers_a_confirmation_once_per_bid(self):
        box = self.prompt.offer()
        self.assertIsNotNone(box)
        self.assertEqual(box.text(), REBIND_PROMPT_TEXT)
        self.assertFalse(box.isModal())
        self.assertIsNone(self.prompt.offer())

    def test_yes_rebinds_and_no_leaves_it(self):
        box = self.prompt.offer()
        box.button(QtWidgets.QMessageBox.StandardButton.No).click()
        self.assertEqual(self.sidecars.rebinds, 0)
        other = AiSidecarRebindPrompt(self.sidecars)
        self.addCleanup(other.cleanup)
        other.offer().button(QtWidgets.QMessageBox.StandardButton.Yes).click()
        self.assertEqual(self.sidecars.rebinds, 1)
        self.assertEqual(self.sidecars.expected_keys, ["k" * 32])

    def test_other_statuses_never_offer_a_rebind(self):
        for status in (
            "ok",
            "empty",
            "fingerprint_mismatch",
            "corrupt",
            "unavailable_no_database_guid",
        ):
            with self.subTest(status=status):
                prompt = AiSidecarRebindPrompt(FakeSidecars(status))
                self.addCleanup(prompt.cleanup)
                self.assertIsNone(prompt.offer())

    def test_a_refused_rebind_is_reported_not_raised(self):
        self.sidecars.refuse = True
        self.prompt.offer().button(QtWidgets.QMessageBox.StandardButton.Yes).click()
        self.assertIn("fingerprint_mismatch", self.prompt.last_message)


class RebindBidSwitchPromptTests(SidecarServiceTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_a_bid_switch_before_yes_is_refused_and_reported(self):
        self.write(database_id="db-old")
        other_key = ai_takeoff_bid_key(DatabaseBackend.ACCESS, "{BID-2}")
        other_path = self.sidecar_dir / f"{other_key}.json"
        other_path.write_text(
            self.path().read_text(encoding="utf-8").replace(self.key(), other_key),
            encoding="utf-8",
        )
        first, second = self.path().read_bytes(), other_path.read_bytes()
        prompt = AiSidecarRebindPrompt(self.sidecars)
        self.addCleanup(prompt.cleanup)
        box = prompt.offer()
        self.project.bid_ref = BidRef(ACCESS_PATH, "{BID-2}")
        self.project.bid = Bid(uid="{BID-2}", name="Tower")
        self.assertEqual(self.sidecars.context().status, "rebind_required")
        box.button(QtWidgets.QMessageBox.StandardButton.Yes).click()
        self.assertEqual(
            (self.path().read_bytes(), other_path.read_bytes()), (first, second)
        )
        self.assertIn("open bid changed", prompt.last_message)
        self.assertIsNotNone(prompt.notice)
        self.assertEqual(prompt.notice.text(), prompt.last_message)
        self.project.bid_ref = BidRef(ACCESS_PATH, "{BID-1}")
        self.project.bid = Bid(uid="{BID-1}", name="Tower")
        again = prompt.offer()
        self.assertIsNotNone(again)
        again.button(QtWidgets.QMessageBox.StandardButton.Yes).click()
        self.assertEqual(self.sidecars.context().status, "ok")
        self.assertEqual(other_path.read_bytes(), second)


if __name__ == "__main__":
    unittest.main()
