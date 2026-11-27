import unittest
from pathlib import Path
from unittest.mock import patch
from ost_visualizer.application.dtos.page_write_errors import (
    PAGE_DELETE_WOULD_LEAVE_NO_PAGE,
    PageScaleRangeError,
)
from ost_visualizer.domain.entities.page import PAGE_NAME_MAX_LENGTH
from ost_visualizer.shared.texts import (
    PAGE_OPERATIONS_MESSAGE_THE_SCALE_WAS_NOT_CHANGED_BECAUSE,
)
import tests.helpers.mdb.schema_support as access
from tests.integration.ai_takeoff.access_app_support import (
    configured_app,
    run_in_access_child,
    seed_access_bid,
    temporary_home,
)

_TAKEOFF = b"1000;1000;2000;1000\n"


class _PageAccessCase(unittest.TestCase):
    def setUp(self):
        if run_in_access_child(self):
            self.skip_body = True
            return
        self.skip_body = False
        self.directory = temporary_home()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.db_path = self.home / "pages.mdb"
        self.bid_uid, self.page_uids, self.condition_uid = seed_access_bid(
            self.db_path,
            [
                ("P1", 1000.0, 800.0, 1.0, 1.0),
                ("P2", 1000.0, 800.0, 1.0, 1.0),
                ("P3", 1000.0, 800.0, 1.0, 1.0),
            ],
        )

    def query(self, sql, *params):
        conn = access._connect_mdb(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(sql, *params)
            return [tuple(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def execute(self, sql, *params):
        conn = access._connect_mdb(self.db_path)
        try:
            conn.cursor().execute(sql, *params)
            conn.commit()
        finally:
            conn.close()

    def add_takeoff(self, page_uid, position=_TAKEOFF):
        self.execute(
            "INSERT INTO [BidTakeoffs] ([BidUID], [BidConditionUID], [BidPageUID], "
            "[Position]) VALUES (?, ?, ?, ?)",
            int(self.bid_uid),
            int(self.condition_uid),
            int(page_uid),
            position,
        )
        return self.query("SELECT MAX([UID]) FROM [BidTakeoffs]")[0][0]

    def takeoff_position(self, uid):
        return bytes(
            self.query("SELECT [Position] FROM [BidTakeoffs] WHERE [UID]=?", uid)[0][0]
        )

    def scales(self):
        return {
            str(uid): (sf1, sf2)
            for uid, sf1, sf2 in self.query(
                "SELECT [UID], [ScaleFactor1], [ScaleFactor2] FROM [BidPages] "
                "WHERE [BidUID]=?",
                int(self.bid_uid),
            )
        }

    def names(self):
        return {
            str(uid): name
            for uid, name in self.query(
                "SELECT [UID], [Name] FROM [BidPages] WHERE [BidUID]=?",
                int(self.bid_uid),
            )
        }

    def writer(self):
        connections = access.MdbConnectionManager()
        self.addCleanup(connections.close)
        return access.MdbWriter(connections)

    def app(self):
        return configured_app(self.home, self.db_path, self.bid_uid)


class PageScaleRangeAccessTests(_PageAccessCase):
    def test_a_scale_that_would_store_infinite_or_zero_positions_is_refused(self):
        if self.skip_body:
            return
        uid = self.add_takeoff(self.page_uids[0])
        writer = self.writer()
        for sf2 in (1e308, 1e-9):
            with self.subTest(sf2=sf2):
                with self.assertRaises(PageScaleRangeError) as raised:
                    writer.save_page_scale(
                        str(self.db_path), self.page_uids[0], 1.0, sf2
                    )
                self.assertEqual(
                    str(raised.exception),
                    PAGE_OPERATIONS_MESSAGE_THE_SCALE_WAS_NOT_CHANGED_BECAUSE,
                )
                self.assertEqual(self.takeoff_position(uid), _TAKEOFF)
                self.assertEqual(self.scales()[self.page_uids[0]], (1.0, 1.0))
        self.assertIs(
            writer.save_page_scale(str(self.db_path), self.page_uids[0], 1.0, 2.0),
            True,
        )
        self.assertEqual(self.takeoff_position(uid), b"2000;2000;4000;2000\n")

    def test_the_service_refuses_the_change_and_keeps_the_loaded_page(self):
        if self.skip_body:
            return
        uid = self.add_takeoff(self.page_uids[0])
        with self.app() as (container, _bid_ref):
            service = container.get("project_write_service")
            data = container.get("project_data_service")
            with self.assertRaises(PageScaleRangeError):
                service.save_page_scale(
                    str(self.db_path), self.page_uids[0], 1.0, 1e308
                )
            page = data.get_page(self.page_uids[0])
            self.assertEqual((page.scale_factor1, page.scale_factor2), (1.0, 1.0))
            memory = [
                takeoff.position
                for takeoff in data.get_page_takeoffs(self.page_uids[0])
                if str(takeoff.uid) == str(uid)
            ]
        self.assertEqual(memory, [[1000.0, 1000.0, 2000.0, 1000.0]])
        self.assertEqual(self.takeoff_position(uid), _TAKEOFF)

    def test_apply_to_all_pages_writes_no_page_when_one_page_is_refused(self):
        if self.skip_body:
            return
        self.add_takeoff(self.page_uids[1])
        with self.app() as (container, _bid_ref):
            service = container.get("project_write_service")
            with self.assertRaises(PageScaleRangeError):
                service.save_page_scales(
                    str(self.db_path), list(self.page_uids), 1.0, 1e308
                )
        self.assertEqual(self.scales(), {uid: (1.0, 1.0) for uid in self.page_uids})


class CoverSheetScaleRangeAccessTests(_PageAccessCase):
    def test_a_cover_sheet_scale_the_page_content_cannot_take_saves_nothing(self):
        if self.skip_body:
            return
        uid = self.add_takeoff(self.page_uids[0])
        page_update = {
            "uid": self.page_uids[0],
            "width": 1000.0,
            "height": 800.0,
            "scale_factor1": 1.0,
            "scale_factor2": 1e308,
            "show_mode": 0,
            "sheet_no": "S-1",
            "index": 1,
            "sequence": 1,
            "multi_page_count": 0,
            "name": "Renamed in the same save",
            "image_path": "",
            "overlay_path": "",
        }
        saved = self.writer().save_cover_sheet(
            str(self.db_path),
            str(self.bid_uid),
            {"measure_base": 0, "pages": [page_update]},
        )
        self.assertIs(saved, False)
        self.assertEqual(self.takeoff_position(uid), _TAKEOFF)
        self.assertEqual(self.scales()[self.page_uids[0]], (1.0, 1.0))
        self.assertEqual(self.names()[self.page_uids[0]], "P1")


class PageNameLengthAccessTests(_PageAccessCase):
    def test_the_writer_refuses_a_name_longer_than_the_column(self):
        if self.skip_body:
            return
        writer = self.writer()
        longest = "N" * PAGE_NAME_MAX_LENGTH
        self.assertIs(
            writer.save_page_name(str(self.db_path), self.page_uids[0], longest + "N"),
            False,
        )
        self.assertEqual(self.names()[self.page_uids[0]], "P1")
        self.assertIs(
            writer.save_page_name(str(self.db_path), self.page_uids[0], longest),
            True,
        )
        self.assertEqual(self.names()[self.page_uids[0]], longest)

    def test_the_service_keeps_the_loaded_name_when_the_name_is_too_long(self):
        if self.skip_body:
            return
        with self.app() as (container, _bid_ref):
            service = container.get("project_write_service")
            data = container.get("project_data_service")
            self.assertIs(
                service.save_page_name(
                    str(self.db_path),
                    self.page_uids[0],
                    "N" * (PAGE_NAME_MAX_LENGTH + 1),
                ),
                False,
            )
            self.assertEqual(data.get_page(self.page_uids[0]).name, "P1")
        self.assertEqual(self.names()[self.page_uids[0]], "P1")


class CommittedPageWriteAccessTests(_PageAccessCase):
    def test_a_committed_rename_is_not_reported_failed_when_the_reload_fails(self):
        if self.skip_body:
            return
        with self.app() as (container, _bid_ref):
            service = container.get("project_write_service")
            data = container.get("project_data_service")
            real_get = data.get_page
            with patch.object(
                data,
                "get_page",
                side_effect=lambda uid: (
                    None if uid == self.page_uids[0] else real_get(uid)
                ),
            ), patch.object(service, "_reload_database", return_value=False):
                result = service.save_page_name(
                    str(self.db_path), self.page_uids[0], "Committed"
                )
        self.assertEqual(self.names()[self.page_uids[0]], "Committed")
        self.assertIs(result, True)

    def test_a_committed_delete_whose_reload_fails_reports_the_refresh(self):
        if self.skip_body:
            return
        with self.app() as (container, _bid_ref):
            service = container.get("project_write_service")
            with patch.object(service, "_reload_database", return_value=False):
                result = service.delete_pages_result(
                    str(self.db_path), [self.page_uids[0]]
                )
        self.assertNotIn(self.page_uids[0], self.names())
        self.assertIs(result.write_success, True)
        self.assertIs(result.refresh_failed, True)
        self.assertEqual(result.value, [self.page_uids[0]])

    def test_the_service_refuses_to_delete_every_page_of_the_bid(self):
        if self.skip_body:
            return
        with self.app() as (container, _bid_ref):
            service = container.get("project_write_service")
            result = service.delete_pages_result(
                str(self.db_path), list(self.page_uids)
            )
            self.assertIs(
                service.delete_pages(str(self.db_path), list(self.page_uids)), False
            )
        self.assertIs(result.write_success, False)
        self.assertEqual(result.failure_reason, PAGE_DELETE_WOULD_LEAVE_NO_PAGE)
        self.assertEqual(set(self.names()), set(self.page_uids))
        with self.app() as (container, _bid_ref):
            result = container.get("project_write_service").delete_pages_result(
                str(self.db_path), list(self.page_uids[:2])
            )
        self.assertIs(result.success, True)
        self.assertEqual(set(self.names()), {self.page_uids[2]})


if __name__ == "__main__":
    unittest.main()
