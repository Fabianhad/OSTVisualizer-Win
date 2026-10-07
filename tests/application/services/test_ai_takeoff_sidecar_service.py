import json
import os
import unittest
from ost_visualizer.application.services.ai_takeoff_sidecar_service import (
    AiTakeoffSidecarService,
)
from ost_visualizer.domain.entities.ai_takeoff import SidecarWriteRefused
from ost_visualizer.domain.entities.ai_takeoff import Assumption, ai_takeoff_bid_key
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from tests.application.services.test_ai_takeoff_read_service import (
    ServiceTestCase,
    SpyRepository,
)


def _assumption(uid, value="8", status="open"):
    return Assumption(uid, value, "not shown", "S-101", "high", status)


class SidecarServiceTestCase(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.sidecars = AiTakeoffSidecarService(
            self.project, self.repository, self.descriptors.get
        )

    def key(self):
        return ai_takeoff_bid_key(DatabaseBackend.ACCESS, "{BID-1}")

    def path(self):
        return self.sidecar_dir / f"{self.key()}.json"

    def write(self, database_id="db-1", page_count=3, raw=None):
        self.sidecar_dir.mkdir(parents=True, exist_ok=True)
        if raw is not None:
            self.path().write_bytes(raw)
            return
        self.path().write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "bid_key": self.key(),
                    "fingerprint": {
                        "database_id": database_id,
                        "bid_name": "Tower",
                        "page_count": page_count,
                        "first_page_pdf_source": "S-101.pdf",
                    },
                    "levels": [{"uid": "L1", "name": "Level 1", "top_elev_in": 1200.0}],
                    "registrations": [],
                    "assumptions": [_assumption("A1").to_dict()],
                }
            ),
            encoding="utf-8",
        )

    def assert_refused_and_untouched(self, status, action):
        path = self.path()
        before = path.read_bytes() if path.exists() else None
        mtime = os.stat(path).st_mtime_ns if path.exists() else None
        with self.assertRaises(SidecarWriteRefused) as raised:
            action()
        self.assertEqual(raised.exception.status, status)
        if before is None:
            self.assertFalse(path.exists())
        else:
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(os.stat(path).st_mtime_ns, mtime)


class RecordAssumptionTests(SidecarServiceTestCase):
    def test_a_missing_sidecar_is_created_with_the_current_fingerprint(self):
        self.assertEqual(
            self.sidecars.record_assumptions((_assumption("cs1-a1"),)), "ok"
        )
        data = json.loads(self.path().read_text(encoding="utf-8"))
        self.assertEqual(data["fingerprint"]["database_id"], "db-1")
        self.assertEqual(data["fingerprint"]["page_count"], 3)
        self.assertEqual([a["uid"] for a in data["assumptions"]], ["cs1-a1"])
        self.assertEqual(
            self.service.list_assumptions()["data"]["sidecar_status"], "ok"
        )

    def test_an_ok_sidecar_keeps_its_data_and_updates_by_uid(self):
        self.write()
        self.sidecars.record_assumptions(
            (_assumption("A1", value="10", status="overridden"), _assumption("cs2-a1"))
        )
        data = json.loads(self.path().read_text(encoding="utf-8"))
        self.assertEqual(len(data["levels"]), 1)
        self.assertEqual(
            [(a["uid"], a["value"], a["status"]) for a in data["assumptions"]],
            [("A1", "10", "overridden"), ("cs2-a1", "8", "open")],
        )

    def test_assumptions_not_in_the_write_are_kept(self):
        self.write()
        before = [
            a["uid"]
            for a in json.loads(self.path().read_text(encoding="utf-8"))["assumptions"]
        ]
        self.sidecars.record_assumptions((_assumption("cs3-a1"),))
        data = json.loads(self.path().read_text(encoding="utf-8"))
        self.assertEqual([a["uid"] for a in data["assumptions"]], before + ["cs3-a1"])

    def test_rebind_mismatch_and_corrupt_sidecars_are_never_written(self):
        cases = {
            "rebind_required": dict(database_id="db-old"),
            "fingerprint_mismatch": dict(database_id="db-old", page_count=9),
            "corrupt": dict(raw=b"{broken"),
        }
        for status, values in cases.items():
            with self.subTest(status=status):
                self.write(**values)
                self.assert_refused_and_untouched(
                    status,
                    lambda: self.sidecars.record_assumptions((_assumption("x"),)),
                )

    def test_sql_without_a_database_guid_writes_nothing(self):
        location = SqlServerDatabaseLocation(
            server="srv", database="ost", database_guid=""
        )
        self.descriptors["sql:srv/ost"] = DatabaseDescriptor.for_sql_server(
            location, schema_version=1
        )
        self.project.bid_ref = BidRef("sql:srv/ost", "7")
        self.project.bid = Bid(uid="7", name="Tower")
        spy = SpyRepository()
        sidecars = AiTakeoffSidecarService(self.project, spy, self.descriptors.get)
        with self.assertRaises(SidecarWriteRefused) as raised:
            sidecars.record_assumptions((_assumption("x"),))
        self.assertEqual(raised.exception.status, "unavailable_no_database_guid")
        self.assertEqual(spy.keys, [])


class BidKeyTests(SidecarServiceTestCase):
    def test_the_key_needs_no_sidecar_read(self):
        spy = SpyRepository()
        sidecars = AiTakeoffSidecarService(self.project, spy, self.descriptors.get)
        self.assertEqual(sidecars.bid_key(), self.key())
        self.assertEqual(spy.keys, [])
        self.project.bid = None
        self.assertIsNone(sidecars.bid_key())


class RebindTests(SidecarServiceTestCase):
    def test_rebind_keeps_the_data_and_takes_the_current_database(self):
        self.write(database_id="db-old")
        self.assertEqual(self.sidecars.context().status, "rebind_required")
        self.assertEqual(self.sidecars.rebind(), "ok")
        data = json.loads(self.path().read_text(encoding="utf-8"))
        self.assertEqual(data["fingerprint"]["database_id"], "db-1")
        self.assertEqual([a["uid"] for a in data["assumptions"]], ["A1"])
        self.assertEqual(len(data["levels"]), 1)
        self.assertEqual(self.service.list_levels()["data"]["sidecar_status"], "ok")

    def test_rebind_is_refused_for_every_other_status(self):
        cases = {
            "fingerprint_mismatch": dict(database_id="db-old", page_count=9),
            "corrupt": dict(raw=b"{broken"),
            "ok": dict(),
        }
        for status, values in cases.items():
            with self.subTest(status=status):
                self.write(**values)
                self.assert_refused_and_untouched(status, self.sidecars.rebind)
        self.path().unlink()
        self.assert_refused_and_untouched("empty", self.sidecars.rebind)


class RebindBidSwitchTests(SidecarServiceTestCase):
    def test_rebind_refuses_when_the_open_bid_is_not_the_expected_one(self):
        self.write(database_id="db-old")
        before = self.path().read_bytes()
        with self.assertRaises(SidecarWriteRefused) as raised:
            self.sidecars.rebind(expected_bid_key="0" * 32)
        self.assertEqual(raised.exception.status, "bid_changed")
        self.assertEqual(self.path().read_bytes(), before)
        self.assertEqual(self.sidecars.rebind(expected_bid_key=self.key()), "ok")


if __name__ == "__main__":
    unittest.main()
