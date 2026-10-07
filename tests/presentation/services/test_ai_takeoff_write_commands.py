import json
import threading
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from ost_visualizer.application.dtos.ai_takeoff_dtos import (
    AI_TAKEOFF_COMMANDS,
    ok_result,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.services import (
    ai_takeoff_bridge,
    ai_takeoff_write_commands,
)
from ost_visualizer.presentation.services.ai_takeoff_bridge import TakeoffCommandBridge
from ost_visualizer.presentation.services.ai_takeoff_write_commands import (
    AiTakeoffWriteCommands,
)
from PySide6 import QtCore
from tests.presentation.services.test_ai_takeoff_bridge import (
    BridgeTestCase,
    FakePdfSource,
    FakeReadService,
)


class FakeReadWithBid(FakeReadService):
    def open_bid_ref(self):
        return BidRef("C:/jobs/a.mdb", "7")

    def list_levels(self, bid_uid=None):
        self._record("list_levels", bid_uid=bid_uid)
        return ok_result({"sidecar_status": "rebind_required", "levels": []})


class FakeProposalService:
    def __init__(self):
        self.calls = []
        self.threads = {}
        self.apply_status = "pending_approval"

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        self.threads[name] = threading.get_ident()

    def propose_scale(self, *args, **kwargs):
        self._record("propose_scale", *args, **kwargs)
        return ok_result({"changeset_id": "cs-1", "status": "proposed"})

    def find_regions(self, *args, **kwargs):
        self._record("find_regions", *args, **kwargs)
        return ok_result({"regions": []})

    def propose_element(self, *args, **kwargs):
        self._record("propose_element", *args, **kwargs)
        return ok_result({"changeset_id": "cs-2", "status": "proposed"})

    def apply_changeset(self, changeset_id):
        self._record("apply_changeset", changeset_id)
        return ok_result(
            {"changeset_id": changeset_id, "status": self.apply_status},
            self.apply_status,
        )

    def discard_changeset(self, changeset_id):
        self._record("discard_changeset", changeset_id)
        return ok_result({"changeset_id": changeset_id, "status": "discarded"})

    def update_assumption(self, *args, **kwargs):
        self._record("update_assumption", *args, **kwargs)
        return ok_result({"changeset_id": args[0]})


class FakeProposals:
    def __init__(self):
        self.last = SimpleNamespace(uid="cs-9")

    def last_applied(self, database_id, bid_uid):
        return self.last


class FakeTopView:
    def __init__(self):
        self.render_threads = []

    def snapshot(self):
        return ("snapshot",)

    def render(self, snapshot):
        self.render_threads.append(threading.get_ident())
        return {
            "image": {"png_base64": "", "width_px": 1, "height_px": 1},
            "mesh_count": 1,
        }


class WriteCommandBridgeTests(BridgeTestCase):
    def setUp(self):
        self.proposal = FakeProposalService()
        self.proposals = FakeProposals()
        self.top_view = FakeTopView()
        self.requested = []
        self.undo_calls = []
        self.undo_outcome = SimpleNamespace(success=True, code="", message="")
        self.audit = []
        super().setUp()
        self.bridge.cleanup()
        self.service = FakeReadWithBid()
        self.server_name = f"OstvTakeoffWriteTest-{uuid.uuid4().hex[:12]}"
        self.bridge = TakeoffCommandBridge(
            read_service=self.service,
            pdf_source=FakePdfSource(),
            access_allowed=lambda: self.allowed,
            token_path=self.token_path,
            server_name=self.server_name,
            token_factory=lambda: "write-token",
            write_commands=AiTakeoffWriteCommands(
                read_service=self.service,
                proposal_service=self.proposal,
                proposals=self.proposals,
                undo=self._undo,
                top_view=self.top_view,
                apply_requested=self.requested.append,
            ),
            audit=lambda tool, arguments, outcome: self.audit.append(
                (tool, dict(arguments), outcome)
            ),
        )
        self.assertTrue(self.bridge.start())
        self.addCleanup(self.bridge.cleanup)

    def _undo(self, uid, done):
        self.undo_calls.append(uid)
        QtCore.QTimer.singleShot(50, lambda: done(self.undo_outcome))

    def test_the_command_table_is_the_fifteen_declared_tools(self):
        self.assertEqual(self.bridge.commands, AI_TAKEOFF_COMMANDS)
        self.assertEqual(len(self.bridge.commands), 15)

    def test_no_bridge_code_can_approve_accept_or_reject(self):
        for module in (ai_takeoff_bridge, ai_takeoff_write_commands):
            source = Path(module.__file__).read_text(encoding="utf-8")
            for token in (
                ".approve(",
                "accept_assumption",
                "override_assumption",
                ".reject(",
                "mark_applied",
                "AiChangesetStore",
                "ProjectWriteService",
            ):
                with self.subTest(module=module.__name__, token=token):
                    self.assertNotIn(token, source)
        for command in (
            "approve_changeset",
            "accept_assumption",
            "set_assumption_status",
        ):
            with self.subTest(command=command):
                self.assertEqual(
                    self.call(command, {"changeset_id": "cs-1"})["status"],
                    "unknown_command",
                )

    def test_update_assumption_cannot_carry_a_status(self):
        refused = self.call(
            "update_assumption",
            {
                "changeset_id": "cs-1",
                "op": "revise",
                "assumption_id": "a1",
                "status": "accepted",
            },
        )
        self.assertEqual(refused["status"], "invalid_argument")
        self.assertEqual(self.proposal.calls, [])
        self.assertTrue(
            self.call(
                "update_assumption",
                {"changeset_id": "cs-1", "op": "add", "subject": "other"},
            )["success"]
        )

    def test_apply_changeset_asks_the_app_only_while_pending(self):
        result = self.call("apply_changeset", {"changeset_id": "cs-1"})
        self.assertEqual(result["status"], "pending_approval")
        self.assertEqual(self.requested, ["cs-1"])
        self.proposal.apply_status = "applied"
        self.call("apply_changeset", {"changeset_id": "cs-1"})
        self.assertEqual(self.requested, ["cs-1"])

    def test_regions_and_3d_run_on_worker_threads(self):
        gui = threading.get_ident()
        self.assertTrue(
            self.call("find_regions", {"page_uid": "p1", "bbox_pts": [0, 0, 1, 1]})[
                "success"
            ]
        )
        self.assertNotEqual(self.proposal.threads["find_regions"], gui)
        rendered = self.call("render_3d", {})
        self.assertEqual(rendered["status"], "ok")
        self.assertNotEqual(self.top_view.render_threads[0], gui)
        self.assertEqual(self.proposal.threads.get("propose_scale"), None)
        self.call(
            "propose_scale",
            {"page_uid": "p1", "p1_pts": [0, 0], "p2_pts": [1, 0], "real_in": 1},
        )
        self.assertEqual(self.proposal.threads["propose_scale"], gui)

    def test_undo_replies_when_the_deferred_undo_finishes(self):
        self.assertEqual(
            self.call("undo_last_ai_changeset", {})["data"],
            {"changeset_id": "cs-9", "status": "undone"},
        )
        self.assertEqual(self.undo_calls, ["cs-9"])
        self.undo_outcome = SimpleNamespace(
            success=False, code="stale_changeset", message="Edited since."
        )
        self.assertEqual(
            self.call("undo_last_ai_changeset", {})["status"], "stale_changeset"
        )
        self.proposals.last = None
        self.assertEqual(self.call("undo_last_ai_changeset", {})["status"], "not_found")

    def test_other_bids_are_refused(self):
        self.assertEqual(
            self.call("undo_last_ai_changeset", {"bid_uid": "8"})["status"],
            "bid_not_open",
        )
        self.assertEqual(
            self.call("render_3d", {"bid_uid": "8"})["status"], "bid_not_open"
        )
        self.assertEqual(
            self.call("render_3d", {"view": "iso"})["status"], "invalid_argument"
        )

    def test_every_command_is_audited_without_the_token(self):
        self.call("discard_changeset", {"changeset_id": "cs-1"})
        self.call("list_sheets", {})
        self.assertEqual(
            [(tool, outcome) for tool, _arguments, outcome in self.audit],
            [("discard_changeset", "ok"), ("list_sheets", "ok")],
        )
        self.assertNotIn("write-token", json.dumps(self.audit))

    def test_a_rebind_required_read_suggests_a_rebind(self):
        suggested = []
        self.bridge.rebind_suggested.connect(lambda: suggested.append(True))
        self.call("list_levels", {})
        self.assertEqual(suggested, [True])

    def test_feature_denied_still_blocks_write_tools(self):
        self.allowed = False
        self.assertEqual(
            self.call("apply_changeset", {"changeset_id": "cs-1"})["status"],
            "feature_denied",
        )
        self.assertEqual(self.requested, [])

    def call(self, command, arguments=None, token_path=None):
        client = self.client(token_path)
        deadline = time.monotonic() + 15
        results = []
        thread = threading.Thread(
            target=lambda: results.append(client.call(command, arguments or {}))
        )
        thread.start()
        while thread.is_alive() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
        thread.join(1)
        self.assertFalse(thread.is_alive())
        return results[0]


if __name__ == "__main__":
    unittest.main()
