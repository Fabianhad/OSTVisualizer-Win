import os
import unittest
import uuid
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pyodbc
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.infrastructure.mdb.components import bid_data_reader
from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
from PySide6 import QtWidgets
import tests.helpers.mdb.schema_support as access
from tests.integration.ai_takeoff import test_m1b_golden_end_to_end as m1b
from tests.integration.ai_takeoff.access_app_support import (
    run_in_access_child,
    temporary_home,
)
from tests.presentation.services.ai_takeoff_pdf_support import write_takeoff_pdf

SELECTED_PAGE_INDEX = 8


def seed_two_bids(path, image_path):
    if not access.DatabaseCreator().create_database(Path(path), "LastPage"):
        raise AssertionError("Access database creation failed")
    connections = access.MdbConnectionManager()
    try:
        writer = access.MdbWriter(connections)
        bids = []
        for name in ("Bid A", "Bid B"):
            bid_uid = writer.create_bid(
                str(path),
                None,
                {
                    "job_name": name,
                    "pages": [
                        dict(
                            name=f"{name[-1]}-{number}",
                            width=8.5,
                            height=11.0,
                            scale_factor1=0.125,
                            scale_factor2=12.0,
                            image_path=image_path,
                            index=1,
                        )
                        for number in (1, 2, 3)
                    ],
                },
            )
            page_uids = sorted(
                access.MdbReader(connections).get_bid_data(str(path), bid_uid)[3]
            )
            bids.append((str(bid_uid), [str(uid) for uid in page_uids]))
        return bids
    finally:
        connections.close()


def clear_saved_page(path, bid_uid):
    connection = access._connect_mdb(Path(path))
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE [BidSettings] SET [BidPageSelectedUID]=NULL WHERE [BidUID]=?",
            int(bid_uid),
        )
        connection.commit()
    finally:
        connection.close()


def saved_page(path, bid_uid):
    connections = access.MdbConnectionManager()
    try:
        data = access.MdbReader(connections).get_bid_data(str(path), bid_uid)
        return data[SELECTED_PAGE_INDEX]
    finally:
        connections.close()


class BidSwitchLastPageTests(unittest.TestCase):
    window = m1b.M1bGoldenEndToEndTests.window

    def setUp(self):
        if run_in_access_child(self):
            self.skip_body = True
            return
        self.skip_body = False
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        directory = temporary_home()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        self.server_name = f"OstvLastPage-{uuid.uuid4().hex[:12]}"
        self.db_path = self.home / "last_page.mdb"

    def pump(self, count=60):
        for _ in range(count):
            self.app.processEvents()

    def open_two_bids(self):
        pdf = write_takeoff_pdf(self.home / "plan.pdf", lines=[(100, 100, 400, 100)])
        (a_uid, a_pages), (b_uid, b_pages) = seed_two_bids(self.db_path, str(pdf))
        self.a_uid, self.a_pages = a_uid, a_pages
        self.b_uid, self.b_pages = b_uid, b_pages
        self.refs = {
            "A": BidRef(str(self.db_path), a_uid),
            "B": BidRef(str(self.db_path), b_uid),
        }

    def start(self, win):
        ui = win.handlers.ui_event
        win.tab_widget.setCurrentIndex(TAB_INDEX_TAKEOFF)
        win.set_active_takeoff_view("2d")
        win.resize(1200, 800)
        win.show()
        self.pump()
        ui.sync_after_startup_load()
        return ui

    def select(self, ui, key):
        ui.handle_bid_selection(self.refs[key], force=True)
        self.pump()

    def test_returning_to_a_bid_restores_the_page_the_user_picked(self):
        if self.skip_body:
            return
        self.open_two_bids()
        with self.window(self.a_uid) as (win, _controller):
            ui = self.start(win)
            combo = ui.takeoff_sidebar
            self.select(ui, "A")
            combo._set_active(self.a_pages[2])
            self.pump()
            self.select(ui, "B")
            self.assertEqual(saved_page(self.db_path, self.a_uid), self.a_pages[2])
            self.select(ui, "A")
            self.assertEqual(combo.get_active_page_uid(), self.a_pages[2])
            self.assertEqual(ui.plan_view.current_page_uid, self.a_pages[2])

    def test_failed_saved_page_read_does_not_overwrite_the_saved_page(self):
        if self.skip_body:
            return
        self.open_two_bids()
        with self.window(self.a_uid) as (win, _controller):
            ui = self.start(win)
            combo = ui.takeoff_sidebar
            self.select(ui, "A")
            combo._set_active(self.a_pages[2])
            self.pump()
            self.select(ui, "B")
            real = bid_data_reader.fetch_optional_bid_settings_row
            failures = []

            def fail_once(cursor, bid_uid, columns):
                if columns == ("BidPageSelectedUID",) and not failures:
                    failures.append(bid_uid)
                    raise pyodbc.Error("HY000", "transient lock error")
                return real(cursor, bid_uid, columns)

            with mock.patch.object(
                bid_data_reader, "fetch_optional_bid_settings_row", fail_once
            ):
                self.select(ui, "A")
            # Positive control: the saved page really was unreadable once, so
            # the first page is shown instead.
            self.assertEqual(len(failures), 1)
            self.assertEqual(combo.get_active_page_uid(), self.a_pages[0])
            self.select(ui, "B")
            self.assertEqual(saved_page(self.db_path, self.a_uid), self.a_pages[2])
            self.select(ui, "A")
            self.assertEqual(combo.get_active_page_uid(), self.a_pages[2])

    def test_first_page_shown_without_a_saved_page_is_not_saved_until_picked(self):
        if self.skip_body:
            return
        self.open_two_bids()
        with self.window(self.a_uid) as (win, _controller):
            ui = self.start(win)
            combo = ui.takeoff_sidebar
            # Creating a bid stores its first page; start from a bid that has
            # never had a page saved.
            clear_saved_page(self.db_path, self.b_uid)
            self.assertIsNone(saved_page(self.db_path, self.b_uid))
            self.select(ui, "B")
            self.assertEqual(combo.get_active_page_uid(), self.b_pages[0])
            self.select(ui, "A")
            self.assertIsNone(saved_page(self.db_path, self.b_uid))
            self.select(ui, "B")
            combo._set_active(self.b_pages[1])
            self.pump()
            self.select(ui, "A")
            self.assertEqual(saved_page(self.db_path, self.b_uid), self.b_pages[1])
            # Going back to the first page is a pick and is saved like any other.
            self.select(ui, "B")
            combo._set_active(self.b_pages[0])
            self.pump()
            self.select(ui, "A")
            self.assertEqual(saved_page(self.db_path, self.b_uid), self.b_pages[0])


if __name__ == "__main__":
    unittest.main()
