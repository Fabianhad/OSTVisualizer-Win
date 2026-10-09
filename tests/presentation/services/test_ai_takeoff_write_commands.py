import json
import secrets
import threading
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from ost_visualizer.application.dtos.ai_takeoff_audit_dtos import (
    AuditEntry,
    hash_arguments,
)
from ost_visualizer.application.dtos.ai_changeset_write_dtos import AppliedChangeset
from ost_visualizer.application.dtos.ai_takeoff_dtos import (
    AI_TAKEOFF_COMMANDS,
    AiTakeoffRequestError,
    error_result,
    ok_result,
)
from ost_visualizer.application.services.ai_changeset_store import (
    AiChangesetProposals,
    AiChangesetStore,
)
from ost_visualizer.domain.entities.ai_changeset import (
    KIND_ELEMENTS,
    STATUS_UNDONE,
    AiChangeset,
    ChangesetError,
    ProposedCondition,
    ProposedTakeoff,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.infrastructure.persistence.ai_takeoff_audit_log import (
    AiTakeoffAuditLog,
)
from ost_visualizer.presentation.services import (
    ai_takeoff_bridge,
    ai_takeoff_write_commands,
)
from ost_visualizer.presentation.services.ai_takeoff_bridge import TakeoffCommandBridge
from ost_visualizer.presentation.services.ai_takeoff_write_commands import (
    AiTakeoffWriteCommands,
    DeferredReply,
)
from PySide6 import QtCore
from PySide6.QtNetwork import QLocalSocket
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

    def _record(self, call_name, /, *args, **kwargs):
        self.calls.append((call_name, args, kwargs))
        self.threads[call_name] = threading.get_ident()

    def plan_scale(self, *args, **kwargs):
        self._record("plan_scale", *args, **kwargs)
        return lambda: self.propose_scale(*args, **kwargs)

    def propose_scale(self, *args, **kwargs):
        self._record("propose_scale", *args, **kwargs)
        return ok_result({"changeset_id": "cs-1", "status": "proposed"})

    def find_regions(self, *args, **kwargs):
        self._record("find_regions", *args, **kwargs)
        return ok_result({"regions": []})

    def plan_element(self, *args, **kwargs):
        self._record("plan_element", *args, **kwargs)
        return lambda: self.propose_element(*args, **kwargs)

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
        self.last = SimpleNamespace(
            uid="cs-9", status="applied", database_id="C:/jobs/a.mdb", bid_uid="7"
        )

    def get(self, uid):
        if self.last is None or uid != self.last.uid:
            raise ChangesetError("not_found", "Unknown changeset_id")
        return self.last

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


class DeferredReplyTests(unittest.TestCase):
    def test_a_callback_attached_after_resolve_gets_the_result_at_once(self):
        reply = DeferredReply()
        reply.resolve({"status": "ok"})
        received = []
        reply.attach(received.append)
        self.assertEqual(received, [{"status": "ok"}])

    def test_only_the_first_resolution_is_delivered(self):
        reply = DeferredReply()
        received = []
        reply.attach(received.append)
        reply.resolve({"status": "ok"})
        reply.resolve({"status": "late"})
        self.assertEqual(received, [{"status": "ok"}])
        later = []
        reply.attach(later.append)
        self.assertEqual(later, [{"status": "ok"}])


class UndoIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.store = AiChangesetStore(clock=lambda: 10.0)
        self.proposals = AiChangesetProposals(self.store)
        self.undo_calls = []
        self.held = []
        self.commands = AiTakeoffWriteCommands(
            read_service=FakeReadWithBid(),
            proposal_service=FakeProposalService(),
            proposals=self.proposals,
            undo=self._undo,
            top_view=FakeTopView(),
            apply_requested=lambda _uid: None,
        )
        self.handler = self.commands.handlers()["undo_last_ai_changeset"]

    def _undo(self, uid, done):
        self.undo_calls.append(uid)
        self.held.append((uid, done))

    def finish(self, index, success, code="", message=""):
        uid, done = self.held[index]
        if success:
            self.store.mark_undone(uid)
        done(SimpleNamespace(success=success, code=code, message=message))

    def applied(self):
        added = self.proposals.add(
            AiChangeset(
                uid="",
                database_id="C:/jobs/a.mdb",
                bid_uid="7",
                bid_key="a" * 32,
                kind=KIND_ELEMENTS,
                created_at=0.0,
                conditions=(ProposedCondition("c1", "Slab", 8.0, 0.0),),
                takeoffs=(
                    ProposedTakeoff(
                        "t1", "p1", "c1", (0.0, 0.0, 10.0, 0.0, 10.0, 10.0)
                    ),
                ),
            )
        )
        self.proposals.request_apply(added.uid)
        self.store.approve(added.uid)
        self.store.mark_applied(added.uid, AppliedChangeset(takeoff_uids=("T1",)))
        return added.uid

    def results(self, reply):
        received = []
        reply.attach(received.append)
        return received

    def test_a_retry_during_a_slow_undo_never_undoes_twice(self):
        uid = self.applied()
        first = self.results(self.handler({"changeset_id": uid}))
        retry = self.results(self.handler({"changeset_id": uid}))
        self.assertEqual(self.undo_calls, [uid])
        self.assertEqual((first, retry), ([], []))
        self.finish(0, True)
        self.assertEqual(
            first, [ok_result({"changeset_id": uid, "status": STATUS_UNDONE})]
        )
        self.assertEqual(
            retry,
            [
                ok_result(
                    {"changeset_id": uid, "status": "already_undone"}, "already_undone"
                )
            ],
        )
        again = self.handler({"changeset_id": uid})
        self.assertEqual(
            again,
            ok_result(
                {"changeset_id": uid, "status": "already_undone"}, "already_undone"
            ),
        )
        self.assertEqual(self.undo_calls, [uid])

    def test_a_retry_after_a_timed_out_undo_finished_never_undoes_the_one_before(self):
        older = self.applied()
        self.handler({"changeset_id": older})
        self.finish(0, True)
        newer = self.applied()
        self.handler({"changeset_id": newer})
        self.finish(1, True)
        retried = self.handler({"changeset_id": newer})
        self.assertEqual(retried["status"], "already_undone")
        self.assertEqual(self.undo_calls, [older, newer])

    def test_a_failed_undo_answers_every_waiting_call_and_can_be_retried(self):
        uid = self.applied()
        first = self.results(self.handler({"changeset_id": uid}))
        retry = self.results(self.handler({"changeset_id": uid}))
        self.finish(0, False, "stale_changeset", "Edited since.")
        self.assertEqual(first, [error_result("stale_changeset", "Edited since.")])
        self.assertEqual(retry, first)
        self.results(self.handler({"changeset_id": uid}))
        self.assertEqual(self.undo_calls, [uid, uid])

    def test_a_changeset_of_another_bid_or_database_is_never_undone(self):
        uid = self.applied()
        for database_id, bid_uid in (("C:/jobs/b.mdb", "7"), ("C:/jobs/a.mdb", "8")):
            with self.subTest(database_id=database_id, bid_uid=bid_uid):
                other = self.proposals.add(
                    AiChangeset(
                        uid="",
                        database_id=database_id,
                        bid_uid=bid_uid,
                        bid_key="b" * 32,
                        kind=KIND_ELEMENTS,
                        created_at=0.0,
                        conditions=(ProposedCondition("c1", "Slab", 8.0, 0.0),),
                        takeoffs=(
                            ProposedTakeoff(
                                "t1", "p1", "c1", (0.0, 0.0, 10.0, 0.0, 10.0, 10.0)
                            ),
                        ),
                    )
                )
                self.proposals.request_apply(other.uid)
                self.store.approve(other.uid)
                self.store.mark_applied(
                    other.uid, AppliedChangeset(takeoff_uids=("T9",))
                )
                self.store.mark_undone(other.uid)
                with self.assertRaises(AiTakeoffRequestError) as raised:
                    self.handler({"changeset_id": other.uid})
                self.assertEqual(raised.exception.code, "not_found")
        self.assertEqual(self.undo_calls, [])
        self.results(self.handler({"changeset_id": uid}))
        self.assertEqual(self.undo_calls, [uid])

    def test_the_changeset_must_be_named_and_be_the_latest_applied(self):
        older = self.applied()
        newer = self.applied()
        for arguments, code in (
            ({}, "invalid_argument"),
            ({"changeset_id": ""}, "invalid_argument"),
            ({"changeset_id": 5}, "invalid_argument"),
            ({"changeset_id": "missing"}, "not_found"),
            ({"changeset_id": older}, "invalid_state"),
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(AiTakeoffRequestError) as raised:
                    self.handler(arguments)
                self.assertEqual(raised.exception.code, code)
        self.assertEqual(self.undo_calls, [])
        self.results(self.handler({"changeset_id": newer}))
        self.assertEqual(self.undo_calls, [newer])


class WriteCommandBridgeTests(BridgeTestCase):
    def setUp(self):
        self.proposal = FakeProposalService()
        self.proposals = FakeProposals()
        self.top_view = FakeTopView()
        self.requested = []
        self.undo_calls = []
        self.held_undos = []
        self.hold_undo = False
        self.undo_outcome = SimpleNamespace(success=True, code="", message="")
        self.audit = []
        super().setUp()
        self.service = FakeReadWithBid()
        self.server_name = f"OstvTakeoffWriteTest-{uuid.uuid4().hex[:12]}"
        self.start_bridge()

    def start_bridge(self, **overrides):
        self.bridge.cleanup()
        options = dict(
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
        options.update(overrides)
        self.bridge = TakeoffCommandBridge(**options)
        self.assertTrue(self.bridge.start())
        self.addCleanup(self.bridge.cleanup)

    def _undo(self, uid, done):
        self.undo_calls.append(uid)
        if self.hold_undo:
            self.held_undos.append(done)
            return
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
        filters = {
            "max_gap_in": 36.0,
            "min_width": 1.0,
            "exclude_dashed": False,
            "exclude_thin_curves": False,
            "colors": ["#000000"],
            "min_area_sf": 5.0,
            "symbol_max_pts": 30.0,
            "cursor": "c:2",
            "limit": 5,
            "boundary_kinds": ["dashed"],
        }
        self.assertTrue(
            self.call(
                "find_regions",
                {
                    "page_uid": "p1",
                    "bbox_pts": [0, 0, 1, 1],
                    "seed_pts": [0.5, 0.5],
                    **filters,
                },
            )["success"]
        )
        _name, args, kwargs = self.proposal.calls[-1]
        self.assertEqual(args[1], [0, 0, 1, 1])
        self.assertEqual(
            kwargs, {"gap_close_in": None, "seed_pts": [0.5, 0.5], **filters}
        )
        rendered = self.call("render_3d", {})
        self.assertEqual(rendered["status"], "ok")
        self.assertNotEqual(self.top_view.render_threads[0], gui)
        self.assertEqual(self.proposal.threads.get("propose_scale"), None)
        self.call(
            "propose_scale",
            {"page_uid": "p1", "p1_pts": [0, 0], "p2_pts": [1, 0], "real_in": 1},
        )
        self.assertEqual(self.proposal.threads["plan_scale"], gui)
        self.assertNotEqual(self.proposal.threads["propose_scale"], gui)
        self.call(
            "propose_element", {"kind": "slab", "page_uid": "p1", "region_id": "r1"}
        )
        self.assertEqual(self.proposal.threads["plan_element"], gui)
        self.assertNotEqual(self.proposal.threads["propose_element"], gui)

    def test_undo_replies_when_the_deferred_undo_finishes(self):
        self.assertEqual(
            self.call("undo_last_ai_changeset", {"changeset_id": "cs-9"})["data"],
            {"changeset_id": "cs-9", "status": "undone"},
        )
        self.assertEqual(self.undo_calls, ["cs-9"])
        self.undo_outcome = SimpleNamespace(
            success=False, code="stale_changeset", message="Edited since."
        )
        self.assertEqual(
            self.call("undo_last_ai_changeset", {"changeset_id": "cs-9"})["status"],
            "stale_changeset",
        )
        self.proposals.last = None
        self.assertEqual(
            self.call("undo_last_ai_changeset", {"changeset_id": "cs-9"})["status"],
            "not_found",
        )

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
        audit_dir = self.directory / "audit"
        audit_log = AiTakeoffAuditLog(audit_dir)

        def record(tool, arguments, outcome):
            audit_log.record(
                None,
                AuditEntry(
                    event="tool",
                    tool=tool,
                    input_hash=hash_arguments(arguments),
                    changeset_id=str(arguments.get("changeset_id") or ""),
                    outcome=outcome,
                ),
            )

        self.start_bridge(token_factory=lambda: secrets.token_urlsafe(32), audit=record)
        token = self.token_path.read_text(encoding="utf-8").strip()
        self.assertGreaterEqual(len(token), 32)
        self.call("discard_changeset", {"changeset_id": "cs-1"})
        self.call("list_sheets", {})
        files = sorted(audit_dir.rglob("*.jsonl"))
        self.assertEqual([path.name for path in files], ["unkeyed.jsonl"])
        contents = files[0].read_text(encoding="utf-8")
        self.assertNotIn(token, contents)
        self.assertEqual(
            [
                (
                    entry["tool"],
                    entry["input_hash"],
                    entry["changeset_id"],
                    entry["outcome"],
                )
                for entry in map(json.loads, contents.splitlines())
            ],
            [
                (
                    "discard_changeset",
                    hash_arguments({"changeset_id": "cs-1"}),
                    "cs-1",
                    "ok",
                ),
                ("list_sheets", hash_arguments({}), "", "ok"),
            ],
        )

    def test_propose_element_forwards_its_arguments_and_returns_the_proposal(self):
        result = self.call(
            "propose_element",
            {"kind": "slab", "page_uid": "p1", "region_id": "r1", "thickness_in": 6},
        )
        self.assertEqual(result["data"], {"changeset_id": "cs-2", "status": "proposed"})
        name, args, kwargs = self.proposal.calls[-1]
        self.assertEqual((name, args), ("propose_element", ("slab", "p1")))
        self.assertEqual((kwargs["region_id"], kwargs["thickness_in"]), ("r1", 6))

    def test_an_undo_finishing_after_the_client_left_writes_nothing(self):
        client = self.send_held_undo()
        client.abort()
        self.wait_until(lambda: not self.bridge.findChildren(QLocalSocket))
        self.held_undos[0](self.undo_outcome)
        self.assertEqual(self.audit, [])
        self.assertEqual(
            self.call("discard_changeset", {"changeset_id": "cs-1"})["status"], "ok"
        )

    def test_an_undo_finishing_after_cleanup_writes_nothing(self):
        client = self.send_held_undo()
        self.bridge.cleanup()
        self.held_undos[0](self.undo_outcome)
        self.wait_until(
            lambda: client.state() == QLocalSocket.LocalSocketState.UnconnectedState
        )
        self.assertEqual(bytes(client.readAll()), b"")
        self.assertEqual(self.audit, [])

    def test_a_retry_over_the_pipe_during_a_slow_undo_never_undoes_twice(self):
        first = self.send_held_undo()
        retry = self.send_undo_request()
        self.proposals.last.status = "undone"
        self.held_undos[0](self.undo_outcome)
        replies = [self.reply_of(first), self.reply_of(retry)]
        self.assertEqual(
            [(reply["status"], reply["data"]["status"]) for reply in replies],
            [("ok", "undone"), ("already_undone", "already_undone")],
        )
        self.assertEqual(self.undo_calls, ["cs-9"])

    def reply_of(self, client):
        self.wait_until(client.canReadLine)
        return json.loads(bytes(client.readLine()).decode("ascii"))

    def send_held_undo(self):
        self.hold_undo = True
        client = self.send_undo_request()
        self.wait_until(lambda: self.held_undos)
        return client

    def send_undo_request(self):
        client = QLocalSocket()
        self.addCleanup(client.abort)
        client.connectToServer(self.server_name)
        self.assertTrue(client.waitForConnected(2000))
        client.write(
            json.dumps(
                {
                    "token": "write-token",
                    "command": "undo_last_ai_changeset",
                    "arguments": {"changeset_id": "cs-9"},
                }
            ).encode("ascii")
            + b"\n"
        )
        client.flush()
        return client

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
        results = []
        thread = threading.Thread(
            target=lambda: results.append(client.call(command, arguments or {}))
        )
        thread.start()
        self.wait_until(lambda: not thread.is_alive())
        thread.join(1)
        return results[0]

    def wait_until(self, predicate, timeout_ms=15000):
        loop = QtCore.QEventLoop()
        poll = QtCore.QTimer()
        poll.setInterval(1)
        poll.timeout.connect(lambda: loop.quit() if predicate() else None)
        deadline = QtCore.QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        poll.start()
        deadline.start(timeout_ms)
        if not predicate():
            loop.exec()
        poll.stop()
        deadline.stop()
        self.assertTrue(predicate())


if __name__ == "__main__":
    unittest.main()
