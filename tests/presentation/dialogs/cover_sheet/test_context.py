import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.dialogs.cover_sheet.context import CoverSheetContext


class _RecordingWriteService:
    def __init__(self, events):
        self._events = events

    def save_cover_sheet(self, db_path, bid_uid, updates):
        self._events.append(("save_cover_sheet", db_path, bid_uid, updates))
        return "cover-result"

    def save_job_statuses(self, db_path, changes):
        self._events.append(("save_job_statuses", db_path, changes))
        return "job-status-result"

    def save_employees_result(self, db_path, changes):
        self._events.append(("save_employees_result", db_path, changes))
        return "employees-result"

    def save_pay_classes(self, db_path, changes):
        self._events.append(("save_pay_classes", db_path, changes))
        return "pay-classes-result"

    def save_bid_areas_result(
        self, db_path, bid_uid, changes, publish_database_refreshed_after_write
    ):
        self._events.append(
            (
                "save_bid_areas_result",
                db_path,
                bid_uid,
                changes,
                publish_database_refreshed_after_write,
            )
        )
        return "bid-areas-result"

    def reload_and_notify(self, db_path):
        self._events.append(("reload_and_notify", db_path))
        return True

    def update_bid_job_status(self, db_path, bid_uid, job_status_uid):
        self._events.append(("update_bid_job_status", db_path, bid_uid, job_status_uid))
        return "update-status-result"


class CoverSheetDeferredBoundaryTests(unittest.TestCase):
    def _context(self, events, flush_result):
        def flush_for_file(db_path):
            events.append(("flush", db_path))
            return flush_result

        return CoverSheetContext(
            project_read_service=SimpleNamespace(),
            project_write_service=_RecordingWriteService(events),
            bid_ref=BidRef("a.mdb", "bid-1"),
            deferred_persistence_manager=SimpleNamespace(flush_for_file=flush_for_file),
        )

    def _writes(self, context):
        return (
            ("save_cover_sheet", lambda: context.save_cover_sheet({"job_name": "A"})),
            ("save_job_statuses", lambda: context.save_job_statuses(["status"])),
            ("save_employees", lambda: context.save_employees(["employee"])),
            ("save_pay_classes", lambda: context.save_pay_classes(["pay-class"])),
            ("save_bid_areas", lambda: context.save_bid_areas(["area"])),
            ("refresh", context.refresh),
            ("update_bid_job_status", lambda: context.update_bid_job_status("job-1")),
        )

    def test_cover_sheet_save_flushes_pending_visual_state_before_write(self):
        events = []
        context = self._context(events, flush_result=False)
        self.assertFalse(context.save_cover_sheet({"job_name": "A"}))
        self.assertEqual(events, [("flush", "a.mdb")])

    def test_cover_sheet_save_writes_after_successful_flush(self):
        events = []
        context = self._context(events, flush_result=True)
        self.assertEqual(context.save_cover_sheet({"job_name": "A"}), "cover-result")
        self.assertEqual(
            events,
            [
                ("flush", "a.mdb"),
                ("save_cover_sheet", "a.mdb", "bid-1", {"job_name": "A"}),
            ],
        )

    def test_every_cover_sheet_write_is_blocked_by_a_failed_flush(self):
        events = []
        context = self._context(events, flush_result=False)
        for name, action in self._writes(context):
            with self.subTest(name):
                del events[:]
                self.assertFalse(action())
                self.assertEqual(events, [("flush", "a.mdb")])

    def test_every_cover_sheet_write_flushes_first_then_targets_the_bid(self):
        events = []
        context = self._context(events, flush_result=True)
        expected_write = {
            "save_cover_sheet": (
                "save_cover_sheet",
                "a.mdb",
                "bid-1",
                {"job_name": "A"},
            ),
            "save_job_statuses": ("save_job_statuses", "a.mdb", ["status"]),
            "save_employees": ("save_employees_result", "a.mdb", ["employee"]),
            "save_pay_classes": ("save_pay_classes", "a.mdb", ["pay-class"]),
            "save_bid_areas": (
                "save_bid_areas_result",
                "a.mdb",
                "bid-1",
                ["area"],
                False,
            ),
            "refresh": ("reload_and_notify", "a.mdb"),
            "update_bid_job_status": (
                "update_bid_job_status",
                "a.mdb",
                "bid-1",
                "job-1",
            ),
        }
        for name, action in self._writes(context):
            with self.subTest(name):
                del events[:]
                self.assertTrue(action())
                self.assertEqual(events, [("flush", "a.mdb"), expected_write[name]])
